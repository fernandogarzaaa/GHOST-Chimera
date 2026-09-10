"""Strict EVE project scan.

Observes a repository through the StealthLoop without side effects: every
tracked file becomes a ``file.modified`` event evaluated under a strict
observe-only policy, plus deterministic structural checks for secret-like
content and oversized files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import new_event
from .loop import StealthLoop
from .stealth_policy import GhostPolicy

HEAD_BYTES = 65536
LARGE_FILE_BYTES = 1_000_000
SKIP_DIRS = frozenset({"node_modules", "__pycache__", "dist", "build", ".venv", "venv"})

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github-token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{10,}")),
    ("slack-token", re.compile(r"xox[bpas]-[A-Za-z0-9-]{10,}")),
    ("private-key", re.compile(r"BEGIN [A-Z0-9 ]*PRIVATE KEY")),
    (
        "password-assignment",
        re.compile(
            r"(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"](?=[^'\"]*[A-Za-z0-9])[^'\"]{4,}['\"]",
            re.IGNORECASE,
        ),
    ),
)

SYNTHETIC_MARKERS = ("abcdef", "123456", "example", "sample", "mock", "fake", "xxxx", "000000")


def _looks_synthetic(token: str) -> bool:
    lowered = token.lower()
    if any(marker in lowered for marker in SYNTHETIC_MARKERS):
        return True
    return re.search(r"(.)\1{5,}", token) is not None


@dataclass(frozen=True)
class ProjectFinding:
    path: str
    severity: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "severity": self.severity, "reason": self.reason, "detail": self.detail}


@dataclass
class ProjectScanReport:
    root: str
    strict: bool
    files_scanned: int = 0
    bytes_scanned: int = 0
    decisions: dict[str, int] = field(default_factory=dict)
    attended: int = 0
    max_friction: float = 0.0
    findings: list[ProjectFinding] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not any(finding.severity == "high" for finding in self.findings)

    @property
    def verdict(self) -> str:
        return "pass" if self.ok else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "strict": self.strict,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "decisions": dict(self.decisions),
            "attended": self.attended,
            "max_friction": round(self.max_friction, 3),
            "findings": [finding.to_dict() for finding in self.findings],
            "verdict": self.verdict,
            "duration_s": round(self.duration_s, 3),
        }


def _tracked_files(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for extra in ([], ["--others", "--exclude-standard"]):
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", *extra],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return _walk_files(root)
        paths.update(Path(root, part) for part in completed.stdout.split("\0") if part)
    return sorted(paths)


def _walk_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith(".") and name not in SKIP_DIRS)
        for filename in sorted(filenames):
            found.append(Path(dirpath, filename))
    return found


def _is_test_path(relative: str) -> bool:
    markers = ("test", "fixture", "example", "sample", "mock")
    return any(marker in part.lower() for part in Path(relative).parts for marker in markers)


def _check_content(head: bytes) -> tuple[str, str]:
    if b"\x00" in head:
        return "", ""
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return "", ""
    for name, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            return name, match.group(0)
    return "", ""


def _scan_file(path: Path, relative: str) -> tuple[ProjectFinding | None, float]:
    try:
        size = path.stat().st_size
    except OSError:
        return ProjectFinding(relative, "medium", "unreadable-file"), 0.9
    if size > LARGE_FILE_BYTES:
        return ProjectFinding(relative, "medium", "oversized-file", f"size_bytes={size}"), 0.9
    try:
        with open(path, "rb") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError:
        return ProjectFinding(relative, "medium", "unreadable-file"), 0.9
    match_name, match_text = _check_content(head)
    if not match_name:
        return None, 0.2
    if _looks_synthetic(match_text):
        return ProjectFinding(relative, "medium", f"synthetic-secret-like-pattern:{match_name}"), 0.9
    severity = "medium" if _is_test_path(relative) else "high"
    reason = (
        f"secret-like-pattern-in-test-fixture:{match_name}"
        if severity == "medium"
        else f"secret-like-pattern:{match_name}"
    )
    return ProjectFinding(relative, severity, reason), 0.99


def scan_project(root: str | Path, *, strict: bool = True) -> ProjectScanReport:
    root_path = Path(root).resolve()
    report = ProjectScanReport(root=str(root_path), strict=strict)
    policy = GhostPolicy.strict_observe() if strict else GhostPolicy.conservative_default()
    started = time.time()
    loop = StealthLoop(policy=policy)
    try:
        for path in _tracked_files(root_path):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root_path).as_posix()
            finding, confidence = _scan_file(path, relative)
            if finding is not None:
                report.findings.append(finding)
            with suppress(OSError):
                report.bytes_scanned += path.stat().st_size
            report.files_scanned += 1
            loop.emit(
                new_event(
                    "file.modified",
                    source="eve-project-scan",
                    payload={
                        "path": relative,
                        "size_bytes": report.bytes_scanned,
                        "relevance": 0.9 if finding is not None else 0.2,
                        "confidence": confidence,
                        "benefit": 0.5,
                        "finding": finding.reason if finding is not None else "",
                    },
                    confidence=confidence,
                )
            )
            result = loop.last_result
            if result is not None:
                report.decisions[result.decision.value] = report.decisions.get(result.decision.value, 0) + 1
                if result.attention and result.attention.get("should_attend"):
                    report.attended += 1
                if result.friction:
                    report.max_friction = max(report.max_friction, float(result.friction.get("score", 0.0)))
    finally:
        loop.close()
    severity_rank = {"high": 0, "medium": 1}
    report.findings.sort(key=lambda finding: (severity_rank.get(finding.severity, 2), finding.path))
    report.duration_s = time.time() - started
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a strict EVE project scan")
    parser.add_argument("--root", default=".", help="Repository root to scan")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="Use the default policy")
    parser.set_defaults(strict=True)
    args = parser.parse_args(argv)
    report = scan_project(args.root, strict=args.strict)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["ProjectFinding", "ProjectScanReport", "SECRET_PATTERNS", "scan_project", "main"]
