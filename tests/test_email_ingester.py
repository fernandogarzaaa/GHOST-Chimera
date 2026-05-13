"""Tests for ghostchimera.personalization.email_ingester."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.personalization.email_ingester import (
    EmailIngester,
    EmailRecord,
    _decode_header_value,
)


class DecodeHeaderTests(unittest.TestCase):
    def test_plain_ascii(self) -> None:
        self.assertEqual(_decode_header_value("Hello World"), "Hello World")

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_decode_header_value(None), "")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(_decode_header_value(""), "")


class EmailRecordTests(unittest.TestCase):
    def _make_record(self, **kwargs) -> EmailRecord:  # type: ignore[type-arg]
        defaults = dict(
            subject="Test Subject",
            sender="alice@example.com",
            recipients=("bob@example.com",),
            date="Mon, 01 Jan 2024 12:00:00 +0000",
            body="This is the body.",
            source_path="/tmp/test.eml",
        )
        defaults.update(kwargs)
        return EmailRecord(**defaults)

    def test_to_memory_content_includes_subject(self) -> None:
        record = self._make_record(subject="Meeting tomorrow")
        content = record.to_memory_content()
        self.assertIn("Meeting tomorrow", content)

    def test_to_memory_content_includes_sender(self) -> None:
        record = self._make_record(sender="boss@company.com")
        content = record.to_memory_content()
        self.assertIn("boss@company.com", content)

    def test_to_memory_content_includes_body(self) -> None:
        record = self._make_record(body="Please review the attached document.")
        content = record.to_memory_content()
        self.assertIn("Please review the attached document.", content)

    def test_to_dict_structure(self) -> None:
        record = self._make_record()
        d = record.to_dict()
        self.assertIn("subject", d)
        self.assertIn("sender", d)
        self.assertIn("recipients", d)
        self.assertIn("body", d)


class EmailIngesterTests(unittest.TestCase):
    _RAW_EMAIL = textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com
        Subject: Q4 Planning
        Date: Mon, 01 Jan 2024 09:00:00 +0000
        Content-Type: text/plain; charset=utf-8

        Hi Bob,

        Let's talk about Q4 goals. We should hit 1M ARR by December.

        Cheers,
        Alice
    """)

    def _store(self, tmp: str) -> MemoryStore:
        return MemoryStore(Path(tmp) / "mem.sqlite3")

    def test_ingest_raw_email(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_raw_email(self._RAW_EMAIL)
            self.assertEqual(result.ingested, 1)
            self.assertEqual(result.skipped, 0)
            self.assertEqual(len(result.errors), 0)
            self.assertEqual(store.count(), 1)
            hits = store.search("Q4 goals")
            self.assertGreater(len(hits), 0)
            self.assertIn("Q4", hits[0]["content"])

    def test_ingest_raw_email_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            ingester.ingest_raw_email(self._RAW_EMAIL)
            result = ingester.ingest_raw_email(self._RAW_EMAIL)
            self.assertEqual(result.skipped, 1)
            self.assertEqual(store.count(), 1)

    def test_ingest_eml_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            eml_path = Path(tmp) / "message.eml"
            eml_path.write_text(self._RAW_EMAIL, encoding="utf-8")
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_eml_file(eml_path)
            self.assertEqual(result.ingested, 1)
            self.assertEqual(len(result.errors), 0)
            self.assertGreater(store.count(), 0)

    def test_ingest_missing_eml_file_records_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_eml_file("/nonexistent/path/test.eml")
            self.assertEqual(result.ingested, 0)
            self.assertGreater(len(result.errors), 0)

    def test_ingest_directory_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_directory(tmp)
            self.assertEqual(result.ingested, 0)

    def test_ingest_directory_with_eml_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            for i in range(3):
                eml = Path(tmp) / f"msg_{i}.eml"
                eml.write_text(
                    self._RAW_EMAIL.replace("Q4 Planning", f"Q4 Planning #{i}"),
                    encoding="utf-8",
                )
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_directory(tmp)
            self.assertEqual(result.ingested, 3)
            self.assertEqual(store.count(), 3)

    def test_empty_email_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_raw_email("")
            self.assertEqual(result.skipped, 1)
            self.assertEqual(result.ingested, 0)

    def test_result_to_dict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-email-test-") as tmp:
            store = self._store(tmp)
            ingester = EmailIngester(store)
            result = ingester.ingest_raw_email(self._RAW_EMAIL)
            d = result.to_dict()
            self.assertIn("ingested", d)
            self.assertIn("skipped", d)
            self.assertIn("errors", d)
            self.assertIn("records", d)
            self.assertEqual(len(d["records"]), 1)
            self.assertEqual(d["records"][0]["subject"], "Q4 Planning")
