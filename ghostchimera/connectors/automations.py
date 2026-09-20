"""Automations: cron + email triggers firing typed actions, with run history.

Grok-Automations shaped, Ghost-disciplined. Each automation has one
trigger (cron expression or inbound-email match) and one action:

- ``log`` — record the trigger event + instruction (detection value).
- ``webhook`` — POST JSON to a URL (Home Assistant, n8n, …).
- ``connector_write`` — a provider write executed ONLY with a fresh
  single-use action approval (see trust layer): the run requests the
  approval and parks as ``awaiting-approval``; the operator approves in
  Trust & Approvals, then the run executes via ``execute-approved``.

Every firing appends a run record (JSONL): trigger context, status,
summary, optional parent link for continuations. Notification preference
is recorded; delivery beyond the console/audit trail is a later phase.
A single daemon poll thread handles cron due-checks and email polling.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

POLL_INTERVAL_S = 60.0
EMAIL_CHECK_MIN_GAP_S = 300.0
MAX_SEEN_UIDS = 200


class AutomationError(RuntimeError):
    pass


def _now() -> float:
    return time.time()


def _next_cron_run(cron_expression: str, *, now: float | None = None) -> float:
    try:
        from croniter import croniter
    except ImportError as exc:
        raise AutomationError("cron automations need the 'croniter' package") from exc
    try:
        return float(croniter(cron_expression, now or _now()).get_next())
    except Exception as exc:
        raise AutomationError(f"bad cron expression: {exc}") from exc


def _close_engine(engine: Any) -> None:
    with contextlib.suppress(Exception):
        engine.close()


class AutomationsEngine:
    """Automation store + poller + run history."""

    def __init__(self, state_dir: str | Path, *, poll_interval: float = POLL_INTERVAL_S) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._store_path = self.state_dir / "automations.json"
        self._runs_path = self.state_dir / "automations_runs.jsonl"
        self._lock = threading.RLock()
        self._poll_interval = max(5.0, float(poll_interval))
        self._thread: threading.Thread | None = None
        self._running = False
        self._automations: list[dict[str, Any]] = []
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._automations = data
        except (OSError, json.JSONDecodeError):
            self._automations = []

    def _save(self) -> None:
        with contextlib.suppress(OSError):
            self._store_path.write_text(json.dumps(self._automations, indent=2), encoding="utf-8")

    def _record_run(self, run: dict[str, Any]) -> None:
        with contextlib.suppress(OSError), open(self._runs_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(run) + "\n")

    # -- CRUD ------------------------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._automations]

    def _find_mutable(self, automation_id: str) -> dict[str, Any]:
        for item in self._automations:
            if item["id"] == automation_id:
                return item
        raise AutomationError(f"unknown automation: {automation_id}")

    def create(
        self,
        *,
        name: str,
        instruction: str,
        trigger: dict[str, Any],
        action: dict[str, Any] | None = None,
        notify: str = "console",
    ) -> dict[str, Any]:
        name, instruction = name.strip(), instruction.strip()
        if not name or not instruction:
            raise AutomationError("name and instruction are required")
        trigger = self._validate_trigger(trigger or {})
        action = self._validate_action(action or {"type": "log"})
        if notify not in ("console", "audit", "both", "neither"):
            raise AutomationError("notify must be console, audit, both, or neither")
        record = {
            "id": f"auto-{uuid.uuid4().hex[:12]}",
            "name": name[:120],
            "instruction": instruction[:2000],
            "trigger": trigger,
            "action": action,
            "notify": notify,
            "enabled": True,
            "created_at": _now(),
            "updated_at": _now(),
            "last_run_at": 0.0,
            "run_count": 0,
            "seen_uids": [],
            "last_check_at": 0.0,
        }
        if trigger["type"] == "cron":
            record["next_run_at"] = _next_cron_run(trigger["cron"])
        with self._lock:
            self._automations.append(record)
            self._save()
            return dict(record)

    def _validate_trigger(self, trigger: dict[str, Any]) -> dict[str, Any]:
        kind = str(trigger.get("type") or "").strip()
        if kind == "cron":
            cron = str(trigger.get("cron") or "").strip()
            if not cron:
                raise AutomationError("cron trigger needs a cron expression")
            _next_cron_run(cron)  # validates
            return {"type": "cron", "cron": cron}
        if kind == "email":
            key_ref = str(trigger.get("key_id") or trigger.get("label") or "").strip()
            if not key_ref:
                raise AutomationError("email trigger needs a vault key id or label")
            return {
                "type": "email",
                "key_id": str(trigger.get("key_id") or ""),
                "label": str(trigger.get("label") or ""),
                "sender": str(trigger.get("sender") or "").strip().lower(),
                "subject": str(trigger.get("subject") or "").strip().lower(),
            }
        raise AutomationError("trigger type must be cron or email")

    def _validate_action(self, action: dict[str, Any]) -> dict[str, Any]:
        kind = str(action.get("type") or "log").strip()
        if kind == "log":
            return {"type": "log"}
        if kind == "webhook":
            url = str(action.get("url") or "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                raise AutomationError("webhook action needs an http(s) url")
            return {"type": "webhook", "url": url}
        if kind == "connector_write":
            for field in ("provider", "method", "url"):
                if not str(action.get(field) or "").strip():
                    raise AutomationError(f"connector_write action needs {field}")
            method = str(action["method"]).upper()
            if method == "GET":
                raise AutomationError("connector_write is for writes; reads need no automation")
            return {
                "type": "connector_write",
                "provider": str(action["provider"]).strip().lower(),
                "method": method,
                "url": str(action["url"]).strip(),
                "data": action.get("data") if isinstance(action.get("data"), dict) else {},
                "scope": str(action.get("scope") or ""),
            }
        raise AutomationError("action type must be log, webhook, or connector_write")

    def set_enabled(self, automation_id: str, *, enabled: bool) -> dict[str, Any]:
        with self._lock:
            record = self._find_mutable(automation_id)
            record["enabled"] = bool(enabled)
            record["updated_at"] = _now()
            if enabled and record["trigger"]["type"] == "cron":
                record["next_run_at"] = _next_cron_run(record["trigger"]["cron"])
            self._save()
            return dict(record)

    def delete(self, automation_id: str) -> bool:
        with self._lock:
            before = len(self._automations)
            self._automations = [a for a in self._automations if a["id"] != automation_id]
            self._save()
            return len(self._automations) < before

    # -- runs --------------------------------------------------------------------
    def runs(self, automation_id: str = "", *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(200, limit))
        try:
            lines = self._runs_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in reversed(lines[-500:]):
            try:
                run = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(run, dict) and (not automation_id or run.get("automation_id") == automation_id):
                out.append(run)
            if len(out) >= limit:
                break
        return out

    def fire(
        self,
        automation_id: str,
        *,
        trigger_context: dict[str, Any] | None = None,
        parent_run_id: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        """Execute one run now (manual run-now, continuation, or poller)."""
        with self._lock:
            record = self._find_mutable(automation_id)
            if not record["enabled"]:
                raise AutomationError("automation is paused")
            snapshot = dict(record)
        run = {
            "run_id": f"run-{uuid.uuid4().hex[:12]}",
            "automation_id": automation_id,
            "automation_name": snapshot["name"],
            "trigger": trigger_context or {"type": snapshot["trigger"]["type"]},
            "parent_run_id": parent_run_id,
            "note": note[:500],
            "started_at": _now(),
            "finished_at": 0.0,
            "status": "running",
            "summary": "",
        }
        try:
            summary = self._execute_action(snapshot, run)
            run["status"] = "awaiting-approval" if summary.get("awaiting_approval") else "complete"
            run["summary"] = str(summary.get("summary", ""))[:1000]
            run["result"] = summary.get("result")
        except Exception as exc:
            run["status"] = "failed"
            run["summary"] = f"{type(exc).__name__}: {exc}"[:500]
        run["finished_at"] = _now()
        with self._lock:
            try:
                live = self._find_mutable(automation_id)
                live["last_run_at"] = run["finished_at"]
                live["run_count"] = int(live.get("run_count", 0)) + 1
                live["updated_at"] = _now()
                if live["trigger"]["type"] == "cron":
                    live["next_run_at"] = _next_cron_run(live["trigger"]["cron"])
                self._save()
            except AutomationError:
                pass
        self._record_run(run)
        self._notify(snapshot, run)
        return run

    def _execute_action(self, automation: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
        action = automation["action"]
        if action["type"] == "log":
            return {"summary": f"trigger observed: {json.dumps(run['trigger'])[:300]}"}
        if action["type"] == "webhook":
            payload = {
                "automation": automation["name"],
                "instruction": automation["instruction"],
                "trigger": run["trigger"],
                "run_id": run["run_id"],
            }
            req = urllib.request.Request(
                action["url"],
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20.0) as resp:
                    body = resp.read().decode("utf-8", "replace")[:500]
                return {
                    "summary": f"webhook POSTed (HTTP {resp.status})",
                    "result": {"status": resp.status, "body": body},
                }
            except Exception as exc:
                raise AutomationError(f"webhook failed: {type(exc).__name__}") from exc
        # connector_write: request the single-use approval, park the run.
        from .auth_engine import CustomAuthEngine

        engine = CustomAuthEngine(self.state_dir)
        try:
            created = engine.request_action_approval(
                "console-user",
                action["provider"],
                action["method"],
                action["url"],
                action.get("data", {}),
                scope=action.get("scope", ""),
                summary=f"[{automation['name']}] {automation['instruction'][:200]}",
                requested_by=f"automation:{automation['id']}",
            )
            return {
                "awaiting_approval": True,
                "summary": f"approval requested ({created['id']}); approve in Trust & Approvals, then execute",
                "result": {"approval_id": created["id"]},
            }
        finally:
            _close_engine(engine)

    def execute_approved(self, run_id: str, approval_id: str) -> dict[str, Any]:
        """Complete an awaiting-approval run by consuming its approval."""
        from .auth_engine import CustomAuthEngine, NeedsApproval

        target = None
        for run in self.runs(limit=200):
            if run.get("run_id") == run_id:
                target = run
                break
        if target is None or target.get("status") != "awaiting-approval":
            raise AutomationError("run is not awaiting approval")
        for run in self.runs(limit=200):
            if run.get("parent_run_id") == run_id and run.get("status") == "complete":
                raise AutomationError("run was already executed")
        automation_id = target["automation_id"]
        with self._lock:
            automation = dict(self._find_mutable(automation_id))
        action = automation["action"]
        if action["type"] != "connector_write":
            raise AutomationError("run has no connector write to execute")
        engine = CustomAuthEngine(self.state_dir)
        try:
            try:
                result = engine.proxy_request(
                    action["provider"],
                    "console-user",
                    action["method"],
                    action["url"],
                    data=action.get("data", {}),
                    approval_id=approval_id,
                )
            except NeedsApproval as exc:
                raise AutomationError(str(exc)) from exc
        finally:
            _close_engine(engine)
        completion = {
            "run_id": f"run-{uuid.uuid4().hex[:12]}",
            "automation_id": automation_id,
            "automation_name": automation["name"],
            "trigger": {"type": "manual-execute", "approval_id": approval_id},
            "parent_run_id": run_id,
            "note": "approved execution",
            "started_at": _now(),
            "finished_at": _now(),
            "status": "complete",
            "summary": f"executed with approval {approval_id}",
            "result": result,
        }
        self._record_run(completion)
        return completion

    def _notify(self, automation: dict[str, Any], run: dict[str, Any]) -> None:
        if automation.get("notify", "console") == "neither":
            return
        # v1: console/audit record only (push delivery is a later phase).
        try:
            from .auth_engine import CustomAuthEngine

            engine = CustomAuthEngine(self.state_dir)
            try:
                engine.audit.record(
                    "automation.ran",
                    entity_id="console-user",
                    provider=automation["name"][:60],
                    detail={"run_id": run["run_id"], "status": run["status"], "summary": run["summary"][:200]},
                )
            finally:
                _close_engine(engine)
        except Exception:
            pass

    # -- poller ----------------------------------------------------------------------
    def ensure_running(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._running = True
            self._thread = threading.Thread(target=self._poll_loop, name="ghost-automations", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _poll_loop(self) -> None:
        while self._running:
            with contextlib.suppress(Exception):
                self.tick()
            for _ in range(int(self._poll_interval)):
                if not self._running:
                    return
                time.sleep(1)

    def tick(self) -> list[dict[str, Any]]:
        """Fire due cron automations and poll email triggers. Returns runs."""
        now = _now()
        runs = []
        with self._lock:
            snapshot = [dict(a) for a in self._automations if a.get("enabled")]
        for automation in snapshot:
            try:
                if automation["trigger"]["type"] == "cron" and float(automation.get("next_run_at", 0)) <= now:
                    runs.append(self.fire(automation["id"], trigger_context={"type": "cron"}))
                elif automation["trigger"]["type"] == "email" and (
                    now - float(automation.get("last_check_at", 0)) >= EMAIL_CHECK_MIN_GAP_S
                ):
                    runs.extend(self._check_email(automation))
            except Exception:
                continue
        return runs

    def _check_email(self, automation: dict[str, Any]) -> list[dict[str, Any]]:
        from ..integrations.mail_basic import fetch_inbox, resolve_app_password
        from .auth_engine import CustomAuthEngine

        trigger = automation["trigger"]
        engine = CustomAuthEngine(self.state_dir)
        try:
            try:
                account = resolve_app_password(
                    engine,
                    "console-user",
                    key_id=trigger.get("key_id", ""),
                    label=trigger.get("label", ""),
                )
            except ValueError:
                return []
            try:
                fetched = fetch_inbox(account["email"], account["secret"], max_messages=10, query="UNSEEN")
            except ValueError:
                return []
        finally:
            _close_engine(engine)
        sender_filter, subject_filter = trigger.get("sender", ""), trigger.get("subject", "")
        with self._lock:
            try:
                live = self._find_mutable(automation["id"])
                live["last_check_at"] = _now()
                seen = set(live.get("seen_uids", []))
            except AutomationError:
                return []
            runs = []
            for message in fetched.get("messages", []):
                uid = message.get("uid", "")
                if not uid or uid in seen:
                    continue
                if sender_filter and sender_filter not in str(message.get("from", "")).lower():
                    continue
                if subject_filter and subject_filter not in str(message.get("subject", "")).lower():
                    continue
                seen.add(uid)
                runs.append(
                    self.fire(
                        automation["id"],
                        trigger_context={
                            "type": "email",
                            "from": message.get("from", ""),
                            "subject": message.get("subject", ""),
                            "uid": uid,
                        },
                    )
                )
            try:
                live = self._find_mutable(automation["id"])
                live["seen_uids"] = sorted(seen)[-MAX_SEEN_UIDS:]
                live["last_check_at"] = _now()
                self._save()
            except AutomationError:
                pass
            return runs


__all__ = ["AutomationError", "AutomationsEngine"]
