"""Tests for GitHub task conversion and work discovery."""

from __future__ import annotations

import unittest

from ghostchimera.integrations.github_discovery import rank_work_items
from ghostchimera.integrations.github_tasks import GitHubIssue, GitHubRepoScan, issue_to_objective


class GitHubTaskTests(unittest.TestCase):
    def test_issue_to_objective_includes_repo_issue_and_acceptance(self) -> None:
        issue = GitHubIssue(
            repo="owner/repo",
            number=42,
            title="Add dashboard filter",
            body="Users need a status filter.\nAcceptance: filter queued and failed jobs.",
            labels=["enhancement"],
            url="https://github.com/owner/repo/issues/42",
        )

        objective = issue_to_objective(issue)

        self.assertIn("owner/repo#42", objective)
        self.assertIn("Add dashboard filter", objective)
        self.assertIn("Acceptance", objective)

    def test_repo_scan_reports_release_commands(self) -> None:
        scan = GitHubRepoScan(repo="owner/repo", default_branch="main", languages=["Python"], release_commands=["python -m pytest -q"])

        payload = scan.to_dict()

        self.assertEqual(payload["repo"], "owner/repo")
        self.assertEqual(payload["release_commands"], ["python -m pytest -q"])

    def test_rank_work_items_prioritizes_assigned_bug_and_user_context(self) -> None:
        items = [
            {"kind": "issue", "title": "Refactor docs", "labels": ["docs"], "assigned": False},
            {"kind": "issue", "title": "Fix failing release gate", "labels": ["bug"], "assigned": True},
        ]

        ranked = rank_work_items(items, personal_context="I maintain release gates and CI.")

        self.assertEqual(ranked[0]["title"], "Fix failing release gate")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])


if __name__ == "__main__":
    unittest.main()
