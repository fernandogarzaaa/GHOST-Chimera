"""Tests for graduated action tiers (SUGGEST / PREVIEW / PRE-FILL / SUBMIT)."""

from __future__ import annotations

import unittest

from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.graduation import (
    ProposalQueue,
    ProposalState,
    ProposalTier,
    proposal_from_hit,
)
from ghostchimera.stealth.stealth_policy import AutonomyLevel
from ghostchimera.stealth.triggers import TriggerHit


class AdvanceTests(unittest.TestCase):
    def test_full_ladder_with_gates(self) -> None:
        queue = ProposalQueue()
        proposal = queue.propose(ProposalTier.SUGGEST, title="pay invoice", now=1000.0)

        self.assertTrue(queue.advance(proposal.id, AutonomyLevel.OBSERVE, now=1001.0))
        self.assertEqual(proposal.tier, ProposalTier.PREVIEW)
        self.assertFalse(queue.advance(proposal.id, AutonomyLevel.OBSERVE, now=1001.0))
        self.assertTrue(queue.advance(proposal.id, AutonomyLevel.PREPARE, now=1001.0))
        self.assertEqual(proposal.tier, ProposalTier.PREFILL)
        self.assertFalse(queue.advance(proposal.id, AutonomyLevel.PREPARE, now=1001.0))
        self.assertFalse(queue.submit(proposal.id, AutonomyLevel.PREPARE, now=1001.0))
        self.assertTrue(queue.submit(proposal.id, AutonomyLevel.ACT, now=1001.0))
        self.assertEqual(proposal.state, ProposalState.SUBMITTED)
        self.assertFalse(queue.advance(proposal.id, AutonomyLevel.ACT, now=1001.0))
        self.assertFalse(queue.dismiss(proposal.id, now=1001.0))

    def test_dismiss_and_unknown_ids(self) -> None:
        queue = ProposalQueue()
        proposal = queue.propose("suggest", title="x", now=1000.0)

        self.assertTrue(queue.dismiss(proposal.id, now=1001.0))
        self.assertEqual(proposal.state, ProposalState.DISMISSED)
        self.assertFalse(queue.dismiss(proposal.id, now=1001.0))
        self.assertFalse(queue.advance("missing", AutonomyLevel.ACT, now=1001.0))
        self.assertFalse(queue.submit("missing", AutonomyLevel.ACT, now=1001.0))

    def test_unknown_tier_falls_back_to_suggest(self) -> None:
        queue = ProposalQueue()
        proposal = queue.propose("frob", title="x", now=1000.0)

        self.assertEqual(proposal.tier, ProposalTier.SUGGEST)


class ExpiryTests(unittest.TestCase):
    def test_sweep_expires_overdue_only(self) -> None:
        queue = ProposalQueue()
        old = queue.propose("suggest", title="old", now=1000.0, ttl_s=60.0)
        fresh = queue.propose("suggest", title="fresh", now=1000.0, ttl_s=3600.0)

        self.assertEqual(queue.sweep(now=1070.0), 1)
        self.assertEqual(old.state, ProposalState.EXPIRED)
        self.assertEqual(fresh.state, ProposalState.PENDING)
        self.assertEqual(queue.pending(now=1070.0), [fresh])

    def test_advance_refuses_expired_proposals(self) -> None:
        queue = ProposalQueue()
        proposal = queue.propose("suggest", title="stale", now=1000.0, ttl_s=60.0)

        self.assertFalse(queue.advance(proposal.id, AutonomyLevel.ACT, now=2000.0))
        self.assertEqual(proposal.state, ProposalState.EXPIRED)
        self.assertEqual(queue.pending(now=2000.0), [])


class FromHitTests(unittest.TestCase):
    def _hit(self, kind: str) -> TriggerHit:
        return TriggerHit(
            trigger_name="invoice-watch",
            event_id="evt-1",
            action={"kind": kind, "workflow": "pay-invoice", "prefill": {"amount": 42}},
            fired_at=2000.0,
        )

    def test_kinds_map_to_tiers(self) -> None:
        for kind, tier in (
            ("suggest", ProposalTier.SUGGEST),
            ("preview", ProposalTier.PREVIEW),
            ("prefill", ProposalTier.PREFILL),
            ("submit", ProposalTier.SUBMIT),
        ):
            proposal = proposal_from_hit(self._hit(kind), now=2000.0)
            self.assertEqual(proposal.tier, tier)
            self.assertEqual(proposal.workflow, "pay-invoice")
            self.assertEqual(proposal.prefill, {"amount": 42})
            self.assertEqual(proposal.source, "invoice-watch")

    def test_non_graduated_kinds_stay_bare_hits(self) -> None:
        self.assertIsNone(proposal_from_hit(self._hit("note")))
        self.assertIsNone(proposal_from_hit(self._hit("frob")))
        self.assertIsNone(proposal_from_hit(TriggerHit("t", "e", {}, 0.0)))


class QueueCapTests(unittest.TestCase):
    def test_full_queue_recycles_oldest_suggest(self) -> None:
        queue = ProposalQueue(max_pending=2)
        first = queue.propose("suggest", title="first", now=1000.0)
        queue.propose("suggest", title="second", now=1001.0)
        third = queue.propose("suggest", title="third", now=1002.0)

        self.assertIsNotNone(third)
        self.assertEqual(first.state, ProposalState.DISMISSED)

    def test_full_queue_of_drafts_refuses_new(self) -> None:
        queue = ProposalQueue(max_pending=1)
        queue.propose("prefill", title="draft", now=1000.0)

        self.assertIsNone(queue.propose("suggest", title="extra", now=1001.0))


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        queue = ProposalQueue()
        created = queue.propose("prefill", title="draft", workflow="w", prefill={"a": 1}, now=1000.0)
        queue.dismiss(created.id, now=1001.0)
        restored = ProposalQueue.from_dict(queue.to_dict())

        self.assertEqual(len(restored), 1)
        loaded = restored.get(created.id)
        self.assertEqual(loaded.tier, ProposalTier.PREFILL)
        self.assertEqual(loaded.state, ProposalState.DISMISSED)
        self.assertEqual(loaded.prefill, {"a": 1})

    def test_corrupt_tier_and_state_fall_back(self) -> None:
        restored = ProposalQueue.from_dict(
            {"proposals": [{"id": "p1", "tier": "frob", "state": "bogus", "created_at": 1.0}]}
        )
        loaded = restored.get("p1")

        self.assertEqual(loaded.tier, ProposalTier.SUGGEST)
        self.assertEqual(loaded.state, ProposalState.PENDING)


class LoopIntegrationTests(unittest.TestCase):
    def test_trigger_hit_becomes_pending_proposal(self) -> None:
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        plain = StealthLoop()
        try:
            loop.triggers.define(
                {
                    "name": "invoice-watch",
                    "event_type": "email.received",
                    "conditions": [{"field": "payload.subject", "op": "contains", "value": "invoice"}],
                    "action": {"kind": "suggest", "workflow": "pay-invoice"},
                }
            )
            event = new_event(
                "email.received",
                source="gmail",
                payload={"subject": "invoice overdue"},
                timestamp=3000.0,
            )
            loop.emit(event)
            plain.emit(
                new_event(
                    "email.received",
                    source="gmail",
                    payload={"subject": "invoice overdue"},
                    timestamp=3000.0,
                )
            )

            self.assertEqual(loop.last_result.decision, plain.last_result.decision)
            pending = loop.proposals.pending(now=3001.0)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].tier, ProposalTier.SUGGEST)
            self.assertEqual(pending[0].workflow, "pay-invoice")
            self.assertEqual(pending[0].source, "invoice-watch")
        finally:
            loop.close()
            plain.close()


if __name__ == "__main__":
    unittest.main()
