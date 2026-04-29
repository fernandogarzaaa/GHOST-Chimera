"""
Safety Gating
=============

Defines functions to decide whether a task requires user approval.  In a
production setting this module would implement policies around which
operations may be executed autonomously and which require a human in the
loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping


class PolicyViolation(PermissionError):
    """Raised when a task is blocked by Ghost Chimera policy."""


@dataclass(frozen=True)
class ExecutionPolicy:
    """Default-deny policy for high-impact local operations."""

    allow_shell: bool = False
    allow_network: bool = False
    allow_file_read: bool = False
    allow_file_write: bool = False
    allowed_roots: tuple[str, ...] = ()
    shell_timeout_seconds: int = 10
    output_limit_bytes: int = 20_000

    @classmethod
    def from_env(cls) -> "ExecutionPolicy":
        roots = tuple(
            item.strip()
            for item in os.environ.get("GHOSTCHIMERA_ALLOWED_ROOTS", "").split(os.pathsep)
            if item.strip()
        )
        return cls(
            allow_shell=_truthy(os.environ.get("GHOSTCHIMERA_ALLOW_SHELL")),
            allow_network=_truthy(os.environ.get("GHOSTCHIMERA_ALLOW_NETWORK")),
            allow_file_read=_truthy(os.environ.get("GHOSTCHIMERA_ALLOW_FILE_READ")),
            allow_file_write=_truthy(os.environ.get("GHOSTCHIMERA_ALLOW_FILE_WRITE")),
            allowed_roots=roots,
            shell_timeout_seconds=int(os.environ.get("GHOSTCHIMERA_SHELL_TIMEOUT_SECONDS", "10")),
        )

    def authorize_task(self, task: Mapping[str, Any]) -> dict[str, Any]:
        """Return a policy-stamped copy of a task or raise ``PolicyViolation``."""

        action = str(task.get("action", ""))
        sanitized = dict(task)
        cwd: str | None = None

        if action == "shell":
            if not self.allow_shell:
                raise PolicyViolation("Shell execution is disabled by policy")
            cwd = self._resolve_cwd(task)
        elif action == "http_get":
            if not self.allow_network:
                raise PolicyViolation("Network access is disabled by policy")
        elif action == "read_file":
            if not self.allow_file_read:
                raise PolicyViolation("File reads are disabled by policy")
            self._require_path_under_allowed_root(str(task.get("path", "")))
        elif action == "write_file":
            if not self.allow_file_write:
                raise PolicyViolation("File writes are disabled by policy")
            self._require_path_under_allowed_root(str(task.get("path", "")))

        sanitized["_ghostchimera_policy"] = {
            "authorized": True,
            "allowed_roots": [str(path) for path in self._resolved_roots()],
            "cwd": cwd,
            "timeout_seconds": max(1, int(self.shell_timeout_seconds)),
            "output_limit_bytes": max(1, int(self.output_limit_bytes)),
        }
        return sanitized

    def _resolve_cwd(self, task: Mapping[str, Any]) -> str:
        cwd_value = task.get("cwd")
        if cwd_value:
            return str(self._require_path_under_allowed_root(str(cwd_value)))

        roots = self._resolved_roots()
        if roots:
            return str(roots[0])

        raise PolicyViolation("Shell execution requires at least one allowed root")

    def _require_path_under_allowed_root(self, raw_path: str) -> Path:
        if not raw_path:
            raise PolicyViolation("Task path is required")
        path = Path(raw_path).expanduser().resolve()
        roots = self._resolved_roots()
        if not roots:
            raise PolicyViolation("No allowed filesystem roots are configured")
        if not any(path == root or root in path.parents for root in roots):
            raise PolicyViolation(f"Path is outside allowed roots: {path}")
        return path

    def _resolved_roots(self) -> tuple[Path, ...]:
        return tuple(Path(root).expanduser().resolve() for root in self.allowed_roots)


def requires_approval(task: Dict[str, Any]) -> bool:
    """Return True if the given task needs explicit user approval."""
    return str(task.get("action", "")) in {"shell", "write_file", "read_file", "http_get"}


def ensure_authorized(policy: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Validate an internal policy stamp passed from the executor to a tool."""

    if not policy or not policy.get("authorized"):
        raise PolicyViolation("Operation requires policy authorization")
    return policy


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
