"""Unit tests for the ghostchimera local-model CLI subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ghostchimera", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


class LocalModelCLIProfilesTests(unittest.TestCase):
    def test_profiles_returns_ok_with_all_profiles(self) -> None:
        result = _run(["local-model", "profiles"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        profile_names = {p["profile"] for p in payload["profiles"]}
        self.assertIn("tiny", profile_names)
        self.assertIn("balanced", profile_names)
        self.assertIn("stronger", profile_names)

    def test_profiles_returns_resources_section(self) -> None:
        result = _run(["local-model", "profiles"])
        payload = json.loads(result.stdout)
        self.assertIn("resources", payload)
        self.assertIn("cpu_count", payload["resources"])
        self.assertIn("llama_cpp_available", payload["resources"])

    def test_each_profile_has_required_fields(self) -> None:
        result = _run(["local-model", "profiles"])
        payload = json.loads(result.stdout)
        for profile in payload["profiles"]:
            with self.subTest(profile=profile["profile"]):
                self.assertIn("model_id", profile)
                self.assertIn("quantization", profile)
                self.assertIn("max_context_tokens", profile)
                self.assertIn("estimated_system_ram_gb", profile)
                self.assertIn("fit_detail", profile)


class LocalModelCLICheckTests(unittest.TestCase):
    def test_check_default_returns_ok(self) -> None:
        result = _run(["local-model", "check"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

    def test_check_includes_recommendations(self) -> None:
        result = _run(["local-model", "check"])
        payload = json.loads(result.stdout)
        self.assertIn("recommendations", payload)
        self.assertIsInstance(payload["recommendations"], list)
        self.assertGreater(len(payload["recommendations"]), 0)

    def test_check_tiny_profile(self) -> None:
        result = _run(["local-model", "check", "--profile", "tiny"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"]["profile"], "tiny")

    def test_check_reports_llama_cpp_status(self) -> None:
        result = _run(["local-model", "check"])
        payload = json.loads(result.stdout)
        self.assertIn("llama_cpp_installed", payload)
        self.assertIsInstance(payload["llama_cpp_installed"], bool)

    def test_check_reports_model_path(self) -> None:
        result = _run(["local-model", "check"])
        payload = json.loads(result.stdout)
        self.assertIn("model_path_env", payload)
        self.assertIn("model_file_found", payload)


class LocalModelCLIGuideTests(unittest.TestCase):
    def test_guide_returns_steps_for_balanced(self) -> None:
        result = _run(["local-model", "guide", "--profile", "balanced"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["steps"], list)
        self.assertGreater(len(payload["steps"]), 0)

    def test_guide_returns_steps_for_tiny(self) -> None:
        result = _run(["local-model", "guide", "--profile", "tiny"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"], "tiny")
        self.assertIsInstance(payload["steps"], list)

    def test_guide_returns_steps_for_stronger(self) -> None:
        result = _run(["local-model", "guide", "--profile", "stronger"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"], "stronger")

    def test_guide_unknown_profile_returns_nonzero(self) -> None:
        result = _run(["local-model", "guide", "--profile", "nonexistent-profile"])
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)


class LocalModelCLIDefaultActionTests(unittest.TestCase):
    def test_default_action_is_check(self) -> None:
        result = _run(["local-model"])
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        # Default action is 'check' so it should have 'profile' and 'recommendations'
        self.assertIn("recommendations", payload)

    def test_unknown_action_returns_nonzero(self) -> None:
        result = _run(["local-model", "unknown-action"])
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
