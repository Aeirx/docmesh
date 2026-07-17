"""End-to-end ingest -> search over the real app.

Two tiers share one test body:
- Fast (default): the conftest autouse fixture swaps in FakeEmbedder/FakeReranker.
  Everything else — extraction, chunker, FAISS, BM25, RRF, SSE, the worker,
  SQLite — is real.
- Real (``pytest -m slow``): the same flow against the true models. First run
  downloads ~220 MB into the HF cache; model load dominates the runtime.
"""

import asyncio
import json

import pytest

# Two identical "Energy" sections: the second produces a chunk with the same
# content hash as the first -> exercises exact-duplicate detection end to end.
_DOC = """# Biology Notes

## Energy

The mitochondria is the powerhouse of the cell. Adenosine triphosphate fuels most
cellular processes in living organisms.

## Storage

Chloroplasts capture light energy in plants. DNA stores genetic information inside
the cell nucleus.

## Energy

The mitochondria is the powerhouse of the cell. Adenosine triphosphate fuels most
cellular processes in living organisms.
"""


async def _upload_and_wait(app, client, timeout: float = 120.0) -> str:
    response = await client.post(
        "/api/documents", files={"file": ("bio.md", _DOC.encode("utf-8"), "text/markdown")}
    )
    assert response.status_code == 202, response.text
    doc_id = response.json()["document"]["id"]

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        doc = (await client.get(f"/api/documents/{doc_id}")).json()
        if doc["status"] in ("done", "failed"):
            break
        assert asyncio.get_event_loop().time() < deadline, f"ingestion timed out: {doc}"
        await asyncio.sleep(0.05)

    assert doc["status"] == "done", doc.get("error_message")
    assert doc["chunk_count"] > 0
    return doc_id


async def _run_flow(app, client) -> None:
    doc_id = await _upload_and_wait(app, client)

    # --- pipeline audit trail --------------------------------------------------
    events = await app.state.event_repo.list_for_document(doc_id)
    assert [e.status for e in events] == [
        "queued",
        "parsing",
        "chunking",
        "embedding",
        "indexing",
        "done",
    ]
    done_detail = events[-1].detail or {}
    assert done_detail["duplicate_count"] >= 1
    assert done_detail["indexed_count"] == done_detail["chunk_count"] - done_detail[
        "duplicate_count"
    ]

    # --- search ----------------------------------------------------------------
    response = await client.post(
        "/api/search", json={"query": "powerhouse of the cell", "debug": True}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    hits = body["hits"]
    assert hits, "expected at least one hit"
    top = hits[0]
    assert top["rank"] == 1
    assert top["document_id"] == doc_id
    assert "powerhouse" in top["text"]
    assert top["fused_score"] > 0
    assert "rerank_score" in top
    covered = [
        top["text"][span["start"] : span["end"]].lower() for span in top["term_highlights"]
    ]
    assert "powerhouse" in covered
    for field in ("embed_ms", "dense_ms", "bm25_ms", "fuse_ms", "rerank_ms", "total_ms"):
        assert body["timings"][field] >= 0
    assert body["debug"]["dense_ranking"]
    assert body["debug"]["bm25_ranking"]
    print(f"\nsearch timings: {body['timings']}")  # noqa: T201 - real latency for the report

    # --- SSE replay after completion -------------------------------------------
    statuses: list[str] = []
    async with client.stream("GET", f"/api/documents/{doc_id}/events") as stream:
        async for line in stream.aiter_lines():
            if line.startswith("data:"):
                statuses.append(json.loads(line[5:].strip())["status"])
    # Full history replays and the stream closes itself on the terminal event.
    assert statuses[0] == "queued"
    assert statuses[-1] == "done"

    # --- delete purges the indexes ----------------------------------------------
    assert (await client.delete(f"/api/documents/{doc_id}")).status_code == 204
    response = await client.post("/api/search", json={"query": "powerhouse of the cell"})
    assert response.status_code == 200
    assert all(hit["document_id"] != doc_id for hit in response.json()["hits"])


async def test_ingest_search_fast(app, client):
    """Fast tier: fake models (via the conftest autouse fixture), everything else real."""
    await _run_flow(app, client)


@pytest.mark.slow
async def test_ingest_search_real(app, client):
    """Real tier: true bge-small + cross-encoder. Proves the exact production path."""
    await _run_flow(app, client)
