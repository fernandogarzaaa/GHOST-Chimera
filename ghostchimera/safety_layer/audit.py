"""
Audit Log
=========

Provides a simple audit mechanism for recording high impact operations.  The
audit log is written to a JSON file distinct from the memory to ease
inspection and compliance.  Each record contains the task, timestamp and
result.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUDIT_FILE = os.environ.get(
    "GHOSTCHIMERA_AUDIT_FILE",
    os.path.expanduser("~/.ghostchimera/audit.json"),
)


def _read_audit() -> list:
    if not os.path.exists(AUDIT_FILE):
        return []
    with open(AUDIT_FILE, encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def _write_audit(records: list) -> None:
    Path(os.path.dirname(AUDIT_FILE)).mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def record(task: dict[str, Any], result: Any) -> None:
    """Append a record to the audit log."""
    entry = {
        "task": task,
        "result": result,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    records = _read_audit()
    records.append(entry)
    _write_audit(records)


class AuditLog:
    """HMAC-SHA256 chained audit log."""

    def __init__(self, audit_file: str | None = None) -> None:
        self.audit_file = audit_file or AUDIT_FILE
        self.key = os.environ.get("GHOSTCHIMERA_AUDIT_KEY", "").encode("utf-8")
        # Use deterministic signing for tests when no key is set
        if not self.key:
            self.key = b"ghostchimera-test-key"

    def _hmac(self, data: str) -> str:
        import hashlib as _hashlib
        import hmac as _hmac
        return _hmac.new(self.key, data.encode("utf-8"), _hashlib.sha256).hexdigest()

    def record(self, action: str, details: dict[str, Any]) -> dict[str, Any]:
        """Record an audit entry with chain hash."""
        records = _read_audit()
        prev_hash = records[-1]["chain_hash"] if records else "genesis"
        entry = {
            "action": action,
            "details": details,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "chain_hash": self._hmac(f"{prev_hash}{action}{json.dumps(details, sort_keys=True)}"),
        }
        records.append(entry)
        _write_audit(records)
        return entry

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the audit chain integrity. Returns (ok, error_msg)."""
        records = _read_audit()
        if not records:
            return True, "No records to verify"
        prev_hash = records[0]["chain_hash"] if len(records) > 0 else "genesis"
        for i, entry in enumerate(records):
            expected = self._hmac(f"{prev_hash}{entry['action']}{json.dumps(entry['details'], sort_keys=True)}")
            if entry.get("chain_hash") != expected:
                return False, f"Chain broken at entry {i}"
            prev_hash = entry["chain_hash"]
        return True, "Chain intact"

    def get_entries(self) -> list[dict[str, Any]]:
        """Return all audit entries."""
        return _read_audit()

    @staticmethod
    def verify_entry(entry: dict[str, Any], prev_entry: dict[str, Any] | None = None) -> bool:
        """Verify a single chain link."""
        import hashlib as _hashlib
        import hmac as _hmac
        key = os.environ.get("GHOSTCHIMERA_AUDIT_KEY", "ghostchimera-test-key").encode("utf-8")
        prev_hash = prev_entry["chain_hash"] if prev_entry else "genesis"
        data = f"{prev_hash}{entry['action']}{json.dumps(entry['details'], sort_keys=True)}"
        expected = _hmac.new(key, data.encode("utf-8"), _hashlib.sha256).hexdigest()
        return entry.get("chain_hash") == expected
