"""Shared extraction types and helpers.

Every extractor produces the same structure: one ``full_text`` string plus a list of
``Block``s whose char offsets index into it exactly. The load-bearing invariant is

    full_text[block.char_start:block.char_end] == block.text

for every block — chunk spans computed downstream map back to the source forever.
The invariant holds because all text normalization (a single ``strip`` per block)
happens in ``_DocBuilder.add`` BEFORE offsets are taken, and never again after.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    """One contiguous unit of source text (a paragraph, or a heading line)."""

    text: str  # exactly full_text[char_start:char_end]
    char_start: int  # offsets into ExtractedDoc.full_text
    char_end: int
    page_number: int | None  # 1-based; None for docx/txt/md
    section: str | None  # section path this block lives under, e.g. "3 Methods > 3.2 Eval"
    is_heading: bool = False
    heading_level: int | None = None  # 1..3 (pdf/docx/md), None for body


@dataclass(frozen=True)
class ExtractedDoc:
    full_text: str
    blocks: list[Block]
    page_count: int | None  # None for docx/txt/md
    title: str | None  # first level-1 heading, else None


class ExtractionError(Exception):
    """Raised for unreadable/corrupt files; the pipeline maps it to status=failed."""


class _DocBuilder:
    """Appends blocks and maintains exact offsets.

    Blocks are joined by ``\\n\\n`` in full_text; separators live BETWEEN blocks and
    belong to no block, so every block's span contains only its own text.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._blocks: list[Block] = []
        self._pos = 0

    def add(
        self,
        text: str,
        *,
        page: int | None,
        section: str | None,
        is_heading: bool = False,
        heading_level: int | None = None,
    ) -> None:
        # Normalize block edges once, here, before offsets are taken.
        text = text.strip()
        if not text:
            return
        if self._parts:
            self._parts.append("\n\n")
            self._pos += 2
        start = self._pos
        self._parts.append(text)
        self._pos += len(text)
        self._blocks.append(
            Block(text, start, self._pos, page, section, is_heading, heading_level)
        )

    def build(self, *, page_count: int | None, title: str | None) -> ExtractedDoc:
        return ExtractedDoc("".join(self._parts), self._blocks, page_count, title)


class _SectionTracker:
    """Stack of (level, heading_text) maintaining the current section path.

    On a level-L heading: pop every entry with level >= L, then push (L, text) —
    a new "3.2" replaces the previous "3.1" but keeps its parent "3" on the stack.
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def on_heading(self, level: int, text: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))

    def path(self) -> str | None:
        return " > ".join(text for _, text in self._stack) or None
