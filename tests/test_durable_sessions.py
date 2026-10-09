"""Durable gateway sessions backed by the extended TrustRuntimeStore.

Covers: TrustRuntimeStore session CRUD, SessionState to_dict/from_dict
round-trips plus save/load, and gateway restore-on-restart / resume.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ghostchimera.chimera_pilot.agent_loop import Message, SessionState
from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.trust_runtime import TrustRuntimeStore


def _config(state_dir: Path) -> GhostChimeraConfig:
    return dataclasses.replace(GhostChimeraConfig.from_env(), state_dir=state_dir)


def _sample_payload(session_id: str = "sess-1") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "system_prompt": "be helpful",
        "model_name": "test-model",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there", "tokens": 4},
        ],
        "total_tokens": 12,
        "compression_count": 1,
    }


class TrustRuntimeSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-sessions-")
        self.store = TrustRuntimeStore(Path(self._dir.name) / "state")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_save_and_get_round_trip(self) -> None:
        receipt = self.store.save_session(_sample_payload())
        self.assertEqual(receipt, {"ok": True, "session_id": "sess-1"})
        loaded = self.store.get_session("sess-1")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["messages"], _sample_payload()["messages"])
        self.assertEqual(loaded["total_tokens"], 12)
        self.assertIn("updated_at", loaded)

    def test_save_requires_session_id(self) -> None:
        receipt = self.store.save_session({"messages": []})
        self.assertFalse(receipt["ok"])
        self.assertIsNone(self.store.get_session(""))

    def test_get_unknown_returns_none(self) -> None:
        self.assertIsNone(self.store.get_session("nope"))

    def test_list_orders_by_recency(self) -> None:
        self.store.save_session(_sample_payload("old"))
        self.store.save_session(_sample_payload("new"))
        result = self.store.list_sessions()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["sessions"][0]["session_id"], "new")

    def test_delete_session(self) -> None:
        self.store.save_session(_sample_payload())
        receipt = self.store.delete_session("sess-1")
        self.assertEqual(receipt, {"ok": True, "session_id": "sess-1"})
        self.assertIsNone(self.store.get_session("sess-1"))
        missing = self.store.delete_session("sess-1")
        self.assertFalse(missing["ok"])

    def test_corrupt_file_recovers_to_default(self) -> None:
        self.store.sessions_path.write_text("not json{{{", encoding="utf-8")
        self.assertIsNone(self.store.get_session("sess-1"))
        result = self.store.list_sessions()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 0)

    def test_session_messages_written_unredacted(self) -> None:
        # Redaction would corrupt message fidelity on resume, so session
        # snapshots must be stored verbatim.
        secret_like = "sk-test-1234567890abcdef"
        self.store.save_session(
            {
                "session_id": "sess-1",
                "messages": [{"role": "user", "content": f"my api_key is {secret_like}"}],
            }
        )
        raw = self.store.sessions_path.read_text(encoding="utf-8")
        self.assertIn(secret_like, raw)
        loaded = self.store.get_session("sess-1")
        assert loaded is not None
        self.assertIn(secret_like, loaded["messages"][0]["content"])

    def test_save_is_atomic(self) -> None:
        self.store.save_session(_sample_payload())
        leftovers = list(self.store.sessions_path.parent.glob("sessions.json.tmp"))
        self.assertEqual(leftovers, [])

    def test_store_creates_directories(self) -> None:
        self.assertTrue(self.store.trust_dir.is_dir())
        self.assertTrue(self.store.runs_dir.is_dir())
        self.assertEqual(self.store.sessions_path.parent, self.store.trust_dir)

    def test_list_respects_limit(self) -> None:
        for i in range(3):
            self.store.save_session(_sample_payload(f"s-{i}"))
        result = self.store.list_sessions(limit=2)
        self.assertEqual(len(result["sessions"]), 2)
        self.assertEqual(result["count"], 3)

    def test_list_limit_zero_clamps_to_one(self) -> None:
        for i in range(3):
            self.store.save_session(_sample_payload(f"s-{i}"))
        result = self.store.list_sessions(limit=0)
        self.assertEqual(len(result["sessions"]), 1)

    def test_list_tolerates_record_without_updated_at(self) -> None:
        self.store.save_session(_sample_payload("with-ts"))
        sessions = {**self.store._load_json(self.store.sessions_path, {})}
        sessions["legacy"] = {"session_id": "legacy", "messages": []}
        self.store._write_json(self.store.sessions_path, sessions, redact=False)
        result = self.store.list_sessions()
        self.assertEqual(result["count"], 2)
        # The record without updated_at sorts as oldest (fallback 0), not crash.
        self.assertEqual(result["sessions"][-1]["session_id"], "legacy")

    def test_delete_keeps_remaining_sessions_unredacted(self) -> None:
        secret_like = "sk-test-1234567890abcdef"
        self.store.save_session({"session_id": "keep", "messages": [{"role": "user", "content": f"key {secret_like}"}]})
        self.store.save_session(_sample_payload("drop"))
        self.store.delete_session("drop")
        raw = self.store.sessions_path.read_text(encoding="utf-8")
        self.assertIn(secret_like, raw)
        kept = self.store.get_session("keep")
        assert kept is not None
        self.assertIn(secret_like, kept["messages"][0]["content"])

    def test_write_json_redacts_by_default(self) -> None:
        path = self.store.trust_dir / "probe.json"
        self.store._write_json(path, {"api_key": "sk-test-1234567890"})
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("sk-test-1234567890", raw)
        self.assertIn("[redacted]", raw)

    def test_write_json_raw_when_asked(self) -> None:
        path = self.store.trust_dir / "probe-raw.json"
        self.store._write_json(path, {"api_key": "sk-test-1234567890"}, redact=False)
        raw = path.read_text(encoding="utf-8")
        self.assertIn("sk-test-1234567890", raw)


class SessionStateSerializationTests(unittest.TestCase):
    def _state(self) -> SessionState:
        state = SessionState(session_id="s-9", system_prompt="sys", model_name="m")
        state.messages.append(Message(role="user", content="hi"))
        state.messages.append(
            Message(
                role="assistant",
                content="done",
                tool_calls=[{"name": "t", "arguments": {}}],
                tokens=7,
            )
        )
        state.total_tokens = 42
        state.compression_count = 2
        state.confidence_history = [0.5, 0.9]
        state.api_call_count = 3
        state.estimated_cost_usd = 0.001
        return state

    def test_to_from_dict_round_trip(self) -> None:
        original = self._state()
        restored = SessionState.from_dict(original.to_dict())
        self.assertEqual(restored.session_id, "s-9")
        self.assertEqual(restored.system_prompt, "sys")
        self.assertEqual(len(restored.messages), 2)
        self.assertEqual(restored.messages[1].tool_calls, [{"name": "t", "arguments": {}}])
        self.assertEqual(restored.messages[1].tokens, 7)
        self.assertEqual(restored.total_tokens, 42)
        self.assertEqual(restored.compression_count, 2)
        self.assertEqual(restored.confidence_history, [0.5, 0.9])
        self.assertEqual(restored.api_call_count, 3)
        self.assertAlmostEqual(restored.estimated_cost_usd, 0.001)

    def test_from_dict_skips_malformed_messages(self) -> None:
        restored = SessionState.from_dict({"session_id": "s", "messages": [{"role": "user"}, "junk", 42]})
        self.assertEqual(len(restored.messages), 1)
        self.assertEqual(restored.messages[0].role, "user")

    def test_from_dict_rejects_non_dict(self) -> None:
        with self.assertRaises(TypeError):
            SessionState.from_dict("nope")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            Message.from_dict([])  # type: ignore[arg-type]

    def test_from_dict_applies_defaults(self) -> None:
        state = SessionState.from_dict({"session_id": "bare"})
        self.assertEqual(state.session_id, "bare")
        self.assertEqual(state.messages, [])
        self.assertEqual(state.system_prompt, "")
        self.assertEqual(state.model_name, "")
        self.assertEqual(state.max_tokens, 16384)
        self.assertEqual(state.prompt_tokens, 0)
        self.assertEqual(state.completion_tokens, 0)
        self.assertEqual(state.total_tokens, 0)
        self.assertEqual(state.compression_count, 0)
        self.assertEqual(state.started_at, 0.0)
        self.assertIsNone(state.ended_at)
        self.assertIsNone(state.end_reason)
        self.assertEqual(state.api_call_count, 0)
        self.assertEqual(state.estimated_cost_usd, 0.0)
        self.assertEqual(state.confidence_history, [])

    def test_save_load_via_store(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-sessions-") as tmp:
            store = TrustRuntimeStore(Path(tmp) / "state")
            original = self._state()
            receipt = original.save(store)
            self.assertEqual(receipt["session_id"], "s-9")
            restored = SessionState.load(store, "s-9")
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual(restored.to_dict()["messages"], original.to_dict()["messages"])
            self.assertIsNone(SessionState.load(store, "missing"))


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)

    def __aiter__(self):  # pragma: no cover - only used when iterated
        return self

    async def __anext__(self):  # pragma: no cover
        raise StopAsyncIteration


class GatewayDurableSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-gateway-")
        self.state_dir = Path(self._dir.name) / "state"
        self.server = GatewayServer(config=_config(self.state_dir))

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _fresh_server(self) -> GatewayServer:
        return GatewayServer(config=_config(self.state_dir))

    def test_create_session_persists_snapshot(self) -> None:
        self.server.create_session("gw-1")
        stored = TrustRuntimeStore(self.state_dir).get_session("gw-1")
        self.assertIsNotNone(stored)

    def test_rehydrate_on_restart_restores_history(self) -> None:
        session = self.server.create_session("gw-2")
        session.agent.session.messages.append(Message(role="user", content="remember me"))
        session.agent.session.total_tokens = 99
        self.server._persist_session(session)

        restarted = self._fresh_server()
        revived = restarted.get_session("gw-2")
        self.assertIsNotNone(revived)
        assert revived is not None
        texts = [m.content for m in revived.agent.session.messages]
        self.assertIn("remember me", texts)
        self.assertEqual(revived.agent.session.total_tokens, 99)
        self.assertFalse(revived.is_connected)

    def test_get_session_unknown_still_none(self) -> None:
        self.assertIsNone(self._fresh_server().get_session("ghost"))

    def test_list_sessions_marks_stored_as_resumable(self) -> None:
        self.server.create_session("gw-live")
        self.server.create_session("gw-stored")
        restarted = self._fresh_server()
        payload = restarted._handle_list_sessions({})
        by_id = {s["session_id"]: s for s in payload["sessions"]}
        self.assertIn("gw-stored", by_id)
        self.assertTrue(by_id["gw-stored"]["resumable"])
        self.assertFalse(by_id["gw-stored"]["is_connected"])
        # Live sessions are not duplicated by their stored snapshot.
        live_again = restarted.get_session("gw-live")
        self.assertIsNotNone(live_again)
        payload = restarted._handle_list_sessions({})
        ids = [s["session_id"] for s in payload["sessions"]]
        self.assertEqual(ids.count("gw-live"), 1)

    def test_resume_session_receipt(self) -> None:
        session = self.server.create_session("gw-3")
        session.agent.session.messages.append(Message(role="user", content="one"))
        session.touch()
        self.server._persist_session(session)

        restarted = self._fresh_server()
        receipt = restarted.resume_session("gw-3")
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["resume"]["session_id"], "gw-3")
        self.assertEqual(receipt["resume"]["reason"], "reconnect")
        self.assertGreaterEqual(receipt["resume"]["history_messages"], 1)

    def test_resume_unknown_session(self) -> None:
        receipt = self._fresh_server().resume_session("ghost")
        self.assertFalse(receipt["ok"])

    def test_turn_persists_session(self) -> None:
        session = self.server.create_session("gw-4")

        def fake_run(message: str) -> str:
            session.agent.session.messages.append(Message(role="user", content=message))
            session.agent.session.messages.append(Message(role="assistant", content="answer"))
            return "answer"

        session.agent.run = fake_run  # type: ignore[method-assign]
        asyncio.run(self.server._handle_user_message(session, "hello?", FakeWebSocket()))

        stored = TrustRuntimeStore(self.state_dir).get_session("gw-4")
        self.assertIsNotNone(stored)
        assert stored is not None
        contents = [m["content"] for m in stored["messages"]]
        self.assertIn("hello?", contents)
        self.assertIn("answer", contents)

    def test_turn_persists_even_on_agent_error(self) -> None:
        session = self.server.create_session("gw-5")
        session.agent.session.messages.append(Message(role="user", content="before boom"))

        def boom(message: str) -> str:
            raise RuntimeError("boom")

        session.agent.run = boom  # type: ignore[method-assign]
        ws = FakeWebSocket()
        asyncio.run(self.server._handle_user_message(session, "x", ws))

        stored = TrustRuntimeStore(self.state_dir).get_session("gw-5")
        assert stored is not None
        self.assertIn("before boom", [m["content"] for m in stored["messages"]])
        # The client still got an error frame.
        frames = [json.loads(raw) for raw in ws.sent]
        self.assertTrue(any(f["type"] == "error" for f in frames))


class MutationHardeningTests(unittest.TestCase):
    """Pin down defaults and fallback paths the mutation gate flagged."""

    def test_from_dict_falsy_max_tokens_falls_back_to_default(self) -> None:
        state = SessionState.from_dict({"session_id": "s", "max_tokens": 0})
        self.assertEqual(state.max_tokens, 16384)

    def test_from_dict_explicit_max_tokens_used(self) -> None:
        state = SessionState.from_dict({"session_id": "s", "max_tokens": 8192})
        self.assertEqual(state.max_tokens, 8192)

    def test_from_dict_default_max_tokens_exact(self) -> None:
        state = SessionState.from_dict({"session_id": "s"})
        self.assertEqual(state.max_tokens, 16384)

    def test_from_dict_falsy_started_at_falls_back(self) -> None:
        state = SessionState.from_dict({"session_id": "s", "started_at": 0.0})
        self.assertEqual(state.started_at, 0.0)
        state2 = SessionState.from_dict({"session_id": "s", "started_at": 123.5})
        self.assertEqual(state2.started_at, 123.5)

    def test_agent_init_max_tool_rounds_explicit(self) -> None:
        from ghostchimera.chimera_pilot.agent_loop import AIAgent
        from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

        agent = AIAgent(
            model_name="t",
            autonomy_profile=get_autonomy_profile("supervised"),
            max_tool_rounds=3,
        )
        self.assertEqual(agent.max_tool_rounds, 3)

    def test_agent_init_max_tool_rounds_defaults_to_profile(self) -> None:
        from ghostchimera.chimera_pilot.agent_loop import AIAgent
        from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

        profile = get_autonomy_profile("supervised")
        agent = AIAgent(model_name="t", autonomy_profile=profile)
        self.assertEqual(agent.max_tool_rounds, profile.max_tool_rounds)

    def test_agent_init_defaults(self) -> None:
        from ghostchimera.chimera_pilot.agent_loop import AIAgent
        from ghostchimera.chimera_pilot.autonomy import get_autonomy_profile

        agent = AIAgent(model_name="t", autonomy_profile=get_autonomy_profile("supervised"))
        self.assertEqual(agent.max_tokens, 16384)
        self.assertEqual(agent.current_confidence, 0.0)

    def test_gateway_init_bad_http_port_env_falls_back(self) -> None:
        import os
        from unittest.mock import patch

        from ghostchimera.chimera_pilot.gateway_server import HTTP_PORT

        with patch.dict(os.environ, {"GHOSTCHIMERA_HTTP_PORT": "notaport"}):
            server = GatewayServer()
        self.assertEqual(server.http_port, HTTP_PORT)

    def test_persist_session_error_is_logged_not_raised(self) -> None:
        from unittest.mock import patch

        from ghostchimera.chimera_pilot.gateway_server import GatewayServer

        with tempfile.TemporaryDirectory(prefix="ghost-mut-") as tmp:
            config = dataclasses.replace(GhostChimeraConfig.from_env(), state_dir=tmp)
            server = GatewayServer(config=config)
            session = server.create_session("gw-mut-1")
            with (
                patch.object(server._session_store, "save_session", side_effect=RuntimeError("disk gone")),
                self.assertLogs("ghostchimera.gateway_server", level="ERROR"),
            ):
                server._persist_session(session)
            # The session still works; persistence failure never breaks a turn.
            self.assertIsNotNone(server.get_session("gw-mut-1"))
