"""End-to-end graph flow over the real app: upload -> ingest -> recompute ->
graph API -> delete.

Two tiers, same shape:
- Fast (default): FakeEmbedder/FakeEntityExtractor via the conftest autouse
  fixture. sklearn/scipy run for REAL (normal deps, fast, no download) — only
  spaCy and torch are faked.
- Slow (``pytest -m slow``): the true bge + en_core_web_sm models — the
  known-shared-entity test, and the source of real recompute latency numbers.

Polling GET /api/graph is deliberate: the worker marks a document ``done``
BEFORE its recompute finishes (the graph is a post-done side effect), so "both
docs done" does not yet imply "edges written".
"""

import asyncio
import json

import pytest

# A distinctive capitalized name both docs share, plus overlapping vocabulary so
# every signal (entity, topic, semantic) has something to fire on.
_DOC_A = (
    "Zephyrium Corporation announced a quantum encryption product. "
    "Research at Zephyrium Corporation focuses on lattice cryptography, "
    "secure key exchange, and encryption performance for cloud workloads."
)
_DOC_B = (
    "A security review of Zephyrium Corporation examined lattice cryptography "
    "weaknesses. Zephyrium Corporation ships encryption libraries implementing "
    "secure key exchange for cloud workloads."
)

# Slow tier uses a real-world entity en_core_web_sm reliably tags as ORG.
_REAL_DOC_A = (
    "Microsoft released a new version of Azure confidential computing. "
    "Microsoft Azure provides trusted execution environments that isolate "
    "sensitive cloud workloads from the hypervisor."
)
_REAL_DOC_B = (
    "A security audit of Microsoft Azure examined trusted execution "
    "environments. Microsoft documented the isolation guarantees offered to "
    "confidential cloud workloads."
)


@pytest.fixture
def graph_env(monkeypatch):
    """Runs before ``settings`` builds (listed first in test signatures): a low
    edge threshold makes edge existence deterministic across tiers."""
    monkeypatch.setenv("DOCMESH_GRAPH__EDGE_THRESHOLD", "0.01")


async def _upload_txt(client, name: str, text: str) -> str:
    response = await client.post(
        "/api/documents", files={"file": (name, text.encode("utf-8"), "text/plain")}
    )
    assert response.status_code == 202, response.text
    return response.json()["document"]["id"]


async def _wait_done(client, doc_id: str, timeout: float = 120.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        doc = (await client.get(f"/api/documents/{doc_id}")).json()
        if doc["status"] in ("done", "failed"):
            break
        assert asyncio.get_event_loop().time() < deadline, f"ingestion timed out: {doc}"
        await asyncio.sleep(0.05)
    assert doc["status"] == "done", doc.get("error_message")


async def _wait_graph(client, predicate, timeout: float = 60.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        response = await client.get("/api/graph")
        assert response.status_code == 200, response.text
        body = response.json()
        if predicate(body):
            return body
        assert asyncio.get_event_loop().time() < deadline, f"graph never converged: {body}"
        await asyncio.sleep(0.1)


async def _run_flow(app, client, doc_a_text: str, doc_b_text: str, entity: str) -> None:
    id_a = await _upload_txt(client, "a.txt", doc_a_text)
    id_b = await _upload_txt(client, "b.txt", doc_b_text)
    await _wait_done(client, id_a)
    await _wait_done(client, id_b)

    # Wait for a CONSISTENT graph, not merely a non-empty one: recompute writes
    # edges before analysis rows (the analysis write is the completion marker),
    # so polling on edges alone can catch the in-between window where meta.stale
    # is still True and nodes lack entities.
    body = await _wait_graph(client, lambda b: b["edges"] and not b["meta"]["stale"])

    # --- nodes -----------------------------------------------------------------
    assert {n["id"] for n in body["nodes"]} == {id_a, id_b}
    for node in body["nodes"]:
        assert node["top_entities"], f"node {node['filename']} has no entities"
        assert node["chunk_count"] > 0

    # --- the edge --------------------------------------------------------------
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert {edge["source"], edge["target"]} == {id_a, id_b}
    assert edge["source"] < edge["target"]  # canonical ordering on the wire
    assert edge["entity_score"] > 0
    assert entity in [e["text"] for e in edge["shared_entities"]]
    assert edge["combined_score"] >= body["meta"]["threshold"]
    assert edge["dominant_signal"] in ("semantic", "entity", "topic")
    assert 0.0 <= edge["semantic_score"] <= 1.0
    assert 0.0 <= edge["topic_score"] <= 1.0

    # --- meta / staleness ------------------------------------------------------
    meta = body["meta"]
    assert meta["document_count"] == 2
    assert meta["edge_count"] == 1
    assert meta["stale"] is False  # analysis rows written last, under this hash
    stored = await app.state.edge_repo.list_all()
    assert stored[0].params_hash == meta["params_hash"]

    # --- edge detail, both orders ----------------------------------------------
    for source, target in ((id_a, id_b), (id_b, id_a)):
        response = await client.get(f"/api/graph/edges/{source}/{target}")
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["edge"]["id"] == edge["id"]
        assert detail["top_pairs"], "expected hydrated evidence pairs"
        pair = detail["top_pairs"][0]
        assert pair["a"]["text"] and pair["b"]["text"]
        assert pair["a"]["document_id"] == edge["source"]
        assert pair["b"]["document_id"] == edge["target"]
    assert (await client.get(f"/api/graph/edges/{id_a}/{'f' * 32}")).status_code == 404

    # --- manual recompute is idempotent ----------------------------------------
    response = await client.post("/api/graph/recompute")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["edge_count"] == 1
    assert result["document_count"] == 2
    assert result["params_hash"] == meta["params_hash"]

    # --- graph events reached the audit log ------------------------------------
    events = await app.state.event_repo.list_for_document(id_b)
    statuses = [e.status for e in events]
    assert "graph_start" in statuses and "graph_done" in statuses
    done_event = next(e for e in events if e.status == "graph_done")
    print(  # noqa: T201 - real recompute latency for the report
        f"\ngraph_done duration_ms={done_event.duration_ms} detail={json.dumps(done_event.detail)}"
    )

    # --- delete removes the edge -----------------------------------------------
    assert (await client.delete(f"/api/documents/{id_a}")).status_code == 204
    body = await _wait_graph(
        client, lambda b: not b["edges"] and len(b["nodes"]) == 1
    )
    assert body["nodes"][0]["id"] == id_b


async def test_graph_flow_fast(graph_env, app, client) -> None:
    """Fast tier: fake spaCy/torch, real sklearn + FAISS + SQLite + worker.
    The fake extractor emits single capitalized tokens, hence "zephyrium"
    (the real spaCy span "zephyrium corporation" belongs to the slow tier)."""
    await _run_flow(app, client, _DOC_A, _DOC_B, entity="zephyrium")


@pytest.mark.slow
async def test_graph_flow_real(graph_env, app, client) -> None:
    """Real tier: en_core_web_sm NER + bge embeddings — the known-shared-entity
    test, printing true recompute latency."""
    await _run_flow(app, client, _REAL_DOC_A, _REAL_DOC_B, entity="microsoft")
