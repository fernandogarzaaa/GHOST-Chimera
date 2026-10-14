"""
Audit Log
=========

Records high impact operations in an HMAC-SHA256 hash-chained JSON file,
kept apart from memory to ease inspection and compliance.

There is one record shape. The legacy module-level :func:`record` (used by
``AgentCore``'s executor) writes a proper chained record through
:class:`AuditLog`, so the two writers can share a file without breaking
the chain. Integrity is fail-closed: a missing, unreadable, truncated or
rolled-back log is reported as *not* intact. Truncation is detected with
a keyed head anchor (``<audit file>.head``: record count + latest chain
hash, HMAC-signed) updated on every append.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import state_io

logger = logging.getLogger(__name__)

# Explicit override (tests/embedders may assign it); None means "resolve
# lazily from GHOSTCHIMERA_AUDIT_FILE / GHOSTCHIMERA_STATE_DIR on each use".
AUDIT_FILE: str | None = None


def default_audit_file() -> str:
    from ..paths import audit_file_path

    return AUDIT_FILE or str(audit_file_path())


_REQUIRED_KEYS = ("action", "details", "chain_hash")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _load_records(path: str) -> tuple[list[Any], str]:
    """Return (records, status) where status is ok | missing | unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return [], "missing"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], "unreadable"
    if not isinstance(data, list):
        return [], "unreadable"
    return data, "ok"


def _read_audit(audit_file: str | None = None) -> list:
    """Best-effort read (``[]`` when missing/unreadable). Not for verification."""
    records, _status = _load_records(audit_file or default_audit_file())
    return records


def _write_audit(records: list, audit_file: str | None = None) -> None:
    path = audit_file or default_audit_file()
    state_io.atomic_write_json(path, records, ensure_ascii=False, indent=2, sort_keys=False)


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


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON so the hashed form equals the stored form."""
    return json.loads(json.dumps(value, default=str))


def record(task: dict[str, Any], result: Any) -> None:
    """Append a chained record for an AgentCore task (legacy API).

    The entry is a normal :class:`AuditLog` record (``action`` = the task's
    action, ``details`` = task + result) and keeps the historical top-level
    ``task``/``result`` fields as read-only mirrors, which verification
    checks against the signed ``details``.
    """
    task = _jsonable(task)
    result = _jsonable(result)
    action = str(task.get("action") or "task") if isinstance(task, dict) else "task"
    AuditLog().record(action, {"task": task, "result": result}, _mirror={"task": task, "result": result})


class AuditLog:
    """HMAC-SHA256 chained audit log."""

    def __init__(self, audit_file: str | None = None) -> None:
        self.audit_file = audit_file or default_audit_file()
        self.key = _resolve_key(self.audit_file)

    @property
    def head_file(self) -> str:
        return self.audit_file + ".head"

    def _hmac(self, data: str) -> str:
        return hmac.new(self.key, data.encode("utf-8"), hashlib.sha256).hexdigest()

    def _link(self, prev_hash: str, action: str, details: Any) -> str:
        return self._hmac(f"{prev_hash}{action}{json.dumps(details, sort_keys=True)}")

    # -- head anchor -------------------------------------------------------
    def _anchor_mac(self, count: int, chain_hash: str) -> str:
        return self._hmac(f"audit-head|{count}|{chain_hash}")

    def _read_anchor(self) -> dict[str, Any] | None:
        data = state_io.read_json(self.head_file, None, expect=dict, quarantine=False)
        return data if isinstance(data, dict) else None

    def _write_anchor(self, count: int, chain_hash: str) -> None:
        state_io.atomic_write_json(
            self.head_file,
            {"count": count, "chain_hash": chain_hash, "mac": self._anchor_mac(count, chain_hash)},
        )

    def _anchor_problem(self, records: list[Any], status: str) -> str:
        """Describe how the file disagrees with the signed head anchor."""
        anchor = self._read_anchor()
        if anchor is None:
            return ""
        try:
            count = int(anchor.get("count", -1))
        except (TypeError, ValueError):
            count = -1
        head = str(anchor.get("chain_hash") or "")
        if not hmac.compare_digest(str(anchor.get("mac") or ""), self._anchor_mac(count, head)):
            return "audit head anchor is invalid (forged or written with another key)"
        if status == "missing":
            return f"audit log is missing (head anchor expects {count} records)"
        last = records[-1].get("chain_hash") if records and isinstance(records[-1], dict) else ""
        if len(records) != count or (count and last != head):
            return f"audit log truncated or rolled back: {len(records)} records, head anchor expects {count}"
        return ""

    # -- write ---------------------------------------------------------------
    def record(self, action: str, details: dict[str, Any], *, _mirror: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record an audit entry with chain hash (locked, atomic)."""
        with state_io.locked(self.audit_file):
            records, status = _load_records(self.audit_file)
            problem = ""
            if status == "unreadable":
                problem = "previous audit log was unreadable"
            elif records and not all(isinstance(r, dict) and all(k in r for k in _REQUIRED_KEYS) for r in records):
                problem = "previous audit log contained unchained (legacy or foreign) records"
            if problem:
                # Never overwrite evidence: move it aside and start a new
                # chain whose first, signed entry says why.
                backup = state_io.quarantine_corrupt(self.audit_file)
                anchor = self._read_anchor() or {}
                records = []
                reset = {
                    "reason": problem,
                    "preserved_as": backup.name if backup else "",
                    "previous_anchor_count": anchor.get("count"),
                }
                records.append(self._entry("audit.reset", reset, "genesis"))
            else:
                mismatch = self._anchor_problem(records, status)
                if mismatch and status != "missing":
                    prev = records[-1]["chain_hash"] if records else "genesis"
                    records.append(self._entry("audit.anchor_mismatch", {"reason": mismatch}, prev))
                elif mismatch:
                    records.append(self._entry("audit.reset", {"reason": mismatch}, "genesis"))
            prev_hash = records[-1]["chain_hash"] if records else "genesis"
            entry = self._entry(action, details, prev_hash)
            if _mirror:
                entry.update(_mirror)
            records.append(entry)
            _write_audit(records, self.audit_file)
            self._write_anchor(len(records), entry["chain_hash"])
        return entry

    def _entry(self, action: str, details: dict[str, Any], prev_hash: str) -> dict[str, Any]:
        return {
            "action": action,
            "details": details,
            "timestamp": _now_iso(),
            "chain_hash": self._link(prev_hash, action, details),
        }

    # -- verify --------------------------------------------------------------
    def verify_integrity(self) -> tuple[bool, str]:
        """Verify the audit chain. Returns (ok, message); fail-closed."""
        records, status = _load_records(self.audit_file)
        if status == "unreadable":
            return False, "Audit log unreadable (corrupt or not a JSON list)"
        prev_hash = "genesis"
        for i, entry in enumerate(records):
            if not isinstance(entry, dict) or not all(key in entry for key in _REQUIRED_KEYS):
                return False, f"Chain broken at entry {i}: not a chained audit record"
            try:
                expected = self._link(prev_hash, str(entry["action"]), entry["details"])
            except (TypeError, ValueError):
                return False, f"Chain broken at entry {i}: details not serialisable"
            if not hmac.compare_digest(str(entry.get("chain_hash")), expected):
                return False, f"Chain broken at entry {i}"
            details = entry["details"] if isinstance(entry["details"], dict) else {}
            for mirror in ("task", "result"):
                if mirror in entry and entry[mirror] != details.get(mirror):
                    return False, f"Chain broken at entry {i}: unsigned '{mirror}' field altered"
            prev_hash = entry["chain_hash"]
        problem = self._anchor_problem(records, status)
        if problem:
            return False, problem
        if not records:
            return True, "No records to verify"
        events = sum(1 for entry in records if entry.get("action") in {"audit.reset", "audit.anchor_mismatch"})
        if events:
            return True, f"Chain intact ({events} signed reset/anchor-mismatch event(s) recorded; review them)"
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
        resolved = key
        if resolved is None:
            resolved = os.environ.get("GHOSTCHIMERA_AUDIT_KEY", "").strip().encode("utf-8")
        if not resolved:
            raise ValueError("audit HMAC key required: pass key= or set GHOSTCHIMERA_AUDIT_KEY")
        prev_hash = prev_entry["chain_hash"] if prev_entry else "genesis"
        data = f"{prev_hash}{entry['action']}{json.dumps(entry['details'], sort_keys=True)}"
        expected = hmac.new(resolved, data.encode("utf-8"), hashlib.sha256).hexdigest()
        return entry.get("chain_hash") == expected
