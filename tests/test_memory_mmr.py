"""Tests for MMR-lite diverse retrieval (LangChain-inspired, no embeddings)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.memory_layer.store import MemoryStore, mmr_select


def _candidate(content: str, score: float) -> dict:
    return {"content": content, "score": score}


class MmrSelectTests(unittest.TestCase):
    def test_pure_relevance_keeps_input_order(self) -> None:
        candidates = [_candidate("b", 0.9), _candidate("a", 0.8)]
        self.assertEqual([c["content"] for c in mmr_select(candidates, 2, mmr_lambda=1.0)], ["b", "a"])

    def test_diversifies_against_near_duplicates(self) -> None:
        dup_a = "the quick brown fox jumps over the lazy dog near the river bank"
        dup_b = "the quick brown fox jumps over the lazy dog near the river side"
        other = "quantum entanglement enables secure communication protocols"
        candidates = [_candidate(dup_a, 0.95), _candidate(dup_b, 0.94), _candidate(other, 0.60)]
        selected = mmr_select(candidates, 2, mmr_lambda=0.3)
        contents = [c["content"] for c in selected]
        self.assertEqual(contents[0], dup_a)
        self.assertEqual(contents[1], other)

    def test_lambda_clamped_to_unit_interval(self) -> None:
        candidates = [_candidate("x y z", 0.5), _candidate("x y z", 0.5)]
        self.assertEqual(len(mmr_select(candidates, 5, mmr_lambda=99.0)), 2)
        self.assertEqual(len(mmr_select(candidates, 5, mmr_lambda=-3.0)), 2)

    def test_respects_limit_and_empty_input(self) -> None:
        candidates = [_candidate("alpha beta", 0.7), _candidate("gamma delta", 0.6)]
        self.assertEqual(len(mmr_select(candidates, 1, mmr_lambda=0.5)), 1)
        self.assertEqual(mmr_select([], 5, mmr_lambda=0.5), [])


class MemoryStoreMmrTests(unittest.TestCase):
    def _store(self, tmp: str) -> MemoryStore:
        return MemoryStore(Path(tmp) / "mem.sqlite3")

    def test_default_search_order_unchanged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-mmr-test-") as tmp:
            store = self._store(tmp)
            store.add_document("s1", "Ghost Chimera stealth loop observes events")
            store.add_document("s2", "Ghost Chimera stealth loop observes outcomes")
            store.add_document("s3", "unrelated gardening notes about roses")
            plain = store.search("stealth loop", limit=2)
            reranked = store.search("stealth loop", limit=2, mmr_lambda=1.0)
            self.assertEqual([r["id"] for r in plain], [r["id"] for r in reranked])

    def test_mmr_diversifies_duplicate_heavy_results(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-mmr-test-") as tmp:
            store = self._store(tmp)
            store.add_document("d1", "deployment runbook for the gateway server restart steps")
            store.add_document("d2", "deployment runbook for the gateway server restart guide")
            store.add_document("d3", "deployment runbook for the gateway server restart notes")
            store.add_document("d4", "deployment of tents for weekend hiking trips")
            results = store.search("deployment runbook gateway", limit=2, mmr_lambda=0.2, mmr_fetch_k=10)
            self.assertEqual(len(results), 2)
            sources = {r["source"] for r in results}
            # The hiking doc is the only novel content; MMR must surface it.
            self.assertIn("d4", sources)


if __name__ == "__main__":
    unittest.main()
