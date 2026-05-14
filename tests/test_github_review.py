"""Tests for GitHub PR review comment formatting."""

from __future__ import annotations

import unittest

from ghostchimera.chimera_pilot.pr_review import PRReviewReport, ReviewFinding
from ghostchimera.integrations.github_review import format_github_review_comment


class GitHubReviewPostingTests(unittest.TestCase):
    def test_format_github_review_comment_marks_blocking_findings(self) -> None:
        report = PRReviewReport(
            base="origin/main",
            head="HEAD",
            root=".",
            files_changed=["app.py"],
            findings=[ReviewFinding(severity="P1", title="Secret detected", path="app.py", line=7)],
        )

        body = format_github_review_comment(report)

        self.assertIn("Ghost Chimera PR Review", body)
        self.assertIn("Blocking findings: 1", body)
        self.assertIn("P1 Secret detected", body)


if __name__ == "__main__":
    unittest.main()
