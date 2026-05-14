"""GitHub review comment rendering for Ghost PR review reports."""

from __future__ import annotations

from ghostchimera.chimera_pilot.pr_review import PRReviewReport, format_pr_review_report


def format_github_review_comment(report: PRReviewReport) -> str:
    """Render a deterministic review report as a GitHub issue comment."""

    payload = report.to_dict()
    blocking = [item for item in payload["findings"] if item["severity"] in {"P0", "P1"}]
    header = [
        "## Ghost Chimera PR Review",
        "",
        f"- Blocking findings: {len(blocking)}",
        f"- Risk score: {payload['risk_score']}",
        f"- Summary: {payload['summary']}",
        "",
    ]
    return "\n".join(header) + format_pr_review_report(report)
