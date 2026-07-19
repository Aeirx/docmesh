"""Explanation endpoint over the real app: generate -> cache -> refresh ->
rate limit -> template degrade.

Reuses the Phase-3 graph-flow corpus (two docs sharing a distinctive entity)
to obtain a real edge; the conftest autouse fixture has already swapped
LocalLlamaClient for FakeLLM, so the fast tier never loads a model.
"""

import pytest
from sqlalchemy import func, select

from app.storage.tables import edge_explanations
from tests.integration.test_graph_flow import (
    _DOC_A,
    _DOC_B,
    _upload_txt,
    _wait_done,
    _wait_graph,
)


@pytest.fixture
def explain_env(monkeypatch):
    """Runs before ``settings`` builds (listed first in test signatures)."""
    monkeypatch.setenv("DOCMESH_GRAPH__EDGE_THRESHOLD", "0.01")


@pytest.fixture
def rpm1_env(explain_env, monkeypatch):
    monkeypatch.setenv("DOCMESH_LLM__RPM_LIMIT", "1")


@pytest.fixture
def disabled_env(explain_env, monkeypatch):
    monkeypatch.setenv("DOCMESH_LLM__ENABLED", "false")


async def _make_edge(client) -> tuple[str, str]:
    id_a = await _upload_txt(client, "a.txt", _DOC_A)
    id_b = await _upload_txt(client, "b.txt", _DOC_B)
    await _wait_done(client, id_a)
    await _wait_done(client, id_b)
    body = await _wait_graph(client, lambda b: b["edges"] and not b["meta"]["stale"])
    edge = body["edges"][0]
    return edge["source"], edge["target"]


async def _row_count(app) -> int:
    async with app.state.engine.connect() as conn:
        result = await conn.execute(
            select(func.count()).select_from(edge_explanations)
        )
        return result.scalar_one()


async def test_generate_cache_refresh_and_404(explain_env, app, client) -> None:
    source, target = await _make_edge(client)
    url = f"/api/graph/edges/{source}/{target}/explanation"

    # First GET generates and persists.
    response = await client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generator"] == "llm"
    assert body["model"] == "fake-llm"
    assert body["cached"] is False
    assert body["explanation"]
    assert body["input_tokens"] == 50 and body["output_tokens"] == 20
    assert body["duration_ms"] is not None
    assert body["source"] == source and body["target"] == target
    assert app.state.llm_client.calls == 1
    assert await _row_count(app) == 1

    # Second GET is a cache hit: no regeneration.
    cached = (await client.get(url)).json()
    assert cached["cached"] is True
    assert cached["explanation"] == body["explanation"]
    assert cached["duration_ms"] is None
    assert app.state.llm_client.calls == 1

    # Reversed order hits the same canonical cache row.
    reversed_body = (
        await client.get(f"/api/graph/edges/{target}/{source}/explanation")
    ).json()
    assert reversed_body["cached"] is True

    # refresh=true regenerates and replaces (upsert, not append).
    refreshed = (await client.get(f"{url}?refresh=true")).json()
    assert refreshed["cached"] is False
    assert app.state.llm_client.calls == 2
    assert await _row_count(app) == 1

    # Non-edge pair 404s.
    missing = await client.get(f"/api/graph/edges/{source}/{'f' * 32}/explanation")
    assert missing.status_code == 404


async def test_rate_limit_charges_generation_only(rpm1_env, app, client) -> None:
    source, target = await _make_edge(client)
    url = f"/api/graph/edges/{source}/{target}/explanation"

    # Capacity 1: the first generation consumes the only token.
    assert (await client.get(url)).status_code == 200

    # Cache hits are free — no 429 even with an empty bucket (deviation #3).
    cached = await client.get(url)
    assert cached.status_code == 200
    assert cached.json()["cached"] is True

    # Forcing a regeneration with an empty bucket is refused.
    limited = await client.get(f"{url}?refresh=true")
    assert limited.status_code == 429, limited.text
    assert limited.json()["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1


async def test_template_when_llm_disabled(disabled_env, app, client) -> None:
    source, target = await _make_edge(client)
    url = f"/api/graph/edges/{source}/{target}/explanation"
    assert app.state.llm_client is None

    body = (await client.get(url)).json()
    assert body["generator"] == "template"
    assert body["model"] == "template"
    assert body["cached"] is False
    assert body["input_tokens"] is None and body["output_tokens"] is None
    # Deterministic evidence prose, cached like any other explanation.
    assert "Signal scores:" in body["explanation"]
    again = (await client.get(url)).json()
    assert again["cached"] is True
    assert again["explanation"] == body["explanation"]


async def test_template_fallback_when_llm_unavailable(explain_env, app, client) -> None:
    source, target = await _make_edge(client)
    url = f"/api/graph/edges/{source}/{target}/explanation"
    app.state.llm_client.fail_unavailable = True

    response = await client.get(url)
    assert response.status_code == 200, response.text  # degrade, never a 500
    body = response.json()
    assert body["generator"] == "template"
    assert app.state.llm_client.calls == 1  # the LLM was attempted first
