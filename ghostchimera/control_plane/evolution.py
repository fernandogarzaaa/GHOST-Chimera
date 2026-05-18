"""Operator UX and consent-gated self-evolution state helpers."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LEARNING_SOURCE_TYPES = {
    "github_repo",
    "docs_url",
    "local_folder",
    "uploaded_text",
    "mcp_server",
    "model_catalog",
    "manual_note",
}
SOURCE_SCOPES = {"path-specific", "role-specific", "global"}
CONSENT_STATUSES = {"pending", "approved", "denied", "revoked"}
RISK_LEVELS = {"low", "medium", "high"}
EVOLUTION_STATUSES = {"discovered", "reviewed", "approved", "indexed", "evaluated", "promoted", "active", "revoked", "rejected"}
PROMOTABLE_STATUSES = {"reviewed", "approved", "evaluated"}
SECRET_MARKERS = ("token", "secret", "api_key", "apikey", "password", "credential", "authorization")


@dataclass
class LearningSource:
    id: str
    source_type: str
    label: str
    uri: str = ""
    scope: str = "global"
    consent_status: str = "pending"
    risk_level: str = "low"
    last_refresh: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


@dataclass
class EvolutionCandidate:
    id: str
    candidate_type: str
    title: str
    status: str = "discovered"
    source_id: str = ""
    required_permissions: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    reviewed_at: float = 0.0
    promoted_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "operator_evolution_state.json"


def _timeline_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "operator_timeline.jsonl"


def _now() -> float:
    return time.time()


def _stable_id(*parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts if part is not None)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_MARKERS):
                redacted[str(key)] = "[redacted]" if item else ""
            else:
                redacted[str(key)] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _load_raw_state(state_dir: str | Path) -> dict[str, Any]:
    path = _state_path(state_dir)
    if not path.exists():
        return {"sources": {}, "candidates": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": {}, "candidates": {}}
    if not isinstance(data, dict):
        return {"sources": {}, "candidates": {}}
    data.setdefault("sources", {})
    data.setdefault("candidates", {})
    if not isinstance(data["sources"], dict):
        data["sources"] = {}
    if not isinstance(data["candidates"], dict):
        data["candidates"] = {}
    return data


def _save_raw_state(state_dir: str | Path, data: dict[str, Any]) -> None:
    path = _state_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_redact_value(data), indent=2, sort_keys=True), encoding="utf-8")


def list_sources(state_dir: str | Path) -> list[dict[str, Any]]:
    data = _load_raw_state(state_dir)
    return [_redact_value(item) for item in data.get("sources", {}).values()]


def list_candidates(state_dir: str | Path) -> list[dict[str, Any]]:
    data = _load_raw_state(state_dir)
    return [_redact_value(item) for item in data.get("candidates", {}).values()]


def create_learning_source(state_dir: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    source_type = str(payload.get("source_type") or "manual_note").strip().lower()
    if source_type not in LEARNING_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type: {source_type}")
    label = str(payload.get("label") or payload.get("uri") or source_type).strip()
    if not label:
        raise ValueError("label is required")
    uri = str(payload.get("uri") or "").strip()
    scope = str(payload.get("scope") or "global").strip().lower()
    if scope not in SOURCE_SCOPES:
        scope = "global"
    consent_status = str(payload.get("consent_status") or "pending").strip().lower()
    if consent_status not in CONSENT_STATUSES:
        consent_status = "pending"
    risk_level = str(payload.get("risk_level") or "low").strip().lower()
    if risk_level not in RISK_LEVELS:
        risk_level = "low"
    provenance = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    source = LearningSource(
        id=str(payload.get("id") or _stable_id(source_type, label, uri)),
        source_type=source_type,
        label=label,
        uri=uri,
        scope=scope,
        consent_status=consent_status,
        risk_level=risk_level,
        last_refresh=float(payload.get("last_refresh") or _now()),
        provenance=provenance,
        notes=str(payload.get("notes") or ""),
    )
    data = _load_raw_state(state_dir)
    data["sources"][source.id] = source.to_dict()
    _save_raw_state(state_dir, data)
    return source.to_dict()


def set_source_consent(state_dir: str | Path, source_id: str, consent_status: str) -> dict[str, Any]:
    status = consent_status.strip().lower()
    if status not in {"approved", "revoked", "denied", "pending"}:
        raise ValueError(f"Unsupported consent status: {consent_status}")
    data = _load_raw_state(state_dir)
    source = data["sources"].get(source_id)
    if not isinstance(source, dict):
        raise KeyError(source_id)
    source["consent_status"] = status
    source["last_refresh"] = _now()
    data["sources"][source_id] = source
    _save_raw_state(state_dir, data)
    return _redact_value(source)


def upsert_candidate(state_dir: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    candidate_type = str(payload.get("candidate_type") or "config_improvement").strip().lower()
    title = str(payload.get("title") or candidate_type.replace("_", " ").title()).strip()
    if not title:
        raise ValueError("title is required")
    status = str(payload.get("status") or "discovered").strip().lower()
    if status not in EVOLUTION_STATUSES:
        status = "discovered"
    candidate = EvolutionCandidate(
        id=str(payload.get("id") or _stable_id(candidate_type, title, str(payload.get("source_id") or ""))),
        candidate_type=candidate_type,
        title=title,
        status=status,
        source_id=str(payload.get("source_id") or ""),
        required_permissions=[str(item) for item in payload.get("required_permissions") or []],
        safety_notes=[str(item) for item in payload.get("safety_notes") or []],
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )
    data = _load_raw_state(state_dir)
    data["candidates"][candidate.id] = candidate.to_dict()
    _save_raw_state(state_dir, data)
    return candidate.to_dict()


def set_candidate_status(state_dir: str | Path, candidate_id: str, status: str, *, notes: str = "") -> dict[str, Any]:
    next_status = status.strip().lower()
    if next_status not in EVOLUTION_STATUSES:
        raise ValueError(f"Unsupported candidate status: {status}")
    data = _load_raw_state(state_dir)
    candidate = data["candidates"].get(candidate_id)
    if not isinstance(candidate, dict):
        raise KeyError(candidate_id)
    current = str(candidate.get("status") or "discovered")
    if next_status in {"promoted", "active"} and current not in PROMOTABLE_STATUSES:
        raise ValueError("Candidate must be reviewed or approved before promotion")
    candidate["status"] = next_status
    if notes:
        candidate.setdefault("safety_notes", [])
        if isinstance(candidate["safety_notes"], list):
            candidate["safety_notes"].append(notes)
    if next_status in {"reviewed", "approved", "rejected"}:
        candidate["reviewed_at"] = _now()
    if next_status in {"promoted", "active"}:
        candidate["promoted_at"] = _now()
    data["candidates"][candidate_id] = candidate
    _save_raw_state(state_dir, data)
    return _redact_value(candidate)


def record_timeline_event(state_dir: str | Path, event_type: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "id": _stable_id(event_type, str(_now()), json.dumps(detail or {}, sort_keys=True, default=str)),
        "timestamp": _now(),
        "event_type": event_type,
        "detail": _redact_value(detail or {}),
    }
    path = _timeline_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def read_timeline(state_dir: str | Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = _timeline_path(state_dir)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, 200)) :]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(_redact_value(data))
    return events


def readiness_summary(
    *,
    config: dict[str, Any],
    active_path: dict[str, Any] | None,
    rag_status: dict[str, Any] | None,
    mcp_status: dict[str, Any] | None,
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    approved_sources = [source for source in sources if source.get("consent_status") == "approved"]
    pending_candidates = [candidate for candidate in candidates if candidate.get("status") in {"discovered", "reviewed"}]
    warnings: list[str] = []
    if not active_path or not active_path.get("profile_id"):
        warnings.append("Choose and save a Ghost Path.")
    if not model.get("provider"):
        warnings.append("Configure a model provider.")
    if model.get("provider") in {"openai", "anthropic", "openrouter", "vultr", "huggingface"} and not model.get("api_key"):
        warnings.append("Add the provider API key in Config before live model runs.")
    if not approved_sources:
        warnings.append("Approve at least one learning source before Self-Evolution.")
    return {
        "ok": True,
        "cards": [
            {"id": "path", "label": "Ghost Path", "status": "ready" if active_path and active_path.get("profile_id") else "needs_setup", "action": "path"},
            {"id": "model", "label": "Model", "status": "ready" if model.get("provider") else "needs_setup", "action": "config"},
            {"id": "rag", "label": "RAG + MiniMind", "status": "ready" if rag_status and rag_status.get("enabled") else "guarded", "action": "rag-builder"},
            {"id": "mcp", "label": "MCP", "status": "enabled" if mcp_status and mcp_status.get("enabled") else "review", "action": "mcp"},
            {"id": "evolution", "label": "Self-Evolution", "status": "ready" if approved_sources else "needs_approval", "action": "evolution"},
            {"id": "skills", "label": "Skills", "status": "review" if pending_candidates else "ready", "action": "skills"},
        ],
        "warnings": warnings,
        "counts": {
            "learning_sources": len(sources),
            "approved_sources": len(approved_sources),
            "candidates": len(candidates),
            "pending_candidates": len(pending_candidates),
        },
        "secret_policy": {"secrets_are_write_only": True, "raw_secret_values_returned": False},
    }
