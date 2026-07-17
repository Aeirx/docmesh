"""Extractor unit tests over txt/md — no binary deps needed.

The one invariant everything downstream depends on:
``full_text[b.char_start:b.char_end] == b.text`` for every block.
"""

from pathlib import Path

from app.ingestion.extractors import extract_document
from app.ingestion.extractors.base import ExtractedDoc, _DocBuilder, _SectionTracker
from app.schemas.documents import FileType


def assert_offsets(extracted: ExtractedDoc) -> None:
    for block in extracted.blocks:
        assert extracted.full_text[block.char_start : block.char_end] == block.text


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestDocBuilder:
    def test_offsets_and_separators(self):
        builder = _DocBuilder()
        builder.add("  first block  ", page=1, section=None)
        builder.add("second block", page=2, section="S")
        doc = builder.build(page_count=2, title=None)
        assert doc.full_text == "first block\n\nsecond block"
        assert_offsets(doc)

    def test_empty_blocks_skipped(self):
        builder = _DocBuilder()
        builder.add("   ", page=None, section=None)
        doc = builder.build(page_count=None, title=None)
        assert doc.full_text == ""
        assert doc.blocks == []


class TestSectionTracker:
    def test_nesting_and_sibling_replacement(self):
        tracker = _SectionTracker()
        assert tracker.path() is None
        tracker.on_heading(1, "A")
        tracker.on_heading(2, "B")
        assert tracker.path() == "A > B"
        tracker.on_heading(2, "C")  # sibling replaces B, keeps parent A
        assert tracker.path() == "A > C"
        tracker.on_heading(1, "D")  # new top level clears everything
        assert tracker.path() == "D"


class TestTxt:
    def test_paragraphs_no_sections(self, tmp_path):
        path = write(tmp_path, "a.txt", "Para one line.\n\nPara two line.\n\n\n\nPara three.")
        doc = extract_document(path, FileType.TXT)
        assert_offsets(doc)
        assert [b.text for b in doc.blocks] == ["Para one line.", "Para two line.", "Para three."]
        assert all(b.section is None and not b.is_heading for b in doc.blocks)
        assert doc.page_count is None and doc.title is None

    def test_bom_and_weird_bytes_survive(self, tmp_path):
        path = tmp_path / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbfhello world")
        doc = extract_document(path, FileType.TXT)
        assert doc.full_text == "hello world"

    def test_hash_line_in_txt_is_not_heading(self, tmp_path):
        path = write(tmp_path, "a.txt", "# not a heading in txt")
        doc = extract_document(path, FileType.TXT)
        assert doc.blocks[0].is_heading is False


class TestMd:
    def test_headings_sections_title(self, tmp_path):
        content = "# Title Here\n\nIntro para.\n\n## Sub Part\n\nSub body."
        doc = extract_document(write(tmp_path, "a.md", content), FileType.MD)
        assert_offsets(doc)
        assert doc.title == "Title Here"
        headings = [b for b in doc.blocks if b.is_heading]
        assert [(b.text, b.heading_level) for b in headings] == [("Title Here", 1), ("Sub Part", 2)]
        # A heading's own section path includes itself.
        assert headings[0].section == "Title Here"
        assert headings[1].section == "Title Here > Sub Part"
        intro = next(b for b in doc.blocks if b.text == "Intro para.")
        assert intro.section == "Title Here"

    def test_heading_with_attached_body_lines(self, tmp_path):
        # No blank line between heading and body: first line splits off.
        doc = extract_document(write(tmp_path, "a.md", "## Head\nbody right after"), FileType.MD)
        assert [(b.text, b.is_heading) for b in doc.blocks] == [
            ("Head", True),
            ("body right after", False),
        ]
        assert_offsets(doc)

    def test_deep_headings_capped_at_level_3(self, tmp_path):
        doc = extract_document(write(tmp_path, "a.md", "#### Deep One"), FileType.MD)
        assert doc.blocks[0].heading_level == 3
        assert doc.title is None  # not a level-1 heading
