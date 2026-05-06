"""Desktop control backend for Ghost Chimera."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..desktop_policy import (
    DesktopActionClass,
    destructive_desktop_confirmation_error,
    infer_desktop_action_class,
)
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult


class DesktopRuntimeBackend:
    """Executes Desktop Control tasks.

    By default, this backend runs in dry-run mode and returns an action log.
    Real mouse/keyboard execution is only attempted when ``dry_run=False``.
    """

    id = "desktop.runtime"
    name = "Desktop Runtime Backend"
    DEFAULT_MAX_LIVE_ACTIONS = 25
    DEFAULT_MAX_SESSION_SECONDS = 300.0

    def __init__(
        self,
        *,
        dry_run: bool = True,
        kill_switch_path: str | None = None,
        action_log_path: str | None = None,
        screenshot_dir: str | None = None,
        max_live_actions: int | None = DEFAULT_MAX_LIVE_ACTIONS,
        max_session_seconds: float | None = DEFAULT_MAX_SESSION_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_live_actions is not None and max_live_actions < 1:
            raise ValueError("max_live_actions must be at least 1")
        if max_session_seconds is not None and max_session_seconds <= 0:
            raise ValueError("max_session_seconds must be greater than 0")
        self.dry_run = dry_run
        self.kill_switch_path = Path(kill_switch_path).expanduser() if kill_switch_path else None
        self.action_log_path = Path(action_log_path).expanduser() if action_log_path else None
        self.screenshot_dir = Path(screenshot_dir).expanduser() if screenshot_dir else None
        self.max_live_actions = max_live_actions
        self.max_session_seconds = max_session_seconds
        self._clock = clock or time.monotonic
        self._session_started_at = self._clock()
        self._live_actions_executed = 0
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.DESKTOP_CONTROL},
            supports_offline=True,
            supports_streaming=False,
            supports_gpu=False,
            supports_network=False,
            metadata={
                "dry_run": dry_run,
                "max_live_actions": max_live_actions,
                "max_session_seconds": max_session_seconds,
                "screenshot_dir": str(self.screenshot_dir) if self.screenshot_dir else None,
            },
        )

    def probe(self) -> BackendHealth:
        return BackendHealth(available=True, reliability=0.9, latency_ms=15, estimated_cost_usd=0.0)

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        return self.probe()

    def execute(self, task: TaskSpec) -> ExecutionResult:
        action = str(task.inputs.get("action", "")).strip().lower()
        action_class = infer_desktop_action_class(action=action, inputs=task.inputs, objective=task.objective)
        target = str(task.inputs.get("target", "")).strip()
        text = str(task.inputs.get("text", ""))
        if action not in {"click", "double_click", "right_click", "type", "hotkey", "move"}:
            self._record_action(
                task,
                action,
                action_class=action_class,
                ok=False,
                error=f"Unsupported desktop action: {action}",
            )
            return ExecutionResult(self.id, task.id, False, "", error=f"Unsupported desktop action: {action}")

        if self.dry_run:
            self._record_action(task, action, action_class=action_class, ok=True, mode="dry_run")
            return ExecutionResult(
                self.id,
                task.id,
                True,
                {
                    "mode": "dry_run",
                    "executed": False,
                    "action": action,
                    "action_class": action_class,
                    "target": target,
                    "text": text if action == "type" else "",
                },
                metrics=self._desktop_metrics(action, action_class),
            )

        live_flag = str(task.constraints.get("live_desktop", "")).strip().lower()
        if live_flag not in {"1", "true", "yes"}:
            self._record_action(task, action, action_class=action_class, ok=False, error="missing live_desktop=true")
            return ExecutionResult(
                self.id,
                task.id,
                False,
                "",
                error="Live desktop control requires task.constraints.live_desktop=true",
            )
        if self._kill_switch_active(task):
            self._record_action(task, action, action_class=action_class, ok=False, error="kill switch active")
            return ExecutionResult(self.id, task.id, False, "", error="Desktop kill switch is active")
        limit_error = self._live_limit_error()
        if limit_error:
            self._record_action(task, action, action_class=action_class, ok=False, error=limit_error)
            return ExecutionResult(self.id, task.id, False, "", error=limit_error)
        if action_class == DesktopActionClass.DESTRUCTIVE.value:
            confirmation_error = destructive_desktop_confirmation_error(task.constraints.get("confirmation_token"))
            if confirmation_error:
                self._record_action(task, action, action_class=action_class, ok=False, error=confirmation_error)
                return ExecutionResult(self.id, task.id, False, "", error=confirmation_error)

        try:
            import pyautogui  # type: ignore
        except Exception:
            self._record_action(task, action, action_class=action_class, ok=False, error="pyautogui missing")
            return ExecutionResult(self.id, task.id, False, "", error="pyautogui is required for live desktop control")

        screenshots: dict[str, str] = {}
        screenshot_errors: list[str] = []
        try:
            self._live_actions_executed += 1
            self.capabilities.metadata["live_actions_executed"] = self._live_actions_executed
            self._capture_screenshot(pyautogui, task, "before", screenshots, screenshot_errors)
            self._execute_live(pyautogui, action=action, target=target, text=text, inputs=task.inputs)
        except Exception as exc:  # noqa: BLE001
            self._capture_screenshot(pyautogui, task, "after", screenshots, screenshot_errors)
            self._record_action(
                task,
                action,
                action_class=action_class,
                ok=False,
                error=f"Desktop action failed: {exc}",
                screenshots=screenshots,
                screenshot_errors=screenshot_errors,
            )
            return ExecutionResult(
                self.id,
                task.id,
                False,
                "",
                error=f"Desktop action failed: {exc}",
                metrics=self._desktop_metrics(
                    action,
                    action_class,
                    screenshots=screenshots,
                    screenshot_errors=screenshot_errors,
                ),
            )
        self._capture_screenshot(pyautogui, task, "after", screenshots, screenshot_errors)
        self._record_action(
            task,
            action,
            action_class=action_class,
            ok=True,
            mode="live",
            screenshots=screenshots,
            screenshot_errors=screenshot_errors,
        )
        return ExecutionResult(
            self.id,
            task.id,
            True,
            {"mode": "live", "executed": True, "action": action, "action_class": action_class, "target": target},
            metrics=self._desktop_metrics(
                action,
                action_class,
                screenshots=screenshots,
                screenshot_errors=screenshot_errors,
            ),
        )

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

    def _live_limit_error(self) -> str | None:
        if self.max_live_actions is not None and self._live_actions_executed >= self.max_live_actions:
            return f"Desktop live action budget exhausted ({self.max_live_actions} actions)"
        if self.max_session_seconds is not None:
            elapsed = self._clock() - self._session_started_at
            if elapsed >= self.max_session_seconds:
                return f"Desktop live session timed out after {self.max_session_seconds:g} seconds"
        return None

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

    def _resolve_action_log_path(self) -> Path | None:
        path = self.action_log_path
        env_path = os.environ.get("GHOSTCHIMERA_DESKTOP_ACTION_LOG", "").strip()
        if path is None and env_path:
            path = Path(env_path).expanduser()
        return path

    def _resolve_screenshot_dir(self) -> Path | None:
        path = self.screenshot_dir
        env_path = os.environ.get("GHOSTCHIMERA_DESKTOP_SCREENSHOT_DIR", "").strip()
        if path is None and env_path:
            path = Path(env_path).expanduser()
        return path

    def _safe_screenshot_name(self, task: TaskSpec, phase: str) -> str:
        timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe_task_id = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in task.id)
        return f"{timestamp}_{safe_task_id}_{phase}.png"

    def _capture_screenshot(
        self,
        pyautogui: Any,
        task: TaskSpec,
        phase: str,
        screenshots: dict[str, str],
        screenshot_errors: list[str],
    ) -> None:
        directory = self._resolve_screenshot_dir()
        if directory is None:
            return
        path = directory / self._safe_screenshot_name(task, phase)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            try:
                pyautogui.screenshot(str(path))
            except TypeError as exc:
                image = pyautogui.screenshot()
                if not hasattr(image, "save"):
                    raise RuntimeError("pyautogui screenshot result cannot be saved") from exc
                image.save(str(path))
        except Exception as exc:  # noqa: BLE001
            screenshot_errors.append(f"{phase}: {exc}")
            return
        screenshots[phase] = str(path)

    def _desktop_metrics(
        self,
        action: str,
        action_class: str,
        *,
        screenshots: dict[str, str] | None = None,
        screenshot_errors: list[str] | None = None,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {"desktop_action": action, "desktop_action_class": action_class}
        action_log_path = self._resolve_action_log_path()
        if action_log_path is not None:
            metrics["desktop_action_log_path"] = str(action_log_path)
        if screenshots:
            metrics["desktop_screenshots"] = dict(screenshots)
        if screenshot_errors:
            metrics["desktop_screenshot_errors"] = list(screenshot_errors)
        return metrics

    def _record_action(
        self,
        task: TaskSpec,
        action: str,
        *,
        action_class: str,
        ok: bool,
        mode: str | None = None,
        error: str | None = None,
        screenshots: dict[str, str] | None = None,
        screenshot_errors: list[str] | None = None,
    ) -> None:
        path = self._resolve_action_log_path()
        if path is None:
            return
        payload = {
            "ts": dt.datetime.now(dt.UTC).isoformat(),
            "task_id": task.id,
            "objective": task.objective,
            "action": action,
            "action_class": action_class,
            "ok": ok,
            "mode": mode or ("dry_run" if self.dry_run else "live"),
            "error": error,
        }
        if screenshots:
            payload["screenshots"] = dict(screenshots)
        if screenshot_errors:
            payload["screenshot_errors"] = list(screenshot_errors)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")
