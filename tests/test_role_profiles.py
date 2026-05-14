"""Tests for multi-purpose Ghost role profiles."""

from __future__ import annotations

import unittest

from ghostchimera.personalization.role_profiles import get_role_profile, list_role_profiles


class RoleProfileTests(unittest.TestCase):
    def test_ai_engineer_proxy_profile_has_training_and_github_sources(self) -> None:
        profile = get_role_profile("ai-engineer-proxy")

        self.assertEqual(profile.id, "ai-engineer-proxy")
        self.assertIn("github_public_repositories", profile.source_scopes)
        self.assertIn("rag", profile.learning_modes)
        self.assertIn("dataset_generation", profile.learning_modes)
        self.assertTrue(profile.requires_disclosure)

    def test_list_role_profiles_includes_multi_purpose_paths(self) -> None:
        ids = {profile.id for profile in list_role_profiles()}

        self.assertIn("autonomous-engineer", ids)
        self.assertIn("ai-engineer-proxy", ids)
        self.assertIn("enterprise-operator", ids)


if __name__ == "__main__":
    unittest.main()
