# DocMesh

**Semantic document intelligence, built from primitives.**

Upload a pile of documents and DocMesh turns them into something you can *interrogate*:
hybrid semantic + keyword search, an automatically inferred knowledge graph linking related
documents, and grounded question-answering with citations — all without LangChain,
LlamaIndex, or any RAG framework. Every layer (chunking, embedding, retrieval fusion,
reranking, graph inference) is hand-built and individually defensible.

> Portfolio project by an MTech Information & Cyber Security student. Uploads are treated
> as hostile input: streamed size caps, magic-byte sniffing, zip-bomb guards, and filename
> sanitization are first-class features, not afterthoughts. See
> [ARCHITECTURE.md](./ARCHITECTURE.md) for the threat model and every design decision.

## Stack

- **Backend** — FastAPI · SQLAlchemy 2.0 Core (not ORM) · Alembic · SQLite (WAL) · structlog
- **Frontend** — React 19 · Vite 6 · Tailwind v4 · TanStack Query · TypeScript strict
- **Coming** — sentence-transformers + FAISS + BM25 hybrid search (Phase 2), NMF topic
  graph (Phase 3), Claude-powered ask-your-corpus with citations (Phase 4)

## Quickstart

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate        # PowerShell; use `source .venv/bin/activate` on Unix
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload  # migrations run automatically on startup
```

API at http://localhost:8000 — try `GET /api/health`. Interactive docs at `/docs`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

UI at http://localhost:5173 (dev server proxies `/api` to the backend).

### Docker

```powershell
docker compose up --build
```

Frontend on http://localhost:5173, backend on http://localhost:8000, data persisted in `./data`.

### Tests

```powershell
cd backend
pytest
```

## Screenshot

![DocMesh documents view](docs/screenshot-documents.png)
*(screenshot placeholder — added once the ingestion pipeline lands)*

## Project phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Scaffold: hostile-upload pipeline, document CRUD, polished shell UI | ✅ |
| 2 | Ingestion workers: parse → chunk → embed → FAISS index, hybrid search | ⏳ |
| 3 | Document graph: semantic + entity + topic edges, graph UI | ⏳ |
| 4 | Ask-your-corpus: Claude RAG with citations and edge explanations | ⏳ |
