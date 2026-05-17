"""Local pull-request and diff review automation for Ghost Chimera."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9_.-]{20,}|AKIA[0-9A-Z]{16})")
_DESTRUCTIVE_RE = re.compile(r"\b(git\s+reset\s+--hard|rm\s+-rf|Remove-Item\b.*-Recurse|del\s+/[sq])\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|NotImplementedError|pass\s*#\s*stub)\b", re.IGNORECASE)
_CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".ps1", ".bat", ".cmd"}


@dataclass(frozen=True)
class ReviewFinding:
    """One actionable automated review finding."""

    severity: str
    title: str
    path: str = ""
    line: int | None = None
    detail: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "title": self.title,
            "path": self.path,
            "line": self.line,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


@dataclass
class PRReviewReport:
    """Structured review report suitable for CLI, console, and evals."""

    base: str
    head: str
    root: str
    files_changed: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    findings: list[ReviewFinding] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and all(f.severity not in {"P0", "P1"} for f in self.findings)

    @property
    def risk_score(self) -> float:
        weights = {"P0": 1.0, "P1": 0.7, "P2": 0.35, "P3": 0.1}
        raw = sum(weights.get(f.severity, 0.1) for f in self.findings)
        return round(min(1.0, raw / max(1, len(self.files_changed))), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "base": self.base,
            "head": self.head,
            "root": self.root,
            "files_changed": self.files_changed,
            "file_count": len(self.files_changed),
            "additions": self.additions,
            "deletions": self.deletions,
            "risk_score": self.risk_score,
            "findings": [finding.to_dict() for finding in self.findings],
            "finding_count": len(self.findings),
            "commands": self.commands,
            "error": self.error,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if self.error:
            return f"Review failed: {self.error}"
        if not self.files_changed:
            return "No diff detected between base and head."
        blocking = [f for f in self.findings if f.severity in {"P0", "P1"}]
        if blocking:
            return f"{len(blocking)} blocking finding(s) across {len(self.files_changed)} changed file(s)."
        return f"No blocking findings across {len(self.files_changed)} changed file(s)."


def run_pr_review(
    *,
    base: str = "origin/main",
    head: str = "HEAD",
    root: str | Path | None = None,
    max_diff_bytes: int = 500_000,
) -> PRReviewReport:
    """Review a git diff using deterministic safety and release heuristics."""

    repo = Path(root).resolve() if root else ROOT
    report = PRReviewReport(base=base, head=head, root=str(repo))
    try:
        _git(repo, ["rev-parse", "--is-inside-work-tree"], report)
        working_tree = head.strip().upper() in {"WORKTREE", "WORKING_TREE", "."}
        diff_base = _merge_base(repo, base, "HEAD", report) if working_tree else _merge_base(repo, base, head, report)
        diff_base = diff_base or base
        range_expr = diff_base if working_tree else f"{diff_base}..{head}"
        report.files_changed = _changed_files(repo, range_expr, report)
        report.additions, report.deletions = _numstat(repo, range_expr, report)
        untracked = _untracked_files(repo, report) if working_tree else []
        if untracked:
            report.files_changed = sorted(dict.fromkeys([*report.files_changed, *untracked]))
        if report.files_changed:
            diff_text = _diff(repo, range_expr, report, max_diff_bytes=max_diff_bytes)
            if untracked:
                diff_text += "\n" + _untracked_as_diff(repo, untracked, max_diff_bytes=max_diff_bytes)
            report.findings.extend(_review_diff(diff_text))
            report.findings.extend(_review_change_shape(report.files_changed))
    except Exception as exc:  # pragma: no cover - defensive CLI/report path
        report.error = str(exc)
    return report


def format_pr_review_report(report: PRReviewReport | dict[str, Any]) -> str:
    """Render a review report as compact Markdown."""

    payload = report.to_dict() if isinstance(report, PRReviewReport) else report
    lines = [
        "# Ghost Chimera PR Review",
        "",
        f"- Base: `{payload['base']}`",
        f"- Head: `{payload['head']}`",
        f"- Files changed: {payload['file_count']}",
        f"- Additions/deletions: +{payload['additions']} / -{payload['deletions']}",
        f"- Risk score: {payload['risk_score']}",
        f"- Summary: {payload['summary']}",
        "",
        "## Findings",
    ]
    findings = payload.get("findings") or []
    if not findings:
        lines.append("- No findings.")
    for finding in findings:
        location = finding.get("path") or "repository"
        if finding.get("line"):
            location += f":{finding['line']}"
        lines.append(f"- **{finding['severity']} {finding['title']}** - `{location}`")
        if finding.get("detail"):
            lines.append(f"  - {finding['detail']}")
        if finding.get("recommendation"):
            lines.append(f"  - Recommendation: {finding['recommendation']}")
    return "\n".join(lines) + "\n"


def _git(repo: Path, args: list[str], report: PRReviewReport) -> str:
    command = ["git", *args]
    report.commands.append(" ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(repo),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "git command failed").strip())
    return completed.stdout


def _merge_base(repo: Path, base: str, head: str, report: PRReviewReport) -> str:
    try:
        return _git(repo, ["merge-base", base, head], report).strip()
    except RuntimeError:
        return ""


def _changed_files(repo: Path, range_expr: str, report: PRReviewReport) -> list[str]:
    output = _git(repo, ["diff", "--name-only", "--diff-filter=ACMRT", range_expr], report)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _numstat(repo: Path, range_expr: str, report: PRReviewReport) -> tuple[int, int]:
    output = _git(repo, ["diff", "--numstat", range_expr], report)
    additions = 0
    deletions = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            additions += int(parts[0]) if parts[0].isdigit() else 0
            deletions += int(parts[1]) if parts[1].isdigit() else 0
    return additions, deletions


def _diff(repo: Path, range_expr: str, report: PRReviewReport, *, max_diff_bytes: int) -> str:
    output = _git(repo, ["diff", "--unified=80", "--no-ext-diff", range_expr], report)
    encoded = output.encode("utf-8", errors="ignore")
    if len(encoded) <= max_diff_bytes:
        return output
    return encoded[:max_diff_bytes].decode("utf-8", errors="ignore")


def _untracked_files(repo: Path, report: PRReviewReport) -> list[str]:
    output = _git(repo, ["ls-files", "--others", "--exclude-standard"], report)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _untracked_as_diff(repo: Path, files: list[str], *, max_diff_bytes: int) -> str:
    chunks: list[str] = []
    remaining = max_diff_bytes
    for rel in files:
        path = repo / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        body = "\n".join("+" + line for line in text.splitlines())
        chunk = f"diff --git a/{rel} b/{rel}\n+++ b/{rel}\n@@ -0,0 +1,{len(text.splitlines())} @@\n{body}\n"
        encoded = chunk.encode("utf-8", errors="ignore")
        if len(encoded) > remaining:
            chunks.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            break
        chunks.append(chunk)
        remaining -= len(encoded)
        if remaining <= 0:
            break
    return "\n".join(chunks)


def _review_diff(diff_text: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    current_path = ""
    current_line: int | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_path = raw[6:]
            current_line = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            current_line = int(match.group(1)) if match else None
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:]
            line = current_line
            is_code = _is_code_path(current_path)
            if _SECRET_RE.search(text):
                findings.append(
                    ReviewFinding(
                        "P0",
                        "Potential secret added to diff",
                        current_path,
                        line,
                        "The added line resembles an API key, bearer token, or provider credential.",
                        "Remove the secret, rotate it if it was real, and load it from environment or a secret store.",
                    )
                )
            if is_code and "_DESTRUCTIVE_RE" not in text and _DESTRUCTIVE_RE.search(text):
                findings.append(
                    ReviewFinding(
                        "P1",
                        "Destructive command added",
                        current_path,
                        line,
                        "The diff adds a broad destructive shell command or hard reset pattern.",
                        "Scope destructive operations to verified paths and require explicit operator confirmation.",
                    )
                )
            if (
                is_code
                and "shell=True" in text
                and '"shell=True"' not in text
                and "'shell=True'" not in text
                and "Using shell=True" not in text
                and " in text" not in text
            ):
                findings.append(
                    ReviewFinding(
                        "P1",
                        "Subprocess shell execution added",
                        current_path,
                        line,
                        "Using shell=True increases command injection risk in agent/tool paths.",
                        "Pass argv lists to subprocess and validate all user-provided arguments.",
                    )
                )
            if is_code and "_PLACEHOLDER_RE" not in text and _PLACEHOLDER_RE.search(text):
                findings.append(
                    ReviewFinding(
                        "P2",
                        "Placeholder implementation added",
                        current_path,
                        line,
                        "The added line looks like unfinished beta code.",
                        "Replace placeholders with shipped behavior or remove the incomplete surface.",
                    )
                )
            if current_line is not None:
                current_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif current_line is not None:
            current_line += 1
    return findings


def _is_code_path(path: str) -> bool:
    return Path(path).suffix.lower() in _CODE_EXTENSIONS


def _review_change_shape(files: list[str]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    file_set = set(files)
    source_changes = [path for path in files if path.startswith("ghostchimera/") and path.endswith(".py")]
    test_changes = [path for path in files if path.startswith("tests/")]
    if source_changes and not test_changes:
        findings.append(
            ReviewFinding(
                "P1",
                "Source changes lack test updates",
                detail=f"{len(source_changes)} Python source file(s) changed without tests in the same diff.",
                recommendation="Add focused tests or document why existing coverage is sufficient.",
            )
        )
    cli_or_console = any(
        path in {"ghostchimera/control_plane/cli.py", "ghostchimera/control_plane/console.py"} for path in files
    )
    if cli_or_console and "README.md" not in file_set:
        findings.append(
            ReviewFinding(
                "P2",
                "Control-plane change lacks README update",
                detail="CLI or console behavior changed without README discoverability.",
                recommendation="Document the new command, API route, or dashboard surface.",
            )
        )
    release_surface = any(
        path.startswith("ghostchimera/evals/") or path == "scripts/validate_release.py" for path in files
    )
    if release_surface and "docs/RELEASE_CHECKLIST.md" not in file_set:
        findings.append(
            ReviewFinding(
                "P2",
                "Release-gate change lacks checklist update",
                detail="Eval or release validation behavior changed without the operator checklist.",
                recommendation="Update docs/RELEASE_CHECKLIST.md so beta release validation remains reproducible.",
            )
        )
    generated = [path for path in files if path.startswith(("dist/", "build/")) or path.endswith((".pyc", ".pyo"))]
    if generated:
        findings.append(
            ReviewFinding(
                "P2",
                "Generated artifacts included",
                detail=", ".join(generated[:5]),
                recommendation="Remove generated build artifacts from the source diff unless explicitly publishing them.",
            )
        )
    return findings


__all__ = ["PRReviewReport", "ReviewFinding", "format_pr_review_report", "run_pr_review"]
