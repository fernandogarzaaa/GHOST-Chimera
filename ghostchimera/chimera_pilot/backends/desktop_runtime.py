"""Desktop control backend for Ghost Chimera."""

from __future__ import annotations

import os
import json
import datetime as dt
from pathlib import Path
from typing import Any

from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult


class DesktopRuntimeBackend:
    """Executes Desktop Control tasks.

    By default, this backend runs in dry-run mode and returns an action log.
    Real mouse/keyboard execution is only attempted when ``dry_run=False``.
    """

    id = "desktop.runtime"
    name = "Desktop Runtime Backend"

    def __init__(
        self,
        *,
        dry_run: bool = True,
        kill_switch_path: str | None = None,
        action_log_path: str | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.kill_switch_path = Path(kill_switch_path).expanduser() if kill_switch_path else None
        self.action_log_path = Path(action_log_path).expanduser() if action_log_path else None
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.DESKTOP_CONTROL},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            metadata={"dry_run": dry_run},
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=0.9, latency_ms=15, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        action = str(task.inputs.get("action", "")).strip().lower()
        target = str(task.inputs.get("target", "")).strip()
        text = str(task.inputs.get("text", ""))
        if action not in {"click", "double_click", "right_click", "type", "hotkey", "move"}:
            self._record_action(task, action, ok=False, error=f"Unsupported desktop action: {action}")
            return ExecutionResult(self.id, task.id, False, "", error=f"Unsupported desktop action: {action}")

        if self.dry_run:
            self._record_action(task, action, ok=True, mode="dry_run")
            return ExecutionResult(
                self.id,
                task.id,
                True,
                {
                    "mode": "dry_run",
                    "executed": False,
                    "action": action,
                    "target": target,
                    "text": text if action == "type" else "",
                },
                metrics={"desktop_action": action},
            )

        live_flag = str(task.constraints.get("live_desktop", "")).strip().lower()
        if live_flag not in {"1", "true", "yes"}:
            self._record_action(task, action, ok=False, error="missing live_desktop=true")
            return ExecutionResult(
                self.id,
                task.id,
                False,
                "",
                error="Live desktop control requires task.constraints.live_desktop=true",
            )
        if self._kill_switch_active(task):
            self._record_action(task, action, ok=False, error="kill switch active")
            return ExecutionResult(self.id, task.id, False, "", error="Desktop kill switch is active")

        try:
            import pyautogui  # type: ignore
        except Exception:
            self._record_action(task, action, ok=False, error="pyautogui missing")
            return ExecutionResult(self.id, task.id, False, "", error="pyautogui is required for live desktop control")

        try:
            self._execute_live(pyautogui, action=action, target=target, text=text, inputs=task.inputs)
        except Exception as exc:  # noqa: BLE001
            self._record_action(task, action, ok=False, error=f"Desktop action failed: {exc}")
            return ExecutionResult(self.id, task.id, False, "", error=f"Desktop action failed: {exc}")
        self._record_action(task, action, ok=True, mode="live")
        return ExecutionResult(self.id, task.id, True, {"mode": "live", "executed": True, "action": action, "target": target})

    def _execute_live(self, pg: Any, *, action: str, target: str, text: str, inputs: dict[str, Any]) -> None:
        x = inputs.get("x")
        y = inputs.get("y")
        if action in {"click", "double_click", "right_click", "move"} and x is not None and y is not None:
            pg.moveTo(int(x), int(y))
        if action == "click":
            pg.click()
        elif action == "double_click":
            pg.doubleClick()
        elif action == "right_click":
            pg.rightClick()
        elif action == "type":
            pg.write(text, interval=0.01)
        elif action == "hotkey":
            keys = inputs.get("keys", [])
            if not isinstance(keys, list) or not keys:
                raise ValueError("hotkey action requires non-empty keys list")
            pg.hotkey(*[str(k) for k in keys])

    def _kill_switch_active(self, task: TaskSpec) -> bool:
        task_switch = task.constraints.get("kill_switch")
        if isinstance(task_switch, str) and task_switch.strip():
            return Path(task_switch).expanduser().exists()
        if self.kill_switch_path is not None and self.kill_switch_path.exists():
            return True
        env_switch = os.environ.get("GHOSTCHIMERA_DESKTOP_KILL_SWITCH", "").strip()
        if env_switch:
            return Path(env_switch).expanduser().exists()
        return False

    def _record_action(self, task: TaskSpec, action: str, *, ok: bool, mode: str | None = None, error: str | None = None) -> None:
        path = self.action_log_path
        env_path = os.environ.get("GHOSTCHIMERA_DESKTOP_ACTION_LOG", "").strip()
        if path is None and env_path:
            path = Path(env_path).expanduser()
        if path is None:
            return
        payload = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "task_id": task.id,
            "objective": task.objective,
            "action": action,
            "ok": ok,
            "mode": mode or ("dry_run" if self.dry_run else "live"),
            "error": error,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")
