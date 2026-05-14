"""Tests for user-selected Ghost path synthesis."""

from __future__ import annotations

import unittest

from ghostchimera.personalization.path_synthesizer import synthesize_path


class PathSynthesizerTests(unittest.TestCase):
    def test_ai_engineer_proxy_synthesis_enables_github_and_guarded_training(self) -> None:
        result = synthesize_path(
            "ai-engineer-proxy",
            preferences={"training_mode": "rag-first", "approval_level": "supervised"},
        )

        self.assertEqual(result["role"]["id"], "ai-engineer-proxy")
        self.assertIn("github", result["dashboard_tabs"])
        self.assertEqual(result["learning_strategy"]["default_mode"], "rag-first")
        self.assertIn("license_check_required", result["source_policy"])
        self.assertTrue(result["proxy_policy"]["disclosure_required"])

    def test_virtual_assistant_synthesis_emits_personal_ghost_blueprint(self) -> None:
        result = synthesize_path(
            "virtual-assistant",
            preferences={"training_mode": "dataset_generation", "approval_level": "assist"},
        )

        blueprint = result["ghost_blueprint"]
        self.assertEqual(blueprint["concept"], "personalized AI operator proxy")
        self.assertIn("schedule_exports", blueprint["learns_from"])
        self.assertIn("personal_admin", blueprint["can_operate"])
        self.assertIn("local memory RAG", blueprint["training_pipeline"])
        self.assertIn("MiniMind dataset generation", blueprint["training_pipeline"])
        self.assertTrue(result["tool_policy"]["admin_controls_required"])

    def test_marketing_profile_requires_approval_for_external_campaign_surfaces(self) -> None:
        result = synthesize_path(
            "marketing-specialist",
            preferences={"training_mode": "rag-first", "approval_level": "supervised"},
        )

        self.assertIn("campaign_assets", result["ghost_blueprint"]["learns_from"])
        self.assertIn("content_operations", result["ghost_blueprint"]["can_operate"])
        self.assertTrue(result["tool_policy"]["admin_controls_required"])

    def test_default_path_synthesis_uses_autonomous_engineer(self) -> None:
        from ghostchimera.personalization.path_state import get_active_ghost_path

        result = get_active_ghost_path(config={})

        self.assertEqual(result["profile_id"], "autonomous-engineer")
        self.assertIn("github", result["synthesis"]["dashboard_tabs"])


if __name__ == "__main__":
    unittest.main()
