"""Table-driven tests for the upload security core — pure functions, no server."""

import hashlib

import pytest

from app.ingestion.validators import (
    UploadValidationError,
    detect_file_type,
    sanitize_filename,
    stream_to_disk_capped,
)
from app.schemas.documents import FileType
from tests.fixtures.make_files import (
    FakeUpload,
    binary_garbage,
    exe_bytes,
    fake_pdf_wrong_magic,
    oversized_stream,
    tiny_docx,
    tiny_pdf,
    zip_bomb_many_entries,
)

# --- sanitize_filename -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Path traversal, both separator styles, reduces to the basename
        ("..\\..\\evil.txt", "evil.txt"),
        ("../../evil.txt", "evil.txt"),
        ("/etc/passwd", "passwd"),
        ("C:\\Users\\x\\notes.pdf", "notes.pdf"),
        # Windows reserved device names get renamed, case-insensitively
        ("C:\\x\\CON.pdf", "_CON.pdf"),
        ("nul.txt", "_nul.txt"),
        ("COM7.docx", "_COM7.docx"),
        # NUL bytes and control chars are stripped
        ("file\x00name.txt", "filename.txt"),
        ("a\x01\x02b\x1f.md", "ab.md"),
        # Whitespace collapsed, trailing dots/spaces removed
        ("  report    final  .txt", "report final .txt"),
        ("trailing...", "trailing"),
        # Degenerate inputs fall back
        ("", "unnamed"),
        ("....", "unnamed"),
        ("\x00\x01", "unnamed"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_caps_length_and_keeps_extension() -> None:
    out = sanitize_filename("a" * 400 + ".pdf")
    assert len(out) <= 255
    assert out.endswith(".pdf")


# --- detect_file_type ------------------------------------------------------------


# Explicit ids: without them pytest embeds the raw file bytes in the test id, which
# overflows the Windows 32k env-var limit via PYTEST_CURRENT_TEST.
@pytest.mark.parametrize(
    ("data", "ext", "expected"),
    [
        (tiny_pdf(), "pdf", FileType.PDF),
        (tiny_docx(), "docx", FileType.DOCX),
        (b"plain text content", "txt", FileType.TXT),
        ("# heading\nutf-8 ✓".encode(), "md", FileType.MD),
    ],
    ids=["pdf", "docx", "txt", "md"],
)
def test_detect_file_type_accepts_valid(data: bytes, ext: str, expected: FileType) -> None:
    assert detect_file_type(data[:8], data, ext) is expected


@pytest.mark.parametrize(
    ("data", "ext", "code"),
    [
        # ZIP content claiming to be a PDF
        (fake_pdf_wrong_magic(), "pdf", "magic_mismatch"),
        # Real PDF claiming to be text
        (tiny_pdf(), "txt", "magic_mismatch"),
        # Plain text claiming to be a docx
        (b"just some text", "docx", "magic_mismatch"),
        # EXE header under any claimed extension
        (exe_bytes(), "pdf", "unsupported_type"),
        (exe_bytes(), "txt", "unsupported_type"),
        # Binary garbage claiming .txt
        (binary_garbage(), "txt", "unsupported_type"),
        # Disallowed extension outright
        (b"hello", "exe", "unsupported_type"),
        # Empty file
        (b"", "txt", "empty_file"),
        # Zip bomb: too many archive entries
        (zip_bomb_many_entries(), "docx", "zip_bomb"),
    ],
    ids=[
        "zip-claiming-pdf",
        "pdf-claiming-txt",
        "text-claiming-docx",
        "exe-claiming-pdf",
        "exe-claiming-txt",
        "garbage-claiming-txt",
        "disallowed-ext",
        "empty-file",
        "zip-bomb-entries",
    ],
)
def test_detect_file_type_rejects(data: bytes, ext: str, code: str) -> None:
    with pytest.raises(UploadValidationError) as exc_info:
        detect_file_type(data[:8], data, ext)
    assert exc_info.value.code == code


def test_detect_file_type_reads_from_disk(tmp_path) -> None:
    path = tmp_path / "doc.bin"
    path.write_bytes(tiny_docx())
    assert detect_file_type(path.read_bytes()[:8], path, "docx") is FileType.DOCX


# --- stream_to_disk_capped -------------------------------------------------------


async def test_stream_returns_size_and_sha256(tmp_path) -> None:
    data = b"docmesh streaming test payload"
    dest = tmp_path / "out.bin"
    size, digest = await stream_to_disk_capped(FakeUpload(data), dest, max_bytes=1024)
    assert size == len(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert dest.read_bytes() == data


async def test_stream_over_cap_rejects_and_cleans_up(tmp_path) -> None:
    # cap + 1: the exact boundary. The cap value is a parameter, so a small cap
    # exercises the same code path as 25 MB + 1 without shipping 25 MB.
    cap = 64 * 1024
    dest = tmp_path / "big.bin"
    with pytest.raises(UploadValidationError) as exc_info:
        await stream_to_disk_capped(oversized_stream(cap + 1), dest, max_bytes=cap)
    assert exc_info.value.code == "too_large"
    assert not dest.exists()  # no partial file left on disk


async def test_stream_exactly_at_cap_is_accepted(tmp_path) -> None:
    cap = 4096
    dest = tmp_path / "exact.bin"
    size, _ = await stream_to_disk_capped(oversized_stream(cap), dest, max_bytes=cap)
    assert size == cap
    assert dest.exists()


async def test_stream_empty_upload_rejected(tmp_path) -> None:
    dest = tmp_path / "empty.bin"
    with pytest.raises(UploadValidationError) as exc_info:
        await stream_to_disk_capped(FakeUpload(b""), dest, max_bytes=1024)
    assert exc_info.value.code == "empty_file"
    assert not dest.exists()
