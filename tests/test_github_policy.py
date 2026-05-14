"""Tests for GitHub action policy simulation."""

from __future__ import annotations

import unittest

from ghostchimera.integrations.github_policy import simulate_github_action_policy


class GitHubPolicyTests(unittest.TestCase):
    def test_policy_blocks_push_without_explicit_consent(self) -> None:
        result = simulate_github_action_policy({"action": "push_branch", "autonomous": True}, {"allow_push": False})

        self.assertFalse(result["allowed"])
        self.assertIn("allow_push", result["required_controls"])
        self.assertIn("allow_autonomy", result["required_controls"])


if __name__ == "__main__":
    unittest.main()
