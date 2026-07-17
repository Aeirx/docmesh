"""End-to-end upload flow through the real ASGI app (lifespan, migrations, disk, DB)."""

from tests.fixtures.make_files import tiny_pdf


async def test_upload_accepted_row_file_and_event(client, app, settings) -> None:
    files = {"file": ("report.pdf", tiny_pdf(), "application/pdf")}
    response = await client.post("/api/documents", files=files)
    assert response.status_code == 202
    doc = response.json()["document"]
    assert doc["status"] == "queued"
    assert doc["original_filename"] == "report.pdf"
    assert doc["file_type"] == "pdf"

    # File landed on disk as {id}.pdf — never under the user-supplied name.
    stored = settings.uploads_dir / f"{doc['id']}.pdf"
    assert stored.exists()
    assert doc["stored_filename"] == stored.name

    # A 'queued' audit event was appended.
    events = await app.state.event_repo.list_for_document(doc["id"])
    assert [e.status for e in events] == ["queued"]

    # Response carries the request id for log correlation.
    assert response.headers.get("x-request-id")


async def test_duplicate_content_is_409(client) -> None:
    files = {"file": ("first.pdf", tiny_pdf(), "application/pdf")}
    first = await client.post("/api/documents", files=files)
    assert first.status_code == 202
    existing_id = first.json()["document"]["id"]

    # Same bytes, different name: content hash decides, not the filename.
    dup = await client.post(
        "/api/documents", files={"file": ("renamed.pdf", tiny_pdf(), "application/pdf")}
    )
    assert dup.status_code == 409
    body = dup.json()
    assert body["code"] == "duplicate_document"
    assert existing_id in body["detail"]


async def test_list_get_delete_round_trip(client, settings) -> None:
    files = {"file": ("roundtrip.pdf", tiny_pdf(), "application/pdf")}
    doc = (await client.post("/api/documents", files=files)).json()["document"]

    listing = (await client.get("/api/documents")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == doc["id"]

    fetched = await client.get(f"/api/documents/{doc['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["sha256"] == doc["sha256"]

    deleted = await client.delete(f"/api/documents/{doc['id']}")
    assert deleted.status_code == 204
    assert not (settings.uploads_dir / doc["stored_filename"]).exists()

    assert (await client.get(f"/api/documents/{doc['id']}")).status_code == 404
    assert (await client.delete(f"/api/documents/{doc['id']}")).status_code == 404


async def test_oversized_upload_is_413(client, settings) -> None:
    # conftest caps uploads at 1 MB precisely so this test stays fast.
    too_big = b"a" * (settings.max_upload_bytes + 1)
    response = await client.post(
        "/api/documents", files={"file": ("big.txt", too_big, "text/plain")}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "too_large"
    # Nothing was left behind in the uploads dir.
    assert list(settings.uploads_dir.iterdir()) == []


async def test_magic_mismatch_is_415(client) -> None:
    # Plain text bytes claiming to be a PDF.
    response = await client.post(
        "/api/documents", files={"file": ("fake.pdf", b"not a pdf at all", "application/pdf")}
    )
    assert response.status_code == 415
    assert response.json()["code"] == "magic_mismatch"


async def test_hostile_filename_is_sanitized(client) -> None:
    response = await client.post(
        "/api/documents",
        files={"file": ("..\\..\\CON.pdf", tiny_pdf(), "application/pdf")},
    )
    assert response.status_code == 202
    doc = response.json()["document"]
    assert doc["original_filename"] == "_CON.pdf"  # traversal stripped, reserved name defused
    assert doc["stored_filename"] == f"{doc['id']}.pdf"
