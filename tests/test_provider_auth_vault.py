from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.config import config_to_env_vars
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.model_layer.provider_auth import (
    get_provider_auth_spec,
    list_provider_options,
    provider_auth_summary,
)


class ProviderAuthCatalogTests(unittest.TestCase):
    def test_catalog_contains_registered_cloud_and_local_providers(self) -> None:
        ids = {option["id"] for option in list_provider_options()}

        for provider in {"openai", "anthropic", "gemini", "openrouter", "ollama", "lmstudio", "vultr"}:
            self.assertIn(provider, ids)

    def test_openai_reports_oauth_without_claiming_runtime_activation(self) -> None:
        spec = get_provider_auth_spec("openai")
        self.assertIsNotNone(spec)
        option = spec.to_console_option()
        oauth = [item for item in option["auth_methods"] if item["method"] == "oauth"][0]

        self.assertTrue(option["oauth_supported"])
        self.assertFalse(oauth["supports_runtime_activation"])
        self.assertIn("ChatGPT", oauth["label"])

    def test_config_to_env_vars_maps_all_openai_compatible_provider_secrets(self) -> None:
        cases = {
            "groq": ("GROQ_API_KEY", "GROQ_MODEL", "llama-3.3-70b-versatile"),
            "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-chat"),
            "mistral": ("MISTRAL_API_KEY", "MISTRAL_MODEL", "mistral-small-latest"),
            "nvidia": ("NVIDIA_API_KEY", "NVIDIA_MODEL", "meta/llama-3.1-70b-instruct"),
            "venice": ("VENICE_API_KEY", "VENICE_MODEL", "llama-3.3-70b"),
        }

        for provider, (key_env, model_env, model_id) in cases.items():
            with self.subTest(provider=provider):
                env = config_to_env_vars(
                    {"model": {"provider": provider, "model": model_id, "api_key": f"{provider}-secret"}}
                )
                self.assertEqual(env["GHOSTCHIMERA_MODEL_PROVIDER"], provider)
                self.assertEqual(env[key_env], f"{provider}-secret")
                self.assertEqual(env[model_env], model_id)

    def test_provider_auth_summary_redacts_by_absence_and_marks_local_no_key(self) -> None:
        summary = provider_auth_summary(
            {
                "model": {"provider": "ollama", "model": "llama3.2"},
                "provider_auth": {"openrouter": {"provider": "openrouter", "api_key": "router-secret"}},
            }
        )

        serialized = json.dumps(summary)
        self.assertNotIn("router-secret", serialized)
        openrouter = next(item for item in summary["providers"] if item["id"] == "openrouter")
        ollama = next(item for item in summary["providers"] if item["id"] == "ollama")
        self.assertTrue(openrouter["api_key_configured"])
        self.assertFalse(ollama["requires_api_key"])
        self.assertTrue(ollama["active"])


class ProviderAuthConsoleRouteTests(unittest.TestCase):
    def test_provider_auth_routes_save_write_only_secret_and_do_not_echo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-provider-auth-") as tmp:
            config_path = Path(tmp) / "config.json"
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp, config_path=config_path)
            route = server.routes.find("POST", "/api/console/provider-auth")
            self.assertIsNotNone(route)

            payload = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/provider-auth",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "provider": "groq",
                            "method": "api_key",
                            "api_key": "groq-secret",
                            "model": "llama-3.3-70b-versatile",
                            "make_active": True,
                        }
                    ),
                    "query": {},
                }
            )

            self.assertTrue(payload["ok"])
            serialized = json.dumps(payload)
            self.assertNotIn("groq-secret", serialized)
            self.assertEqual(payload["model"]["provider"], "groq")
            self.assertTrue(payload["model"]["api_key_configured"])

    def test_oauth_connect_route_is_connector_based_and_secret_safe(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth/connect")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth/connect",
                "headers": {},
                "body": json.dumps({"provider": "openai", "method": "oauth"}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "connector_required")
        self.assertFalse(payload["runtime_activation_supported"])
        self.assertFalse(payload["raw_secret_returned"])
        self.assertTrue(payload["policy"]["no_browser_cookie_scraping"])

    def test_oauth_cannot_be_made_active_without_connector(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth",
                "headers": {},
                "body": json.dumps(
                    {
                        "provider": "openai",
                        "method": "oauth",
                        "oauth_token": "oauth-secret",
                        "make_active": True,
                    }
                ),
                "query": {},
            }
        )

        self.assertFalse(payload["ok"])
        self.assertIn("ExternalAuthProvider", payload["error"])
        self.assertNotIn("oauth-secret", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
