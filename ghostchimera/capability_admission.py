"""Local capability admission registry for Ghost Chimera.

The admission registry is the review gate for models, MCP servers, skills,
connectors, local model candidates, remote channels, and self-evolution
capabilities before they become active runtime inputs.
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
RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
ADMISSION_STATUSES = {
    "discovered",
    "inspected",
    "review_required",
    "approved",
    "active",
    "quarantined",
    "revoked",
}
ALLOWED_TRANSITIONS = {
    "discovered": {"inspected", "revoked", "quarantined"},
    "inspected": {"review_required", "approved", "revoked", "quarantined"},
    "review_required": {"approved", "revoked", "quarantined"},
    "approved": {"active", "revoked", "quarantined"},
    "active": {"revoked", "quarantined"},
    "quarantined": {"revoked"},
    "revoked": set(),
}


@dataclass(frozen=True)
class CapabilityAdmissionRecord:
    id: str
    capability_kind: str
    name: str
    source: str = "local"
    status: str = "discovered"
    risk_level: str = "medium"
    risk_ceiling: str = "medium"
    requested_permissions: list[str] = field(default_factory=list)
    approved_permissions: list[str] = field(default_factory=list)
    trust_class: str = "unreviewed"
    inspection: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    reviewer: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return _redact_value(asdict(self))


def _now() -> float:
    return time.time()


def _stable_id(*parts: object, length: int = 18) -> str:
    raw = "|".join(str(part).strip().lower() for part in parts if part is not None)
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


def _normalize_risk(risk: str) -> str:
    risk = str(risk or "").strip().lower()
    return risk if risk in RISK_ORDER else "medium"


class CapabilityAdmissionStore:
    """Persistent local admission registry."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.admission_dir = self.state_dir / "capability_admission"
        self.records_path = self.admission_dir / "records.json"
        self.admission_dir.mkdir(parents=True, exist_ok=True)

    def create_record(
        self,
        *,
        capability_kind: str,
        name: str,
        source: str = "local",
        risk_level: str = "medium",
        risk_ceiling: str = "medium",
        requested_permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inspection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        capability_kind = str(capability_kind or "").strip().lower()
        name = str(name or "").strip()
        if not capability_kind:
            raise ValueError("capability_kind is required")
        if not name:
            raise ValueError("name is required")
        record_id = _stable_id(capability_kind, source, name)
        records = self._load_records()
        if record_id in records:
            return {"ok": False, "error": "Capability admission record already exists.", "record": _redact_value(records[record_id])}
        record = CapabilityAdmissionRecord(
            id=record_id,
            capability_kind=capability_kind,
            name=name,
            source=str(source or "local").strip() or "local",
            risk_level=_normalize_risk(risk_level),
            risk_ceiling=_normalize_risk(risk_ceiling),
            requested_permissions=sorted({str(item) for item in (requested_permissions or []) if str(item).strip()}),
            inspection=_redact_value(inspection or {}),
            metadata=_redact_value(metadata or {}),
        ).to_dict()
        records[record_id] = record
        self._save_records(records)
        return {"ok": True, "record": record}

    def register_or_update(
        self,
        *,
        capability_kind: str,
        name: str,
        source: str = "local",
        risk_level: str = "medium",
        risk_ceiling: str = "medium",
        requested_permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inspection: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_id = _stable_id(capability_kind, source, name)
        records = self._load_records()
        if record_id not in records:
            return self.create_record(
                capability_kind=capability_kind,
                name=name,
                source=source,
                risk_level=risk_level,
                risk_ceiling=risk_ceiling,
                requested_permissions=requested_permissions,
                metadata=metadata,
                inspection=inspection,
            )
        record = dict(records[record_id])
        record["risk_level"] = _normalize_risk(risk_level or record.get("risk_level", "medium"))
        record["risk_ceiling"] = _normalize_risk(risk_ceiling or record.get("risk_ceiling", "medium"))
        record["requested_permissions"] = sorted(
            {str(item) for item in (requested_permissions or record.get("requested_permissions") or []) if str(item).strip()}
        )
        record["metadata"] = _redact_value({**(record.get("metadata") or {}), **(metadata or {})})
        record["inspection"] = _redact_value({**(record.get("inspection") or {}), **(inspection or {})})
        record["updated_at"] = _now()
        records[record_id] = record
        self._save_records(records)
        return {"ok": True, "record": _redact_value(record)}

    def list_records(self, *, status: str = "", capability_kind: str = "", limit: int = 200) -> dict[str, Any]:
        records = list(self._load_records().values())
        if status:
            records = [record for record in records if record.get("status") == status]
        if capability_kind:
            records = [record for record in records if record.get("capability_kind") == capability_kind]
        records.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
        limit = max(1, min(int(limit), 500))
        return {"ok": True, "records": _redact_value(records[:limit]), "count": len(records)}

    def get_record(self, record_id: str) -> dict[str, Any]:
        record = self._load_records().get(str(record_id or "").strip())
        if not isinstance(record, dict):
            return {"ok": False, "error": "Capability admission record not found."}
        return {"ok": True, "record": _redact_value(record)}

    def transition(self, record_id: str, status: str, *, reviewer: str = "", reason: str = "") -> dict[str, Any]:
        status = str(status or "").strip().lower()
        if status not in ADMISSION_STATUSES:
            return {"ok": False, "error": f"Unsupported admission status: {status}"}
        records = self._load_records()
        record = records.get(str(record_id or "").strip())
        if not isinstance(record, dict):
            return {"ok": False, "error": "Capability admission record not found."}
        current = str(record.get("status") or "discovered")
        if status == current:
            return {"ok": True, "record": _redact_value(record)}
        if status not in ALLOWED_TRANSITIONS.get(current, set()):
            return {"ok": False, "error": f"Invalid transition: {current} -> {status}", "record": _redact_value(record)}
        record["status"] = status
        record["reviewer"] = str(reviewer or record.get("reviewer") or "")
        record["reason"] = str(reason or record.get("reason") or "")
        record["updated_at"] = _now()
        if status in {"approved", "active"}:
            requested = [str(item) for item in record.get("requested_permissions") or [] if str(item).strip()]
            record["approved_permissions"] = sorted(set(record.get("approved_permissions") or requested))
            record["trust_class"] = "reviewed"
        if status in {"revoked", "quarantined"}:
            record["trust_class"] = status
        records[str(record_id).strip()] = record
        self._save_records(records)
        return {"ok": True, "record": _redact_value(record)}

    def summary(self) -> dict[str, Any]:
        records = list(self._load_records().values())
        unreviewed_high = [
            record
            for record in records
            if record.get("status") not in {"approved", "active", "revoked", "quarantined"}
            and RISK_ORDER.get(str(record.get("risk_level") or "medium"), 2) >= RISK_ORDER["high"]
        ]
        active = [record for record in records if record.get("status") == "active"]
        quarantined = [record for record in records if record.get("status") == "quarantined"]
        warnings: list[str] = []
        if unreviewed_high:
            warnings.append("Review or revoke high-risk capability admission records before production.")
        if quarantined:
            warnings.append("Resolve quarantined capability admission records before production.")
        return {
            "ok": True,
            "production_ready": not unreviewed_high and not quarantined,
            "counts": {
                "total": len(records),
                "active": len(active),
                "unreviewed_high_risk": len(unreviewed_high),
                "quarantined": len(quarantined),
            },
            "warnings": warnings,
            "unreviewed_high_risk": _redact_value(unreviewed_high),
            "active": _redact_value(active),
        }

    def _load_records(self) -> dict[str, dict[str, Any]]:
        if not self.records_path.exists():
            return {}
        try:
            data = json.loads(self.records_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = data.get("records") if isinstance(data, dict) else {}
        return records if isinstance(records, dict) else {}

    def _save_records(self, records: dict[str, dict[str, Any]]) -> None:
        self.records_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.records_path.with_suffix(self.records_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"records": _redact_value(records)}, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.records_path)


__all__ = [
    "ADMISSION_STATUSES",
    "ALLOWED_TRANSITIONS",
    "CapabilityAdmissionRecord",
    "CapabilityAdmissionStore",
]
