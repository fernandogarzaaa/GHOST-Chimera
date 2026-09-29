"""Tests for automatic context compaction."""

from __future__ import annotations

import unittest

from ghostchimera.chimera_pilot.always_on.compaction import AutoCompactor
from ghostchimera.chimera_pilot.context_compressor import ContextCompressor


def _messages(count: int, chars_each: int = 400) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + ("x" * chars_each)}
        for i in range(count)
    ]


class AutoCompactorTests(unittest.TestCase):
    def test_short_session_is_untouched(self) -> None:
        compactor = AutoCompactor(model_context_length=128_000)
        messages = _messages(4)
        result, did_compact = compactor.maybe_compact(messages)
        self.assertFalse(did_compact)
        self.assertEqual(result, messages)

    def test_over_budget_session_compacts_automatically(self) -> None:
        # Tiny context window so the threshold is crossed quickly.
        compactor = AutoCompactor(model_context_length=4_000, threshold_percent=0.5)
        messages = _messages(40, chars_each=400)
        self.assertTrue(compactor.over_budget(messages))
        compacted, did_compact = compactor.maybe_compact(messages)
        self.assertTrue(did_compact)
        self.assertLess(len(compacted), len(messages))
        self.assertEqual(compactor.auto_compactions, 1)

    def test_compacted_output_preserves_tail(self) -> None:
        compactor = AutoCompactor(model_context_length=4_000, threshold_percent=0.5)
        messages = _messages(40, chars_each=400)
        compacted, did_compact = compactor.maybe_compact(messages)
        self.assertTrue(did_compact)
        tail_contents = [m.get("content") for m in compacted[-3:]]
        original_tail = [m["content"] for m in messages[-3:]]
        for original in original_tail:
            self.assertIn(original, tail_contents)

    def test_continuity_survives_state_round_trip(self) -> None:
        first = AutoCompactor(model_context_length=4_000, threshold_percent=0.5)
        messages = _messages(40, chars_each=400)
        compacted, did_compact = first.maybe_compact(messages)
        self.assertTrue(did_compact)
        state = first.get_compaction_state()
        self.assertTrue(state["iterative_summary"])

        # A fresh compactor restored from state keeps the earlier summary.
        second = AutoCompactor(model_context_length=4_000, threshold_percent=0.5)
        second.set_compaction_state(state)
        more = [{"role": "user", "content": "follow-up " + ("y" * 400)} for _ in range(40)]
        combined = compacted + more
        recompaced, did_compact_again = second.maybe_compact(combined)
        self.assertTrue(did_compact_again)
        summary_text = second.get_compaction_state()["iterative_summary"]
        self.assertIn("Previous compaction", summary_text)

    def test_invalid_threshold_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AutoCompactor(threshold_percent=1.5)
        with self.assertRaises(ValueError):
            AutoCompactor(threshold_percent=0.0)

    def test_compressor_state_export_import(self) -> None:
        compressor = ContextCompressor()
        compressor.set_compaction_state({"iterative_summary": "abc", "compression_count": 3})
        state = compressor.get_compaction_state()
        self.assertEqual(state["iterative_summary"], "abc")
        self.assertEqual(state["compression_count"], 3)
        compressor.set_compaction_state(None)
        self.assertEqual(compressor.get_compaction_state()["compression_count"], 0)

    def test_stats_reports_budget(self) -> None:
        compactor = AutoCompactor(model_context_length=8_000, threshold_percent=0.5)
        stats = compactor.stats()
        self.assertEqual(stats["threshold_tokens"], 4_000)
        self.assertEqual(stats["auto_compactions"], 0)


if __name__ == "__main__":
    unittest.main()
