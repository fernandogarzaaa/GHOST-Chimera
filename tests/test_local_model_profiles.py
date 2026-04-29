from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from ghostchimera.model_layer.local_profiles import get_local_model_profile
from ghostchimera.model_layer.providers import MinimindProvider


class LocalModelProfileTests(unittest.TestCase):
    def test_tiny_profile_fits_target_local_budget(self) -> None:
        profile = get_local_model_profile("tiny")

        self.assertEqual(profile.name, "tiny")
        self.assertIn("0.5B", profile.model_id)
        self.assertTrue(profile.fits_budget(system_ram_gb=4, gpu_vram_gb=8))
        self.assertGreaterEqual(profile.max_context_tokens, 8192)

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            get_local_model_profile("missing")

    def test_minimind_provider_loads_configured_profile_contract(self) -> None:
        fake = types.ModuleType("minimind")
        calls: list[dict] = []

        class Runtime:
            def chat(self, messages, **kwargs):
                calls.append({"messages": messages, "kwargs": kwargs})
                return "local response"

        def load_model(profile):
            calls.append({"profile": profile})
            return Runtime()

        fake.load_model = load_model  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"minimind": fake}):
            with patch.dict(os.environ, {"MINIMIND_MODEL_PROFILE": "tiny"}, clear=False):
                provider = MinimindProvider()
                response = provider.chat("system", "hello")

        self.assertTrue(provider.available)
        self.assertEqual(response, "local response")
        self.assertEqual(calls[0]["profile"]["name"], "tiny")
        self.assertEqual(calls[0]["profile"]["quantization"], "q4")
        self.assertEqual(calls[1]["messages"][0]["role"], "system")


if __name__ == "__main__":
    unittest.main()
