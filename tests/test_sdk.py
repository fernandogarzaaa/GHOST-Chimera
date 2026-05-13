"""Tests for ghostchimera.sdk (GhostClient)."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from ghostchimera.sdk import GhostClient, RunResult


class GhostClientTests(unittest.TestCase):
    _RAW_EMAIL = textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com
        Subject: Tech Stack Discussion
        Date: Mon, 01 Jan 2024 09:00:00 +0000
        Content-Type: text/plain; charset=utf-8

        Hi Bob,

        Our backend is built on FastAPI and PostgreSQL. We deploy on AWS.

        Alice
    """)

    def _client(self, tmp: str) -> GhostClient:
        return GhostClient(state_dir=tmp, enable_personal_context=False)

    # ── Construction ──────────────────────────────────────────────────────

    def test_client_constructs_without_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            self.assertIsNotNone(client)

    def test_client_repr(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            r = repr(client)
            self.assertIn("GhostClient", r)
            self.assertIn("supervised", r)

    # ── Memory / ingestion ─────────────────────────────────────────────────

    def test_ingest_document_basic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            result = client.ingest_document("notes", "We use FastAPI and PostgreSQL.")
            self.assertEqual(result.ingested, 1)
            self.assertEqual(client.memory_count(), 1)

    def test_search_returns_relevant_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            client.ingest_document("notes", "Our primary database is PostgreSQL.")
            hits = client.search("database")
            self.assertGreater(len(hits), 0)
            self.assertIn("PostgreSQL", hits[0]["content"])

    def test_ingest_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            p = Path(tmp) / "info.txt"
            p.write_text("Ghost Chimera bridges the gap.", encoding="utf-8")
            client = self._client(tmp)
            result = client.ingest_file(p)
            self.assertEqual(result.ingested, 1)
            self.assertGreater(client.memory_count(), 0)

    def test_ingest_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            docs = Path(tmp) / "docs"
            docs.mkdir()
            (docs / "a.txt").write_text("Service A uses Redis.", encoding="utf-8")
            (docs / "b.md").write_text("Service B uses Kafka.", encoding="utf-8")
            client = self._client(tmp)
            result = client.ingest_directory(docs)
            self.assertEqual(result.ingested, 2)

    def test_ingest_raw_email(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            result = client.ingest_raw_email(self._RAW_EMAIL)
            self.assertEqual(result.ingested, 1)
            hits = client.search("FastAPI")
            self.assertGreater(len(hits), 0)

    def test_ingest_email_file_eml(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            eml = Path(tmp) / "msg.eml"
            eml.write_text(self._RAW_EMAIL, encoding="utf-8")
            client = self._client(tmp)
            result = client.ingest_email_file(eml)
            self.assertEqual(result.ingested, 1)

    def test_memory_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            self.assertEqual(client.memory_count(), 0)
            client.ingest_document("test", "sample content")
            self.assertEqual(client.memory_count(), 1)

    # ── Teaching ──────────────────────────────────────────────────────────

    def test_teach_creates_dataset_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            path = client.teach("What is our DB?", "PostgreSQL, as in project notes.")
            self.assertIsInstance(path, Path)
            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("PostgreSQL", content)

    def test_teach_appends_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            client.teach("Q1?", "A1")
            client.teach("Q2?", "A2")
            status = client.training_status()
            self.assertGreaterEqual(status["dataset_count"], 2)

    def test_training_status_returns_dict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            status = client.training_status()
            self.assertIn("dataset_path", status)
            self.assertIn("dataset_count", status)

    def test_personal_minimind_workflow_available_from_sdk(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            base = Path(tmp)
            note = base / "work.txt"
            note.write_text("Follow-up: draft the MiniMind v0.4.0 beta notes.", encoding="utf-8")
            client = self._client(tmp)

            consent = client.enable_personal_minimind(
                admin_controls=True,
                allow_files=True,
                allow_training=True,
                file_paths=[note],
            )
            bootstrapped = client.bootstrap_personal_minimind()
            handoff = client.minimind_handoff("What should I work on?")

            self.assertTrue(consent["ok"])
            self.assertTrue(bootstrapped["ok"])
            self.assertIn("MiniMind v0.4.0", handoff["personal_context"])
            self.assertIn("primary_model_prompt", handoff)

    # ── Context preview ────────────────────────────────────────────────────

    def test_preview_context_empty_memory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            result = client.preview_context("What is our database?")
            self.assertIn("context", result)

    def test_preview_context_with_memory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            client.ingest_document("notes", "Our database is PostgreSQL version 15.")
            result = client.preview_context("What database do we use?")
            self.assertEqual(result["ok"], True)
            self.assertIn("PostgreSQL", result.get("context", ""))

    # ── Run ───────────────────────────────────────────────────────────────

    def test_run_returns_run_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            client.ingest_document("notes", "The answer is 42.")
            result = client.run("retrieve notes")
            self.assertIsInstance(result, RunResult)
            self.assertIsInstance(result.ok, bool)

    def test_run_result_to_dict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            result = client.run("retrieve notes")
            d = result.to_dict()
            self.assertIn("ok", d)
            self.assertIn("output", d)
            self.assertIn("backend_id", d)
            self.assertIn("executions", d)

    # ── Memory property ───────────────────────────────────────────────────

    def test_memory_property_returns_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-sdk-test-") as tmp:
            client = self._client(tmp)
            from ghostchimera.memory_layer.store import MemoryStore
            self.assertIsInstance(client.memory, MemoryStore)
