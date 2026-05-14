"""Tests for GitHub-connected CLI workflows."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ghostchimera.control_plane.cli import _main


class GitHubCLITests(unittest.TestCase):
    def test_github_status_prints_auth_mode(self) -> None:
        with patch.dict(os.environ, {"GHOSTCHIMERA_GITHUB_TOKEN": "ghs_test"}, clear=True):
            output = io.StringIO()
            with redirect_stdout(output):
                code = _main(["github", "status"])

        self.assertEqual(code, 0)
        self.assertIn('"auth_mode": "token"', output.getvalue())

    def test_github_plan_prints_issue_objective(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = _main(["github", "plan", "--repo", "owner/repo", "--issue", "7", "--title", "Fix CI"])

        self.assertEqual(code, 0)
        self.assertIn("owner/repo#7", output.getvalue())
        self.assertIn("Fix CI", output.getvalue())


if __name__ == "__main__":
    unittest.main()
