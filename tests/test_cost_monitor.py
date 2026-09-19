"""Tests for cost monitoring ledger (no network, no real spend)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.model_layer.cost_monitor import (
    BudgetExceeded,
    CostLedger,
    estimate_tokens,
    price_usd_per_1k,
)


class EstimateTests(unittest.TestCase):
    def test_empty_is_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)

    def test_roughly_four_chars_per_token(self) -> None:
        self.assertEqual(estimate_tokens("abcd" * 100), 100)


class PriceTests(unittest.TestCase):
    def test_unknown_model_is_zero(self) -> None:
        self.assertEqual(price_usd_per_1k("nope", "nothing"), (0.0, 0.0))

    def test_known_model_has_price(self) -> None:
        price_in, price_out = price_usd_per_1k("openai", "gpt-3.5-turbo")
        self.assertGreater(price_in, 0.0)
        self.assertGreater(price_out, 0.0)


class LedgerTests(unittest.TestCase):
    def test_record_and_totals(self) -> None:
        ledger = CostLedger()
        cost = ledger.record("openai", "gpt-3.5-turbo", input_tokens=1000, output_tokens=1000)
        self.assertAlmostEqual(cost, 0.0005 + 0.0015)
        self.assertAlmostEqual(ledger.spend("openai"), cost)
        self.assertAlmostEqual(ledger.total_spend(), cost)
        self.assertEqual(ledger.calls("openai"), 1)

    def test_unpriced_records_zero_but_counts_calls(self) -> None:
        ledger = CostLedger()
        cost = ledger.record("mystery", "mystery-model", input_text="hello world", output_text="hi")
        self.assertEqual(cost, 0.0)
        self.assertEqual(ledger.calls("mystery"), 1)

    def test_budget_enforcement(self) -> None:
        ledger = CostLedger()
        ledger.set_budget("openai", 0.001)
        ledger.record("openai", "gpt-3.5-turbo", input_tokens=1000, output_tokens=1000)
        with self.assertRaises(BudgetExceeded):
            ledger.check("openai")
        ledger.set_budget("openai", 0)  # removes the cap
        ledger.check("openai")  # no raise

    def test_other_providers_unaffected_by_cap(self) -> None:
        ledger = CostLedger()
        ledger.set_budget("openai", 0.0000001)
        ledger.record("anthropic", "x", input_tokens=10**9, output_tokens=0)
        ledger.check("anthropic")  # no raise

    def test_save_and_load_round_trip(self) -> None:
        ledger = CostLedger()
        ledger.record("openai", "gpt-3.5-turbo", input_tokens=2000, output_tokens=0)
        ledger.set_budget("openai", 9.0)
        with tempfile.TemporaryDirectory(prefix="gc-cost-") as tmp:
            path = ledger.save(Path(tmp) / "costs.json")
            loaded = CostLedger.load(path)
        self.assertAlmostEqual(loaded.spend("openai"), ledger.spend("openai"))
        self.assertEqual(loaded.calls("openai"), 1)
        loaded.check("openai")  # budget persisted, spend below it

    def test_load_missing_file_is_empty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gc-cost-") as tmp:
            loaded = CostLedger.load(Path(tmp) / "nope.json")
        self.assertEqual(loaded.total_spend(), 0.0)


if __name__ == "__main__":
    unittest.main()
