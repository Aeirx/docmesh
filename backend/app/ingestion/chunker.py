"""Recursive semantic chunking — pure, deterministic, zero ML imports.

Boundary hierarchy: heading > paragraph (block) > sentence > hard word-level cap.
Headings are hard walls (a chunk never spans two sections); paragraphs and
sentences are the packing units; the word cap only fires for pathological single
sentences longer than the whole token budget.

Token counting is injected as a plain callable so the 400-token budget is measured
in the embedding model's own tokens (bge tokenizer in production) while this module
stays pure and unit-testable with a whitespace counter.

Key invariant: every chunk is a contiguous slice of the extracted full_text —
``text == full_text[char_start:char_end]`` — which is possible because overlap
carries the *trailing sentences of the previous chunk* (contiguous with what
follows) and never crosses a section boundary. Exact provenance forever.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from math import floor

from app.ingestion.extractors.base import Block, ExtractedDoc

# Words whose trailing period is not a sentence boundary. Compared against the
# preceding word lowercased with leading/trailing dots stripped, so "e.g." and
# "etc." both resolve to entries here.
_ABBREVIATIONS = frozenset(
    {"e.g", "i.e", "etc", "vs", "cf", "fig", "eq", "al", "dr", "mr", "mrs", "ms", "prof", "no"}
)

# A candidate boundary: a run of terminal punctuation followed by whitespace.
_BOUNDARY_RE = re.compile(r"[.!?]+(?=\s)")
_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class DraftChunk:
    text: str  # ALWAYS == extracted.full_text[char_start:char_end]
    token_count: int
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    section: str | None
    content_hash: str  # sha256 over whitespace/case-normalized text


@dataclass(frozen=True)
class _Unit:
    """One packing unit: a sentence, a heading, or a forced word-cap piece.
    Offsets are absolute (into full_text)."""

    char_start: int
    char_end: int
    page: int | None
    tokens: int


def content_hash(text: str) -> str:
    """Whitespace/case-robust identity: reflowed or re-cased copies hash the same."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) spans relative to ``text``, end-exclusive, non-overlapping, in
    order. A boundary is a run of [.!?] followed by whitespace, EXCEPT when:

    - the preceding word (lowercased, dots stripped) is a known abbreviation
    - the '.' terminates a single capital letter (initials: 'J. Smith')
    - the next non-space char is a lowercase letter (mid-sentence period)

    If no boundary is found the whole text is one sentence. Each span starts at the
    first non-space char after the previous boundary.
    """
    boundaries: list[int] = []
    for m in _BOUNDARY_RE.finditer(text):
        before = _WORD_RE.findall(text[: m.start()])
        prev_word = before[-1] if before else ""
        stripped = prev_word.lower().strip(".")
        if stripped in _ABBREVIATIONS:
            continue
        if m.group() == "." and len(prev_word) == 1 and prev_word.isupper():
            continue
        rest = text[m.end() :].lstrip()
        if rest and rest[0].islower():
            continue
        boundaries.append(m.end())

    spans: list[tuple[int, int]] = []
    start = 0
    for end in [*boundaries, len(text)]:
        # Trim the span to its non-space extent; skip whitespace-only spans.
        while start < end and text[start].isspace():
            start += 1
        trimmed_end = end
        while trimmed_end > start and text[trimmed_end - 1].isspace():
            trimmed_end -= 1
        if trimmed_end > start:
            spans.append((start, trimmed_end))
        start = end
    return spans


def _split_oversized(
    unit: _Unit, full_text: str, target: int, count_tokens: Callable[[str], int]
) -> list[_Unit]:
    """Pre-split a unit whose token count exceeds ``target`` at word boundaries,
    greedily packing words left-to-right. A single word that alone exceeds the
    budget (pathological) is sliced by characters, halving recursively until each
    piece fits."""

    def char_halves(start: int, end: int) -> list[tuple[int, int]]:
        if count_tokens(full_text[start:end]) <= target or end - start <= 1:
            return [(start, end)]
        mid = start + (end - start) // 2
        return char_halves(start, mid) + char_halves(mid, end)

    word_spans: list[tuple[int, int]] = []
    for m in _WORD_RE.finditer(full_text[unit.char_start : unit.char_end]):
        w_start, w_end = unit.char_start + m.start(), unit.char_start + m.end()
        word_spans.extend(char_halves(w_start, w_end))

    pieces: list[_Unit] = []
    piece_start: int | None = None
    piece_end = 0
    piece_tokens = 0
    for w_start, w_end in word_spans:
        w_tokens = count_tokens(full_text[w_start:w_end])
        if piece_start is not None and piece_tokens + w_tokens > target:
            pieces.append(_Unit(piece_start, piece_end, unit.page, piece_tokens))
            piece_start = None
            piece_tokens = 0
        if piece_start is None:
            piece_start = w_start
        piece_end = w_end
        piece_tokens += w_tokens
    if piece_start is not None:
        pieces.append(_Unit(piece_start, piece_end, unit.page, piece_tokens))
    return pieces or [unit]


def _section_units(
    blocks: list[Block], full_text: str, target: int, count_tokens: Callable[[str], int]
) -> list[_Unit]:
    """Blocks -> packing units: a heading is one unit; a body block contributes one
    unit per sentence. Every returned unit fits within ``target`` (step 3)."""
    units: list[_Unit] = []
    for block in blocks:
        if block.is_heading:
            units.append(
                _Unit(block.char_start, block.char_end, block.page_number, count_tokens(block.text))
            )
            continue
        for s, e in split_sentences(block.text):
            start, end = block.char_start + s, block.char_start + e
            units.append(_Unit(start, end, block.page_number, count_tokens(full_text[start:end])))

    fitted: list[_Unit] = []
    for unit in units:
        if unit.tokens > target:
            fitted.extend(_split_oversized(unit, full_text, target, count_tokens))
        else:
            fitted.append(unit)
    return fitted


def chunk_document(
    extracted: ExtractedDoc,
    *,
    target_tokens: int,
    overlap_ratio: float,
    count_tokens: Callable[[str], int],
) -> list[DraftChunk]:
    """Pure function of (extracted, params, counter) — no randomness, no dict-order
    dependence. Returns [] for empty/whitespace documents."""
    full_text = extracted.full_text
    if not full_text.strip():
        return []
    overlap_budget = floor(target_tokens * overlap_ratio)

    # 1. Group blocks into sections: cut before every heading block, so a heading
    #    STARTS its section and is included in it. Pre-heading blocks form a
    #    leading section of their own.
    sections: list[list[Block]] = []
    for block in extracted.blocks:
        if block.is_heading or not sections:
            sections.append([])
        sections[-1].append(block)

    chunks: list[DraftChunk] = []
    for section_blocks in sections:
        section_path = section_blocks[0].section
        units = _section_units(section_blocks, full_text, target_tokens, count_tokens)

        # 4. Pack units into chunks. Overlap never crosses a section boundary.
        overlap_units: list[_Unit] = []
        i = 0
        while i < len(units):
            chunk_units = list(overlap_units)
            total = sum(u.tokens for u in chunk_units)
            # Guarantee progress: always consume at least one NEW unit. If overlap
            # plus the first new unit would bust the budget, shed overlap from the
            # FRONT until it fits (possibly all of it).
            while chunk_units and total + units[i].tokens > target_tokens:
                total -= chunk_units.pop(0).tokens
            new_start = len(chunk_units)
            chunk_units.append(units[i])
            total += units[i].tokens
            i += 1
            while i < len(units) and total + units[i].tokens <= target_tokens:
                chunk_units.append(units[i])
                total += units[i].tokens
                i += 1

            char_start = chunk_units[0].char_start
            char_end = chunk_units[-1].char_end
            text = full_text[char_start:char_end]
            pages = [u.page for u in chunk_units if u.page is not None]
            chunks.append(
                DraftChunk(
                    text=text,
                    # Recount the joined slice: sub-word merges at unit boundaries
                    # mean the sum of parts can drift; the recount is the number
                    # that must stay under the model's 512 hard limit.
                    token_count=count_tokens(text),
                    char_start=char_start,
                    char_end=char_end,
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    section=section_path,
                    content_hash=content_hash(text),
                )
            )

            # 5. Next overlap: the longest suffix of the NEWLY-consumed units whose
            #    token sum fits the overlap budget, and strictly shorter than the
            #    full new-unit list (a 1-new-unit chunk contributes no overlap).
            #    Only new units are eligible — re-carrying old overlap would let
            #    the window stagnate.
            if i >= len(units):
                overlap_units = []
                continue
            new_units = chunk_units[new_start:]
            overlap_units = []
            suffix_tokens = 0
            for unit in reversed(new_units[1:]):  # suffix strictly shorter than new_units
                if suffix_tokens + unit.tokens > overlap_budget:
                    break
                overlap_units.insert(0, unit)
                suffix_tokens += unit.tokens

    return chunks
