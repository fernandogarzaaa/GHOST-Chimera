"""Tests for GitHub integration client behavior."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ghostchimera.integrations.github_client import GitHubAuth, GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_auth_prefers_ghost_token_then_standard_token_then_gh_cli(self) -> None:
        with patch.dict(os.environ, {"GHOSTCHIMERA_GITHUB_TOKEN": "ghs_app", "GITHUB_TOKEN": "ghp_pat"}, clear=True):
            auth = GitHubAuth.discover()
        self.assertEqual(auth.mode, "token")
        self.assertEqual(auth.token, "ghs_app")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_pat"}, clear=True):
            auth = GitHubAuth.discover()
        self.assertEqual(auth.mode, "token")
        self.assertEqual(auth.token, "ghp_pat")

        with patch.dict(os.environ, {}, clear=True):
            auth = GitHubAuth.discover()
        self.assertEqual(auth.mode, "gh-cli")
        self.assertEqual(auth.token, "")

    def test_client_builds_headers_without_leaking_secret_in_repr(self) -> None:
        client = GitHubClient(auth=GitHubAuth(mode="token", token="ghs_secret"))

        headers = client.headers()

        self.assertEqual(headers["Authorization"], "Bearer ghs_secret")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertNotIn("ghs_secret", repr(client))


if __name__ == "__main__":
    unittest.main()
