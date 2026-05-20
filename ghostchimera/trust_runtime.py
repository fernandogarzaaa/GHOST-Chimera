"""Local-first trust runtime for durable agent runs.

The trust runtime stores append-only run journals, approval checkpoints,
MCP/tool trust metadata, local trace bundles, and simple regression baselines.
It is deliberately dependency-free and local-only: no OTLP collector, workflow
engine, external MCP registry, or network service is required.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SECRET_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization", "bearer")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:ghp|github_pat|xoxb|xoxp)_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{12,}", re.IGNORECASE),
)
POISON_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"exfiltrat(?:e|ion)", re.IGNORECASE),
    re.compile(r"send\s+(?:the\s+)?(?:secret|token|password|credential)", re.IGNORECASE),
    re.compile(r"call\s+(?:restricted|admin|internal)\s+tool", re.IGNORECASE),
)
STATUS_RESUMABLE = {"pending_approval", "retryable_failure", "interrupted"}
RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
TRUST_BASELINE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class ToolTrustEnvelope:
    tool_name: str
    source: str = "internal"
    risk_level: str = "low"
    source_trust: str = "trusted"
    data_class: str = "general"
    required_approval: bool = False
    expected_schema: dict[str, Any] = field(default_factory=dict)
    sanitized: bool = True
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass(frozen=True)
class DurableRun:
    run_id: str
    objective: str
    source: str = "console"
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    agent_name: str = "ghost-chimera"
    ghost_path: str = ""
    model_provider: str = ""
    model_name: str = ""
    step_count: int = 0
    pending_approval_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass(frozen=True)
class RunStepRecord:
    run_id: str
    step_id: str
    step_type: str
    status: str
    input_ref: dict[str, Any] = field(default_factory=dict)
    output_ref: dict[str, Any] = field(default_factory=dict)
    policy_decision: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    retryable: bool = False
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass(frozen=True)
class ApprovalCheckpoint:
    approval_id: str
    run_id: str
    step_id: str
    summary: str
    risk_level: str = "medium"
    status: str = "pending"
    requested_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    decision: str = ""
    reviewer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass(frozen=True)
class ToolCallRecord:
    run_id: str
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    envelope: ToolTrustEnvelope
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["envelope"] = self.envelope.to_dict()
        return _redact_value(data)


@dataclass(frozen=True)
class RunResumeToken:
    run_id: str
    resume_from_step: str
    reason: str
    token: str
    created_at: float = field(default_factory=time.time)
    used_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["token"] = _preview_secret(self.token)
        return data


@dataclass(frozen=True)
class TrustEvalCase:
    case_id: str
    source: str
    label: str
    severity: str
    run_id: str = ""
    expected_status: str = "ok"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _now() -> float:
    return time.time()


def _stable_id(*parts: object, length: int = 16) -> str:
    raw = "|".join(str(part) for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


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


def _preview_secret(secret: str) -> str:
    if not secret:
        return ""
    return secret[:4] + "..." + secret[-4:] if len(secret) > 10 else "***"


def _safe_snippet(value: Any, *, limit: int = 280) -> dict[str, Any]:
    text = json.dumps(_redact_value(value), sort_keys=True, default=str)
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "preview": text[:limit],
        "truncated": len(text) > limit,
    }


def classify_tool_risk(tool_name: str, arguments: dict[str, Any] | None = None, *, source: str = "internal") -> str:
    name = str(tool_name or "").lower()
    args_text = json.dumps(arguments or {}, sort_keys=True, default=str).lower()
    if any(term in name for term in ("delete", "remove", "rm_", "drop", "shell", "desktop", "send", "write")):
        return "high"
    if any(term in args_text for term in ("password", "token", "secret", "credential", "private key")):
        return "high"
    if source not in {"internal", "builtin", "ghost"}:
        return "medium"
    if any(term in name for term in ("read", "search", "status", "list", "inspect")):
        return "low"
    return "medium"


def inspect_tool_output(output: Any, expected_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    text = json.dumps(output, sort_keys=True, default=str)
    violations: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            violations.append("secret_like_output")
            break
    for pattern in POISON_PATTERNS:
        if pattern.search(text):
            violations.append("prompt_injection_like_output")
            break
    if expected_schema:
        required = expected_schema.get("required")
        if isinstance(required, list) and isinstance(output, dict):
            missing = [str(key) for key in required if key not in output]
            if missing:
                violations.append("schema_missing:" + ",".join(missing[:5]))
        elif isinstance(required, list):
            violations.append("schema_type_mismatch")
    return {
        "ok": not violations,
        "violations": violations,
        "sanitized_output": _redact_value(output),
        "redacted": _redact_value(output) != output,
    }


def build_tool_trust_envelope(
    tool_name: str,
    *,
    arguments: dict[str, Any] | None = None,
    source: str = "internal",
    expected_schema: dict[str, Any] | None = None,
    output: Any | None = None,
) -> ToolTrustEnvelope:
    risk = classify_tool_risk(tool_name, arguments, source=source)
    source_trust = "trusted" if source in {"internal", "builtin", "ghost"} else "untrusted"
    inspection = inspect_tool_output(output if output is not None else {}, expected_schema or {})
    required_approval = risk in {"high", "critical"} or source_trust == "untrusted"
    return ToolTrustEnvelope(
        tool_name=tool_name,
        source=source,
        risk_level=risk,
        source_trust=source_trust,
        data_class="sensitive" if risk == "high" else "general",
        required_approval=required_approval,
        expected_schema=expected_schema or {},
        sanitized=bool(inspection["ok"]),
        violations=list(inspection["violations"]),
    )


class TrustRuntimeStore:
    """Persistent local storage for the Ghost trust runtime."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.trust_dir = self.state_dir / "trust_runtime"
        self.runs_dir = self.trust_dir / "runs"
        self.index_path = self.trust_dir / "run_index.json"
        self.approvals_path = self.trust_dir / "approvals.json"
        self.mcp_trust_path = self.trust_dir / "mcp_trust.json"
        self.eval_baseline_path = self.trust_dir / "trust_eval_baseline.json"
        self.eval_cases_path = self.trust_dir / "eval_cases.jsonl"
        self.trust_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run(
        self,
        objective: str,
        *,
        source: str = "console",
        agent_name: str = "ghost-chimera",
        ghost_path: str = "",
        model_provider: str = "",
        model_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = _stable_id(source, objective, _now(), length=20)
        run = DurableRun(
            run_id=run_id,
            objective=objective,
            source=source,
            agent_name=agent_name,
            ghost_path=ghost_path,
            model_provider=model_provider,
            model_name=model_name,
        )
        run_payload = run.to_dict()
        if metadata:
            run_payload["metadata"] = _redact_value(metadata)
        index = self._load_index()
        index[run_id] = run_payload
        self._save_index(index)
        self.record_step(
            run_id,
            step_type="run_created",
            status="ok",
            input_payload={"objective": objective, "source": source},
            idempotency_key=f"{run_id}:created",
        )
        return run_payload

    def record_step(
        self,
        run_id: str,
        *,
        step_type: str,
        status: str,
        input_payload: Any | None = None,
        output_payload: Any | None = None,
        inputs: Any | None = None,
        outputs: Any | None = None,
        policy_decision: dict[str, Any] | None = None,
        idempotency_key: str = "",
        retryable: bool = False,
        duration_ms: float = 0.0,
        error: str = "",
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self._find_step_by_idempotency(run_id, idempotency_key)
            if existing:
                return existing
        step_id = _stable_id(run_id, step_type, status, idempotency_key or _now(), length=18)
        record = RunStepRecord(
            run_id=run_id,
            step_id=step_id,
            step_type=step_type,
            status=status,
            input_ref=_safe_snippet(input_payload if input_payload is not None else (inputs or {})),
            output_ref=_safe_snippet(output_payload if output_payload is not None else (outputs or {})),
            policy_decision=_redact_value(policy_decision or {}),
            idempotency_key=idempotency_key,
            retryable=retryable,
            duration_ms=duration_ms,
            error=_redact_text(error)[:500],
        ).to_dict()
        record = self._with_record_hash(self._run_journal_path(run_id), record)
        self._append_jsonl(self._run_journal_path(run_id), record)
        self._touch_run(run_id, status=status, increment_step=True)
        return record

    def record_tool_call(
        self,
        run_id: str,
        *,
        step_id: str = "",
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        source: str = "internal",
        expected_schema: dict[str, Any] | None = None,
        envelope: ToolTrustEnvelope | None = None,
    ) -> dict[str, Any]:
        output = result or {}
        if envelope is None:
            envelope = build_tool_trust_envelope(
                tool_name,
                arguments=arguments or {},
                source=source,
                expected_schema=expected_schema,
                output=output,
            )
        step = self.record_step(
            run_id,
            step_type="tool_call",
            status="blocked" if envelope.violations else "ok",
            input_payload={"tool_name": tool_name, "arguments": arguments or {}, "source": source},
            output_payload=output,
            policy_decision=envelope.to_dict(),
            idempotency_key=f"{run_id}:tool:{tool_name}:{_stable_id(arguments or {})}",
            retryable=bool(envelope.violations),
        )
        call = ToolCallRecord(
            run_id=run_id,
            step_id=step_id or step["step_id"],
            tool_name=tool_name,
            arguments=arguments or {},
            result=output,
            envelope=envelope,
        ).to_dict()
        self._append_jsonl(self._run_tool_path(run_id), call)
        return call

    def create_approval(
        self,
        run_id: str,
        *,
        step_id: str = "",
        summary: str = "",
        reason: str = "",
        risk_level: str = "medium",
        requested_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = summary or reason
        approval_id = _stable_id(run_id, step_id, summary or _now(), length=18)
        checkpoint = ApprovalCheckpoint(
            approval_id=approval_id,
            run_id=run_id,
            step_id=step_id or "manual",
            summary=summary,
            risk_level=risk_level,
        ).to_dict()
        checkpoint["id"] = approval_id
        if requested_by:
            checkpoint["requested_by"] = requested_by
        if metadata:
            checkpoint["metadata"] = _redact_value(metadata)
        approvals = self._load_json(self.approvals_path, {})
        approvals[approval_id] = checkpoint
        self._write_json(self.approvals_path, approvals)
        self.record_step(
            run_id,
            step_type="approval_checkpoint",
            status="pending_approval",
            input_payload={"summary": summary, "risk_level": risk_level},
            output_payload={"approval_id": approval_id},
            policy_decision={"requires_human": True},
            idempotency_key=f"{run_id}:approval:{approval_id}",
        )
        self._touch_run(run_id, status="pending_approval")
        return checkpoint

    def resolve_approval(self, approval_id: str, decision: str, *, reviewer: str = "operator") -> dict[str, Any]:
        decision = decision.strip().lower()
        if decision not in {"approved", "denied"}:
            raise ValueError("decision must be approved or denied")
        approvals = self._load_json(self.approvals_path, {})
        checkpoint = approvals.get(approval_id)
        if not isinstance(checkpoint, dict):
            raise KeyError(approval_id)
        if checkpoint.get("status") != "pending":
            return {"ok": False, "error": "Approval checkpoint is already resolved.", "approval": _redact_value(checkpoint)}
        checkpoint["status"] = "resolved"
        checkpoint["decision"] = decision
        checkpoint["reviewer"] = reviewer
        checkpoint["resolved_at"] = _now()
        approvals[approval_id] = checkpoint
        self._write_json(self.approvals_path, approvals)
        self.record_step(
            str(checkpoint["run_id"]),
            step_type="approval_resolved",
            status=decision,
            input_payload={"approval_id": approval_id},
            output_payload=checkpoint,
            idempotency_key=f"{checkpoint['run_id']}:approval_resolved:{approval_id}",
        )
        self._touch_run(str(checkpoint["run_id"]), status="resumable" if decision == "approved" else "denied")
        return {"ok": True, "approval": _redact_value(checkpoint)}

    def resume_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run.get("ok"):
            return run
        pending = [item for item in run.get("approvals", []) if item.get("status") == "pending"]
        if pending:
            return {
                "ok": False,
                "error": "Run is waiting for approval before it can resume.",
                "pending_approvals": pending,
                "run": run["run"],
            }
        status = str(run["run"].get("status") or "")
        steps = run.get("steps", [])
        last_step = steps[-1] if steps else {}
        if status not in STATUS_RESUMABLE and last_step.get("status") not in STATUS_RESUMABLE and status != "resumable":
            return {"ok": False, "error": "Run is not at a safe resume boundary.", "run": run["run"]}
        token = RunResumeToken(
            run_id=run_id,
            resume_from_step=str(last_step.get("step_id") or "start"),
            reason=status or str(last_step.get("status") or "manual"),
            token=_stable_id(run_id, last_step.get("step_id"), _now(), length=32),
        )
        self.record_step(
            run_id,
            step_type="run_resumed",
            status="resumed",
            input_payload=token.to_dict(),
            output_payload={"resume_boundary": token.resume_from_step},
            idempotency_key=f"{run_id}:resume:{token.resume_from_step}:{int(token.created_at)}",
        )
        self._touch_run(run_id, status="running")
        return {"ok": True, "resume": token.to_dict(), "run": self.get_run(run_id).get("run", {})}

    def list_runs(self, *, limit: int = 50) -> dict[str, Any]:
        index = self._load_index()
        runs = sorted(index.values(), key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        return {"ok": True, "runs": [_redact_value(item) for item in runs[: max(1, min(limit, 200))]], "count": len(runs)}

    def get_run(self, run_id: str) -> dict[str, Any]:
        index = self._load_index()
        run = index.get(run_id)
        if not isinstance(run, dict):
            return {"ok": False, "error": "Run not found."}
        steps = self._read_jsonl(self._run_journal_path(run_id))
        tools = self._read_jsonl(self._run_tool_path(run_id))
        approvals = [item for item in self.pending_approvals(include_resolved=True)["approvals"] if item.get("run_id") == run_id]
        return {"ok": True, "run": _redact_value(run), "steps": steps, "tool_calls": tools, "approvals": approvals}

    def pending_approvals(self, *, include_resolved: bool = False) -> dict[str, Any]:
        approvals = self._load_json(self.approvals_path, {})
        items = [
            _redact_value({**item, "id": item.get("id") or item.get("approval_id", "")})
            for item in approvals.values()
            if isinstance(item, dict) and (include_resolved or item.get("status") == "pending")
        ]
        items.sort(key=lambda item: float(item.get("requested_at") or 0), reverse=True)
        return {"ok": True, "approvals": items, "count": len(items)}

    def promote_run_to_eval_case(self, run_id: str, *, label: str = "", severity: str = "P2") -> dict[str, Any]:
        detail = self.get_run(run_id)
        if not detail.get("ok"):
            return detail
        run = detail["run"]
        steps = detail.get("steps", [])
        blocked = [step for step in steps if step.get("status") in {"blocked", "denied"}]
        severity = severity.upper() if severity.upper() in {"P0", "P1", "P2", "P3"} else "P2"
        label = label.strip() or str(run.get("objective") or run_id)[:80]
        case = TrustEvalCase(
            case_id=_stable_id("trust_eval", run_id, label, severity, length=20),
            source="trust_eval_case",
            label=label,
            severity=severity,
            run_id=run_id,
            expected_status="blocked" if blocked else "ok",
            metadata={
                "objective_ref": _safe_snippet(run.get("objective", "")),
                "source": run.get("source", ""),
                "step_count": len(steps),
                "blocked_step_count": len(blocked),
                "run_status": run.get("status", ""),
            },
        ).to_dict()
        existing = {item.get("case_id"): item for item in self._read_jsonl(self.eval_cases_path)}
        existing[case["case_id"]] = case
        self._write_jsonl(self.eval_cases_path, sorted(existing.values(), key=lambda item: str(item.get("case_id"))))
        return {"ok": True, "case": case}

    def list_eval_cases(self, *, limit: int = 100) -> dict[str, Any]:
        cases = self._read_jsonl(self.eval_cases_path)
        cases.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
        limit = max(1, min(int(limit), 500))
        return {"ok": True, "cases": _redact_value(cases[:limit]), "count": len(cases)}

    def verify_run_integrity(self, run_id: str) -> dict[str, Any]:
        previous_hash = ""
        steps = self._read_jsonl(self._run_journal_path(run_id))
        for index, step in enumerate(steps):
            expected_previous = str(step.get("previous_hash") or "")
            if expected_previous != previous_hash:
                return {
                    "ok": False,
                    "verified": False,
                    "error": "previous_hash mismatch",
                    "index": index,
                    "step_id": step.get("step_id", ""),
                }
            recorded_hash = str(step.get("record_hash") or "")
            payload = {key: value for key, value in step.items() if key != "record_hash"}
            actual_hash = _hash_payload(payload)
            if recorded_hash != actual_hash:
                return {
                    "ok": False,
                    "verified": False,
                    "error": "record_hash mismatch",
                    "index": index,
                    "step_id": step.get("step_id", ""),
                }
            previous_hash = recorded_hash
        return {"ok": True, "verified": True, "run_id": run_id, "step_count": len(steps), "latest_hash": previous_hash}

    def simulate_replay(
        self,
        run_id: str,
        *,
        mode: str = "same_policy",
        model_provider: str = "",
        disabled_tools: list[str] | None = None,
        stricter_policy: bool = False,
    ) -> dict[str, Any]:
        """Preview replay impact without executing tools or model calls."""

        payload = self.get_run(run_id)
        if not payload.get("ok"):
            return payload
        mode = str(mode or "same_policy").strip().lower()
        if mode not in {"same_policy", "stricter_policy", "try_model", "disable_tools"}:
            return {"ok": False, "error": "Unsupported replay simulation mode."}
        disabled = {str(tool).strip().lower() for tool in (disabled_tools or []) if str(tool).strip()}
        run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
        tool_calls = payload.get("tool_calls") if isinstance(payload.get("tool_calls"), list) else []
        approvals = payload.get("approvals") if isinstance(payload.get("approvals"), list) else []
        blocked_steps = [step for step in steps if str(step.get("status") or "") in {"blocked", "denied", "error"}]
        pending_approvals = [item for item in approvals if str(item.get("status") or "") == "pending"]
        high_risk_tools = [
            call
            for call in tool_calls
            if str(((call.get("envelope") or {}) if isinstance(call, dict) else {}).get("risk_level") or "") in {"high", "critical"}
        ]
        disabled_hits = [call for call in tool_calls if str(call.get("tool_name") or "").strip().lower() in disabled]
        replay_steps: list[dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            strict = bool(stricter_policy or mode == "stricter_policy")
            replay_steps.append(
                {
                    "step_id": step.get("step_id"),
                    "step_type": step.get("step_type"),
                    "original_status": step.get("status"),
                    "replay_status": "needs_approval"
                    if strict and str(step.get("step_type") or "") in {"tool_call", "execution_result"}
                    else step.get("status"),
                    "policy_preview": "stricter approval boundary" if strict else "unchanged",
                }
            )
        warnings: list[str] = []
        if pending_approvals:
            warnings.append("Replay starts behind unresolved approval checkpoints.")
        if blocked_steps:
            warnings.append("Original run contains blocked, denied, or error steps.")
        if high_risk_tools and (mode == "stricter_policy" or stricter_policy):
            warnings.append("Stricter policy would require approval before high-risk tool execution.")
        if disabled_hits:
            warnings.append("Simulation disables tools used by the original run.")
        if mode == "try_model" and model_provider and model_provider != run.get("model_provider"):
            warnings.append("Model change may alter cost, latency, and output quality.")
        projected_status = "blocked_preview" if pending_approvals or disabled_hits else "replayable_preview"
        return {
            "ok": True,
            "simulation": {
                "run_id": run_id,
                "mode": mode,
                "projected_status": projected_status,
                "execution_performed": False,
                "mutation_performed": False,
                "model_provider": model_provider or run.get("model_provider", ""),
                "disabled_tools": sorted(disabled),
                "stricter_policy": bool(stricter_policy or mode == "stricter_policy"),
                "step_count": len(steps),
                "tool_call_count": len(tool_calls),
                "approval_count": len(approvals),
                "blocked_step_count": len(blocked_steps),
                "warnings": warnings,
                "steps": replay_steps[:100],
            },
        }

    def export_trace(self, run_id: str) -> dict[str, Any]:
        if run_id == "latest":
            runs = self.list_runs(limit=1)["runs"]
            if not runs:
                return {"ok": False, "error": "No runs available."}
            run_id = str(runs[0]["run_id"])
        payload = self.get_run(run_id)
        if not payload.get("ok"):
            return payload
        run = payload["run"]
        spans: list[dict[str, Any]] = []
        for step in payload.get("steps", []):
            spans.append(
                {
                    "name": f"ghost.{step.get('step_type', 'step')}",
                    "span_id": step.get("step_id", ""),
                    "parent_id": run_id,
                    "start_time_unix_nano": int(float(step.get("timestamp") or 0) * 1_000_000_000),
                    "duration_ms": step.get("duration_ms", 0.0),
                    "status": step.get("status", "unknown"),
                    "attributes": {
                        "gen_ai.operation.name": step.get("step_type", "workflow"),
                        "gen_ai.agent.name": run.get("agent_name", "ghost-chimera"),
                        "gen_ai.request.model": run.get("model_name", ""),
                        "gen_ai.provider.name": run.get("model_provider", ""),
                        "ghost.run_id": run_id,
                        "ghost.source": run.get("source", ""),
                        "ghost.redacted": True,
                        "ghost.idempotency_key": step.get("idempotency_key", ""),
                    },
                    "error.type": step.get("error", "")[:120],
                }
            )
        trace_bundle = {
            "run_id": run_id,
            "resource": {
                "gen_ai.agent.name": run.get("agent_name", "ghost-chimera"),
                "gen_ai.provider.name": run.get("model_provider", ""),
                "gen_ai.request.model": run.get("model_name", ""),
                "ghost.source": run.get("source", ""),
            },
            "spans": _redact_value(spans),
        }
        return {
            "ok": True,
            "schema": "ghost-trace-export/v1",
            "otel_compatible": True,
            "raw_prompts_included": False,
            "hidden_reasoning_included": False,
            "bundle": trace_bundle,
            "run": run,
            "spans": _redact_value(spans),
        }

    def trust_status(self) -> dict[str, Any]:
        runs = self.list_runs(limit=200)["runs"]
        approvals = self.pending_approvals()["approvals"]
        mcp = self.mcp_trust_list()
        latest_baseline = self._load_json(self.eval_baseline_path, {})
        baseline_created_at = float(latest_baseline.get("created_at") or 0.0) if latest_baseline else 0.0
        baseline_age_seconds = (_now() - baseline_created_at) if baseline_created_at else None
        baseline_is_stale = baseline_age_seconds is None or baseline_age_seconds > TRUST_BASELINE_MAX_AGE_SECONDS
        baseline_p0_failures = int(latest_baseline.get("p0_failures") or 0) if latest_baseline else 0
        if not latest_baseline:
            baseline_status = "missing"
        elif baseline_p0_failures:
            baseline_status = "failing"
        elif baseline_is_stale:
            baseline_status = "stale"
        else:
            baseline_status = "fresh"
        high_risk_unreviewed = [
            item for item in mcp.get("servers", []) if item.get("status") not in {"approved", "revoked"} and item.get("risk_ceiling") in {"high", "critical"}
        ]
        blocked_steps = 0
        for run in runs[:50]:
            detail = self.get_run(str(run.get("run_id")))
            blocked_steps += sum(1 for step in detail.get("steps", []) if step.get("status") == "blocked")
        ready = not approvals and not high_risk_unreviewed and blocked_steps == 0 and baseline_status == "fresh"
        return {
            "ok": True,
            "ready": ready,
            "journal": {"ok": True, "state_dir": str(self.trust_dir), "append_only": True},
            "runs": {"total": len(runs), "latest": runs[:5]},
            "approvals": {"pending": len(approvals)},
            "counts": {
                "runs": len(runs),
                "pending_approvals": len(approvals),
                "mcp_servers": len(mcp.get("servers", [])),
                "high_risk_unreviewed_mcp": len(high_risk_unreviewed),
                "blocked_steps_recent": blocked_steps,
                "has_eval_baseline": bool(latest_baseline),
                "baseline_p0_failures": baseline_p0_failures,
            },
            "production_readiness": {"status": "ready" if ready else "review"},
            "trace_health": {"status": "local-json", "raw_prompts_exported": False, "secrets_exported": False},
            "latest_runs": runs[:5],
            "mcp_trust": mcp,
            "eval_baseline": _redact_value(latest_baseline),
            "eval_baseline_status": {
                "status": baseline_status,
                "age_seconds": round(baseline_age_seconds, 3) if baseline_age_seconds is not None else None,
                "max_age_seconds": TRUST_BASELINE_MAX_AGE_SECONDS,
                "p0_failures": baseline_p0_failures,
                "case_count": int(latest_baseline.get("case_count") or 0) if latest_baseline else 0,
            },
            "warnings": self._trust_warnings(
                approvals,
                high_risk_unreviewed,
                blocked_steps,
                latest_baseline,
                baseline_status=baseline_status,
                baseline_age_seconds=baseline_age_seconds,
                baseline_p0_failures=baseline_p0_failures,
            ),
        }

    def mcp_trust_list(self) -> dict[str, Any]:
        data = self._load_json(self.mcp_trust_path, {"servers": {}})
        servers = list(data.get("servers", {}).values()) if isinstance(data.get("servers"), dict) else []
        servers.sort(key=lambda item: str(item.get("server_id") or ""))
        return {"ok": True, "servers": _redact_value(servers)}

    def mcp_trust_set(self, server_id: str, status: str, *, risk_ceiling: str = "medium", tools: list[str] | None = None) -> dict[str, Any]:
        server_id = server_id.strip()
        if not server_id:
            raise ValueError("server_id is required")
        if status not in {"approved", "revoked", "reviewed"}:
            raise ValueError("status must be approved, revoked, or reviewed")
        if risk_ceiling not in RISK_ORDER:
            risk_ceiling = "medium"
        data = self._load_json(self.mcp_trust_path, {"servers": {}})
        servers = data.setdefault("servers", {})
        servers[server_id] = {
            "server_id": server_id,
            "status": status,
            "risk_ceiling": risk_ceiling,
            "reviewed_tools": sorted({str(tool) for tool in (tools or []) if str(tool).strip()}),
            "last_health_check": _now(),
            "updated_at": _now(),
        }
        self._write_json(self.mcp_trust_path, data)
        return {"ok": True, "server": _redact_value(servers[server_id])}

    def is_mcp_tool_allowed(self, server_id: str, tool_name: str, risk_level: str) -> bool:
        data = self._load_json(self.mcp_trust_path, {"servers": {}})
        server = data.get("servers", {}).get(server_id) if isinstance(data.get("servers"), dict) else None
        if not isinstance(server, dict) or server.get("status") != "approved":
            return False
        ceiling = str(server.get("risk_ceiling") or "medium")
        if RISK_ORDER.get(risk_level, 3) > RISK_ORDER.get(ceiling, 2):
            return False
        reviewed = set(server.get("reviewed_tools") or [])
        return not reviewed or tool_name in reviewed

    def eval_baseline(self) -> dict[str, Any]:
        runs = self.list_runs(limit=200)["runs"]
        approvals = self.pending_approvals(include_resolved=True)["approvals"]
        mcp = self.mcp_trust_list()["servers"]
        promoted_cases = self.list_eval_cases(limit=500)["cases"]
        cases: list[dict[str, Any]] = []
        for promoted in promoted_cases:
            cases.append(
                {
                    "case_id": promoted.get("case_id"),
                    "source": "trust_eval_case",
                    "ok": promoted.get("expected_status") != "blocked",
                    "status": promoted.get("expected_status"),
                    "severity": promoted.get("severity"),
                    "label": promoted.get("label"),
                    "run_id": promoted.get("run_id"),
                }
            )
        for run in runs[:25]:
            detail = self.get_run(str(run.get("run_id")))
            steps = detail.get("steps", [])
            violations = [step for step in steps if step.get("status") in {"blocked", "denied"}]
            cases.append(
                {
                    "case_id": f"run:{run.get('run_id')}",
                    "source": "run_journal",
                    "ok": not violations,
                    "status": run.get("status"),
                    "violation_count": len(violations),
                }
            )
        for approval in approvals[:25]:
            cases.append(
                {
                    "case_id": f"approval:{approval.get('approval_id')}",
                    "source": "approval_checkpoint",
                    "ok": approval.get("status") == "resolved",
                    "status": approval.get("status"),
                }
            )
        for server in mcp:
            cases.append(
                {
                    "case_id": f"mcp:{server.get('server_id')}",
                    "source": "mcp_trust",
                    "ok": server.get("status") == "approved",
                    "status": server.get("status"),
                    "risk_ceiling": server.get("risk_ceiling"),
                }
            )
        total = len(cases)
        passed = sum(1 for item in cases if item.get("ok"))
        baseline = {
            "ok": True,
            "created_at": _now(),
            "case_count": total,
            "passed": passed,
            "failed": total - passed,
            "p0_failures": total - passed,
            "trust_score": round((passed / total) if total else 1.0, 3),
            "cases": cases,
        }
        self._write_json(self.eval_baseline_path, baseline)
        return _redact_value(baseline)

    def eval_compare(self) -> dict[str, Any]:
        previous = self._load_json(self.eval_baseline_path, {})
        current = self.eval_baseline()
        return {
            "ok": True,
            "previous": _redact_value(previous),
            "current": current,
            "p0_failures": int(current.get("p0_failures") or 0),
            "delta": round(float(current.get("trust_score", 0.0)) - float(previous.get("trust_score", 0.0)), 3)
            if previous
            else 0.0,
        }

    def _trust_warnings(
        self,
        approvals: list[dict[str, Any]],
        high_risk_unreviewed: list[dict[str, Any]],
        blocked_steps: int,
        latest_baseline: dict[str, Any],
        *,
        baseline_status: str = "",
        baseline_age_seconds: float | None = None,
        baseline_p0_failures: int = 0,
    ) -> list[str]:
        warnings: list[str] = []
        if approvals:
            warnings.append("Resolve pending trust approvals before production operation.")
        if high_risk_unreviewed:
            warnings.append("Review or revoke high-risk MCP servers.")
        if blocked_steps:
            warnings.append("Recent runs contain blocked or denied trust steps.")
        if not latest_baseline:
            warnings.append("Create a trust eval baseline before release.")
        elif baseline_status == "stale":
            days = round((baseline_age_seconds or 0.0) / 86400, 1)
            warnings.append(f"Refresh the trust eval baseline; latest baseline is {days} days old.")
        elif baseline_status == "failing" or baseline_p0_failures:
            warnings.append("Resolve trust eval P0 failures before production operation.")
        return warnings

    def _load_index(self) -> dict[str, Any]:
        return self._load_json(self.index_path, {})

    def _save_index(self, index: dict[str, Any]) -> None:
        self._write_json(self.index_path, index)

    def _touch_run(self, run_id: str, *, status: str, increment_step: bool = False) -> None:
        index = self._load_index()
        run = index.get(run_id)
        if not isinstance(run, dict):
            return
        run["updated_at"] = _now()
        if status:
            run["status"] = status
        if increment_step:
            run["step_count"] = int(run.get("step_count") or 0) + 1
        approvals = self.pending_approvals()["approvals"]
        run["pending_approval_count"] = sum(1 for item in approvals if item.get("run_id") == run_id)
        index[run_id] = run
        self._save_index(index)

    def _run_journal_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.jsonl"

    def _run_tool_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.tools.jsonl"

    def _find_step_by_idempotency(self, run_id: str, idempotency_key: str) -> dict[str, Any] | None:
        for step in self._read_jsonl(self._run_journal_path(run_id)):
            if step.get("idempotency_key") == idempotency_key:
                return step
        return None

    def _with_record_hash(self, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        previous_hash = ""
        existing = self._read_jsonl(path)
        if existing:
            previous_hash = str(existing[-1].get("record_hash") or "")
        record = {**payload, "previous_hash": previous_hash}
        record["record_hash"] = _hash_payload(record)
        return record

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_redact_value(payload), sort_keys=True) + "\n")

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            "".join(json.dumps(_redact_value(row), sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(_redact_value(data))
        return rows

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return data if isinstance(data, type(default)) else default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(_redact_value(payload), indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


__all__ = [
    "ApprovalCheckpoint",
    "DurableRun",
    "RunResumeToken",
    "RunStepRecord",
    "ToolCallRecord",
    "ToolTrustEnvelope",
    "TrustEvalCase",
    "TrustRuntimeStore",
    "build_tool_trust_envelope",
    "classify_tool_risk",
    "inspect_tool_output",
]
