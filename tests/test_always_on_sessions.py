"""Tests for durable always-on sessions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.always_on.sessions import DurableSession, SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_create_and_get_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            session = store.create("ghost-agent-1", metadata={"purpose": "test"})
            self.assertTrue(session.session_id.startswith("session-"))
            self.assertEqual(session.agent_id, "ghost-agent-1")
            self.assertTrue((Path(tmp) / "always_on" / "sessions" / f"{session.session_id}.json").exists())
            reloaded = SessionStore(tmp).get(session.session_id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertEqual(reloaded.session_id, session.session_id)

    def test_append_message_persists_transcript(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            session = store.create("ghost-agent-1")
            store.append_message(session.session_id, {"role": "user", "content": "hello"})
            store.append_message(session.session_id, {"role": "assistant", "content": "hi there"})
            reloaded = SessionStore(tmp).get(session.session_id)
            assert reloaded is not None
            self.assertEqual(len(reloaded.messages), 2)
            self.assertEqual(reloaded.messages[0]["content"], "hello")

    def test_append_message_rejects_invalid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            session = store.create("ghost-agent-1")
            with self.assertRaises(ValueError):
                store.append_message(session.session_id, {"content": "missing role"})
            with self.assertRaises(KeyError):
                store.append_message("session-unknown", {"role": "user", "content": "x"})

    def test_get_or_create_for_agent_reuses_newest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            first = store.get_or_create_for_agent("ghost-agent-1")
            second = store.get_or_create_for_agent("ghost-agent-1")
            self.assertEqual(first.session_id, second.session_id)

    def test_set_state_persists_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            session = store.create("ghost-agent-1")
            store.set_state(session.session_id, "awake")
            reloaded = SessionStore(tmp).get(session.session_id)
            assert reloaded is not None
            self.assertEqual(reloaded.lifecycle_state, "awake")

    def test_record_wake_appends_history_and_compaction_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            session = store.create("ghost-agent-1")
            wake = {"request_id": "wake-1", "objective": "check inbox", "status": "completed"}
            compaction_state = {"iterative_summary": "earlier summary", "compression_count": 2}
            store.record_wake(session.session_id, wake, compaction_state=compaction_state, compaction_count=2)
            reloaded = SessionStore(tmp).get(session.session_id)
            assert reloaded is not None
            self.assertEqual(len(reloaded.wake_history), 1)
            self.assertEqual(reloaded.wake_history[0]["request_id"], "wake-1")
            self.assertEqual(reloaded.compaction_state["iterative_summary"], "earlier summary")
            self.assertEqual(reloaded.compaction_count, 2)

    def test_list_for_agent_filters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-session-") as tmp:
            store = SessionStore(tmp)
            store.create("ghost-agent-1")
            store.create("ghost-agent-2")
            self.assertEqual(len(store.list_for_agent("ghost-agent-1")), 1)
            self.assertEqual(len(store.list_all()), 2)

    def test_session_round_trip(self) -> None:
        session = DurableSession(
            session_id="session-x",
            agent_id="ghost-a",
            created_at=1.0,
            updated_at=2.0,
            messages=[{"role": "user", "content": "hi"}],
        )
        restored = DurableSession.from_dict(session.to_dict())
        self.assertEqual(restored.session_id, "session-x")
        self.assertEqual(restored.messages, [{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
