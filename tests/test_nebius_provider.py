"""Tests for NebiusProvider (Nebius Token Factory / NVIDIA Nemotron)."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from ghostchimera.model_layer import openai_compatible_providers as ocp


def _fake_chat_response(text: str = "hello from nemotron"):
    resp = MagicMock()
    resp.status = 200
    resp.headers = {}
    resp.read.return_value = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestNebiusProviderInit(unittest.TestCase):
    def test_no_key_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("NEBIUS_API_KEY", None)
            p = ocp.NebiusProvider()
        self.assertFalse(p.available)

    def test_key_sets_available(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "nb-key"}):
            p = ocp.NebiusProvider()
        self.assertTrue(p.available)
        self.assertEqual(p.api_key, "nb-key")

    def test_defaults(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "k"}):
            os.environ.pop("NEBIUS_MODEL", None)
            p = ocp.NebiusProvider()
        self.assertEqual(p.name, "nebius")
        self.assertEqual(p.model, "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        self.assertEqual(p._base_url, "https://api.tokenfactory.nebius.com/v1/chat/completions")

    def test_model_override(self):
        with patch.dict(
            os.environ,
            {"NEBIUS_API_KEY": "k", "NEBIUS_MODEL": "nvidia/nemotron-3-super-120b-a12b"},
        ):
            p = ocp.NebiusProvider()
        self.assertEqual(p.model, "nvidia/nemotron-3-super-120b-a12b")

    def test_profile_injection(self):
        from ghostchimera.model_layer.auth_profiles import AuthProfile
        from ghostchimera.model_layer.openai_compatible_providers import NebiusProvider

        profile = AuthProfile(provider="nebius", api_key="injected", model="nvidia/nemotron-3-super-120b-a12b")
        p = NebiusProvider(profile=profile)
        self.assertEqual(p.api_key, "injected")
        self.assertEqual(p.model, "nvidia/nemotron-3-super-120b-a12b")
        self.assertTrue(p.available)

    def test_validate_config(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("NEBIUS_API_KEY", None)
            p = ocp.NebiusProvider()
        self.assertTrue(any("NEBIUS_API_KEY" in e for e in p.validate_config()))
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "k"}):
            self.assertEqual(ocp.NebiusProvider().validate_config(), [])


class TestNebiusProviderChat(unittest.TestCase):
    def test_chat_posts_to_token_factory(self):
        with patch.dict(
            os.environ,
            {"NEBIUS_API_KEY": "nb-secret", "NEBIUS_MODEL": "nvidia/nemotron-3-super-120b-a12b"},
        ):
            p = ocp.NebiusProvider()
        fake_urlopen = MagicMock(return_value=_fake_chat_response("understood"))
        with patch.object(ocp, "urllib_request") as fake_urllib, patch("ssl.create_default_context"):
            fake_urllib.urlopen = fake_urlopen
            fake_urllib.Request.side_effect = lambda url, data=None, headers=None, method=None: (
                url,
                data,
                headers,
                method,
            )
            result = p.chat("sys", "hello")
        self.assertEqual(result, "understood")
        (url,), kwargs = fake_urllib.Request.call_args
        data, headers, method = kwargs["data"], kwargs["headers"], kwargs["method"]
        self.assertEqual(url, "https://api.tokenfactory.nebius.com/v1/chat/completions")
        self.assertEqual(method, "POST")
        self.assertEqual(headers["Authorization"], "Bearer nb-secret")
        body = json.loads(data.decode("utf-8"))
        self.assertEqual(body["model"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["content"], "hello")

    def test_chat_unavailable_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("NEBIUS_API_KEY", None)
            p = ocp.NebiusProvider()
        with self.assertRaises(RuntimeError):
            p.chat("sys", "hi")


class TestNebiusRegistration(unittest.TestCase):
    def test_registered_in_provider_registries(self):
        from ghostchimera.model_layer.providers import PROVIDERS, TEXT_PROVIDERS, get_provider

        self.assertIn("nebius", PROVIDERS)
        self.assertIn("nebius", TEXT_PROVIDERS)
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "k"}):
            p = get_provider("nebius")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "nebius")

    def test_auth_spec(self):
        from ghostchimera.model_layer.provider_auth import (
            get_provider_auth_spec,
            provider_auth_setup_url,
        )

        spec = get_provider_auth_spec("nebius")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.api_key_env, "NEBIUS_API_KEY")
        self.assertEqual(spec.model_env, "NEBIUS_MODEL")
        self.assertIn("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", spec.models)
        self.assertEqual(provider_auth_setup_url("nebius"), "https://console.nebius.com")

    def test_catalog_entries(self):
        from ghostchimera.model_layer.model_catalog import get_catalog_entry

        nano = get_catalog_entry("nebius", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        sup = get_catalog_entry("nebius", "nvidia/nemotron-3-super-120b-a12b")
        self.assertIsNotNone(nano)
        self.assertIsNotNone(sup)
        self.assertIn("Nemotron 3 Nano", nano.display_name)
        self.assertIn("Nemotron 3 Super", sup.display_name)

    def test_picker_and_wizard_lists(self):
        from ghostchimera.control_plane.model_picker import _MODEL_LISTS, _PROVIDER_DISPLAY

        self.assertIn("nebius", _MODEL_LISTS)
        self.assertIn("nebius", _PROVIDER_DISPLAY)
        from ghostchimera.control_plane.setup_wizard import (
            _PROVIDER_CHOICES,
            _PROVIDER_KEYS,
            _PROVIDER_MODELS,
            _PROVIDER_URLS,
        )

        self.assertTrue(any("Nebius" in c for c in _PROVIDER_CHOICES))
        self.assertEqual(_PROVIDER_KEYS["nebius"], "NEBIUS_API_KEY")
        self.assertIn("nebius", _PROVIDER_MODELS)
        self.assertEqual(_PROVIDER_URLS["nebius"], "https://console.nebius.com")


if __name__ == "__main__":
    unittest.main()
