"""
File System Tool
================

Helpers for reading and writing files on the host.  These functions are
thin wrappers around the Python standard library and can be extended to
enforce access controls.
"""

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
    allowed_roots = [
        Path(str(root)).expanduser().resolve()
        for root in policy.get("allowed_roots", [])
    ]
    if not allowed_roots:
        raise PolicyViolation("No allowed filesystem roots are configured")
    if not any(_path_is_under_root(root, candidate) for root in allowed_roots):
        raise PolicyViolation(f"Path is outside allowed roots: {candidate}")
    return candidate
