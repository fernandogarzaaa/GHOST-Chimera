"""Tests for ghostchimera.personalization.document_ingester."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.personalization.document_ingester import (
    DocumentIngester,
    _chunk_text,
)


class ChunkTextTests(unittest.TestCase):
    def test_short_text_not_chunked(self) -> None:
        text = "Hello, world."
        chunks = _chunk_text(text)
        self.assertEqual(chunks, ["Hello, world."])

    def test_empty_text_returns_empty(self) -> None:
        self.assertEqual(_chunk_text(""), [])
        self.assertEqual(_chunk_text("   "), [])

    def test_long_text_is_chunked(self) -> None:
        para = "A " * 400  # 800 chars
        text = (para.strip() + "\n\n") * 5  # 5 paragraphs
        chunks = _chunk_text(text, max_chars=1500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1500)

    def test_single_long_paragraph_chunked_at_sentence_boundary(self) -> None:
        sentences = [f"This is sentence number {i}. " for i in range(100)]
        text = "".join(sentences)
        chunks = _chunk_text(text, max_chars=200)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)


class DocumentIngesterTests(unittest.TestCase):
    def _store(self, tmp: str) -> MemoryStore:
        return MemoryStore(Path(tmp) / "mem.sqlite3")

    def test_ingest_text_basic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_text("notes", "We use FastAPI and PostgreSQL for our backend.")
            self.assertEqual(result.ingested, 1)
            self.assertEqual(result.skipped, 0)
            self.assertGreater(result.chunks, 0)
            hits = store.search("PostgreSQL")
            self.assertGreater(len(hits), 0)

    def test_ingest_text_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            ingester.ingest_text("notes", "We use FastAPI.")
            result = ingester.ingest_text("notes", "We use FastAPI.")
            self.assertEqual(result.skipped, 1)

    def test_ingest_empty_text_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_text("notes", "   ")
            self.assertEqual(result.skipped, 1)
            self.assertEqual(result.ingested, 0)

    def test_ingest_file_txt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            p = Path(tmp) / "notes.txt"
            p.write_text("Ghost Chimera is a local-first agent.", encoding="utf-8")
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_file(p)
            self.assertEqual(result.ingested, 1)
            self.assertEqual(len(result.errors), 0)
            hits = store.search("local-first agent")
            self.assertGreater(len(hits), 0)

    def test_ingest_file_markdown(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            p = Path(tmp) / "README.md"
            p.write_text("# My Project\n\nThis project uses Python 3.12.", encoding="utf-8")
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_file(p)
            self.assertEqual(result.ingested, 1)

    def test_ingest_unsupported_extension_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            p = Path(tmp) / "binary.exe"
            p.write_bytes(b"\x00\x01\x02")
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_file(p)
            self.assertEqual(result.skipped, 1)
            self.assertEqual(result.ingested, 0)

    def test_ingest_missing_file_records_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            # Missing path but extension is supported
            result = ingester.ingest_file("/nonexistent/path/notes.txt")
            self.assertEqual(result.ingested, 0)
            self.assertGreater(len(result.errors), 0)

    def test_ingest_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            d = Path(tmp) / "docs"
            d.mkdir()
            (d / "a.txt").write_text("Document A content about Python.", encoding="utf-8")
            (d / "b.md").write_text("Document B content about Go.", encoding="utf-8")
            (d / "c.exe").write_bytes(b"\x00")  # should be skipped
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_directory(d)
            self.assertEqual(result.ingested, 2)
            hits = store.search("Python")
            self.assertGreater(len(hits), 0)

    def test_ingest_text_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_text("crm", "Customer ABC signed contract.", metadata={"customer": "ABC"})
            self.assertEqual(result.ingested, 1)

    def test_result_to_dict_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-doc-test-") as tmp:
            store = self._store(tmp)
            ingester = DocumentIngester(store)
            result = ingester.ingest_text("notes", "Some content.")
            d = result.to_dict()
            self.assertIn("ingested", d)
            self.assertIn("skipped", d)
            self.assertIn("chunks", d)
            self.assertIn("errors", d)
