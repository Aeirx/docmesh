"""Query-scoped graph annotation (Phase 5): GET /api/graph?query=... adds
calibrated per-node relevance + match counts; without a query those fields are
absent, keeping the response wire-identical to Phase 4 (exclude_none).

FakeEmbedder note: the fast tier embeds hashed bags-of-words, and the server
calibrates raw cosine with the measured bge floor of 0.5 — so the query must
lexically mirror a chunk heavily to clear the floor. Reusing a full sentence
verbatim from doc A guarantees that; a disjoint-vocabulary doc lands near 0.
"""

import asyncio

# Doc A: distinctive crypto vocabulary. The query below is its first sentence.
_DOC_A = (
    "Zephyrium Corporation announced a quantum encryption product line. "
    "Research at Zephyrium Corporation focuses on lattice cryptography, "
    "secure key exchange, and encryption performance for cloud workloads."
)
_QUERY = "Zephyrium Corporation announced a quantum encryption product line."

# Doc B: deliberately disjoint vocabulary (no token overlap with the query).
_DOC_B = (
    "Tomato seedlings thrive in loamy soil with regular watering. "
    "Prune basil weekly and mulch the garden beds before summer heat arrives."
)


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


async def test_graph_query_annotates_relevance_and_match_counts(app, client) -> None:
    id_a = await _upload_txt(client, "crypto.txt", _DOC_A)
    id_b = await _upload_txt(client, "garden.txt", _DOC_B)
    await _wait_done(client, id_a)
    await _wait_done(client, id_b)

    response = await client.get("/api/graph", params={"query": _QUERY})
    assert response.status_code == 200, response.text
    body = response.json()

    nodes = {n["id"]: n for n in body["nodes"]}
    assert set(nodes) == {id_a, id_b}

    # Doc A lexically contains the query sentence -> calibrated relevance well
    # above zero and at least one chunk over the match threshold.
    assert nodes[id_a]["relevance"] > 0
    assert nodes[id_a]["match_count"] >= 1
    # Doc B shares no vocabulary -> raw cosine below the 0.5 floor -> 0 after
    # calibration, and no matching chunks.
    assert nodes[id_b]["relevance"] < body["meta"]["relevance_threshold"]
    assert nodes[id_b]["match_count"] == 0
    # The matching doc must clear the threshold the server itself shipped.
    assert nodes[id_a]["relevance"] >= body["meta"]["relevance_threshold"]

    meta = body["meta"]
    assert meta["query"] == _QUERY
    assert meta["relevance_threshold"] == 0.35


async def test_graph_without_query_omits_query_fields(app, client) -> None:
    """Backward compat: non-query responses carry none of the query-mode fields
    (response_model_exclude_none strips the Nones from the wire)."""
    id_a = await _upload_txt(client, "solo.txt", _DOC_A)
    await _wait_done(client, id_a)

    body = (await client.get("/api/graph")).json()
    for node in body["nodes"]:
        assert "relevance" not in node
        assert "match_count" not in node
    assert "query" not in body["meta"]
    assert "relevance_threshold" not in body["meta"]
