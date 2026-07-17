# DocMesh — Architecture & Decision Log

This document grows with each phase. Every non-obvious decision lands here with its
rationale, because the point of this project is that every layer can be defended in an
interview.

---

## 1. Stack choice

**FastAPI + SQLite + FAISS-on-disk + React, two containers, no framework RAG.**

- **No LangChain / LlamaIndex** (hard constraint). RAG is retrieval + prompt assembly +
  an API call. Building it from primitives (sentence-transformers, FAISS, rank-bm25,
  the raw `anthropic` SDK) means every behavior is inspectable and explainable. Framework
  abstractions hide exactly the parts an interviewer asks about.
- **SQLite, not Postgres, for v1.** Single-writer document ingestion with a handful of
  concurrent readers is squarely inside SQLite's comfort zone. WAL mode gives concurrent
  reads during writes; `busy_timeout=5000` absorbs writer contention. Zero ops burden.
  The swap path to Postgres is designed in (see §6) rather than paid for up front.
- **Two containers only** (backend, frontend). No Redis, no Celery, no vector DB service.
  Each extra service must justify its ops cost; at this scale none do. The ingestion
  queue is an in-process asyncio worker with durable state in SQLite (§5).

## 2. Repository pattern over SQLAlchemy Core

All persistence goes through abstract repositories (`app/storage/interfaces.py`):
`DocumentRepository`, `ChunkRepository`, `IngestionEventRepository`, plus a `VectorStore`
ABC for the Phase-2 FAISS index.

- Repos accept and return **Pydantic models, never SQLAlchemy rows**. The API layer and
  services are persistence-agnostic; the Pydantic schemas are the single source of truth
  for both the wire contract and the storage contract.
- One SQL implementation (`app/storage/sql/`) serves both SQLite and Postgres because it
  only uses portable Core constructs — the seam exists for *vector store* swaps
  (FAISS → Pinecone/pgvector), not because we expect to rewrite SQL.
- Testing: repositories are exercised against a real temp SQLite file, not mocks —
  mocking the DB tests the mock.

## 3. SQLAlchemy Core, not ORM

- Core keeps SQL visible: every query in `app/storage/sql/` reads like the SQL it emits.
  No identity map, no lazy-loading surprises, no session lifecycle to reason about in
  async code.
- The ORM's win is object graph navigation; DocMesh's access patterns are flat
  (by-id, by-hash, paged lists, bulk inserts) so the ORM would add concepts without
  removing code.
- Tables are defined once in `app/storage/tables.py` on a single `MetaData`, using only
  portable types (`String/Text/Integer/Float/Boolean/JSON/DateTime(timezone=True)`), so
  the same definitions drive Alembic migrations on SQLite today and Postgres later.
- Datetimes are stored UTC. SQLite returns them naive; the Pydantic read models re-attach
  UTC so the API always emits timezone-aware ISO-8601.

## 4. Upload threat model

Uploads are the only user-controlled input in Phase 1 and are treated as hostile.
All validation lives in pure functions in `app/ingestion/validators.py` so it is
table-driven-testable without a server.

| Threat | Mitigation |
|---|---|
| Oversized body / decompression flooding disk | `stream_to_disk_capped` counts bytes as they stream in 1 MB chunks and aborts (deleting the partial file) the instant the running total passes the cap. **Content-Length is never trusted** — it is attacker-controlled. |
| Content-type spoofing (EXE renamed `.pdf`) | Magic-byte sniffing of the *on-disk* file, not the client's claimed MIME. `%PDF-` → pdf; `PK\x03\x04` + `[Content_Types].xml` present → docx; strict UTF-8 decode → txt/md. A mismatch with the claimed extension is a hard reject (`magic_mismatch`), not a silent correction. |
| Zip bombs inside DOCX | DOCX is a ZIP; before accepting we reject archives with > 200 entries or > 50 MB declared decompressed size. Phase 2's parser never sees an unvetted archive. |
| Path traversal / reserved names (`..\..\evil`, `CON.pdf`, NUL bytes) | `sanitize_filename` strips path components (both `/` and `\`), control characters, and Windows reserved device names. Crucially, the sanitized name is **display/DB-only** — files on disk are always named `{uuid4hex}.{sniffed_ext}`, so no user-controlled string ever becomes a filesystem path. |
| Duplicate-content resource abuse | SHA-256 computed in the same streaming pass as the size check; a content-duplicate upload is a 409 pointing at the existing document. |
| Info leaks via errors | Validation failures map to typed error codes (400/413/415/409); unexpected failures return a generic 500 with a request id — never a stack trace. |

**Rejected: `python-magic`.** It wraps libmagic, which is a native-DLL headache on Windows
(the primary dev machine) and would outsource exactly the logic this project wants to
demonstrate. We only accept four formats, whose signatures are trivially checkable by
hand — a full magic database is scope without benefit.

## 5. Ingestion runner (designed now, built in Phase 2)

In-process asyncio worker, not Celery/RQ:

- On upload, a document row is inserted with `status='queued'` and an event appended;
  the HTTP response is 202 immediately.
- A single background asyncio task per process drains queued documents through
  `parsing → chunking → embedding → indexing → done`, updating `documents.status` and
  appending to `ingestion_events` (an append-only audit trail with per-stage durations)
  at each transition.
- **Durability comes from SQLite, not the queue**: on startup the runner re-queues any
  document stuck in a non-terminal status, so a crash mid-ingest recovers by re-running
  from the persisted state. A broker would add a service to buy delivery guarantees that
  the status column already provides at this scale.
- CPU-heavy steps (embedding) run in a thread/process executor so the event loop keeps
  serving requests.

## 6. Planned Postgres / Pinecone swap mechanics

- **Postgres**: set `DOCMESH_DATABASE_URL=postgresql+asyncpg://…`, `pip install asyncpg`,
  run `alembic upgrade head`. The SQL repos already speak portable Core; the SQLite
  PRAGMA listener is applied only when the URL is `sqlite`. No code changes.
- **Pinecone / pgvector**: implement the `VectorStore` ABC (`upsert/query/
  delete_by_document/persist/count/health`) against the hosted index and switch the
  wiring in the app factory. `VectorRecord`/`VectorHit` are deliberately plain frozen
  dataclasses so the interface has no FAISS types in it.
- The `chunks.vector_id` integer column is the join key between SQL rows and the dense
  index; it is allocated by the repo (`max_vector_id() + 1` onward) rather than by FAISS,
  so the mapping survives index rebuilds.

## 7. Chunking strategy (Phase 2)

**Recursive semantic chunking: heading > paragraph > sentence > hard word cap, ~400
tokens per chunk with 15% token-based overlap, counted in the embedding model's own
tokenizer.**

- Chunk size is a retrieval-precision vs context-completeness trade-off measured in
  the *model's* tokens: bge-small has a 512-token window, so a 400 budget guarantees
  no silent truncation at embed time while staying large enough that a chunk carries a
  self-contained idea. Much smaller and embeddings become ambiguous fragments; much
  larger and one vector averages several topics and matches none of them well.
- Fixed character windows cut sentences and topics mid-thought — the severed halves
  each embed to a point representing neither. Sentence alignment keeps every chunk a
  set of complete propositions; heading boundaries are hard walls so one vector never
  blends two sections' topics.
- **Why token-based overlap**: the failure mode overlap insures against is an answer
  straddling a chunk boundary. 15% of the *token budget* (not characters, not
  sentences) bounds the cost precisely — the index grows by at most 15% — and the
  config validator enforces < 50%, past which consecutive chunks are mostly the same
  text and the window stops advancing usefully. Overlap carries the trailing
  *sentences* of the previous chunk, so every chunk remains a contiguous slice of the
  source (`text == full_text[char_start:char_end]` — exact provenance forever).
- Token counting uses the real bge tokenizer **injected as a plain callable**: a
  words×1.3 heuristic can drift 30%+ on technical text and silently blow the 512
  limit, while injection keeps the chunker pure — zero ML imports, deterministic,
  unit-testable with a whitespace counter. Loading the HF tokenizer is milliseconds
  and pulls no model weights.

## 8. Hybrid retrieval: RRF over score normalization (Phase 2)

**`score(c) = w·1/(k + dense_rank) + (1−w)·1/(k + bm25_rank)`, k = 60.**

- Raw cosine and BM25 scores are incommensurable: cosine lives in [−1, 1] with
  query-dependent spread; BM25 is unbounded and corpus-statistics-dependent. Any
  min–max or z-score normalization is per-query and distribution-sensitive — one
  outlier rescales everything. RRF (Cormack et al., 2009) discards scores entirely
  and fuses on *ranks*: scale-free, no tuning data, and empirically competitive with
  trained fusion in the original paper.
- **Why k = 60**: it is the paper's constant, and its role is to flatten the
  reciprocal curve near the top. With k = 0, rank 1 contributes double rank 2 and one
  ranker dominates; with k = 60, ranks 1 and 2 contribute 1/61 vs 1/62 — consensus
  across rankers decides, not one ranker's #1.
- `dense_weight` stays an explicit, per-request-overridable knob, and every raw
  score/rank survives to the response — fusion just doesn't *depend* on them.

## 9. Cross-encoder rerank: top-30 → top-10 (Phase 2)

- The bi-encoder embeds query and passage *independently* — that independence is what
  makes indexed search possible (passages embedded once at ingest; a query is one
  forward pass plus a scan) but forces each text through a single 384-dim bottleneck
  with no query–passage token interaction.
- The cross-encoder (`ms-marco-MiniLM-L-6-v2`) attends jointly over the concatenated
  pair, so every query token interacts with every passage token — substantially more
  accurate, but one full forward pass *per pair*: scoring the corpus per query is
  O(N) model inferences and unusable.
- Retrieve-then-rerank is a compute-asymmetry funnel: cheap recall gets top-30
  (`retrieve_n`), the expensive model spends its 30 forward passes only where they can
  change the answer, and returns top-10 (`return_n`). Pool size is the knob: larger
  raises the recall ceiling at linear rerank latency.

## 10. FAISS IndexFlatIP, exact over approximate (Phase 2)

- `IndexIDMap2(IndexFlatIP(384))` over L2-normalized vectors: inner product == exact
  cosine, zero recall loss, zero training, and IDMap2 gives stable int64 ids plus
  `remove_ids` for document deletion.
- At this scale (tens of thousands of vectors, not millions) a brute-force scan is
  sub-millisecond; IVF/HNSW would add recall risk and tuning knobs (nlist, nprobe, ef)
  to solve a latency problem that does not exist. The `VectorStore` ABC is the swap
  seam if the corpus ever outgrows flat.
- Concurrency: one `asyncio.Lock` serializes every index touch, with the C++ calls in
  `asyncio.to_thread` — the event loop never blocks and the (write-thread-unsafe)
  index sees one caller at a time. Persistence is crash-safe: write to `.tmp`, then
  atomic `os.replace` (NTFS and POSIX).
- SQL is the source of truth for the id mapping; if the on-disk index disagrees with
  SQL at startup, the index is cleared and every affected document is uniformly
  re-queued for re-ingestion — vectors exist *only* in FAISS, so re-embedding is the
  only honest recovery, and one uniform mechanism beats a partial-repair special case.

## 11. Near-duplicate removal at cosine > 0.98 (Phase 2)

- Exact duplicates are caught first by `content_hash` (sha256 over
  whitespace/case-normalized text) — free, no model. Near-dups are a cosine threshold
  on embeddings we computed anyway (see §7 note on MinHash).
- 0.98 is deliberately conservative: at that similarity two chunks are reworded copies
  (boilerplate headers, pasted paragraphs), not merely same-topic text (~0.8–0.9).
  False-positive dedup silently loses content; false-negative costs one redundant
  vector — so the threshold errs hard toward keeping.
- Duplicates keep their rows (`is_duplicate=True`, provenance preserved) but never
  reach FAISS or BM25 — search results stay diverse without losing the audit trail.
  First occurrence wins: cross-document dups chain to the already-indexed original.

## 12. BM25 rebuilt in memory, not persisted (Phase 2)

- `rank_bm25`'s `BM25Okapi` precomputes corpus-global IDF at construction: it cannot
  be incrementally updated (every add/remove shifts every IDF) or meaningfully
  serialized apart from its corpus. So the index is rebuilt from SQLite — the durable
  store — at startup and after every ingestion/deletion.
- At ~50k chunks a rebuild is a few hundred ms of pure Python, well under a single
  ingestion's embedding time, and runs off the event loop. A persisted BM25 artifact
  would be a cache with invalidation bugs waiting to happen.
- Readers never lock: searches read one attribute holding an immutable
  `(bm25, ids)` snapshot (atomic under the GIL); writers rebuild off-line and swap.

## 13. SSE: replay-then-live (Phase 2)

- Per-document stream (`GET /api/documents/{id}/events`): **subscribe to the broker
  first, replay persisted history second** — the subscriber queue buffers anything
  published during replay, so no event can fall in the gap; an id watermark dedupes
  the overlap. Event ids are the `ingestion_events` autoincrement ids, so the standard
  `Last-Event-ID` header resumes with one indexed query. The stream closes itself on
  `done`/`failed` — EventSource clients won't reconnect after a clean close.
- Global stream (`GET /api/events`) is a live activity ticker with no replay: history
  belongs to the per-document endpoint.
- The broker never blocks ingestion: per-subscriber bounded queues drop the *oldest*
  event on overflow — a slow SSE client loses history it can recover via replay; the
  worker never stalls. Ordering rule: events are persisted to SQLite first, published
  second — the broker is a best-effort mirror of the database, never the reverse.

## 14. Decisions banked for later phases

- **NMF over BERTopic for topic edges (Phase 3).** BERTopic drags in UMAP + HDBSCAN
  (heavy, stochastic, version-sensitive) for corpora of tens-to-hundreds of documents.
  NMF over TF-IDF is deterministic, fast, dependency-light (scikit-learn only), and its
  topic loadings are directly explainable — which matters because graph edges must be
  *justified* in the UI, not just drawn.
- **Cosine ≥ 0.98 over MinHash for near-duplicate chunks (Phase 2).** We already have
  dense embeddings for every chunk, so near-dup detection is a threshold on vectors we
  computed anyway. MinHash shines at web scale on shingled text; here it would be a
  second similarity machinery to explain and tune for zero added recall.
- **numpy pinned < 2** once ML deps land: faiss-cpu 1.10 wheels and parts of the
  spacy/thinc stack are still built against the numpy 1.x ABI; mixing ABIs is a
  runtime crash, not an install error, so the pin is explicit and commented.
