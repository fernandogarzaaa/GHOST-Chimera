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
                ("POST", "/api/console/live-presence/sessions/demo/transcript"),
                ("POST", "/api/console/live-presence/sessions/demo/report"),
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
        self.assertIn("/api/console/live-presence/status", js)
        self.assertIn("refreshLivePresence", js)


class LivePresenceCliTests(unittest.TestCase):
    def test_live_presence_cli_status_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-live-presence-cli-") as tmp:
            code = _main(["live-presence", "status", "--state-dir", tmp])

            self.assertEqual(code, 0)

