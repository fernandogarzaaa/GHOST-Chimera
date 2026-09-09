"""Local-first conversational loop state for Ghost Console.

This module provides the durable, redacted state contract used by the browser
console and CLI. It stores transcripts and approvals, but not raw audio or
hidden reasoning.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..trust_runtime import TrustRuntimeStore

ConversationRunner = Callable[[str], Any]
ConversationStatusProvider = Callable[[], dict[str, Any]]

SESSION_MODES = {
    "listening",
    "thinking",
    "waiting_for_user",
    "waiting_for_approval",
    "executing",
    "sleeping",
    "error",
}
SECRET_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "bearer")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:ghp|github_pat|xoxb|xoxp)_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{12,}", re.IGNORECASE),
)
HIGH_IMPACT_TERMS = (
    "delete",
    "remove",
    "write file",
    "modify file",
    "install",
    "execute",
    "desktop",
    "email crawl",
    "scrape email",
    "send email",
    "enable mcp",
    "activate skill",
    "switch model",
)


@dataclass
class ConversationTurn:
    id: str
    role: str
    content: str
    intent: str = ""
    input_mode: str = "text"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass
class ConversationSession:
    session_id: str
    title: str = "Ghost Conversation"
    mode: str = "listening"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    turns: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    last_reply: str = ""
    last_intent: str = ""
    stopped: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode if self.mode in SESSION_MODES else "listening"
        return _redact_value(data)


def _now() -> float:
    return time.time()


def _stable_id(*parts: object, length: int = 16) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                out[str(key)] = "[redacted]" if item else ""
            else:
                out[str(key)] = _redact_value(item)
        return out
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def classify_conversation_intent(message: str) -> dict[str, Any]:
    text = str(message or "").strip()
    lowered = text.lower()
    if not text:
        return {"intent": "empty", "high_impact": False}
    if any(term in lowered for term in ("ghost stop", "stop listening", "stop all", "emergency stop")):
        return {"intent": "stop", "high_impact": False}
    if "ghost sleep" in lowered or lowered == "sleep":
        return {"intent": "sleep", "high_impact": False}
    if "wake up" in lowered or "hey ghost" in lowered or lowered == "wake":
        return {"intent": "wake", "high_impact": False}
    if lowered in {"approve", "approved"} or lowered.startswith("approve "):
        return {"intent": "approve", "high_impact": False}
    if lowered in {"deny", "denied"} or lowered.startswith("deny "):
        return {"intent": "deny", "high_impact": False}
    if "show evidence" in lowered:
        return {"intent": "show_evidence", "high_impact": False}
    if "readiness" in lowered or "status" in lowered or lowered == "/status":
        return {"intent": "readiness", "high_impact": False}
    if "sandbox" in lowered:
        return {"intent": "sandbox", "high_impact": False}
    if "evolve yourself" in lowered or "self-evolution" in lowered or "self evolution" in lowered:
        return {"intent": "self_evolution", "high_impact": False}
    high_impact = any(term in lowered for term in HIGH_IMPACT_TERMS)
    return {"intent": "run", "high_impact": high_impact}


def summarize_run_result(result: Any, *, ok: bool, intent: str = "run", objective: str = "") -> str:
    """Create the operator-facing reply for a run result."""

    if isinstance(result, dict) and result.get("operator_report"):
        return str(result["operator_report"])
    if not ok:
        if isinstance(result, dict) and result.get("error"):
            return f"I could not complete that: {result.get('error')}"
        if isinstance(result, dict) and isinstance(result.get("executions"), list):
            errors = [
                _redact_text(str(item.get("error") or "").strip())
                for item in result["executions"]
                if isinstance(item, dict) and str(item.get("error") or "").strip()
            ]
            if errors:
                return f"I could not complete that: {errors[0][:1200]}"
        return "I could not complete that. Check Trust Runtime for details."
    if intent == "sandbox":
        return "Sandbox journey completed. I recorded the run in Trust Runtime. Review findings and approve any follow-up before changes."
    if intent == "self_evolution":
        return "Self-Evolution review completed. I recorded the run and staged recommendations for approval instead of activating them."

    lines = ["I completed the run and recorded it in Trust Runtime."]
    if objective:
        lines.append(f"Objective: {_redact_text(str(objective).strip())[:180]}")
    if isinstance(result, dict):
        executions = result.get("executions") if isinstance(result.get("executions"), list) else []
        if executions:
            passed = sum(1 for item in executions if isinstance(item, dict) and item.get("ok") is not False)
            backends = sorted(
                {
                    str(item.get("backend_id") or item.get("backend") or "").strip()
                    for item in executions
                    if isinstance(item, dict) and str(item.get("backend_id") or item.get("backend") or "").strip()
                }
            )
            outputs = [
                _redact_text(str(item.get("output") or item.get("result") or "").strip())
                for item in executions
                if isinstance(item, dict) and str(item.get("output") or item.get("result") or "").strip()
            ]
            lines.append(f"Execution: {passed}/{len(executions)} task(s) passed" + (f" via {', '.join(backends[:3])}" if backends else "") + ".")
            if outputs:
                result_preview = outputs[0][:3000]
                lines.append(f"Result:\n{result_preview}")
        trust_run = result.get("trust_run") if isinstance(result.get("trust_run"), dict) else {}
        run_meta = trust_run.get("run") if isinstance(trust_run.get("run"), dict) else {}
        run_id = str(run_meta.get("run_id") or "").strip()
        if run_id:
            lines.append(f"Evidence: Trust run {run_id} is available in the Trust Runtime tab.")
        tool_calls = trust_run.get("tool_calls") if isinstance(trust_run.get("tool_calls"), list) else []
        approvals = trust_run.get("approvals") if isinstance(trust_run.get("approvals"), list) else []
        if not tool_calls:
            lines.append("Side effects: no tool calls were reported by this run.")
        if approvals:
            lines.append(f"Approval: {len(approvals)} approval checkpoint(s) are attached to the run.")
    lines.append("Next: ask me to show evidence, run a readiness check, or approve a specific follow-up.")
    return " ".join(lines)


class ConversationStore:
    """Durable JSON store for local conversation sessions."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.path = self.state_dir / "conversation_sessions.json"

    def _default_state(self) -> dict[str, Any]:
        return {
            "settings": {
                "always_listening": False,
                "hands_free": False,
                "full_bypass": False,
                "local_fallback": True,
                "presenter_coach_mode": False,
                "voice_provider": "browser",
                "voice_id": "browser-default",
                "raw_audio_stored": False,
            },
            "active_session_id": "",
            "sessions": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        default = self._default_state()
        default["settings"].update(data.get("settings") if isinstance(data.get("settings"), dict) else {})
        default["active_session_id"] = str(data.get("active_session_id") or "")
        default["sessions"] = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        return _redact_value(default)

    def _save(self, data: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(_redact_value(data), indent=2, sort_keys=True), encoding="utf-8")

    def settings(self) -> dict[str, Any]:
        return dict(self._load().get("settings") or {})

    def update_settings(self, **updates: Any) -> dict[str, Any]:
        data = self._load()
        settings = dict(data.get("settings") or {})
        for key in ("always_listening", "hands_free", "full_bypass", "local_fallback", "presenter_coach_mode"):
            if key in updates:
                settings[key] = bool(updates[key])
        for key in ("voice_provider", "voice_id"):
            if key in updates and updates[key] is not None:
                settings[key] = str(updates[key] or "").strip()
        settings["raw_audio_stored"] = False
        data["settings"] = settings
        self._save(data)
        return {"ok": True, "settings": settings}

    def create_session(
        self,
        *,
        session_id: str = "",
        title: str = "Ghost Conversation",
        mode: str = "listening",
        always_listening: bool | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        sid = session_id.strip() if session_id else _stable_id("conversation", _now(), title)
        session = ConversationSession(session_id=sid, title=title, mode=mode if mode in SESSION_MODES else "listening")
        data["sessions"][sid] = session.to_dict()
        data["active_session_id"] = sid
        if always_listening is not None:
            data["settings"]["always_listening"] = bool(always_listening)
        self._save(data)
        return {"ok": True, "session": session.to_dict(), "session_id": sid}

    def list_sessions(self) -> dict[str, Any]:
        data = self._load()
        sessions = list((data.get("sessions") or {}).values())
        sessions.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        return {"ok": True, "sessions": sessions, "active_session_id": data.get("active_session_id", "")}

    def get_session(self, session_id: str = "") -> dict[str, Any]:
        data = self._load()
        sid = session_id or str(data.get("active_session_id") or "")
        session = (data.get("sessions") or {}).get(sid)
        if not isinstance(session, dict):
            raise KeyError(sid)
        return _redact_value(session)

    def active_session(self) -> dict[str, Any] | None:
        data = self._load()
        sid = str(data.get("active_session_id") or "")
        session = (data.get("sessions") or {}).get(sid)
        return _redact_value(session) if isinstance(session, dict) else None

    def _mutate_session(self, session_id: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        data = self._load()
        session = (data.get("sessions") or {}).get(session_id)
        if not isinstance(session, dict):
            raise KeyError(session_id)
        mutator(session)
        session["updated_at"] = _now()
        data["sessions"][session_id] = _redact_value(session)
        data["active_session_id"] = session_id
        self._save(data)
        return _redact_value(session)

    def append_turn(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        intent: str = "",
        input_mode: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        turn = ConversationTurn(
            id=_stable_id(session_id, role, content, _now()),
            role=role,
            content=content,
            intent=intent,
            input_mode=input_mode,
            metadata=metadata or {},
        ).to_dict()

        def mutate(session: dict[str, Any]) -> None:
            turns = session.setdefault("turns", [])
            if isinstance(turns, list):
                turns.append(turn)
            session["last_intent"] = intent
            if role == "ghost":
                session["last_reply"] = _redact_text(content)

        return self._mutate_session(session_id, mutate)

    def update_session(
        self,
        session_id: str,
        *,
        mode: str | None = None,
        pending_approval: dict[str, Any] | None | bool = False,
        last_reply: str | None = None,
        stopped: bool | None = None,
    ) -> dict[str, Any]:
        def mutate(session: dict[str, Any]) -> None:
            if mode:
                session["mode"] = mode if mode in SESSION_MODES else "listening"
            if pending_approval is not False:
                session["pending_approval"] = _redact_value(pending_approval)
            if last_reply is not None:
                session["last_reply"] = _redact_text(last_reply)
            if stopped is not None:
                session["stopped"] = bool(stopped)

        return self._mutate_session(session_id, mutate)


class ConversationalLoopController:
    """Route conversation turns through trust-aware Ghost actions."""

    def __init__(
        self,
        *,
        state_dir: str | Path,
        store: ConversationStore | None = None,
        trust_store: TrustRuntimeStore | None = None,
        objective_runner: ConversationRunner | None = None,
        status_provider: ConversationStatusProvider | None = None,
        timeline_recorder: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.store = store or ConversationStore(self.state_dir)
        self.trust_store = trust_store or TrustRuntimeStore(self.state_dir)
        self.objective_runner = objective_runner or (lambda objective: {"ok": True, "objective": objective})
        self.status_provider = status_provider or (lambda: {"ok": False, "error": "No status provider is attached."})
        self.timeline_recorder = timeline_recorder

    def _record(self, event_type: str, detail: dict[str, Any] | None = None) -> None:
        if self.timeline_recorder:
            self.timeline_recorder(event_type, _redact_value(detail or {}))

    def create_session(self, *, session_id: str = "", title: str = "Ghost Conversation", always_listening: bool = True) -> dict[str, Any]:
        payload = self.store.create_session(
            session_id=session_id,
            title=title,
            mode="listening" if always_listening else "waiting_for_user",
            always_listening=always_listening,
        )
        self._record("conversation_session_started", {"session_id": payload["session_id"], "always_listening": always_listening})
        return payload["session"]

    def update_settings(self, **updates: Any) -> dict[str, Any]:
        payload = self.store.update_settings(**updates)
        self._record("conversation_settings_updated", payload["settings"])
        return payload

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "settings": self.store.settings(),
            "active_session": self.store.active_session(),
            "sessions": self.store.list_sessions().get("sessions", []),
            "voice_catalog": voice_catalog(),
            "privacy": {
                "raw_audio_stored": False,
                "transcripts_redacted": True,
                "anti_detection_supported": False,
                "coaching_requires_visible_console": True,
            },
        }

    def stop(self, session_id: str) -> dict[str, Any]:
        self.store.update_settings(always_listening=False)
        self.store.update_session(session_id, mode="sleeping", pending_approval=None, stopped=True)
        reply = "Ghost stopped listening. Say or press wake when you want to resume."
        self.store.append_turn(session_id, role="ghost", content=reply, intent="stop")
        self._record("conversation_stopped", {"session_id": session_id})
        return {"ok": True, "session": self.store.get_session(session_id), "mode": "sleeping", "reply": reply}

    def handle_turn(self, session_id: str, message: str, *, input_mode: str = "text") -> dict[str, Any]:
        session = self.store.get_session(session_id)
        intent_payload = classify_conversation_intent(message)
        intent = intent_payload["intent"]
        if intent == "empty":
            return {"ok": False, "error": "Message is required", "mode": session.get("mode", "listening")}
        self.store.append_turn(session_id, role="user", content=message, intent=intent, input_mode=input_mode)
        self._record("conversation_turn_received", {"session_id": session_id, "intent": intent, "input_mode": input_mode})

        if intent == "stop":
            return self.stop(session_id)
        if intent == "sleep":
            self.store.update_settings(always_listening=False)
            return self._reply(session_id, intent, "Ghost is sleeping. Say Hey Ghost or use Wake to resume.", mode="sleeping")
        if intent == "wake":
            self.store.update_settings(always_listening=True)
            return self._reply(session_id, intent, "I am listening. Tell me what you want to do next.", mode="listening")
        if intent == "deny":
            self.store.update_session(session_id, mode="listening", pending_approval=None)
            return self._reply(session_id, intent, "Denied. I cleared the pending action and stayed in listening mode.", mode="listening")
        if intent == "approve":
            return self._approve_pending(session_id, input_mode=input_mode)
        if intent == "show_evidence":
            return self._reply(session_id, intent, self._evidence_reply(), mode="listening")
        if intent == "readiness":
            return self._reply(session_id, intent, self._readiness_reply(), mode="listening")

        objective = self._objective_for_intent(intent, message)
        if intent_payload.get("high_impact"):
            approval = {
                "id": _stable_id(session_id, objective, "approval"),
                "objective": objective,
                "risk_level": "high",
                "input_mode": input_mode,
                "reason": "High-impact conversational action requires approval unless Full Bypass is armed.",
            }
            session = self.store.update_session(session_id, mode="waiting_for_approval", pending_approval=approval)
            reply = "This is high impact. Say approve after enabling Full Bypass, or confirm from the dashboard."
            self.store.append_turn(session_id, role="ghost", content=reply, intent="approval_request", metadata={"approval": approval})
            self._record("conversation_approval_requested", {"session_id": session_id, "risk_level": "high"})
            return {"ok": True, "intent": intent, "mode": "waiting_for_approval", "reply": reply, "session": session, "pending_approval": approval}

        return self._execute_objective(session_id, objective, intent=intent, input_mode=input_mode)

    def _reply(self, session_id: str, intent: str, reply: str, *, mode: str) -> dict[str, Any]:
        self.store.update_session(session_id, mode=mode, last_reply=reply)
        self.store.append_turn(session_id, role="ghost", content=reply, intent=intent)
        return {
            "ok": True,
            "intent": intent,
            "mode": mode,
            "reply": reply,
            "operator_report": reply,
            "session": self.store.get_session(session_id),
        }

    def _approve_pending(self, session_id: str, *, input_mode: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        pending = session.get("pending_approval") if isinstance(session.get("pending_approval"), dict) else None
        if not pending:
            return self._reply(session_id, "approve", "There is no pending action to approve.", mode="listening")
        settings = self.store.settings()
        if pending.get("risk_level") == "high" and input_mode == "voice" and not settings.get("full_bypass"):
            reply = "Voice approval for this action requires Full Bypass to be armed first."
            self.store.append_turn(session_id, role="ghost", content=reply, intent="approval_blocked")
            return {
                "ok": False,
                "intent": "approve",
                "mode": "waiting_for_approval",
                "reply": reply,
                "session": session,
                "pending_approval": pending,
            }
        self.store.update_session(session_id, mode="executing", pending_approval=None)
        self._record("conversation_approval_resolved", {"session_id": session_id, "approved": True, "voice": input_mode == "voice"})
        return self._execute_objective(session_id, str(pending.get("objective") or ""), intent="approve", input_mode=input_mode)

    def _execute_objective(self, session_id: str, objective: str, *, intent: str, input_mode: str) -> dict[str, Any]:
        self.store.update_session(session_id, mode="executing")
        trust_run = self.trust_store.create_run(
            agent_name="ghost_conversation",
            objective=objective,
            source="conversation",
            metadata={"session_id": session_id, "intent": intent, "input_mode": input_mode},
        )
        self.trust_store.record_step(
            trust_run["run_id"],
            step_type="conversation_intake",
            status="completed",
            inputs={"objective": objective, "intent": intent},
            idempotency_key=f"{trust_run['run_id']}:conversation-intake",
        )
        try:
            result = self.objective_runner(objective)
            ok = not (isinstance(result, dict) and result.get("ok") is False)
            self.trust_store.record_step(
                trust_run["run_id"],
                step_type="conversation_result",
                status="completed" if ok else "failed",
                outputs=result if isinstance(result, dict) else {"result": result},
                idempotency_key=f"{trust_run['run_id']}:conversation-result",
            )
            reply = self._summarize_result(result, ok=ok, intent=intent, objective=objective)
            self.store.update_session(session_id, mode="listening", last_reply=reply, pending_approval=None)
            self.store.append_turn(
                session_id,
                role="ghost",
                content=reply,
                intent=intent,
                metadata={"trust_run_id": trust_run["run_id"], "ok": ok},
            )
            self._record("conversation_objective_run", {"session_id": session_id, "intent": intent, "ok": ok, "trust_run_id": trust_run["run_id"]})
            return {
                "ok": ok,
                "intent": intent,
                "mode": "listening",
                "reply": reply,
                "operator_report": reply,
                "result": _redact_value(result),
                "session": self.store.get_session(session_id),
                "trust_run": self.trust_store.get_run(trust_run["run_id"]),
                "next_suggestions": self._next_suggestions(intent, ok),
            }
        except Exception as exc:
            self.trust_store.record_step(
                trust_run["run_id"],
                step_type="conversation_result",
                status="failed",
                outputs={"error": str(exc), "type": exc.__class__.__name__},
                idempotency_key=f"{trust_run['run_id']}:conversation-error",
            )
            reply = f"I hit an error: {exc}"
            self.store.update_session(session_id, mode="error", last_reply=reply)
            self.store.append_turn(session_id, role="ghost", content=reply, intent="error")
            return {"ok": False, "intent": intent, "mode": "error", "reply": reply, "error": str(exc)}

    def _objective_for_intent(self, intent: str, message: str) -> str:
        if intent == "sandbox":
            return "Run the operator sandbox journey and summarize findings, warnings, and next safe actions."
        if intent == "self_evolution":
            return (
                "Use MiniMind, RAG, and Trust Runtime context to propose one safe Self-Evolution candidate. "
                "Do not modify files or activate capabilities without explicit approval."
            )
        return message

    def _evidence_reply(self) -> str:
        payload = self.trust_store.list_runs(limit=5)
        runs = payload.get("runs") if isinstance(payload.get("runs"), list) else []
        if not runs:
            return "I do not have Trust Runtime runs to show yet. Run an objective first, then ask me to show evidence."
        lines = ["Recent Trust Runtime evidence:"]
        for run in runs[:5]:
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("run_id") or "").strip()
            status = str(run.get("status") or "unknown").strip()
            source = str(run.get("source") or "unknown").strip()
            objective = _redact_text(str(run.get("objective") or "").strip())
            steps = run.get("step_count", 0)
            lines.append(f"- {run_id}: {status} from {source}, steps={steps}, objective={objective[:140]}")
        lines.append("Open the Trust Runtime tab for full redacted traces and replay/export controls.")
        return "\n".join(lines)

    def _readiness_reply(self) -> str:
        try:
            status = self.status_provider()
        except Exception as exc:
            return f"I could not read operator readiness: {exc}"
        model = status.get("model") if isinstance(status.get("model"), dict) else {}
        active_path = status.get("active_path") if isinstance(status.get("active_path"), dict) else {}
        production = status.get("production_readiness") if isinstance(status.get("production_readiness"), dict) else {}
        counts = status.get("counts") if isinstance(status.get("counts"), dict) else {}
        warnings = [str(item) for item in (status.get("warnings") or []) if str(item).strip()]
        lines = [
            "Readiness check:",
            f"- Active path: {active_path.get('label') or active_path.get('profile_id') or 'not selected'}",
            f"- Model: {model.get('provider') or 'not configured'} / {model.get('model') or 'default'}",
            f"- Model auth configured: {bool(model.get('auth_configured', model.get('api_key_configured')))}",
            f"- Production readiness: {production.get('status') or ('ready' if production.get('ready') else 'review')}",
            f"- Learning sources: {counts.get('approved_sources', 0)} approved of {counts.get('learning_sources', 0)} total",
            f"- Pending evolution candidates: {counts.get('pending_candidates', 0)}",
        ]
        if warnings:
            lines.append("- Warnings: " + "; ".join(warnings[:5]))
            lines.append("Next action: resolve the first warning above, then rerun readiness.")
        else:
            lines.append("- Warnings: none reported")
            lines.append("Next action: run a small sandbox workflow or review the next pending evolution candidate.")
        return "\n".join(lines)

    def _summarize_result(self, result: Any, *, ok: bool, intent: str, objective: str = "") -> str:
        return summarize_run_result(result, ok=ok, intent=intent, objective=objective)

    def _next_suggestions(self, intent: str, ok: bool) -> list[str]:
        if not ok:
            return ["Show evidence", "Run readiness check", "Try a smaller sandbox request"]
        if intent == "self_evolution":
            return ["Review Self-Evolution candidates", "Run readiness check", "Show evidence"]
        if intent == "sandbox":
            return ["Show sandbox findings", "Approve next safe action", "Run readiness check"]
        return ["Show evidence", "Evolve yourself safely", "Run in sandbox"]


def voice_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "browser-default",
            "provider": "browser",
            "label": "Browser Default",
            "privacy": "browser-managed",
            "latency": "low",
            "installed": True,
            "supports_input": True,
            "supports_output": True,
        },
        {
            "id": "sherpa-onnx-local",
            "provider": "local",
            "label": "Sherpa-ONNX Local",
            "privacy": "local/private",
            "latency": "low",
            "installed": False,
            "supports_input": True,
            "supports_output": True,
        },
        {
            "id": "whisper-kokoro-local",
            "provider": "local",
            "label": "Whisper/Kokoro Local",
            "privacy": "local/private",
            "latency": "medium",
            "installed": False,
            "supports_input": True,
            "supports_output": True,
        },
    ]
