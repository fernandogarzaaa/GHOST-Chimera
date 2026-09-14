"""Tests for structured approval requests (submit/ASK handoff)."""

from __future__ import annotations

import json
import unittest

from ghostchimera.stealth.approvals import ApprovalQueue, ApprovalState
from ghostchimera.stealth.graduation import ProposalQueue
from ghostchimera.stealth.intervention import Intervention
from ghostchimera.stealth.stealth_policy import AutonomyLevel


def _auto_output() -> str:
    return json.dumps(
        {
            "event_summary": "Client asks to reschedule.",
            "confidence_score": 0.95,
            "action_type": "AUTONOMOUS_EXECUTE",
            "actions": [{"provider": "slack", "endpoint": "/chat.postMessage", "payload": {"channel": "#ops"}}],
        }
    )


class LifecycleTests(unittest.TestCase):
    def test_approve_and_deny(self) -> None:
        queue = ApprovalQueue()
        item = queue.request("pay invoice", body="42 due", workflow="pay", risk=0.2, requested_by="ghost")

        self.assertEqual(item.state, ApprovalState.PENDING)
        self.assertTrue(queue.approve(item.id, "alex", "looks right"))
        self.assertEqual(item.state, ApprovalState.APPROVED)
        self.assertEqual(item.decided_by, "alex")
        self.assertFalse(queue.approve(item.id, "alex"))
        self.assertFalse(queue.deny(item.id, "alex"))

        other = queue.request("second ask", now=2000.0)
        self.assertTrue(queue.deny(other.id, "alex", "not now", now=2001.0))
        self.assertEqual(other.decision_note, "not now")
        self.assertFalse(queue.approve("missing", "alex"))
        self.assertFalse(queue.deny("missing", "alex"))

    def test_overdue_settles_as_expired(self) -> None:
        queue = ApprovalQueue()
        item = queue.request("stale ask", now=1000.0, ttl_s=60.0)

        self.assertFalse(queue.approve(item.id, "alex", now=2000.0))
        self.assertEqual(item.state, ApprovalState.EXPIRED)

    def test_sweep_expires_overdue_only(self) -> None:
        queue = ApprovalQueue()
        old = queue.request("old", now=1000.0, ttl_s=60.0)
        fresh = queue.request("fresh", now=1000.0, ttl_s=3600.0)

        self.assertEqual(queue.sweep(now=1070.0), 1)
        self.assertEqual(old.state, ApprovalState.EXPIRED)
        self.assertEqual(queue.pending(), [fresh])


class HandoffTests(unittest.TestCase):
    def test_proposal_handoff_requires_submit_tier(self) -> None:
        proposals = ProposalQueue()
        queue = ApprovalQueue()
        draft = proposals.propose("prefill", title="draft", now=1000.0)

        self.assertIsNone(queue.request_for_proposal(draft, now=1000.0))
        self.assertTrue(proposals.submit(draft.id, AutonomyLevel.ACT, now=1001.0))
        ask = queue.request_for_proposal(draft, requested_by="ghost", now=1001.0)

        self.assertIsNotNone(ask)
        self.assertEqual(ask.source_kind, "proposal")
        self.assertEqual(ask.source_id, draft.id)
        self.assertEqual(ask.details["proposal_state"], "submitted")

        stale = proposals.propose("submit", title="stale", now=1000.0, ttl_s=60.0)
        proposals.sweep(now=2000.0)
        self.assertIsNone(queue.request_for_proposal(stale, now=2000.0))

    def test_intervention_handoff_shape(self) -> None:
        queue = ApprovalQueue()
        intervention = Intervention(workflow="pay-invoice", confidence=0.9, reason="external send needs approval")
        ask = queue.request_for_intervention(intervention, now=1000.0)

        self.assertEqual(ask.source_kind, "intervention")
        self.assertEqual(ask.source_id, intervention.id)
        self.assertIn("pay-invoice", ask.subject)
        self.assertEqual(ask.body, "external send needs approval")

    def test_full_queue_refuses_without_recycling(self) -> None:
        queue = ApprovalQueue(max_pending=1)
        queue.request("first", now=1000.0)

        self.assertIsNone(queue.request("second", now=1001.0))
        self.assertEqual(len(queue.pending()), 1)


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        queue = ApprovalQueue()
        item = queue.request("pay", workflow="w", risk=0.9, requested_by="ghost", now=1000.0)
        queue.approve(item.id, "alex", "ok", now=1001.0)
        restored = ApprovalQueue.from_dict(queue.to_dict())
        loaded = restored.get(item.id)

        self.assertEqual(loaded.state, ApprovalState.APPROVED)
        self.assertEqual(loaded.decided_by, "alex")
        self.assertEqual(loaded.risk, 0.9)

    def test_corrupt_state_and_risk_clamped(self) -> None:
        restored = ApprovalQueue.from_dict(
            {"requests": [{"id": "a1", "state": "bogus", "risk": 9.9, "created_at": 1.0}]}
        )
        loaded = restored.get("a1")

        self.assertEqual(loaded.state, ApprovalState.PENDING)
        self.assertEqual(loaded.risk, 1.0)


class LoopHandoffTests(unittest.TestCase):
    def test_submit_proposal_files_approval(self) -> None:
        from ghostchimera.stealth import StealthLoop

        loop = StealthLoop()
        try:
            draft = loop.proposals.propose("prefill", title="pay invoice", workflow="pay", now=1000.0)
            self.assertIsNone(loop.submit_proposal(draft.id, AutonomyLevel.OBSERVE, now=1001.0))

            ask = loop.submit_proposal(draft.id, AutonomyLevel.ACT, requested_by="ghost", now=1001.0)

            self.assertIsNotNone(ask)
            self.assertEqual(ask.source_id, draft.id)
            self.assertEqual(draft.state.value, "submitted")
            self.assertEqual(loop.approvals.pending(), [ask])
        finally:
            loop.close()

    def test_ask_decision_files_approval(self) -> None:
        from ghostchimera.stealth import GhostPolicy, StealthLoop

        loop = StealthLoop(policy=GhostPolicy(autonomy=AutonomyLevel.PREPARE))
        try:
            result = loop.handle_agent_output(_auto_output())

            self.assertEqual(result["decision"], "ask")
            self.assertTrue(result["approval_id"])
            pending = loop.approvals.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].source_kind, "intervention")
            self.assertEqual(pending[0].source_id, result["intervention_id"])
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
