"""Production gap scanner for Ghost Chimera.

This is intentionally local and deterministic. It does not prove production
readiness by itself; it makes scaffold-like markers visible so operators can
separate shipped behavior from work that still needs implementation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

_SCAN_EXTENSIONS = {".py", ".md", ".js", ".html", ".toml", ".yaml", ".yml"}
_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".ghost",
    ".ghost-admin-live",
    ".ghost-test-remote",
    ".ghostchimera",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
_ALLOWED_MARKER_FILES = {
    "ghostchimera/chimera_pilot/pr_review.py",
    "ghostchimera/production_gaps.py",
}
_SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"secret[-_A-Za-z0-9]{6,}|token[-_A-Za-z0-9]{6,})"
)
_MARKERS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("not_implemented", re.compile(r"\bNotImplemented(Error)?\b"), "action_required"),
    ("pass_stub", re.compile(r"^\s*pass(?:\s*#.*\b(stub|placeholder|todo)\b)?\s*$", re.IGNORECASE), "action_required"),
    ("scaffold", re.compile(r"\b(scaffold|placeholder|stub)\b", re.IGNORECASE), "action_required"),
    ("demo_runtime", re.compile(r"\b(preview_only|metadata_only|demo)\b", re.IGNORECASE), "review"),
    ("todo", re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE), "review"),
)


def _redact(text: str) -> str:
    redacted = _SECRET_RE.sub("[redacted]", text)
    return redacted.encode("ascii", errors="replace").decode("ascii")


def _iter_scan_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in _SCAN_EXTENSIONS:
            files.append(path)
    return sorted(files)


def _severity_for(path: Path, default: str) -> str:
    parts = {part.lower() for part in path.parts}
    if {"docs", "tests", "examples", ".github"} & parts:
        return "non_blocking"
    if default == "action_required":
        return "action_required"
    return "non_blocking"


def scan_production_gaps(root: str | Path | None = None, *, limit: int = 200) -> dict[str, Any]:
    """Scan a checkout for placeholder-like markers and return redacted findings."""

    root_path = Path(root).resolve() if root else ROOT
    files = _iter_scan_files(root_path)
    gaps: list[dict[str, Any]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(root_path)
        if rel.as_posix() in _ALLOWED_MARKER_FILES:
            continue
        for line_number, line in enumerate(lines, start=1):
            for marker, pattern, default_severity in _MARKERS:
                if marker == "pass_stub" and "pass" not in line:
                    continue
                if not pattern.search(line):
                    continue
                severity = _severity_for(rel, default_severity)
                gaps.append(
                    {
                        "id": f"{rel.as_posix()}:{line_number}:{marker}",
                        "path": rel.as_posix(),
                        "line": line_number,
                        "marker": marker,
                        "severity": severity,
                        "snippet": _redact(line.strip())[:220],
                    }
                )
                break
            if len(gaps) >= limit:
                break
        if len(gaps) >= limit:
            break
    action_required = [gap for gap in gaps if gap["severity"] == "action_required"]
    non_blocking = [gap for gap in gaps if gap["severity"] != "action_required"]
    return {
        "ok": not action_required,
        "root": str(root_path),
        "counts": {
            "files_scanned": len(files),
            "gaps": len(gaps),
            "action_required": len(action_required),
            "non_blocking": len(non_blocking),
            "truncated": len(gaps) >= limit,
        },
        "gaps": gaps,
        "policy": {
            "secrets_redacted": True,
            "scanner_is_advisory": True,
            "action_required_only_for_runtime_surfaces": True,
        },
    }


__all__ = ["scan_production_gaps"]
