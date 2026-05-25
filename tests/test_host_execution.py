from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.control_plane.host_execution import HostExecutionStore


class HostExecutionStoreTests(unittest.TestCase):
    def test_host_run_is_blocked_until_unrestricted_mode_is_explicitly_armed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-host-exec-") as tmp:
            store = HostExecutionStore(tmp)

            blocked = store.run_command(["python", "--version"], purpose="smoke")
            armed = store.update_settings(
                {
                    "unrestricted_host_mode": True,
                    "confirmation_phrase": "I ACCEPT HOST EXECUTION RISK",
                    "allowed_root": tmp,
                    "audit_dir": str(Path(tmp) / "audit"),
                }
            )
            executed = store.run_command(["python", "--version"], purpose="smoke")

            self.assertFalse(blocked["ok"])
            self.assertIn("not armed", blocked["error"])
            self.assertTrue(armed["settings"]["unrestricted_host_mode"])
            self.assertTrue(executed["ok"])
            self.assertIn("Python", executed["stdout"])
            self.assertNotIn("I ACCEPT HOST EXECUTION RISK", json.dumps(executed))

    def test_self_edit_applies_unified_diff_and_writes_revert_patch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-self-edit-") as tmp:
            root = Path(tmp)
            target = root / "demo.txt"
            target.write_text("alpha\n", encoding="utf-8")
            patch = "\n".join(
                [
                    "--- a/demo.txt",
                    "+++ b/demo.txt",
                    "@@ -1 +1,2 @@",
                    " alpha",
                    "+beta",
                    "",
                ]
            )
            store = HostExecutionStore(tmp)
            store.update_settings(
                {
                    "unrestricted_host_mode": True,
                    "confirmation_phrase": "I ACCEPT HOST EXECUTION RISK",
                    "allowed_root": tmp,
                    "audit_dir": str(root / "audit"),
                }
            )

            result = store.apply_self_edit(patch, objective="add beta line")

            self.assertTrue(result["ok"])
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nbeta\n")
            self.assertTrue(Path(result["audit"]["revert_patch"]).exists())
            self.assertTrue(Path(result["audit"]["applied_patch"]).exists())
            self.assertNotIn("I ACCEPT HOST EXECUTION RISK", json.dumps(result))

    def test_self_edit_rejects_paths_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-self-edit-") as tmp:
            store = HostExecutionStore(tmp)
            store.update_settings(
                {
                    "unrestricted_host_mode": True,
                    "confirmation_phrase": "I ACCEPT HOST EXECUTION RISK",
                    "allowed_root": tmp,
                }
            )

            result = store.apply_self_edit(
                "--- a/../outside.txt\n+++ b/../outside.txt\n@@ -0,0 +1 @@\n+bad\n",
                objective="escape root",
            )

            self.assertFalse(result["ok"])
            self.assertIn("outside allowed root", result["error"])


class HostExecutionConsoleRouteTests(unittest.TestCase):
    def test_console_routes_arm_host_mode_and_apply_self_edit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-host-console-") as tmp:
            root = Path(tmp)
            (root / "demo.txt").write_text("one\n", encoding="utf-8")
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            settings_route = server.routes.find("POST", "/api/console/host-execution/settings")
            edit_route = server.routes.find("POST", "/api/console/host-execution/self-edit")
            self.assertIsNotNone(settings_route)
            self.assertIsNotNone(edit_route)

            settings = settings_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/host-execution/settings",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "unrestricted_host_mode": True,
                            "confirmation_phrase": "I ACCEPT HOST EXECUTION RISK",
                            "allowed_root": tmp,
                        }
                    ),
                    "query": {},
                }
            )
            result = edit_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/host-execution/self-edit",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "objective": "append two",
                            "patch": "--- a/demo.txt\n+++ b/demo.txt\n@@ -1 +1,2 @@\n one\n+two\n",
                        }
                    ),
                    "query": {},
                }
            )

            self.assertTrue(settings["ok"])
            self.assertTrue(result["ok"])
            self.assertEqual((root / "demo.txt").read_text(encoding="utf-8"), "one\ntwo\n")


class HostExecutionUiStaticTests(unittest.TestCase):
    def test_console_exposes_host_execution_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
        js = (root / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")

        for marker in [
            "hostUnrestrictedMode",
            "hostAllowedRoot",
            "hostAuditDir",
            "hostConfirmationPhrase",
            "hostExecutionOutput",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        for marker in [
            "/api/console/host-execution/settings",
            "refreshHostExecution",
            "hostConfirmationPhrase",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, js)


if __name__ == "__main__":
    unittest.main()
