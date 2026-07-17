"""Upload validation primitives — the security core of ingestion.

Uploads are hostile input. Everything here is a pure function (no FastAPI, no DB) so
each check is table-driven-testable in isolation. Design rules:

1. Never trust anything the client claims: not Content-Length, not the extension, not
   the MIME type. Size is enforced while streaming; type is sniffed from bytes on disk.
2. The sanitized filename is for display/DB ONLY. Files on disk are always named
   ``{uuid4hex}.{sniffed_ext}`` — no user-controlled string ever becomes a path.
3. A magic/extension disagreement is a hard reject, never a silent correction: an EXE
   renamed evil.pdf should fail loudly, not be "helpfully" stored as something else.

Windows note: file handles are always closed (context managers) before os.replace or
unlink — Windows refuses to delete/replace open files, which breaks cleanup and tests.
"""

import hashlib
import io
import ntpath
import posixpath
import zipfile
from pathlib import Path
from typing import Protocol

from app.schemas.documents import FileType

# 1 MB streaming granularity: small enough to bound memory, large enough to not
# bottleneck on syscalls.
_CHUNK_SIZE = 1024 * 1024

# DOCX zip-bomb guards. A legitimate DOCX has a few dozen entries; 200 entries or
# 50 MB declared-decompressed is far beyond any real document and cheap to check
# BEFORE any parser touches the archive.
_ZIP_MAX_ENTRIES = 200
_ZIP_MAX_UNCOMPRESSED = 50 * 1024 * 1024

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

# Windows device names are reserved regardless of extension: "CON.pdf" still resolves
# to the console device on some APIs.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "txt", "md"})


class UploadValidationError(Exception):
    """Typed validation failure. ``code`` is stable and machine-readable; the API
    layer maps it to an HTTP status (too_large -> 413, unsupported_type /
    magic_mismatch -> 415, everything else -> 400)."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class AsyncReadable(Protocol):
    """Anything with an async chunked read — satisfied by FastAPI's UploadFile."""

    async def read(self, size: int = -1) -> bytes: ...


def sanitize_filename(name: str) -> str:
    """Make a client-supplied filename safe to display and store in the DB.

    NOT safe for filesystem use — stored files are named ``{uuid}.{ext}`` instead.
    Strips path components (both separator styles, so "..\\..\\evil.txt" and
    "/etc/passwd" both reduce to their basename), control characters, Windows
    reserved device names, collapses whitespace, and caps length at 255.
    """
    # basename twice, once per separator convention: ntpath handles "\\", posixpath "/".
    # Order-independent because each pass only ever shortens the string.
    name = posixpath.basename(ntpath.basename(name))
    # Drop C0 control chars (includes NUL — classic filesystem-API confusion vector)
    # and DEL.
    name = "".join(ch for ch in name if ord(ch) >= 0x20 and ch != "\x7f")
    # Collapse runs of whitespace to single spaces and trim.
    name = " ".join(name.split())
    # Windows also chokes on trailing dots/spaces.
    name = name.rstrip(". ")

    stem = name.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"

    if len(name) > 255:
        # Keep the extension visible when truncating.
        stem_part, dot, ext_part = name.rpartition(".")
        if dot and len(ext_part) < 16:
            name = stem_part[: 255 - len(ext_part) - 1] + "." + ext_part
        else:
            name = name[:255]

    return name or "unnamed"


def _verify_docx_zip(source: Path | bytes) -> None:
    """Confirm a PK-headed blob is a plausible OOXML docx and not a zip bomb."""
    opened: zipfile.ZipFile
    try:
        if isinstance(source, bytes):
            opened = zipfile.ZipFile(io.BytesIO(source))
        else:
            opened = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise UploadValidationError(
            "unsupported_type", "File has a ZIP header but is not a readable archive."
        ) from exc

    with opened as zf:
        infos = zf.infolist()
        if len(infos) > _ZIP_MAX_ENTRIES:
            raise UploadValidationError(
                "zip_bomb", f"Archive has {len(infos)} entries (limit {_ZIP_MAX_ENTRIES})."
            )
        # file_size is the *declared* uncompressed size — checking it costs nothing
        # and rejects decompression bombs before any inflation happens.
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > _ZIP_MAX_UNCOMPRESSED:
            raise UploadValidationError(
                "zip_bomb",
                f"Archive declares {total_uncompressed} decompressed bytes "
                f"(limit {_ZIP_MAX_UNCOMPRESSED}).",
            )
        if "[Content_Types].xml" not in zf.namelist():
            raise UploadValidationError(
                "unsupported_type", "ZIP archive is not an Office Open XML document."
            )


def _is_utf8(source: Path | bytes) -> bool:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    return True


def detect_file_type(header: bytes, source: Path | bytes, claimed_ext: str) -> FileType:
    """Determine the real file type from content and check it against the claim.

    ``header`` is the first bytes of the file (>= 8 is plenty); ``source`` is the full
    on-disk path (or raw bytes in tests) for the deeper ZIP / UTF-8 checks;
    ``claimed_ext`` is the extension from the *sanitized* client filename.
    """
    ext = claimed_ext.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            "unsupported_type",
            f"Extension '.{ext}' is not supported (allowed: pdf, docx, txt, md).",
        )
    if not header:
        raise UploadValidationError("empty_file", "Uploaded file is empty.")

    if header.startswith(_PDF_MAGIC):
        actual = FileType.PDF
    elif header.startswith(_ZIP_MAGIC):
        _verify_docx_zip(source)
        actual = FileType.DOCX
    elif _is_utf8(source):
        # Plain text can't be distinguished from markdown by content; the claimed
        # extension picks between the two — but only between those two.
        if ext in ("txt", "md"):
            return FileType(ext)
        raise UploadValidationError(
            "magic_mismatch",
            f"File claims to be .{ext} but its content is plain text.",
        )
    else:
        raise UploadValidationError(
            "unsupported_type", "File content matches no supported format."
        )

    if actual.value != ext:
        raise UploadValidationError(
            "magic_mismatch",
            f"File claims to be .{ext} but its content is {actual.value.upper()}.",
        )
    return actual


async def stream_to_disk_capped(
    upload: AsyncReadable, dest: Path, max_bytes: int
) -> tuple[int, str]:
    """Stream an upload to ``dest`` enforcing a hard byte cap; return (size, sha256).

    The cap is enforced on the *running total of bytes actually received* — the
    Content-Length header is attacker-controlled and never consulted. The SHA-256 is
    computed in the same pass so dedup costs no extra I/O. On any failure the partial
    file is removed (handle already closed by the context manager — required on
    Windows, which refuses to delete open files).
    """
    hasher = hashlib.sha256()
    total = 0
    try:
        with open(dest, "wb") as fh:
            while True:
                chunk = await upload.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadValidationError(
                        "too_large",
                        f"Upload exceeds the {max_bytes} byte limit.",
                    )
                fh.write(chunk)
                hasher.update(chunk)
    except Exception:
        # The with-block has closed the handle by the time we get here.
        dest.unlink(missing_ok=True)
        raise

    if total == 0:
        dest.unlink(missing_ok=True)
        raise UploadValidationError("empty_file", "Uploaded file is empty.")

    return total, hasher.hexdigest()
