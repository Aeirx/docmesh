"""PDF extraction via PyMuPDF.

Heading detection is relative, not absolute: pass 1 takes a font census (character
mass per rounded font size) to find the document's own body size; pass 2 calls a
block a heading when it is notably larger than that body size (>= 1.15x, top three
sizes = levels 1..3) or bold-at-body-size and shaped like a title (short, not
sentence-punctuated). No fixed point-size thresholds, so it works across papers
with different base fonts.

Known limitations (accepted for Phase 2): multi-column PDFs may interleave block
order (PyMuPDF returns layout order, which is usually right); scanned PDFs yield
no text and fall through to the empty-document path.

pymupdf is imported lazily inside extract(): it is a compiled extension the API
process only needs when a PDF is actually ingested.
"""

from collections import Counter
from pathlib import Path
from typing import Any

from app.ingestion.extractors.base import (
    ExtractedDoc,
    ExtractionError,
    _DocBuilder,
    _SectionTracker,
)

_BOLD_FLAG = 16  # PyMuPDF span flag bit for bold
_MAX_HEADING_CHARS = 120
_MAX_HEADING_WORDS = 12


def _block_spans(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [span for line in block.get("lines", []) for span in line.get("spans", [])]


def _block_text(block: dict[str, Any]) -> str:
    # Spans join with nothing (they are fragments of a line), lines join with \n.
    lines = [
        "".join(span["text"] for span in line.get("spans", [])) for line in block.get("lines", [])
    ]
    return "\n".join(lines)


def _is_heading(text: str, spans: list[dict[str, Any]], body_size: float) -> tuple[bool, bool]:
    """(uniform_size, qualifies_shape): all spans share one size, and the text is
    short and not sentence-punctuated. Callers combine with the size/bold tests."""
    sizes = {round(span["size"], 1) for span in spans}
    uniform = len(sizes) == 1
    shape_ok = (
        len(text) <= _MAX_HEADING_CHARS
        and len(text.split()) <= _MAX_HEADING_WORDS
        and not text.rstrip().endswith((".", ",", ";"))
    )
    return uniform, shape_ok


def extract(path: Path) -> ExtractedDoc:
    import pymupdf

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF: {exc}") from exc

    try:
        pages = [page.get_text("dict") for page in doc]
        page_count = doc.page_count
    except Exception as exc:
        raise ExtractionError(f"Cannot read PDF text: {exc}") from exc
    finally:
        doc.close()

    # Pass 1 — font census: body size = the size carrying the most character mass.
    size_mass: Counter[float] = Counter()
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block
                continue
            for span in _block_spans(block):
                size_mass[round(span["size"], 1)] += len(span["text"])

    if not size_mass:
        return _DocBuilder().build(page_count=page_count, title=None)

    body_size = size_mass.most_common(1)[0][0]
    heading_sizes = sorted(
        (s for s in size_mass if s >= body_size * 1.15), reverse=True
    )[:3]
    level_of = {size: i + 1 for i, size in enumerate(heading_sizes)}

    builder = _DocBuilder()
    tracker = _SectionTracker()
    title: str | None = None

    # Pass 2 — emit blocks in layout order, classifying headings against the census.
    for pnum, page in enumerate(pages, start=1):
        for block in page.get("blocks", []):
            if block.get("type") != 0:
                continue
            spans = _block_spans(block)
            text = " ".join(_block_text(block).split())  # collapse intra-block whitespace
            if not text or not spans:
                continue

            uniform, shape_ok = _is_heading(text, spans, body_size)
            size = round(spans[0]["size"], 1)
            level: int | None = None
            if uniform and shape_ok:
                if size in level_of:
                    level = level_of[size]
                elif size >= body_size and all(span["flags"] & _BOLD_FLAG for span in spans):
                    # Bold at body size: one level deeper than the sized headings.
                    level = min(len(heading_sizes) + 1, 3) if heading_sizes else 1

            if level is not None:
                tracker.on_heading(level, text)
                if title is None and level == 1:
                    title = text
                builder.add(
                    text,
                    page=pnum,
                    section=tracker.path(),
                    is_heading=True,
                    heading_level=level,
                )
            else:
                builder.add(text, page=pnum, section=tracker.path())

    return builder.build(page_count=page_count, title=title)
