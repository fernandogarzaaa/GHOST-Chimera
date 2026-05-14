"""Tests for GitHub task worktree planning."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ghostchimera.integrations.github_worktree import GitHubWorktreePlan


class GitHubWorktreeTests(unittest.TestCase):
    def test_worktree_plan_uses_codex_branch_prefix_and_issue_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = GitHubWorktreePlan.create(
                repo_root=Path(tmp),
                repo="owner/repo",
                issue_number=42,
                base_branch="main",
            )

        self.assertEqual(plan.branch, "codex/github-42")
        self.assertTrue(str(plan.path).endswith("repo-github-42"))
        self.assertIn("git worktree add", " ".join(plan.commands))


if __name__ == "__main__":
    unittest.main()
