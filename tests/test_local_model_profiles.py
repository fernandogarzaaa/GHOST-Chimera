from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from importlib.machinery import ModuleSpec
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
        fake.__spec__ = ModuleSpec("minimind", loader=None)
        calls: list[dict] = []

        class Runtime:
            def chat(self, messages, **kwargs):
                calls.append({"messages": messages, "kwargs": kwargs})
                return "local response"

        def load_model(profile):
            calls.append({"profile": profile})
            return Runtime()

        fake.load_model = load_model  # type: ignore[attr-defined]

        with (
            patch.dict(sys.modules, {"minimind": fake}),
            patch.dict(os.environ, {"MINIMIND_MODEL_PROFILE": "tiny"}, clear=False),
        ):
            provider = MinimindProvider()
            response = provider.chat("system", "hello")

        self.assertTrue(provider.available)
        self.assertEqual(response, "local response")
        self.assertEqual(calls[0]["profile"]["name"], "tiny")
        self.assertEqual(calls[0]["profile"]["quantization"], "q4")
        self.assertEqual(calls[1]["messages"][0]["role"], "system")

    def test_minimind_architecture_specs_are_embedded(self) -> None:
        from ghostchimera.model_layer.minimind_runtime import (
            MINIMIND_LICENSE,
            MINIMIND_SOURCE_COMMIT,
            get_minimind_architecture,
            list_minimind_architectures,
        )

        spec = get_minimind_architecture("minimind-3")
        names = {item.name for item in list_minimind_architectures()}

        self.assertIn("minimind-3", names)
        self.assertTrue(MINIMIND_SOURCE_COMMIT.startswith("dddedc6"))
        self.assertEqual(MINIMIND_LICENSE, "Apache-2.0")
        self.assertEqual(spec.parameter_count, "64M")
        self.assertEqual(spec.vocab_size, 6400)
        self.assertEqual(spec.max_position_embeddings, 32768)
        self.assertEqual(spec.rope_theta, 1_000_000.0)
        self.assertEqual(spec.num_hidden_layers, 8)
        self.assertEqual(spec.hidden_size, 768)
        self.assertEqual(spec.num_attention_heads, 8)
        self.assertEqual(spec.num_key_value_heads, 4)
        self.assertEqual(spec.head_dim, 96)
        self.assertEqual(spec.intermediate_size, 2432)
        self.assertFalse(spec.uses_moe)

    def test_minimind_inspection_reports_broken_package_without_claiming_inference(self) -> None:
        from ghostchimera.model_layer import minimind_runtime

        fake_spec = ModuleSpec("minimind", loader=None)

        with (
            tempfile.TemporaryDirectory() as state_dir,
            patch.object(minimind_runtime.importlib.util, "find_spec", return_value=fake_spec),
            patch.object(
                minimind_runtime.importlib,
                "import_module",
                side_effect=ModuleNotFoundError("No module named 'matplotlib'"),
            ),
        ):
            inspection = minimind_runtime.inspect_minimind_runtime(state_dir=state_dir)

        self.assertTrue(inspection.architecture_embedded)
        self.assertTrue(inspection.package_found)
        self.assertFalse(inspection.package_importable)
        self.assertFalse(inspection.package_compatible)
        self.assertFalse(inspection.inference_available)
        self.assertIn("matplotlib", inspection.package_error)
        self.assertEqual(inspection.runtime_hint, "embedded-architecture")


if __name__ == "__main__":
    unittest.main()
