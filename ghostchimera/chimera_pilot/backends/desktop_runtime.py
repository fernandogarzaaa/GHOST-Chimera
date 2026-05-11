"""Desktop control backend for Ghost Chimera."""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..desktop_adapter import build_desktop_adapter
from ..desktop_policy import (
    DesktopActionClass,
    destructive_desktop_confirmation_error,
    infer_desktop_action_class,
)
from ..desktop_targeting import resolve_target_descriptor
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult


class DesktopRuntimeBackend:
    """Executes Desktop Control tasks."""

    id = "desktop.runtime"
    name = "Desktop Runtime Backend"
    DEFAULT_MAX_LIVE_ACTIONS = 25
    DEFAULT_MAX_SESSION_SECONDS = 300.0
    _SUPPORTED_ACTIONS = {"click", "double_click", "right_click", "type", "hotkey", "move", "plan"}

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
        if action not in self._SUPPORTED_ACTIONS:
            return ExecutionResult(self.id, task.id, False, "", error=f"Unsupported desktop action: {action}")
        trace_id = str(task.constraints.get("trace_id") or task.inputs.get("trace_id") or f"desktop-trace-{uuid.uuid4().hex[:10]}")
        if action == "plan":
            return self._execute_plan(task, trace_id=trace_id)
        single = self._execute_single_action(
            task,
            step_inputs=task.inputs,
            trace_id=trace_id,
            step_index=0,
            step_total=1,
            attempt=1,
        )
        metrics = self._desktop_metrics(
            single["action"],
            single["action_class"],
            trace_id=trace_id,
            screenshots=single["screenshots"],
            screenshot_errors=single["screenshot_errors"],
            step_outcomes=[single["step_outcome"]],
        )
        return ExecutionResult(
            self.id,
            task.id,
            single["ok"],
            single["output"],
            error=single["error"],
            metrics=metrics,
        )

    def _execute_plan(self, task: TaskSpec, *, trace_id: str) -> ExecutionResult:
        raw_plan = task.inputs.get("plan")
        if not isinstance(raw_plan, list) or not raw_plan:
            return ExecutionResult(self.id, task.id, False, "", error="Desktop plan requires a non-empty plan list")
        step_outcomes: list[dict[str, Any]] = []
        for idx, raw_step in enumerate(raw_plan):
            if not isinstance(raw_step, dict):
                return ExecutionResult(self.id, task.id, False, "", error=f"Desktop plan step {idx + 1} is not a dict")
            retries = max(0, int(raw_step.get("retries", task.constraints.get("step_retries", 0)) or 0))
            stop_on_failure = bool(raw_step.get("stop_on_failure", True))
            last_step_result: dict[str, Any] | None = None
            for attempt in range(1, retries + 2):
                step_result = self._execute_single_action(
                    task,
                    step_inputs=raw_step,
                    trace_id=trace_id,
                    step_index=idx,
                    step_total=len(raw_plan),
                    attempt=attempt,
                )
                step_outcomes.append(step_result["step_outcome"])
                last_step_result = step_result
                if step_result["ok"]:
                    break
            assert last_step_result is not None
            if not last_step_result["ok"] and stop_on_failure:
                metrics = self._desktop_metrics(
                    "plan",
                    str(task.inputs.get("action_class", "mutating")),
                    trace_id=trace_id,
                    step_outcomes=step_outcomes,
                )
                return ExecutionResult(
                    self.id,
                    task.id,
                    False,
                    "",
                    error=last_step_result["error"] or f"Desktop plan failed at step {idx + 1}",
                    metrics=metrics,
                )
        metrics = self._desktop_metrics(
            "plan",
            str(task.inputs.get("action_class", "mutating")),
            trace_id=trace_id,
            step_outcomes=step_outcomes,
        )
        return ExecutionResult(
            self.id,
            task.id,
            True,
            {"mode": "dry_run" if self.dry_run else "live", "executed": not self.dry_run, "trace_id": trace_id, "steps": step_outcomes},
            metrics=metrics,
        )

    def _execute_single_action(
        self,
        task: TaskSpec,
        *,
        step_inputs: dict[str, Any],
        trace_id: str,
        step_index: int,
        step_total: int,
        attempt: int,
    ) -> dict[str, Any]:
        action = str(step_inputs.get("action", "")).strip().lower()
        action_class = infer_desktop_action_class(action=action, inputs=step_inputs, objective=task.objective)
        target = str(step_inputs.get("target", "")).strip()
        text = str(step_inputs.get("text", ""))
        target_descriptor = resolve_target_descriptor(step_inputs)
        screenshots: dict[str, str] = {}
        screenshot_errors: list[str] = []

        if action not in {"click", "double_click", "right_click", "type", "hotkey", "move"}:
            error = f"Unsupported desktop action: {action}"
            self._record_action(
                task,
                action,
                action_class=action_class,
                ok=False,
                error=error,
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
            return {
                "ok": False,
                "output": "",
                "error": error,
                "action": action,
                "action_class": action_class,
                "screenshots": screenshots,
                "screenshot_errors": screenshot_errors,
                "step_outcome": self._step_outcome(action, action_class, step_index, attempt, False, error),
            }

        if self.dry_run:
            output = {
                "mode": "dry_run",
                "executed": False,
                "action": action,
                "action_class": action_class,
                "target": target,
                "target_descriptor": target_descriptor,
                "text": text if action == "type" else "",
                "trace_id": trace_id,
            }
            self._record_action(
                task,
                action,
                action_class=action_class,
                ok=True,
                mode="dry_run",
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
            return {
                "ok": True,
                "output": output,
                "error": None,
                "action": action,
                "action_class": action_class,
                "screenshots": screenshots,
                "screenshot_errors": screenshot_errors,
                "step_outcome": self._step_outcome(action, action_class, step_index, attempt, True, None),
            }

        live_flag = str(task.constraints.get("live_desktop", "")).strip().lower()
        if live_flag not in {"1", "true", "yes"}:
            error = "Live desktop control requires task.constraints.live_desktop=true"
            return self._failed_step(
                task,
                action=action,
                action_class=action_class,
                error=error,
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
        if target_descriptor and step_inputs.get("x") is None and step_inputs.get("y") is None:
            error = "Semantic target could not be resolved to coordinates; provide x/y or configure a semantic resolver"
            return self._failed_step(
                task,
                action=action,
                action_class=action_class,
                error=error,
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
        if self._kill_switch_active(task):
            return self._failed_step(
                task,
                action=action,
                action_class=action_class,
                error="Desktop kill switch is active",
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
        limit_error = self._live_limit_error()
        if limit_error:
            return self._failed_step(
                task,
                action=action,
                action_class=action_class,
                error=limit_error,
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
        if action_class == DesktopActionClass.DESTRUCTIVE.value:
            confirmation_error = destructive_desktop_confirmation_error(task.constraints.get("confirmation_token"))
            if confirmation_error:
                return self._failed_step(
                    task,
                    action=action,
                    action_class=action_class,
                    error=confirmation_error,
                    trace_id=trace_id,
                    step_index=step_index,
                    step_total=step_total,
                    attempt=attempt,
                    target_descriptor=target_descriptor,
                )

        try:
            import pyautogui  # type: ignore
        except Exception:
            return self._failed_step(
                task,
                action=action,
                action_class=action_class,
                error="pyautogui is required for live desktop control",
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
        adapter = build_desktop_adapter(pyautogui)
        self.capabilities.metadata["desktop_adapter"] = adapter.info.id
        self.capabilities.metadata["desktop_platform"] = adapter.info.platform

        try:
            self._live_actions_executed += 1
            self.capabilities.metadata["live_actions_executed"] = self._live_actions_executed
            self._capture_screenshot(adapter, task, "before", screenshots, screenshot_errors)
            self._execute_live(adapter, action=action, text=text, inputs=step_inputs)
        except Exception as exc:  # noqa: BLE001
            self._capture_screenshot(adapter, task, "after", screenshots, screenshot_errors)
            error = f"Desktop action failed: {exc}"
            self._record_action(
                task,
                action,
                action_class=action_class,
                ok=False,
                error=error,
                screenshots=screenshots,
                screenshot_errors=screenshot_errors,
                trace_id=trace_id,
                step_index=step_index,
                step_total=step_total,
                attempt=attempt,
                target_descriptor=target_descriptor,
            )
            return {
                "ok": False,
                "output": "",
                "error": error,
                "action": action,
                "action_class": action_class,
                "screenshots": screenshots,
                "screenshot_errors": screenshot_errors,
                "step_outcome": self._step_outcome(action, action_class, step_index, attempt, False, error),
            }
        self._capture_screenshot(adapter, task, "after", screenshots, screenshot_errors)
        self._record_action(
            task,
            action,
            action_class=action_class,
            ok=True,
            mode="live",
            screenshots=screenshots,
            screenshot_errors=screenshot_errors,
            trace_id=trace_id,
            step_index=step_index,
            step_total=step_total,
            attempt=attempt,
            target_descriptor=target_descriptor,
        )
        return {
            "ok": True,
            "output": {
                "mode": "live",
                "executed": True,
                "action": action,
                "action_class": action_class,
                "target": target,
                "target_descriptor": target_descriptor,
                "trace_id": trace_id,
            },
            "error": None,
            "action": action,
            "action_class": action_class,
            "screenshots": screenshots,
            "screenshot_errors": screenshot_errors,
            "step_outcome": self._step_outcome(action, action_class, step_index, attempt, True, None),
        }

    def _failed_step(
        self,
        task: TaskSpec,
        *,
        action: str,
        action_class: str,
        error: str,
        trace_id: str,
        step_index: int,
        step_total: int,
        attempt: int,
        target_descriptor: dict[str, str],
    ) -> dict[str, Any]:
        self._record_action(
            task,
            action,
            action_class=action_class,
            ok=False,
            error=error,
            trace_id=trace_id,
            step_index=step_index,
            step_total=step_total,
            attempt=attempt,
            target_descriptor=target_descriptor,
        )
        return {
            "ok": False,
            "output": "",
            "error": error,
            "action": action,
            "action_class": action_class,
            "screenshots": {},
            "screenshot_errors": [],
            "step_outcome": self._step_outcome(action, action_class, step_index, attempt, False, error),
        }

    def _execute_live(self, adapter: Any, *, action: str, text: str, inputs: dict[str, Any]) -> None:
        x = inputs.get("x")
        y = inputs.get("y")
        if action in {"click", "double_click", "right_click", "move"} and x is not None and y is not None:
            adapter.move_to(int(x), int(y))
        if action == "click":
            adapter.click()
        elif action == "double_click":
            adapter.double_click()
        elif action == "right_click":
            adapter.right_click()
        elif action == "type":
            adapter.type_text(text, interval=0.01)
        elif action == "hotkey":
            keys = inputs.get("keys", [])
            if not isinstance(keys, list) or not keys:
                raise ValueError("hotkey action requires non-empty keys list")
            adapter.hotkey([str(k) for k in keys])

    def _step_outcome(
        self,
        action: str,
        action_class: str,
        step_index: int,
        attempt: int,
        ok: bool,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "step_index": step_index,
            "attempt": attempt,
            "action": action,
            "action_class": action_class,
            "ok": ok,
            "error": error,
        }

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
        adapter: Any,
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
            adapter.screenshot(str(path))
        except Exception as exc:  # noqa: BLE001
            screenshot_errors.append(f"{phase}: {exc}")
            return
        screenshots[phase] = str(path)

    def _desktop_metrics(
        self,
        action: str,
        action_class: str,
        *,
        trace_id: str | None = None,
        screenshots: dict[str, str] | None = None,
        screenshot_errors: list[str] | None = None,
        step_outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {"desktop_action": action, "desktop_action_class": action_class}
        if trace_id:
            metrics["desktop_trace_id"] = trace_id
        action_log_path = self._resolve_action_log_path()
        if action_log_path is not None:
            metrics["desktop_action_log_path"] = str(action_log_path)
        if screenshots:
            metrics["desktop_screenshots"] = dict(screenshots)
        if screenshot_errors:
            metrics["desktop_screenshot_errors"] = list(screenshot_errors)
        if step_outcomes is not None:
            metrics["desktop_step_outcomes"] = list(step_outcomes)
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
        trace_id: str | None = None,
        step_index: int | None = None,
        step_total: int | None = None,
        attempt: int | None = None,
        target_descriptor: dict[str, str] | None = None,
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
            "trace_id": trace_id,
            "step_index": step_index,
            "step_total": step_total,
            "attempt": attempt,
            "target_descriptor": dict(target_descriptor or {}),
        }
        if screenshots:
            payload["screenshots"] = dict(screenshots)
        if screenshot_errors:
            payload["screenshot_errors"] = list(screenshot_errors)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, sort_keys=True) + "\n")

