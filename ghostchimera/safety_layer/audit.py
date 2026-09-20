"""
Audit Log
=========

Provides a simple audit mechanism for recording high impact operations.  The
audit log is written to a JSON file distinct from the memory to ease
inspection and compliance.  Each record contains the task, timestamp and
result.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUDIT_FILE = os.environ.get(
    "GHOSTCHIMERA_AUDIT_FILE",
    os.path.expanduser("~/.ghostchimera/audit.json"),
)


def _read_audit(audit_file: str | None = None) -> list:
    path = audit_file or AUDIT_FILE
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def _write_audit(records: list, audit_file: str | None = None) -> None:
    path = audit_file or AUDIT_FILE
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _key_file_mode_ok(key_path: str) -> bool:
    """Owner-only (or stricter) permissions required for a stored HMAC key.

    POSIX-only enforcement: Windows ACLs do not express ownership through
    mode bits (stat reports 0o666), so the check is vacuous there and the
    file relies on the user's profile directory ACLs instead.
    """
    if os.name != "posix":
        return True
    try:
        mode = stat.S_IMODE(os.stat(key_path).st_mode)
    except OSError:
        return False
    return mode & 0o077 == 0


def _resolve_key(audit_file: str) -> bytes:
    """HMAC key: explicit env wins; else a per-install key file (0o600).

    Never falls back to a public test key: an unconfigured production
    install gets a securely generated key persisted next to the audit
    file. Tests should set GHOSTCHIMERA_AUDIT_KEY for determinism.
    """
    explicit = os.environ.get("GHOSTCHIMERA_AUDIT_KEY", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    key_path = audit_file + ".key"
    try:
        if os.path.exists(key_path):
            if not _key_file_mode_ok(key_path):
                # Repair lax permissions; fail closed if repair is impossible.
                with contextlib.suppress(OSError):
                    os.chmod(key_path, 0o600)
                if not _key_file_mode_ok(key_path):
                    raise ValueError(
                        f"audit key file {key_path} is readable by others and cannot be secured; "
                        "fix its permissions or set GHOSTCHIMERA_AUDIT_KEY"
                    )
            with open(key_path, "rb") as handle:
                stored = handle.read()
            # Exact bytes: no stripping — a generated key may legitimately
            # start or end with whitespace bytes, and read-modify asymmetry
            # would silently fork the chain.
            if len(stored) >= 16:
                return stored
    except OSError:
        pass
    import secrets

    generated = secrets.token_bytes(32)
    fd = None
    try:
        Path(os.path.dirname(key_path) or ".").mkdir(parents=True, exist_ok=True)
        # Exclusive creation: a concurrent process that wins the race keeps
        # its key; the loser rereads instead of overwriting (which would
        # orphan entries the winner already signed).
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            handle.write(generated)
        return generated
    except FileExistsError:
        with contextlib.suppress(OSError):
            if fd is not None:
                os.close(fd)
        with contextlib.suppress(OSError):
            with open(key_path, "rb") as handle:
                stored = handle.read()
            if len(stored) >= 16:
                return stored
        return generated
    except OSError:
        pass
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
    return generated


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
        self.key = _resolve_key(self.audit_file)

    def _hmac(self, data: str) -> str:
        import hashlib as _hashlib
        import hmac as _hmac

        return _hmac.new(self.key, data.encode("utf-8"), _hashlib.sha256).hexdigest()

    def record(self, action: str, details: dict[str, Any]) -> dict[str, Any]:
        """Record an audit entry with chain hash."""
        records = _read_audit(self.audit_file)
        prev_hash = records[-1]["chain_hash"] if records else "genesis"
        entry = {
            "action": action,
            "details": details,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "chain_hash": self._hmac(f"{prev_hash}{action}{json.dumps(details, sort_keys=True)}"),
        }
        records.append(entry)
        _write_audit(records, self.audit_file)
        return entry

    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the audit chain integrity. Returns (ok, error_msg)."""
        records = _read_audit(self.audit_file)
        if not records:
            return True, "No records to verify"
        prev_hash = "genesis"
        for i, entry in enumerate(records):
            expected = self._hmac(f"{prev_hash}{entry['action']}{json.dumps(entry['details'], sort_keys=True)}")
            if entry.get("chain_hash") != expected:
                return False, f"Chain broken at entry {i}"
            prev_hash = entry["chain_hash"]
        return True, "Chain intact"

    def get_entries(self) -> list[dict[str, Any]]:
        """Return all audit entries."""
        return _read_audit(self.audit_file)

    @staticmethod
    def verify_entry(
        entry: dict[str, Any], prev_entry: dict[str, Any] | None = None, *, key: bytes | None = None
    ) -> bool:
        """Verify a single chain link. Key must be explicit or configured —
        there is no test-key fallback."""
        import hashlib as _hashlib
        import hmac as _hmac

        resolved = key
        if resolved is None:
            resolved = os.environ.get("GHOSTCHIMERA_AUDIT_KEY", "").strip().encode("utf-8")
        if not resolved:
            raise ValueError("audit HMAC key required: pass key= or set GHOSTCHIMERA_AUDIT_KEY")
        prev_hash = prev_entry["chain_hash"] if prev_entry else "genesis"
        data = f"{prev_hash}{entry['action']}{json.dumps(entry['details'], sort_keys=True)}"
        expected = _hmac.new(resolved, data.encode("utf-8"), _hashlib.sha256).hexdigest()
        return entry.get("chain_hash") == expected
