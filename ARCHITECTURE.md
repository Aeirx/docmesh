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

## 7. Decisions banked for later phases

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
