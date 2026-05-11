from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.backends.desktop_runtime import DesktopRuntimeBackend
from ghostchimera.chimera_pilot.desktop_policy import DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN
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

            def screenshot(self, path: str | None = None):
                self.calls.append(f"screenshot:{Path(path).name if path else 'memory'}")
                if path:
                    Path(path).write_bytes(b"fake-png")
                return None

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

    def test_live_mode_requires_semantic_resolution_without_coordinates(self) -> None:
        backend = DesktopRuntimeBackend(dry_run=False)
        task = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="click app=chrome window=Docs",
            inputs={"action": "click", "target": "app=chrome window=Docs"},
            constraints={"live_desktop": True},
        )
        result = backend.execute(task)
        self.assertFalse(result.ok)
        self.assertIn("Semantic target", result.error or "")

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
            self.assertEqual(row["action_class"], "mutating")
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

    def test_plan_dry_run_returns_step_outcomes(self) -> None:
        backend = DesktopRuntimeBackend(dry_run=True)
        task = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="plan",
            inputs={
                "action": "plan",
                "plan": [
                    {"action": "click", "target": "submit"},
                    {"action": "type", "text": "hello"},
                    {"action": "hotkey", "keys": ["ctrl", "s"]},
                ],
            },
        )
        result = backend.execute(task)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.metrics["desktop_step_outcomes"]), 3)
        self.assertIn("desktop_trace_id", result.metrics)

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

    def test_live_mode_captures_before_after_screenshots(self) -> None:
        fake, previous = self._install_fake_pyautogui()
        try:
            with tempfile.TemporaryDirectory(prefix="ghostchimera-desktop-artifacts-") as tmp:
                root = Path(tmp)
                log_path = root / "desktop-actions.jsonl"
                screenshot_dir = root / "screens"
                backend = DesktopRuntimeBackend(
                    dry_run=False,
                    action_log_path=str(log_path),
                    screenshot_dir=str(screenshot_dir),
                )
                task = TaskSpec.create(
                    kind=TaskKind.DESKTOP_CONTROL,
                    objective="click submit",
                    inputs={"action": "click"},
                    constraints={"live_desktop": True},
                )

                result = backend.execute(task)

                self.assertTrue(result.ok)
                screenshots = result.metrics["desktop_screenshots"]
                self.assertEqual(set(screenshots), {"before", "after"})
                self.assertTrue(Path(screenshots["before"]).exists())
                self.assertTrue(Path(screenshots["after"]).exists())
                self.assertEqual(result.metrics["desktop_action_log_path"], str(log_path))
                row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(row["screenshots"], screenshots)
                self.assertEqual(fake.calls[0].split(":", 1)[0], "screenshot")
                self.assertEqual(fake.calls[-1].split(":", 1)[0], "screenshot")
        finally:
            self._restore_pyautogui(previous)

    def test_destructive_live_mode_requires_confirmation_token(self) -> None:
        fake, previous = self._install_fake_pyautogui()
        try:
            backend = DesktopRuntimeBackend(dry_run=False)
            task = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective="live desktop: click delete project",
                inputs={"action": "click", "target": "delete project", "action_class": "destructive"},
                constraints={"live_desktop": True},
            )

            result = backend.execute(task)

            self.assertFalse(result.ok)
            self.assertIn("confirmation token", result.error or "")
            self.assertEqual(fake.calls, [])
        finally:
            self._restore_pyautogui(previous)

    def test_destructive_live_mode_runs_with_confirmation_token(self) -> None:
        fake, previous = self._install_fake_pyautogui()
        try:
            backend = DesktopRuntimeBackend(dry_run=False)
            task = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective="live desktop: click delete project",
                inputs={"action": "click", "target": "delete project", "action_class": "destructive"},
                constraints={
                    "live_desktop": True,
                    "confirmation_token": DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN,
                },
            )

            result = backend.execute(task)

            self.assertTrue(result.ok)
            self.assertEqual(result.metrics["desktop_action_class"], "destructive")
            self.assertEqual(fake.calls, ["click"])
        finally:
            self._restore_pyautogui(previous)


if __name__ == "__main__":
    unittest.main()
