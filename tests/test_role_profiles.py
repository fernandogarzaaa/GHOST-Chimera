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
        self.assertIn("manager-operator", ids)
        self.assertIn("marketing-specialist", ids)
        self.assertIn("virtual-assistant", ids)
        self.assertIn("enterprise-operator", ids)

    def test_role_profiles_expose_personalization_and_work_domains(self) -> None:
        manager = get_role_profile("manager-operator")
        marketer = get_role_profile("marketing-specialist")
        assistant = get_role_profile("virtual-assistant")

        self.assertIn("email", manager.personalization_sources)
        self.assertIn("team_coordination", manager.tool_domains)
        self.assertIn("campaign_assets", marketer.personalization_sources)
        self.assertIn("content_operations", marketer.tool_domains)
        self.assertIn("schedule_exports", assistant.personalization_sources)
        self.assertIn("personal_admin", assistant.tool_domains)


if __name__ == "__main__":
    unittest.main()
