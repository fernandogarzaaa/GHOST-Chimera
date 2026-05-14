"""Tests for GitHub CI status classification."""

from __future__ import annotations

import unittest

from ghostchimera.integrations.github_ci import classify_check_runs


class GitHubCITests(unittest.TestCase):
    def test_classify_check_runs_marks_failed_required_checks(self) -> None:
        payload = [
            {"name": "pytest", "status": "completed", "conclusion": "failure", "html_url": "https://ci/1"},
            {"name": "lint", "status": "completed", "conclusion": "success", "html_url": "https://ci/2"},
        ]

        report = classify_check_runs(payload)

        self.assertFalse(report["ok"])
        self.assertEqual(report["failed"], ["pytest"])
        self.assertIn("pytest", report["repair_objective"])


if __name__ == "__main__":
    unittest.main()
