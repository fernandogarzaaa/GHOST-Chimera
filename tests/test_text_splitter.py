"""Tests for the recursive character text splitter (LangChain-inspired)."""

from __future__ import annotations

import unittest

from ghostchimera.memory_layer.text_splitter import RecursiveCharacterSplitter


class SplitterValidationTests(unittest.TestCase):
    def test_rejects_non_positive_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            RecursiveCharacterSplitter(chunk_size=0)

    def test_rejects_overlap_at_least_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=100)

    def test_rejects_empty_separators(self) -> None:
        with self.assertRaises(ValueError):
            RecursiveCharacterSplitter(separators=())


class SplitterBehaviorTests(unittest.TestCase):
    def test_blank_input_yields_no_chunks(self) -> None:
        splitter = RecursiveCharacterSplitter(chunk_size=50, chunk_overlap=10)
        self.assertEqual(splitter.split_text(""), [])
        self.assertEqual(splitter.split_text("   \n\n  "), [])

    def test_short_text_is_single_chunk(self) -> None:
        splitter = RecursiveCharacterSplitter(chunk_size=50, chunk_overlap=10)
        self.assertEqual(splitter.split_with_spans("hello world"), [("hello world", 0)])

    def test_every_chunk_respects_chunk_size(self) -> None:
        text = "\n\n".join(f"Paragraph {i} " + ("word " * 40) for i in range(12))
        splitter = RecursiveCharacterSplitter(chunk_size=200, chunk_overlap=40)
        chunks = splitter.split_text(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)

    def test_overlap_repeats_trailing_context(self) -> None:
        text = " ".join(f"token{i:03d}" for i in range(200))
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=30)
        chunks = splitter.split_text(text)
        self.assertGreater(len(chunks), 1)
        for first, second in zip(chunks, chunks[1:], strict=False):
            tail = first[-30:]
            self.assertIn(tail[:15], second)

    def test_no_overlap_when_disabled(self) -> None:
        text = " ".join(f"token{i:03d}" for i in range(200))
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=0)
        chunks = splitter.split_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)

    def test_spans_point_at_new_content(self) -> None:
        text = "\n\n".join(f"Section {i} content here." for i in range(30))
        splitter = RecursiveCharacterSplitter(chunk_size=120, chunk_overlap=20)
        spans = splitter.split_with_spans(text)
        for chunk, start in spans:
            self.assertGreaterEqual(start, 0)
            # The chunk's tail (past any overlap head) is verbatim source text.
            self.assertIn(chunk[-20:], text)

    def test_hard_splits_long_unbroken_runs(self) -> None:
        text = "x" * 500
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=10)
        chunks = splitter.split_text(text)
        # Max-size pieces leave no room for an overlap window.
        self.assertEqual(len(chunks), 5)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)
        self.assertEqual("".join(chunks), text)

    def test_full_coverage_no_dropped_middle(self) -> None:
        paras = [f"Paragraph {i}: " + ("lorem ipsum dolor sit amet " * 8) for i in range(10)]
        text = "\n\n".join(paras)
        splitter = RecursiveCharacterSplitter(chunk_size=300, chunk_overlap=0)
        self.assertEqual("".join(splitter.split_text(text)), text.strip())


class IngesterOverlapTests(unittest.TestCase):
    def test_ingester_chunks_carry_overlap_and_offsets(self) -> None:
        from ghostchimera.memory_layer.document_ingester import DocumentIngester

        text = "\n\n".join(f"Section {i} " + ("content word " * 60) for i in range(6))
        chunks = DocumentIngester._split_text(text, 400, chunk_overlap=80)
        self.assertGreater(len(chunks), 1)
        for i, (chunk_text, meta) in enumerate(chunks):
            self.assertLessEqual(len(chunk_text), 400)
            self.assertEqual(meta["chunk"], i)
            self.assertIn("start", meta)

    def test_ingester_overlap_disabled_matches_concatenation(self) -> None:
        from ghostchimera.memory_layer.document_ingester import DocumentIngester

        text = "\n\n".join(f"Block {i} data." for i in range(20))
        chunks = DocumentIngester._split_text(text, 60, chunk_overlap=0)
        self.assertEqual("".join(c for c, _ in chunks), text)


if __name__ == "__main__":
    unittest.main()
