"""The repo itself must pass CI's strict project scan (`ghost-eve-scan --root .`).

CI's "Run strict project scan" step fails on any high-severity finding. A
redaction.py comment carried a literal Slack-token-shaped example
(``xoxb-`` followed by digits), which turned every CI job red. This runs the
same per-file check locally so it fails in pytest, not only in CI.
"""

from __future__ import annotations

from pathlib import Path

from ghostchimera.stealth.project_scan import _scan_file, _tracked_files

ROOT = Path(__file__).resolve().parents[1]


def test_no_high_severity_findings_in_tracked_files() -> None:
    high = []
    for path in _tracked_files(ROOT):
        if path.is_symlink() or not path.is_file():
            continue
        finding, _confidence = _scan_file(path, path.relative_to(ROOT).as_posix())
        if finding is not None and finding.severity == "high":
            high.append(finding.to_dict())
    assert not high, high
