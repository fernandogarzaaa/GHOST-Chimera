"""Unit tests for memory store freshness, citation quality, count(), and stale filtering."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ghostchimera.memory_layer.store import MemoryStore, _citation_quality, _freshness_score


class FreshnessScoreTests(unittest.TestCase):
    def test_fresh_document_scores_near_one(self) -> None:
        now = datetime.now(UTC).isoformat()
        score = _freshness_score(now)
        self.assertGreater(score, 0.99)

    def test_very_old_document_scores_near_zero(self) -> None:
        old = (datetime.now(UTC) - timedelta(days=3650)).isoformat()
        score = _freshness_score(old)
        self.assertLess(score, 0.1)

    def test_half_life_at_30_days(self) -> None:
        ts = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        score = _freshness_score(ts, half_life_days=30.0)
        self.assertAlmostEqual(score, 0.5, delta=0.01)

    def test_empty_timestamp_returns_default(self) -> None:
        score = _freshness_score("")
        self.assertEqual(score, 0.5)

    def test_invalid_timestamp_returns_default(self) -> None:
        score = _freshness_score("not-a-date")
        self.assertEqual(score, 0.5)

    def test_zero_half_life_returns_one(self) -> None:
        ts = (datetime.now(UTC) - timedelta(days=999)).isoformat()
        score = _freshness_score(ts, half_life_days=0)
        self.assertEqual(score, 1.0)


class CitationQualityTests(unittest.TestCase):
    def test_long_fresh_document_has_high_quality(self) -> None:
        content = "x" * 500
        quality = _citation_quality(content, freshness=1.0)
        self.assertGreater(quality, 0.9)

    def test_empty_stale_document_has_low_quality(self) -> None:
        quality = _citation_quality("", freshness=0.0)
        self.assertEqual(quality, 0.0)

    def test_quality_bounded_to_one(self) -> None:
        quality = _citation_quality("x" * 10000, freshness=1.0)
        self.assertLessEqual(quality, 1.0)

    def test_quality_bounded_to_zero(self) -> None:
        quality = _citation_quality("x" * 1000, freshness=0.0)
        self.assertGreaterEqual(quality, 0.0)


class MemoryStoreFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="gc-mem-test-")
        self.store = MemoryStore(Path(self.tmp.name) / "mem.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_includes_freshness_score(self) -> None:
        self.store.add_document("src", "freshness score test document")
        results = self.store.search("freshness score")
        self.assertTrue(results)
        self.assertIn("freshness_score", results[0])
        self.assertIn("citation_quality", results[0])
        self.assertIn("created_at", results[0])

    def test_freshness_score_is_float_in_range(self) -> None:
        self.store.add_document("src", "check freshness bounds")
        results = self.store.search("check freshness")
        self.assertIsInstance(results[0]["freshness_score"], float)
        self.assertGreaterEqual(results[0]["freshness_score"], 0.0)
        self.assertLessEqual(results[0]["freshness_score"], 1.0)

    def test_citation_quality_is_float_in_range(self) -> None:
        self.store.add_document("src", "check citation quality")
        results = self.store.search("citation quality")
        self.assertIsInstance(results[0]["citation_quality"], float)
        self.assertGreaterEqual(results[0]["citation_quality"], 0.0)
        self.assertLessEqual(results[0]["citation_quality"], 1.0)

    def test_freshly_inserted_doc_has_near_one_freshness(self) -> None:
        self.store.add_document("src", "brand new document for freshness check")
        results = self.store.search("brand new freshness")
        self.assertGreater(results[0]["freshness_score"], 0.99)

    def test_stale_after_days_excludes_old_documents(self) -> None:
        # Insert and then backdate the created_at
        self.store.add_document("old-src", "old stale document for filter test")
        # Manually update the created_at to a year ago
        old_ts = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        with self.store._connect() as conn:
            conn.execute("UPDATE memory_documents SET created_at = ? WHERE source = 'old-src'", (old_ts,))
        self.store.add_document("new-src", "fresh new document for filter test")

        # Without filter: should see both
        all_results = self.store.search("document filter test", limit=10)
        self.assertGreater(len(all_results), 0)

        # With 30-day filter: old doc should be excluded
        fresh_results = self.store.search("document filter test", limit=10, stale_after_days=30.0)
        sources = {r["source"] for r in fresh_results}
        self.assertNotIn("old-src", sources)
        self.assertIn("new-src", sources)

    def test_stale_filter_none_returns_all(self) -> None:
        self.store.add_document("a", "document alpha test")
        self.store.add_document("b", "document beta test")
        results = self.store.search("document test", stale_after_days=None)
        self.assertGreaterEqual(len(results), 2)

    def test_empty_query_returns_empty_list(self) -> None:
        self.store.add_document("src", "some content")
        results = self.store.search("")
        self.assertEqual(results, [])

    def test_empty_store_returns_empty_list(self) -> None:
        results = self.store.search("anything at all")
        self.assertEqual(results, [])


class MemoryStoreCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="gc-count-test-")
        self.store = MemoryStore(Path(self.tmp.name) / "mem.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_count_zero_on_empty_store(self) -> None:
        self.assertEqual(self.store.count(), 0)

    def test_count_increments_with_inserts(self) -> None:
        self.store.add_document("s1", "first doc")
        self.assertEqual(self.store.count(), 1)
        self.store.add_document("s2", "second doc")
        self.assertEqual(self.store.count(), 2)
        self.store.add_document("s3", "third doc")
        self.assertEqual(self.store.count(), 3)

    def test_count_not_incremented_by_duplicate(self) -> None:
        self.store.add_document_once("src", "unique content")
        self.store.add_document_once("src", "unique content")
        self.assertEqual(self.store.count(), 1)


if __name__ == "__main__":
    unittest.main()
