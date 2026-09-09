from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.control_plane.live_presence import LivePresenceStore
from ghostchimera.trust_runtime import TrustRuntimeStore


class LivePresenceStoreTests(unittest.TestCase):
    def test_external_meeting_requires_disclosure_before_start(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            trust = TrustRuntimeStore(Path(tmp) / "trust")
            store = LivePresenceStore(tmp, trust_store=trust)
            created = store.create_session(
                title="Customer discovery call",
                session_type="meeting",
                participants=[{"name": "Pat", "role": "customer", "external": True}],
            )

            blocked = store.start_session(created["session_id"])
            approved = store.approve_disclosure(created["session_id"], approved_by="admin")
            started = store.start_session(created["session_id"])

            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["required_action"], "approve_disclosure")
            self.assertEqual(approved["session"]["disclosure_status"], "approved")
            self.assertTrue(started["ok"])
            self.assertEqual(started["session"]["mode"], "active")
            self.assertEqual(len(trust.list_runs()["runs"]), 1)
            self.assertEqual(trust.list_runs()["runs"][0]["source"], "live_presence")

    def test_transcript_report_extracts_action_items_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            created = store.create_session(title="Interview", session_type="interview")
            sid = created["session_id"]

            store.record_transcript(sid, speaker="Candidate", content="My token is sk-secret123456789")
            store.record_transcript(sid, speaker="Ghost", content="Action item: send architecture notes tomorrow.")
            report = store.generate_report(sid)
            serialized = json.dumps(report)

            self.assertTrue(report["ok"])
            self.assertIn("send architecture notes tomorrow", report["report"]["action_items"][0]["text"])
            self.assertNotIn("sk-secret123456789", serialized)
            self.assertIn("[redacted]", serialized)

    def test_status_summarizes_pending_disclosures_and_active_sessions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            pending = store.create_session(
                title="Sales call",
                session_type="meeting",
                participants=[{"name": "Client", "external": True}],
            )
            internal = store.create_session(title="Solo planning", session_type="companion")
            store.start_session(internal["session_id"])

            status = store.status()

            self.assertEqual(status["counts"]["sessions"], 2)
            self.assertEqual(status["counts"]["active_sessions"], 1)
            self.assertEqual(status["counts"]["pending_disclosures"], 1)
            self.assertEqual(status["recommended_next_action"]["session_id"], pending["session_id"])

    def test_meeting_bridge_tracks_browser_session_diarization_and_interrupts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            created = store.create_session(title="Product review", session_type="meeting")
            sid = created["session_id"]

            bridge = store.configure_meeting_bridge(
                sid,
                app="google_meet",
                meeting_url="https://meet.google.com/abc-defg-hij",
                browser_session="brave-default",
            )
            store.start_session(sid)
            turn = store.record_transcript(
                sid,
                speaker="Unknown speaker 1",
                content="We should ship the trust runtime update.",
                source="live_audio",
                diarization={"speaker_id": "spk_1", "confidence": 0.82},
            )
            interrupted = store.interrupt_session(sid, reason="User asked Ghost to pause.")

            self.assertTrue(bridge["ok"])
            self.assertEqual(bridge["session"]["meeting_bridge"]["app"], "google_meet")
            self.assertEqual(bridge["session"]["meeting_bridge"]["status"], "ready")
            self.assertEqual(turn["turn"]["diarization"]["speaker_id"], "spk_1")
            self.assertEqual(interrupted["session"]["mode"], "paused")
            self.assertEqual(interrupted["session"]["interruptions"][0]["reason"], "User asked Ghost to pause.")

    def test_delegated_communication_requires_approved_recipient_before_send(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            created = store.create_session(title="Follow-up", session_type="meeting")
            sid = created["session_id"]
            draft = store.create_communication_draft(
                sid,
                channel="email",
                recipient="customer@example.com",
                body="Here are the notes from our meeting.",
                disclosure_template="AI-assisted follow-up from Ghost Chimera.",
            )

            blocked = store.send_communication(sid, draft["draft"]["draft_id"])
            approved = store.approve_recipient(sid, channel="email", recipient="customer@example.com", approved_by="admin")
            sent = store.send_communication(sid, draft["draft"]["draft_id"])

            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["required_action"], "approve_recipient")
            self.assertTrue(approved["ok"])
            self.assertTrue(sent["ok"])
            self.assertEqual(sent["draft"]["status"], "sent")
            self.assertTrue(sent["draft"]["approval_required"])
            self.assertNotIn("pretend", json.dumps(sent).lower())

    def test_interview_operator_generates_questions_and_scores_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            created = store.create_session(title="Engineer interview", session_type="interview")
            sid = created["session_id"]

            bank = store.configure_interview(
                sid,
                mode="interviewer",
                role="Senior Python Engineer",
                competencies=["architecture", "testing"],
            )
            store.record_transcript(sid, speaker="Candidate", content="I designed service boundaries and wrote pytest coverage.")
            scoring = store.score_interview(sid)

            self.assertTrue(bank["ok"])
            self.assertEqual(bank["session"]["interview"]["mode"], "interviewer")
            self.assertGreaterEqual(len(bank["session"]["interview"]["question_bank"]), 2)
            self.assertTrue(scoring["ok"])
            self.assertGreater(scoring["scorecard"]["overall_score"], 0)
            self.assertIn("testing", scoring["scorecard"]["competencies"])
            self.assertTrue(scoring["scorecard"]["evidence"])

    def test_shared_context_adds_agenda_memory_and_user_corrections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            created = store.create_session(title="Roadmap review", session_type="meeting")
            sid = created["session_id"]

            context = store.update_shared_context(
                sid,
                agenda=["review latency", "assign follow-ups"],
                minimind_hints=["User prefers production code only."],
                rag_snippets=[{"source": "README", "text": "Trust Runtime records live runs."}],
                user_correction="Do not say the follow-up was sent until a channel confirms it.",
            )
            report = store.generate_report(sid)

            self.assertTrue(context["ok"])
            self.assertIn("review latency", context["session"]["shared_context"]["agenda"])
            self.assertIn("User prefers production code only.", context["session"]["shared_context"]["minimind_hints"])
            self.assertIn("Do not say", context["session"]["shared_context"]["user_corrections"][0]["text"])
            self.assertIn("Shared context", report["report"]["summary"])

    def test_presence_eval_harness_scores_safety_latency_and_replayability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-") as tmp:
            store = LivePresenceStore(tmp)
            external = store.create_session(
                title="Candidate call",
                session_type="interview",
                participants=[{"name": "Candidate", "external": True}],
            )
            internal = store.create_session(title="Solo sync", session_type="companion")
            store.start_session(internal["session_id"])
            store.record_transcript(internal["session_id"], speaker="Ghost", content="Action item: create summary.")
            eval_payload = store.run_presence_eval_suite()

            self.assertTrue(eval_payload["ok"])
            self.assertEqual(eval_payload["suite"], "presence")
            self.assertGreaterEqual(eval_payload["score"], 0.8)
            self.assertIn("external_disclosure_gate", eval_payload["checks"])
            self.assertFalse(eval_payload["checks"]["external_disclosure_gate"]["passed"] is False and not external)
            self.assertTrue(eval_payload["checks"]["trust_replayability"]["passed"])
            self.assertEqual(store.status()["presence_eval_score"], eval_payload["score"])


class LivePresenceConsoleTests(unittest.TestCase):
    def test_console_registers_live_presence_routes_and_blocks_start_until_disclosure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-console-live-presence-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            for method, path in [
                ("GET", "/api/console/live-presence/status"),
                ("GET", "/api/console/live-presence/sessions"),
                ("POST", "/api/console/live-presence/sessions"),
                ("POST", "/api/console/live-presence/sessions/demo/start"),
                ("POST", "/api/console/live-presence/sessions/demo/disclosure/approve"),
                ("POST", "/api/console/live-presence/sessions/demo/bridge"),
                ("POST", "/api/console/live-presence/sessions/demo/interrupt"),
                ("POST", "/api/console/live-presence/sessions/demo/transcript"),
                ("POST", "/api/console/live-presence/sessions/demo/report"),
                ("POST", "/api/console/live-presence/sessions/demo/communication/draft"),
                ("POST", "/api/console/live-presence/sessions/demo/communication/draft-1/send"),
                ("POST", "/api/console/live-presence/sessions/demo/context"),
                ("POST", "/api/console/live-presence/sessions/demo/interview/configure"),
                ("POST", "/api/console/live-presence/sessions/demo/interview/score"),
                ("POST", "/api/console/live-presence/evals/run"),
            ]:
                with self.subTest(path=path):
                    self.assertIsNotNone(server.routes.find(method, path))

            create = server.routes.find("POST", "/api/console/live-presence/sessions")
            start = server.routes.find("POST", "/api/console/live-presence/sessions/demo/start")
            approve = server.routes.find("POST", "/api/console/live-presence/sessions/demo/disclosure/approve")
            self.assertIsNotNone(create)
            self.assertIsNotNone(start)
            self.assertIsNotNone(approve)

            created = create.handler(
                {
                    "method": "POST",
                    "path": "/api/console/live-presence/sessions",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "session_id": "demo",
                            "title": "Hiring interview",
                            "session_type": "interview",
                            "participants": [{"name": "Candidate", "external": True}],
                        }
                    ),
                    "query": {},
                }
            )
            blocked = start.handler(
                {
                    "method": "POST",
                    "path": "/api/console/live-presence/sessions/demo/start",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            approved = approve.handler(
                {
                    "method": "POST",
                    "path": "/api/console/live-presence/sessions/demo/disclosure/approve",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )

            self.assertTrue(created["ok"])
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["required_action"], "approve_disclosure")
            self.assertTrue(approved["ok"])

    def test_console_static_includes_live_presence_surface(self) -> None:
        html = Path("ghostchimera/control_plane/static/index.html").read_text(encoding="utf-8")
        js = Path("ghostchimera/control_plane/static/app.js").read_text(encoding="utf-8")

        self.assertIn('data-tab="live-presence"', html)
        self.assertIn("livePresenceSessions", html)
        self.assertIn("livePresenceMeetingUrl", html)
        self.assertIn("livePresenceCommunicationBody", html)
        self.assertIn("livePresenceInterviewRole", html)
        self.assertIn("/api/console/live-presence/status", js)
        self.assertIn("refreshLivePresence", js)
        self.assertIn("runLivePresenceEval", js)


class LivePresenceCliTests(unittest.TestCase):
    def test_live_presence_cli_status_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-cli-") as tmp:
            code = _main(["live-presence", "status", "--state-dir", tmp])

            self.assertEqual(code, 0)
