"""Chunker unit tests — pure, deterministic, no ML.

Token counter is a whitespace word count (fast, no HF download); the real
tokenizer is injected in production but the algorithm is counter-agnostic.
ExtractedDocs are built either through the real markdown extractor (heading and
section behavior included) or by hand via _DocBuilder (page-number cases).
"""

from pathlib import Path

from app.ingestion.chunker import chunk_document, content_hash, split_sentences
from app.ingestion.extractors.base import ExtractedDoc, _DocBuilder
from app.ingestion.extractors.text import extract as extract_text


def count_tokens(text: str) -> int:
    return len(text.split())


def make_md(tmp_path: Path, content: str) -> ExtractedDoc:
    path = tmp_path / "doc.md"
    path.write_text(content, encoding="utf-8")
    return extract_text(path, is_markdown=True)


def chunk(extracted: ExtractedDoc, target: int = 400, ratio: float = 0.15):
    chunks = chunk_document(
        extracted, target_tokens=target, overlap_ratio=ratio, count_tokens=count_tokens
    )
    # The big invariant, asserted for every chunk in every test: a chunk is an
    # exact contiguous slice of full_text.
    for c in chunks:
        assert extracted.full_text[c.char_start : c.char_end] == c.text
    return chunks


def sentences(n: int, words_per_sentence: int = 20) -> str:
    return " ".join(
        f"S{i:02d}" + " ".join(f"w{j:02d}" for j in range(1, words_per_sentence)) + "."
        for i in range(n)
    )


class TestChunkDocument:
    def test_empty_doc(self, tmp_path):
        assert chunk(make_md(tmp_path, "")) == []

    def test_whitespace_doc(self, tmp_path):
        assert chunk(make_md(tmp_path, "  \n\n   \n")) == []

    def test_single_short_paragraph(self, tmp_path):
        extracted = make_md(tmp_path, "One tiny paragraph of text.")
        chunks = chunk(extracted)
        assert len(chunks) == 1
        assert chunks[0].text == "One tiny paragraph of text."
        assert chunks[0].token_count == 5
        assert chunks[0].section is None

    def test_multi_chunk_with_overlap(self, tmp_path):
        # 30 sentences x 20 tokens, target 100. Ratio 0.25 -> overlap budget 25,
        # so exactly one 20-token trailing sentence carries over between chunks.
        extracted = make_md(tmp_path, sentences(30, 20))
        chunks = chunk(extracted, target=100, ratio=0.25)
        assert len(chunks) > 1
        for c in chunks:
            assert c.token_count <= 100
        for prev, nxt in zip(chunks, chunks[1:], strict=False):
            assert nxt.char_start < prev.char_end  # overlap exists
            assert nxt.char_start > prev.char_start  # progress guaranteed

    def test_sentence_boundaries_respected(self, tmp_path):
        # All sentences fit under target -> no chunk may end mid-sentence.
        extracted = make_md(tmp_path, sentences(12, 10))
        block = extracted.blocks[0]
        sentence_ends = {block.char_start + e for _, e in split_sentences(block.text)}
        for c in chunk(extracted, target=50, ratio=0.2):
            assert c.char_end in sentence_ends

    def test_heading_is_hard_wall(self, tmp_path):
        extracted = make_md(
            tmp_path,
            "# Alpha\n\nBody about alpha topics here.\n\n## Beta\n\nBody about beta topics here.",
        )
        chunks = chunk(extracted)
        assert [c.section for c in chunks] == ["Alpha", "Alpha > Beta"]
        # Heading text lives in its own section's first chunk.
        assert chunks[0].text.startswith("Alpha")
        assert chunks[1].text.startswith("Beta")
        # No chunk spans both sections.
        beta_heading = next(b for b in extracted.blocks if b.text == "Beta")
        for c in chunks:
            assert not (c.char_start < beta_heading.char_start < c.char_end)

    def test_single_sentence_longer_than_target(self, tmp_path):
        words = " ".join(f"word{i:03d}" for i in range(50))  # one 50-token "sentence"
        extracted = make_md(tmp_path, words)
        chunks = chunk(extracted, target=10)
        assert len(chunks) == 5
        for c in chunks:
            assert c.token_count <= 10
            # Word-boundary splits: no chunk starts or ends mid-word.
            assert not c.text.startswith(" ") and not c.text.endswith(" ")
            if c.char_start > 0:
                assert extracted.full_text[c.char_start - 1] == " "
            if c.char_end < len(extracted.full_text):
                assert extracted.full_text[c.char_end] == " "

    def test_heading_with_no_body(self, tmp_path):
        extracted = make_md(tmp_path, "# Lonely Heading")
        chunks = chunk(extracted)
        assert len(chunks) == 1
        assert chunks[0].text == "Lonely Heading"
        assert chunks[0].section == "Lonely Heading"

    def test_page_spanning(self):
        builder = _DocBuilder()
        builder.add("Text on the first page.", page=1, section=None)
        builder.add("Text on the second page.", page=2, section=None)
        chunks = chunk(builder.build(page_count=2, title=None))
        assert len(chunks) == 1
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 2

    def test_pages_none_for_docx_style(self):
        builder = _DocBuilder()
        builder.add("A paragraph without any page.", page=None, section=None)
        chunks = chunk(builder.build(page_count=None, title=None))
        assert chunks[0].page_start is None
        assert chunks[0].page_end is None

    def test_zero_progress_regression(self, tmp_path):
        # Pathological overlap-vs-target combo: the shed-overlap-from-front rule
        # must keep the window advancing and the loop terminating.
        text = ". ".join(["Aa bb", "Bb cc", "Nine words in this quite long sentence here x"] * 5)
        extracted = make_md(tmp_path, text + ".")
        chunks = chunk(extracted, target=10, ratio=0.45)
        assert chunks
        assert len(chunks) < 40  # generous bound: it terminated and didn't spin
        assert chunks[-1].char_end == len(extracted.full_text)

    def test_determinism(self, tmp_path):
        extracted = make_md(tmp_path, "# A\n\n" + sentences(20, 15) + "\n\n## B\n\n" + sentences(5))
        assert chunk(extracted, target=80, ratio=0.2) == chunk(extracted, target=80, ratio=0.2)

    def test_content_hash_normalizes_whitespace_and_case(self):
        assert content_hash("The  Quick\nBrown Fox") == content_hash("the quick brown fox")
        assert content_hash("different text") != content_hash("the quick brown fox")


class TestSplitSentences:
    def check(self, text: str, expected: list[str]) -> None:
        spans = split_sentences(text)
        assert [text[s:e] for s, e in spans] == expected
        # Offset exactness: spans are in order and non-overlapping.
        for (s1, e1), (s2, _) in zip(spans, spans[1:], strict=False):
            assert s1 < e1 <= s2

    def test_simple_split(self):
        self.check("First one. Second one!", ["First one.", "Second one!"])

    def test_abbreviations(self):
        self.check(
            "We evaluate e.g. the model. It works.",
            ["We evaluate e.g. the model.", "It works."],
        )
        self.check("Dr. Smith arrived. He left.", ["Dr. Smith arrived.", "He left."])

    def test_initials(self):
        self.check("J. Smith wrote it. Then left.", ["J. Smith wrote it.", "Then left."])

    def test_interrobang_run(self):
        self.check("Really?! Yes.", ["Really?!", "Yes."])

    def test_lowercase_continuation_is_not_boundary(self):
        self.check("It costs 5. dollars total", ["It costs 5. dollars total"])

    def test_no_punctuation(self):
        self.check("no terminal punctuation here", ["no terminal punctuation here"])

    def test_empty(self):
        assert split_sentences("") == []
        assert split_sentences("   ") == []
