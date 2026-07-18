"""Edge + analysis repositories against a real migrated SQLite file — no mocks.

Also proves migration 0002 applied (document_analysis exists) and that the FK
CASCADE wiring removes derived graph rows when a document dies.
"""

from app.schemas.documents import DocumentCreate, FileType
from app.schemas.graph import (
    DocumentAnalysisCreate,
    EdgeCreate,
    EntityWeight,
    SharedEntity,
    TopicWeight,
    TopPair,
)
from app.storage.sql.analysis_repo import SqlDocumentAnalysisRepository
from app.storage.sql.document_repo import SqlDocumentRepository
from app.storage.sql.edge_repo import SqlEdgeRepository

_HASH = "0" * 64


async def _make_docs(engine, n: int) -> list[str]:
    repo = SqlDocumentRepository(engine)
    ids = []
    for i in range(n):
        doc = await repo.create(
            DocumentCreate(
                original_filename=f"doc-{i}.txt",
                stored_filename=f"stored-{i}.txt",
                file_type=FileType.TXT,
                size_bytes=100 + i,
                sha256=f"{i:064x}",
            )
        )
        ids.append(doc.id)
    return sorted(ids)  # canonical order for edge construction


def _edge(source: str, target: str, combined: float = 0.5) -> EdgeCreate:
    return EdgeCreate(
        source_doc_id=source,
        target_doc_id=target,
        semantic_score=0.4,
        entity_score=0.6,
        topic_score=0.2,
        combined_score=combined,
        top_pairs=[TopPair(a="ca", b="cb", sim=0.91)],
        shared_entities=[
            SharedEntity(text="zephyrium", label="ORG", idf=1.1, count_a=2, count_b=3)
        ],
        params_hash=_HASH,
    )


async def test_upsert_list_roundtrip(engine) -> None:
    a, b = await _make_docs(engine, 2)
    repo = SqlEdgeRepository(engine)
    await repo.upsert_many([_edge(a, b)])

    edges = await repo.list_all()
    assert len(edges) == 1
    edge = edges[0]
    # JSON columns come back as Pydantic models, not dicts.
    assert edge.top_pairs == [TopPair(a="ca", b="cb", sim=0.91)]
    assert edge.shared_entities[0].text == "zephyrium"
    assert edge.shared_entities[0].count_b == 3
    assert edge.params_hash == _HASH
    assert edge.created_at.tzinfo is not None


async def test_get_is_order_insensitive(engine) -> None:
    a, b = await _make_docs(engine, 2)
    repo = SqlEdgeRepository(engine)
    await repo.upsert_many([_edge(a, b)])

    forward = await repo.get(a, b)
    backward = await repo.get(b, a)
    assert forward is not None and backward is not None
    assert forward == backward
    assert await repo.get(a, "f" * 32) is None


async def test_reupsert_replaces_not_duplicates(engine) -> None:
    a, b = await _make_docs(engine, 2)
    repo = SqlEdgeRepository(engine)
    await repo.upsert_many([_edge(a, b, combined=0.5)])
    await repo.upsert_many([_edge(a, b, combined=0.9)])

    edges = await repo.list_all()
    assert len(edges) == 1
    assert edges[0].combined_score == 0.9


async def test_delete_all_and_for_document(engine) -> None:
    a, b, c = await _make_docs(engine, 3)
    repo = SqlEdgeRepository(engine)
    await repo.upsert_many([_edge(a, b), _edge(a, c), _edge(b, c)])

    assert await repo.delete_for_document(a) == 2
    remaining = await repo.list_all()
    assert [(e.source_doc_id, e.target_doc_id) for e in remaining] == [(b, c)]
    assert await repo.delete_all() == 1
    assert await repo.list_all() == []


async def test_document_delete_cascades_edge_and_analysis(engine) -> None:
    a, b = await _make_docs(engine, 2)
    edge_repo = SqlEdgeRepository(engine)
    analysis_repo = SqlDocumentAnalysisRepository(engine)
    await edge_repo.upsert_many([_edge(a, b)])
    await analysis_repo.replace_all(
        [
            DocumentAnalysisCreate(
                document_id=doc_id,
                dominant_topic_id=0,
                top_topics=[],
                entities=[],
                params_hash=_HASH,
            )
            for doc_id in (a, b)
        ]
    )

    await SqlDocumentRepository(engine).delete(a)
    assert await edge_repo.list_all() == []
    assert await analysis_repo.get(a) is None
    assert await analysis_repo.get(b) is not None  # only the dead doc's row cascades


async def test_analysis_replace_all_roundtrip(engine) -> None:
    (a,) = await _make_docs(engine, 1)
    repo = SqlDocumentAnalysisRepository(engine)
    create = DocumentAnalysisCreate(
        document_id=a,
        dominant_topic_id=2,
        top_topics=[TopicWeight(topic_id=2, weight=0.7, terms=["neural", "training"])],
        entities=[EntityWeight(text="zephyrium", label="ORG", idf=1.1, count=4)],
        params_hash=_HASH,
    )
    await repo.replace_all([create])
    stored = await repo.get(a)
    assert stored is not None
    assert stored.top_topics == create.top_topics
    assert stored.entities == create.entities

    # replace_all is wholesale: an empty list empties the table.
    await repo.replace_all([])
    assert await repo.list_all() == []
