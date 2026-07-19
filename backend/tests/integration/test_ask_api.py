"""POST /api/ask over the real app: upload -> ingest -> ask, with the FakeLLM
(conftest autouse) supplying deterministic answers. Real retrieval pipeline —
FAISS + BM25 + RRF + (fake) rerank — runs underneath."""

import asyncio

import pytest

_DOC_A = (
    "Alpha is an open framework for retrieval evaluation. "
    "Alpha ships a benchmark harness measuring recall and latency."
)
_DOC_B = (
    "The Beta report benchmarks Alpha against classical BM25 baselines "
    "and documents Alpha's recall improvements on long documents."
)


@pytest.fixture
def rpm1_env(monkeypatch):
    monkeypatch.setenv("DOCMESH_LLM__RPM_LIMIT", "1")


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


async def _corpus(client) -> None:
    for name, text in (("alpha.txt", _DOC_A), ("beta.txt", _DOC_B)):
        await _wait_done(client, await _upload_txt(client, name, text))


async def test_ask_returns_grounded_answer_with_verified_citations(app, client) -> None:
    await _corpus(client)
    app.state.llm_client.canned_text = (
        "Alpha is a retrieval evaluation framework [1]. "
        "It is benchmarked against BM25 baselines [2]. Bogus claim [9]."
    )

    response = await client.post("/api/ask", json={"question": "What is Alpha?"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["generator"] == "llm"
    assert body["model"] == "fake-llm"
    assert body["answer"]
    assert "[9]" not in body["answer"]  # hallucinated citation stripped
    evidence_chunks = {h["chunk_id"] for h in body["evidence"]}
    assert body["citations"], "expected at least one verified citation"
    for citation in body["citations"]:
        assert citation["chunk_id"] in evidence_chunks
        assert 1 <= citation["marker"] <= body["context_chunks"]
    # evidence is the full SearchHit shape — retrieval never hidden
    hit = body["evidence"][0]
    for field in ("rerank_score", "fused_score", "filename", "text", "rank"):
        assert field in hit
    assert body["context_chunks"] >= 1
    assert body["timings"]["retrieval"]["total_ms"] >= 0
    assert body["timings"]["generate_ms"] >= 0


async def test_ask_rate_limited_after_bucket_drains(rpm1_env, app, client) -> None:
    await _corpus(client)

    first = await client.post("/api/ask", json={"question": "What is Alpha?"})
    assert first.status_code == 200

    second = await client.post("/api/ask", json={"question": "And Beta?"})
    assert second.status_code == 429
    assert second.json()["code"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in second.headers}
    # generation ran exactly once — the 429 request never touched the model
    assert app.state.llm_client.calls == 1


async def test_ask_unavailable_llm_still_returns_evidence(app, client) -> None:
    await _corpus(client)
    app.state.llm_client.fail_unavailable = True

    response = await client.post("/api/ask", json={"question": "What is Alpha?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generator"] == "unavailable"
    assert body["answer"] == ""
    assert body["evidence"], "retrieval must survive LLM failure"


async def test_ask_no_evidence_on_empty_corpus(app, client) -> None:
    response = await client.post("/api/ask", json={"question": "anything at all?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generator"] == "no_evidence"
    assert body["evidence"] == []
    assert app.state.llm_client.calls == 0  # model never ran


async def test_blank_question_is_422(client) -> None:
    assert (await client.post("/api/ask", json={"question": "   "})).status_code == 422
