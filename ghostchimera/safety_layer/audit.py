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
from typing import Any, Dict

AUDIT_FILE = os.environ.get(
    "GHOSTCHIMERA_AUDIT_FILE",
    os.path.expanduser("~/.ghostchimera/audit.json"),
)


def _read_audit() -> list:
    if not os.path.exists(AUDIT_FILE):
        return []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def _write_audit(records: list) -> None:
    Path(os.path.dirname(AUDIT_FILE)).mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def record(task: Dict[str, Any], result: Any) -> None:
    """Append a record to the audit log."""
    entry = {
        "task": task,
        "result": result,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    records = _read_audit()
    records.append(entry)
    _write_audit(records)
