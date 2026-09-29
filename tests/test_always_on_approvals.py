"""Tests for policy-controlled approval gates."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest

from ghostchimera.chimera_pilot.always_on.approvals import (
    STATUS_APPROVED,
    STATUS_DENIED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    ApprovalStore,
    QueuedApprovalHandler,
)
from ghostchimera.safety_layer.approval import ApprovalRequest


class ApprovalStoreTests(unittest.TestCase):
    def test_create_and_list_pending(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            store = ApprovalStore(tmp)
            ticket = store.create("shell", {"command": "ls"}, requester="agent-1")
            self.assertEqual(ticket.status, STATUS_PENDING)
            pending = store.list_pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].ticket_id, ticket.ticket_id)
            # visible from a second store over the same dir (cross-process)
            self.assertEqual(len(ApprovalStore(tmp).list_pending()), 1)

    def test_decide_approve_and_deny(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            store = ApprovalStore(tmp)
            approved = store.create("shell", {})
            denied = store.create("write_file", {})
            store.decide(approved.ticket_id, True, decided_by="operator")
            store.decide(denied.ticket_id, False, decided_by="operator")
            self.assertEqual(store.get(approved.ticket_id).status, STATUS_APPROVED)  # type: ignore[union-attr]
            self.assertEqual(store.get(denied.ticket_id).status, STATUS_DENIED)  # type: ignore[union-attr]
            self.assertEqual(store.list_pending(), [])

    def test_decide_terminal_ticket_raises(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            store = ApprovalStore(tmp)
            ticket = store.create("shell", {})
            store.decide(ticket.ticket_id, True)
            with self.assertRaises(ValueError):
                store.decide(ticket.ticket_id, False)
            with self.assertRaises(KeyError):
                store.decide("approval-unknown", True)

    def test_expire_stale(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            store = ApprovalStore(tmp)
            ticket = store.create("shell", {})
            self.assertEqual(store.expire_stale(older_than_seconds=-1), 1)
            self.assertEqual(store.get(ticket.ticket_id).status, STATUS_EXPIRED)  # type: ignore[union-attr]


class QueuedApprovalHandlerTests(unittest.TestCase):
    def test_trusted_tool_never_parks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            handler = QueuedApprovalHandler(ApprovalStore(tmp))
            result = handler.handle(ApprovalRequest(tool_name="read_file", requester="agent-1"))
            self.assertTrue(result.approved)
            self.assertEqual(handler.store.list_pending(), [])

    def test_blocked_tool_never_parks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            handler = QueuedApprovalHandler(ApprovalStore(tmp))
            result = handler.handle(ApprovalRequest(tool_name="delete_everything", requester="agent-1"))
            self.assertFalse(result.approved)
            self.assertEqual(handler.store.list_pending(), [])

    def test_approval_blocks_until_decided(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            handler = QueuedApprovalHandler(ApprovalStore(tmp), wait_timeout_seconds=10.0)
            outcomes: list = []

            def requester() -> None:
                outcomes.append(handler.handle(ApprovalRequest(tool_name="shell", requester="agent-1")))

            thread = threading.Thread(target=requester, daemon=True)
            thread.start()
            # wait for the ticket to be parked
            deadline = time.time() + 5
            while not handler.store.list_pending() and time.time() < deadline:
                time.sleep(0.05)
            pending = handler.store.list_pending()
            self.assertEqual(len(pending), 1)
            handler.decide(pending[0].ticket_id, True, decided_by="test-operator")
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertTrue(outcomes[0].approved)
            self.assertIn("test-operator", outcomes[0].reason)

    def test_denied_decision_blocks_tool(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            handler = QueuedApprovalHandler(ApprovalStore(tmp), wait_timeout_seconds=10.0)
            outcomes: list = []
            thread = threading.Thread(
                target=lambda: outcomes.append(handler.handle(ApprovalRequest(tool_name="shell"))),
                daemon=True,
            )
            thread.start()
            deadline = time.time() + 5
            while not handler.store.list_pending() and time.time() < deadline:
                time.sleep(0.05)
            pending = handler.store.list_pending()
            self.assertEqual(len(pending), 1)
            handler.decide(pending[0].ticket_id, False, decided_by="test-operator")
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertFalse(outcomes[0].approved)

    def test_timeout_expires_ticket_and_denies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-approvals-") as tmp:
            handler = QueuedApprovalHandler(ApprovalStore(tmp), wait_timeout_seconds=0.6, poll_interval_seconds=0.1)
            result = handler.handle(ApprovalRequest(tool_name="shell", requester="agent-1"))
            self.assertFalse(result.approved)
            self.assertIn("timed out", result.reason)
            self.assertEqual(handler.store.list_pending(), [])
            recent = handler.store.list_recent()
            self.assertEqual(recent[0].status, STATUS_EXPIRED)


if __name__ == "__main__":
    unittest.main()
