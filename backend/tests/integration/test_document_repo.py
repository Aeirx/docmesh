"""DocumentRepository against a real migrated SQLite file — no mocks."""

from app.schemas.documents import DocumentCreate, DocumentStatus, FileType
from app.storage.sql.document_repo import SqlDocumentRepository


def _make_create(n: int = 0) -> DocumentCreate:
    return DocumentCreate(
        original_filename=f"report-{n}.pdf",
        stored_filename=f"stored-{n}.pdf",
        file_type=FileType.PDF,
        size_bytes=1000 + n,
        sha256=f"{n:064x}",
    )


async def test_create_and_get(engine) -> None:
    repo = SqlDocumentRepository(engine)
    created = await repo.create(_make_create())
    assert created.status is DocumentStatus.QUEUED
    assert created.chunk_count == 0

    fetched = await repo.get(created.id)
    assert fetched is not None
    assert fetched == created

    assert await repo.get("does-not-exist") is None


async def test_get_by_sha256(engine) -> None:
    repo = SqlDocumentRepository(engine)
    created = await repo.create(_make_create(1))
    found = await repo.get_by_sha256(created.sha256)
    assert found is not None
    assert found.id == created.id
    assert await repo.get_by_sha256("f" * 64) is None


async def test_status_transitions(engine) -> None:
    repo = SqlDocumentRepository(engine)
    doc = await repo.create(_make_create(2))

    for status in (
        DocumentStatus.PARSING,
        DocumentStatus.CHUNKING,
        DocumentStatus.EMBEDDING,
        DocumentStatus.INDEXING,
        DocumentStatus.DONE,
    ):
        await repo.update_status(doc.id, status)
        current = await repo.get(doc.id)
        assert current is not None
        assert current.status is status
        assert current.error_message is None
        assert current.updated_at >= doc.updated_at

    await repo.update_status(doc.id, DocumentStatus.FAILED, error_message="parser exploded")
    failed = await repo.get(doc.id)
    assert failed is not None
    assert failed.status is DocumentStatus.FAILED
    assert failed.error_message == "parser exploded"


async def test_set_stats(engine) -> None:
    repo = SqlDocumentRepository(engine)
    doc = await repo.create(_make_create(3))
    await repo.set_stats(doc.id, page_count=12, chunk_count=48)
    updated = await repo.get(doc.id)
    assert updated is not None
    assert updated.page_count == 12
    assert updated.chunk_count == 48


async def test_list_pagination_and_filter(engine) -> None:
    repo = SqlDocumentRepository(engine)
    docs = [await repo.create(_make_create(n)) for n in range(5)]
    await repo.update_status(docs[0].id, DocumentStatus.DONE)

    items, total = await repo.list(offset=0, limit=2)
    assert total == 5
    assert len(items) == 2

    items, total = await repo.list(offset=4, limit=2)
    assert total == 5
    assert len(items) == 1

    done_items, done_total = await repo.list(status=DocumentStatus.DONE)
    assert done_total == 1
    assert done_items[0].id == docs[0].id

    queued_items, queued_total = await repo.list(status=DocumentStatus.QUEUED)
    assert queued_total == 4


async def test_delete(engine) -> None:
    repo = SqlDocumentRepository(engine)
    doc = await repo.create(_make_create(4))
    assert await repo.delete(doc.id) is True
    assert await repo.get(doc.id) is None
    assert await repo.delete(doc.id) is False
