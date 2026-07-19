"""Explanation repository against a real migrated SQLite file — no mocks."""

from app.schemas.graph import EdgeExplanationCreate
from app.storage.sql.edge_repo import SqlEdgeRepository
from app.storage.sql.explanation_repo import SqlExplanationRepository
from tests.integration.test_edge_repo import _edge, _make_docs

_KEY = "c" * 64


def _create(cache_key: str = _KEY, edge_id: str | None = None) -> EdgeExplanationCreate:
    return EdgeExplanationCreate(
        cache_key=cache_key,
        edge_id=edge_id,
        model="fake-llm",
        explanation="Both documents cover Alpha.",
        input_tokens=50,
        output_tokens=20,
    )


async def test_upsert_get_roundtrip(engine) -> None:
    repo = SqlExplanationRepository(engine)
    record = await repo.upsert(_create())
    assert record.id > 0
    assert record.created_at.tzinfo is not None

    fetched = await repo.get_by_cache_key(_KEY)
    assert fetched == record
    assert await repo.get_by_cache_key("d" * 64) is None


async def test_upsert_same_key_replaces(engine) -> None:
    repo = SqlExplanationRepository(engine)
    await repo.upsert(_create())
    replacement = _create()
    replacement = replacement.model_copy(update={"explanation": "Rewritten."})
    await repo.upsert(replacement)

    fetched = await repo.get_by_cache_key(_KEY)
    assert fetched is not None
    assert fetched.explanation == "Rewritten."


async def test_delete_for_edge(engine) -> None:
    a, b = await _make_docs(engine, 2)
    await SqlEdgeRepository(engine).upsert_many([_edge(a, b)])
    edges = await SqlEdgeRepository(engine).list_all()
    edge_id = edges[0].id

    repo = SqlExplanationRepository(engine)
    await repo.upsert(_create(cache_key="1" * 64, edge_id=edge_id))
    await repo.upsert(_create(cache_key="2" * 64, edge_id=edge_id))
    await repo.upsert(_create(cache_key="3" * 64, edge_id=None))

    assert await repo.delete_for_edge(edge_id) == 2
    assert await repo.get_by_cache_key("1" * 64) is None
    assert await repo.get_by_cache_key("3" * 64) is not None
