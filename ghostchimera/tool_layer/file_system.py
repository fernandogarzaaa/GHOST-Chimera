"""
File System Tool
================

Helpers for reading and writing files on the host.  These functions are
thin wrappers around the Python standard library and can be extended to
enforce access controls.
"""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..safety_layer.gating import PolicyViolation, _path_is_under_root, ensure_authorized


def write_file(path: str, content: str, policy: dict[str, Any] | None = None) -> None:
    """Write content to a file, creating parent directories if needed."""
    policy = dict(ensure_authorized(policy))
    p = _authorized_path(path, policy)
    if p.parent:
        p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(path: str, policy: dict[str, Any] | None = None) -> str:
    """Read and return the contents of a file."""
    policy = dict(ensure_authorized(policy))
    p = _authorized_path(path, policy)
    with open(p, encoding="utf-8") as f:
        return f.read()


def _authorized_path(path: str, policy: dict[str, Any]) -> Path:
    candidate = Path(path).expanduser().resolve()
    allowed_roots = [Path(str(root)).expanduser().resolve() for root in policy.get("allowed_roots", [])]
    if not allowed_roots:
        raise PolicyViolation("No allowed filesystem roots are configured")
    if not any(_path_is_under_root(root, candidate) for root in allowed_roots):
        raise PolicyViolation(f"Path is outside allowed roots: {candidate}")
    return candidate


@dataclass(frozen=True)
class MergeConflictReport:
    """Structured conflict report for concurrent file edits."""

    path: str
    conflict_class: str
    baseline_hash: str | None = None
    current_hash: str | None = None
    proposed_hash: str | None = None
    detail: str | None = None


class FileLeaseManager:
    """In-memory file lease manager used to arbitrate concurrent writes."""

    def __init__(self) -> None:
        self._leases: dict[str, str] = {}
        self._lock = threading.Lock()

    def acquire(self, path: str, holder: str) -> bool:
        """Acquire lease for *path* with *holder* identity."""
        with self._lock:
            current = self._leases.get(path)
            if current is None or current == holder:
                self._leases[path] = holder
                return True
            return False

    def release(self, path: str, holder: str) -> bool:
        """Release lease for *path* if held by *holder*."""
        with self._lock:
            current = self._leases.get(path)
            if current != holder:
                return False
            del self._leases[path]
            return True

    def held_by(self, path: str) -> str | None:
        """Return lease holder for *path*, if any."""
        with self._lock:
            return self._leases.get(path)

    def classify_conflict(
        self,
        *,
        path: str,
        baseline_hash: str | None,
        current_hash: str | None,
        proposed_hash: str | None,
        policy_allowed: bool = True,
    ) -> MergeConflictReport:
        """Classify write reconciliation outcome into a structured report."""
        if not policy_allowed:
            conflict_class = "policy-conflict"
            detail = "proposed mutation violates policy constraints"
        elif current_hash == proposed_hash:
            conflict_class = "non-overlap"
            detail = "current and proposed content are compatible"
        elif baseline_hash is not None and current_hash == baseline_hash:
            conflict_class = "non-overlap"
            detail = "no competing changes since baseline"
        else:
            conflict_class = "text-conflict"
            detail = "concurrent edits overlap and require human resolution"
        return MergeConflictReport(
            path=path,
            conflict_class=conflict_class,
            baseline_hash=baseline_hash,
            current_hash=current_hash,
            proposed_hash=proposed_hash,
            detail=detail,
        )
