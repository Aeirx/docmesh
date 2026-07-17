"""Plain-text and Markdown extraction.

Paragraphs are blank-line-separated. For Markdown, ATX headings (``# ...``) become
heading blocks and drive the section path; plain .txt has no structure signal, so
every block gets ``section=None``.

Accepted limitation (documented, not handled): a ``#`` line inside a fenced code
block is read as a heading. The cost is one wrong section label on an edge case,
not corruption — not worth a fence-state parser in Phase 2.
"""

import re
from pathlib import Path

from app.ingestion.extractors.base import ExtractedDoc, _DocBuilder, _SectionTracker

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def extract(path: Path, *, is_markdown: bool) -> ExtractedDoc:
    # utf-8-sig eats a BOM if present; errors="replace" means no text file can crash us.
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    builder = _DocBuilder()
    tracker = _SectionTracker()
    title: str | None = None

    for para in re.split(r"\n\s*\n", raw):
        stripped = para.strip()
        if not stripped:
            continue
        # A paragraph that STARTS with '#' may carry body lines below the heading
        # (no blank line between them): split the first line off as the heading.
        first_line, _, remainder = stripped.partition("\n")
        m = _HEADING_RE.match(first_line) if is_markdown else None
        if m is None:
            builder.add(para, page=None, section=tracker.path() if is_markdown else None)
            continue

        level = min(len(m.group(1)), 3)
        heading_text = m.group(2).strip()
        tracker.on_heading(level, heading_text)
        if title is None and level == 1:
            title = heading_text
        builder.add(
            heading_text,
            page=None,
            section=tracker.path(),
            is_heading=True,
            heading_level=level,
        )
        if remainder.strip():
            builder.add(remainder, page=None, section=tracker.path())

    return builder.build(page_count=None, title=title)
