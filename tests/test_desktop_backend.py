from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.backends.desktop_runtime import DesktopRuntimeBackend
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec


class DesktopRuntimeBackendTests(unittest.TestCase):
    def _install_fake_pyautogui(self) -> tuple[object, object | None]:
        class FakePyAutoGui:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def moveTo(self, x: int, y: int) -> None:  # noqa: N802
                self.calls.append(f"moveTo:{x},{y}")

            def click(self) -> None:
                self.calls.append("click")

            def doubleClick(self) -> None:  # noqa: N802
                self.calls.append("doubleClick")

            def rightClick(self) -> None:  # noqa: N802
                self.calls.append("rightClick")

            def write(self, text: str, interval: float = 0.0) -> None:
                self.calls.append(f"write:{text}:{interval}")

            def hotkey(self, *keys: str) -> None:
                self.calls.append("hotkey:" + "+".join(keys))

        previous = sys.modules.get("pyautogui")
        fake = FakePyAutoGui()
        sys.modules["pyautogui"] = fake
        return fake, previous

    def _restore_pyautogui(self, previous: object | None) -> None:
        if previous is None:
            sys.modules.pop("pyautogui", None)
        else:
            sys.modules["pyautogui"] = previous

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

    def test_live_mode_enforces_action_budget(self) -> None:
        fake, previous = self._install_fake_pyautogui()
        try:
            backend = DesktopRuntimeBackend(dry_run=False, max_live_actions=1)
            task = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective="click submit",
                inputs={"action": "click"},
                constraints={"live_desktop": True},
            )

            first = backend.execute(task)
            second = backend.execute(task)

            self.assertTrue(first.ok)
            self.assertFalse(second.ok)
            self.assertIn("action budget", second.error or "")
            self.assertEqual(fake.calls, ["click"])
        finally:
            self._restore_pyautogui(previous)

    def test_live_mode_enforces_session_duration(self) -> None:
        now = [100.0]

        def clock() -> float:
            return now[0]

        fake, previous = self._install_fake_pyautogui()
        try:
            backend = DesktopRuntimeBackend(dry_run=False, max_session_seconds=5.0, clock=clock)
            task = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective="click submit",
                inputs={"action": "click"},
                constraints={"live_desktop": True},
            )

            first = backend.execute(task)
            now[0] = 105.0
            second = backend.execute(task)

            self.assertTrue(first.ok)
            self.assertFalse(second.ok)
            self.assertIn("timed out", second.error or "")
            self.assertEqual(fake.calls, ["click"])
        finally:
            self._restore_pyautogui(previous)


if __name__ == "__main__":
    unittest.main()
