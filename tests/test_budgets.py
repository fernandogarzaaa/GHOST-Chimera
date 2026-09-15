"""Tests for cost and attention budgets."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.budgets import (
    ATTENTION_BUDGET,
    COST_BUDGET,
    PROPOSAL_BUDGET,
    Budget,
    BudgetTracker,
)
from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.stealth_policy import AutonomyLevel


class BudgetTests(unittest.TestCase):
    def test_spend_gates_and_slides(self) -> None:
        budget = Budget("t", limit=2.0, window_s=60.0)

        self.assertTrue(budget.spend(1.0, now=1000.0))
        self.assertTrue(budget.spend(1.0, now=1001.0))
        self.assertFalse(budget.spend(1.0, now=1002.0))
        self.assertEqual(budget.spent(now=1002.0), 2.0)
        self.assertEqual(budget.remaining(now=1002.0), 0.0)
        self.assertTrue(budget.check(2.0, now=2000.0))
        self.assertEqual(budget.spent(now=2000.0), 0.0)

    def test_failed_spend_records_nothing(self) -> None:
        budget = Budget("t", limit=1.0, window_s=60.0)

        self.assertFalse(budget.spend(2.0, now=1000.0))
        self.assertEqual(budget.spent(now=1000.0), 0.0)
        self.assertFalse(budget.check(-1.0, now=1000.0))

    def test_record_meters_without_gating(self) -> None:
        budget = Budget("t", limit=1.0, window_s=60.0)

        self.assertEqual(budget.record(5.0, now=1000.0), 5.0)
        self.assertFalse(budget.check(1.0, now=1000.0))


class TrackerTests(unittest.TestCase):
    def test_defaults_and_unknown_fail_open(self) -> None:
        tracker = BudgetTracker()

        self.assertEqual(len(tracker), 3)
        self.assertTrue(tracker.spend("nope", 999.0, now=1000.0))
        self.assertTrue(tracker.check("nope", 999.0, now=1000.0))
        self.assertEqual(tracker.record("nope", 999.0, now=1000.0), 0.0)
        self.assertIsNone(tracker.get("nope"))

    def test_redefine_and_cost_units(self) -> None:
        tracker = BudgetTracker(defaults=False)
        tracker.define(COST_BUDGET, 100.0, window_s=60.0, unit="tokens")

        self.assertTrue(tracker.spend(COST_BUDGET, 90.0, now=1000.0))
        self.assertFalse(tracker.spend(COST_BUDGET, 11.0, now=1001.0))
        self.assertEqual(tracker.get(COST_BUDGET).unit, "tokens")

    def test_round_trip_skips_corrupt_spends(self) -> None:
        tracker = BudgetTracker(defaults=False)
        tracker.define("w", 10.0, window_s=60.0)
        tracker.record("w", 4.0, now=1000.0)
        restored = BudgetTracker.from_dict(
            {"budgets": tracker.to_dict()["budgets"] + [{"name": "bad", "spends": [["x"], None, [1.0, -2.0]]}]}
        )

        self.assertEqual(restored.get("w").spent(now=1000.0), 4.0)
        self.assertEqual(restored.get("bad").spent(now=1000.0), 0.0)


class LoopBudgetTests(unittest.TestCase):
    def _firing_loop(self):
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        loop.budgets.define(PROPOSAL_BUDGET, 1.0, window_s=3600.0, unit="test")
        loop.triggers.define(
            {
                "name": "invoice-watch",
                "event_type": "email.received",
                "conditions": [{"field": "payload.subject", "op": "contains", "value": "invoice"}],
                "action": {"kind": "suggest", "workflow": "pay-invoice"},
            }
        )
        return loop

    def test_proposal_creation_obeys_budget(self) -> None:
        loop = self._firing_loop()
        try:
            for step in range(3):
                loop.emit(
                    new_event(
                        "email.received",
                        source="gmail",
                        payload={"subject": "invoice overdue"},
                        timestamp=3000.0 + step,
                    )
                )

            self.assertEqual(len(loop.recent_trigger_hits(10)), 3)
            self.assertEqual(len(loop.proposals.pending(now=3005.0)), 1)
            self.assertEqual(loop.budgets.get(PROPOSAL_BUDGET).spent(now=3005.0), 1.0)
        finally:
            loop.close()

    def test_approval_filing_meters_attention(self) -> None:
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        try:
            draft = loop.proposals.propose("prefill", title="pay", now=1000.0)
            ask = loop.submit_proposal(draft.id, AutonomyLevel.ACT, now=1001.0)

            self.assertIsNotNone(ask)
            self.assertEqual(loop.budgets.get(ATTENTION_BUDGET).spent(), 1.0)
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
