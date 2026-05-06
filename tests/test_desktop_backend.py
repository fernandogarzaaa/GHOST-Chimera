from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
import json

from ghostchimera.chimera_pilot.backends.desktop_runtime import DesktopRuntimeBackend
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


class DesktopRuntimeBackendTests(unittest.TestCase):
    def test_dry_run_returns_action_log(self) -> None:
        backend = DesktopRuntimeBackend(dry_run=True)
        task = TaskSpec.create(kind=TaskKind.DESKTOP_CONTROL, objective="click submit", inputs={"action": "click"})
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(result.output.get("mode"), "dry_run")

    def test_live_mode_requires_explicit_constraint(self) -> None:
        backend = DesktopRuntimeBackend(dry_run=False)
        task = TaskSpec.create(kind=TaskKind.DESKTOP_CONTROL, objective="click submit", inputs={"action": "click"})
        result = backend.execute(task)
        self.assertFalse(result.ok)
        self.assertIn("live_desktop", result.error or "")

    def test_live_mode_respects_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-kill-switch-") as tmp:
            switch = Path(tmp) / "STOP"
            switch.write_text("1", encoding="utf-8")
            backend = DesktopRuntimeBackend(dry_run=False, kill_switch_path=str(switch))
            task = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective="click submit",
                inputs={"action": "click"},
                constraints={"live_desktop": True},
            )
            result = backend.execute(task)
            self.assertFalse(result.ok)
            self.assertIn("kill switch", (result.error or "").lower())

    def test_backend_writes_action_log_when_configured(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-action-log-") as tmp:
            log_path = Path(tmp) / "desktop-actions.jsonl"
            backend = DesktopRuntimeBackend(dry_run=True, action_log_path=str(log_path))
            task = TaskSpec.create(kind=TaskKind.DESKTOP_CONTROL, objective="click submit", inputs={"action": "click"})
            result = backend.execute(task)
            self.assertTrue(result.ok)
            self.assertTrue(log_path.exists())
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["action"], "click")
            self.assertEqual(row["mode"], "dry_run")


if __name__ == "__main__":
    unittest.main()
