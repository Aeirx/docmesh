"""Hand-built test files. No fixture binaries checked into the repo — every byte is
constructed here so it's obvious what each file does and why it passes or fails."""

import io
import zipfile


def tiny_pdf() -> bytes:
    """A minimal but structurally valid single-page PDF (~350 bytes), with a real
    xref table whose offsets are computed, not hardcoded."""
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref_pos = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_pos,
    )
    return bytes(out)


def tiny_docx() -> bytes:
    """A minimal OOXML docx: a ZIP containing [Content_Types].xml + word/document.xml."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Hello DocMesh</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


def fake_pdf_wrong_magic() -> bytes:
    """Bytes that are really a ZIP/docx — used with a claimed .pdf extension."""
    return tiny_docx()


def exe_bytes() -> bytes:
    """An MZ (PE executable) header followed by non-UTF-8 garbage."""
    return b"MZ\x90\x00\x03\x00\x00\x00\xff\xfe\x81\x82" + b"\x00" * 32


def binary_garbage() -> bytes:
    """No known magic and not valid UTF-8 — rejected for every claimed extension."""
    return b"\xff\xfe\xfd\xfc" + bytes(range(128, 256))


def zip_bomb_many_entries(entries: int = 201) -> bytes:
    """A ZIP exceeding the entry-count guard (looks like it could be a docx)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for i in range(entries):
            zf.writestr(f"part{i}.xml", "<x/>")
    return buf.getvalue()


class FakeUpload:
    """Minimal stand-in for FastAPI's UploadFile: async chunked read over bytes."""

    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


class OversizedStream:
    """Yields ``total`` bytes of 'a' without ever materializing them all — lets the
    cap tests use arbitrarily large logical sizes with constant memory."""

    def __init__(self, total: int) -> None:
        self._remaining = total

    async def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        n = self._remaining if size < 0 else min(size, self._remaining)
        self._remaining -= n
        return b"a" * n


def oversized_stream(total: int) -> OversizedStream:
    return OversizedStream(total)
