from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.control_plane.conversation import (
    ConversationalLoopController,
    ConversationStore,
    classify_conversation_intent,
    summarize_run_result,
)
from ghostchimera.trust_runtime import TrustRuntimeStore


class ConversationRuntimeTests(unittest.TestCase):
    def test_sessions_persist_and_turns_redact_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-conversation-") as tmp:
            store = ConversationStore(tmp)
            session = store.create_session(title="Operator loop", mode="listening")

            updated = store.append_turn(
                session["session_id"],
                role="user",
                content="use token sk-testsecret123456 for the status check",
                intent="run",
            )
            reloaded = ConversationStore(tmp).get_session(session["session_id"])

            serialized = json.dumps(updated) + json.dumps(reloaded)
            self.assertIn("Operator loop", reloaded["title"])
            self.assertNotIn("sk-testsecret123456", serialized)
            self.assertIn("[redacted]", serialized)
            self.assertEqual(reloaded["turns"][0]["role"], "user")

    def test_intent_router_recognizes_voice_commands(self) -> None:
        self.assertEqual(classify_conversation_intent("Ghost stop")["intent"], "stop")
        self.assertEqual(classify_conversation_intent("ghost sleep")["intent"], "sleep")
        self.assertEqual(classify_conversation_intent("hey ghost wake up")["intent"], "wake")
        self.assertEqual(classify_conversation_intent("approve")["intent"], "approve")
        self.assertEqual(classify_conversation_intent("deny this")["intent"], "deny")
        self.assertEqual(classify_conversation_intent("run this in sandbox")["intent"], "sandbox")
        self.assertEqual(classify_conversation_intent("evolve yourself safely")["intent"], "self_evolution")

    def test_voice_approval_requires_bypass_for_high_impact_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-conversation-") as tmp:
            store = ConversationStore(tmp)
            trust = TrustRuntimeStore(Path(tmp) / "trust")
            calls: list[str] = []
            controller = ConversationalLoopController(
                state_dir=tmp,
                store=store,
                trust_store=trust,
                objective_runner=lambda objective: calls.append(objective) or {"ok": True, "ran": objective},
            )
            session = controller.create_session(always_listening=True)

            pending = controller.handle_turn(session["session_id"], "delete a local file", input_mode="voice")
            blocked = controller.handle_turn(session["session_id"], "approve", input_mode="voice")

            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["mode"], "waiting_for_approval")
            self.assertIn("Full Bypass", blocked["reply"])
            self.assertEqual(calls, [])

            enabled = controller.update_settings(full_bypass=True)
            approved = controller.handle_turn(session["session_id"], "approve", input_mode="voice")

            self.assertTrue(enabled["settings"]["full_bypass"])
            self.assertTrue(approved["ok"])
            self.assertEqual(approved["intent"], "approve")
            self.assertEqual(approved["mode"], "listening")
            self.assertEqual(calls, [pending["pending_approval"]["objective"]])

    def test_stop_command_sets_sleeping_mode_and_cancels_active_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-conversation-") as tmp:
            controller = ConversationalLoopController(state_dir=tmp)
            session = controller.create_session(always_listening=True)

            stopped = controller.handle_turn(session["session_id"], "Ghost stop", input_mode="voice")
            status = controller.status()

            self.assertTrue(stopped["ok"])
            self.assertEqual(stopped["mode"], "sleeping")
            self.assertEqual(status["active_session"]["mode"], "sleeping")
            self.assertFalse(status["settings"]["always_listening"])

    def test_conversation_turn_creates_trust_run_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-conversation-") as tmp:
            trust = TrustRuntimeStore(Path(tmp) / "trust")
            controller = ConversationalLoopController(
                state_dir=tmp,
                trust_store=trust,
                objective_runner=lambda objective: {"ok": True, "result": "done"},
            )
            session = controller.create_session(always_listening=True)
            result = controller.handle_turn(session["session_id"], "inspect runtime")

            runs = trust.list_runs()["runs"]
            self.assertTrue(result["ok"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["source"], "conversation")
            self.assertIn("trust_run", result)

    def test_successful_run_reply_is_operator_report_not_generic_placeholder(self) -> None:
        result = {
            "ok": True,
            "executions": [
                {"ok": True, "backend_id": "deterministic.local", "output": "workspace status inspected"}
            ],
            "trust_run": {"run": {"run_id": "run-123"}, "tool_calls": [], "approvals": []},
        }

        reply = summarize_run_result(result, ok=True, objective="inspect status")

        self.assertIn("1/1 task", reply)
        self.assertIn("deterministic.local", reply)
        self.assertIn("run-123", reply)
        self.assertNotIn("Done. I recorded the run in Trust Runtime and I am listening for the next step.", reply)

    def test_failed_execution_reply_includes_backend_error(self) -> None:
        result = {"ok": False, "executions": [{"ok": False, "backend_id": "codex_cli", "error": "provider failed"}]}

        reply = summarize_run_result(result, ok=False, objective="run status")

        self.assertIn("provider failed", reply)
        self.assertNotEqual(reply, "I could not complete that. Check Trust Runtime for details.")

    def test_show_evidence_returns_recent_trust_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-conversation-evidence-") as tmp:
            trust = TrustRuntimeStore(tmp)
            trust.create_run(
                agent_name="ghost_conversation",
                objective="inspect live status",
                source="conversation",
            )
            controller = ConversationalLoopController(state_dir=tmp, trust_store=trust)
            session = controller.create_session(session_id="demo", always_listening=False)

            result = controller.handle_turn(session["session_id"], "show evidence")

            self.assertTrue(result["ok"])
            self.assertIn("Recent Trust Runtime evidence", result["reply"])
            self.assertIn("inspect live status", result["reply"])
            self.assertNotIn("Evidence is available in the Trust Runtime", result["reply"])

    def test_readiness_intent_returns_status_provider_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-conversation-readiness-") as tmp:
            controller = ConversationalLoopController(
                state_dir=tmp,
                status_provider=lambda: {
                    "active_path": {"profile_id": "autonomous-engineer"},
                    "model": {"provider": "codex_cli", "model": "gpt-5.4-mini", "auth_configured": True},
                    "production_readiness": {"status": "ready", "ready": True},
                    "counts": {"approved_sources": 5, "learning_sources": 5, "pending_candidates": 1},
                    "warnings": [],
                },
            )
            session = controller.create_session(session_id="demo", always_listening=False)

            result = controller.handle_turn(session["session_id"], "run readiness check")

            self.assertTrue(result["ok"])
            self.assertEqual(result["intent"], "readiness")
            self.assertIn("Readiness check", result["reply"])
            self.assertIn("codex_cli / gpt-5.4-mini", result["reply"])
            self.assertIn("Pending evolution candidates: 1", result["reply"])


class ConversationConsoleRouteTests(unittest.TestCase):
    def test_console_registers_conversation_routes_and_redacts_turns(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-conversation-") as tmp:
            server = GatewayServer()
            register_console_routes(
                server,
                state_dir=tmp,
                run_objective=lambda objective: {"ok": True, "echo": objective},
            )

            for method, path in [
                ("POST", "/api/console/conversation/sessions"),
                ("GET", "/api/console/conversation/sessions"),
                ("GET", "/api/console/conversation/status"),
                ("POST", "/api/console/conversation/settings"),
                ("GET", "/api/console/conversation/local-voice/status"),
                ("POST", "/api/console/conversation/local-voice/transcribe"),
            ]:
                with self.subTest(path=path):
                    self.assertIsNotNone(server.routes.find(method, path))

            create_route = server.routes.find("POST", "/api/console/conversation/sessions")
            turn_route = server.routes.find("POST", "/api/console/conversation/sessions/demo/turn")
            status_route = server.routes.find("GET", "/api/console/conversation/status")
            self.assertIsNotNone(create_route)
            self.assertIsNotNone(turn_route)

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/conversation/sessions",
                    "headers": {},
                    "body": json.dumps({"session_id": "demo", "always_listening": True}),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])

            result = turn_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/conversation/sessions/demo/turn",
                    "headers": {},
                    "body": json.dumps({"message": "status with sk-testsecret123456"}),
                    "query": {},
                }
            )
            status = status_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/conversation/status",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )

            serialized = json.dumps(result) + json.dumps(status)
            self.assertTrue(result["ok"])
            self.assertIn("operator_report", result)
            self.assertNotIn("sk-testsecret123456", serialized)
            self.assertIn("[redacted]", serialized)
            self.assertEqual(status["active_session"]["session_id"], "demo")


class ConversationCliTests(unittest.TestCase):
    def test_conversation_cli_start_send_status_and_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-cli-conversation-") as tmp:
            self.assertEqual(_main(["conversation", "start", "--state-dir", tmp]), 0)
            self.assertEqual(_main(["conversation", "send", "inspect status", "--state-dir", tmp]), 0)
            self.assertEqual(_main(["conversation", "status", "--state-dir", tmp]), 0)
            self.assertEqual(_main(["conversation", "stop", "--state-dir", tmp]), 0)

            session_file = Path(tmp) / "conversation_sessions.json"
            data = json.loads(session_file.read_text(encoding="utf-8"))
            active = data["sessions"][data["active_session_id"]]
            self.assertEqual(active["mode"], "sleeping")
            self.assertTrue(active["stopped"])


class ConversationUiStaticTests(unittest.TestCase):
    def test_home_ui_exposes_conversation_voice_bypass_and_stop_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
        js = (root / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")

        for marker in [
            "ghostConversationPanel",
            "conversationMicState",
            "conversationTranscript",
            "conversationReply",
            "conversationBypassBanner",
            "conversationStopAll",
            "conversationAlwaysListening",
            "conversationFullBypass",
            "conversationLocalFallback",
            "conversationVoiceSelect",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        for marker in [
            "/api/console/conversation/sessions",
            "/api/console/conversation/status",
            "/api/console/conversation/settings",
            "SpeechRecognition",
            "MediaRecorder",
            "local-voice-turn",
            "/api/console/conversation/local-voice/status",
            "speechSynthesis",
            "speechErrorGuidance",
            "voiceRestartBlocked",
            "Voice Network Unavailable",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, js)


if __name__ == "__main__":
    unittest.main()
