from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.config import config_to_env_vars
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.model_layer.codex_cli_provider import CodexCliLoginLaunch, CodexCliStatus
from ghostchimera.model_layer.provider_auth import (
    get_provider_auth_spec,
    list_provider_options,
    provider_auth_setup_url,
    provider_auth_summary,
)
from ghostchimera.model_layer.provider_oauth_connectors import OAuthExchangeResult, OAuthLaunchResult


class ProviderAuthCatalogTests(unittest.TestCase):
    def test_catalog_contains_registered_cloud_and_local_providers(self) -> None:
        ids = {option["id"] for option in list_provider_options()}

        for provider in {"openai", "codex_cli", "anthropic", "gemini", "openrouter", "ollama", "lmstudio", "vultr"}:
            self.assertIn(provider, ids)

    def test_openai_reports_codex_oauth_bridge_runtime_activation(self) -> None:
        spec = get_provider_auth_spec("openai")
        self.assertIsNotNone(spec)
        option = spec.to_console_option()
        oauth = [item for item in option["auth_methods"] if item["method"] == "oauth"][0]

        self.assertTrue(option["oauth_supported"])
        self.assertTrue(oauth["supports_runtime_activation"])
        self.assertEqual(oauth["status"], "codex_cli_bridge")
        self.assertIn("ChatGPT", oauth["label"])

    def test_official_provider_oauth_flows_are_advertised(self) -> None:
        cases = {
            "openrouter": "OpenRouter OAuth PKCE",
            "huggingface": "Hugging Face device OAuth",
            "gemini": "Google OAuth / ADC",
        }
        for provider, label in cases.items():
            with self.subTest(provider=provider):
                spec = get_provider_auth_spec(provider)
                self.assertIsNotNone(spec)
                methods = [choice.to_dict() for choice in spec.auth_choices if choice.method == "oauth"]
                self.assertTrue(any(item["label"] == label for item in methods))

    def test_all_builtin_providers_have_setup_urls(self) -> None:
        options = list_provider_options()
        missing = [option["id"] for option in options if not option.get("setup_url")]
        self.assertEqual(missing, [])
        for option in options:
            with self.subTest(provider=option["id"]):
                self.assertTrue(provider_auth_setup_url(option["id"]).startswith("https://"))

    def test_codex_cli_provider_maps_to_env_without_secret(self) -> None:
        env = config_to_env_vars({"model": {"provider": "codex_cli", "model": "gpt-5.1-codex"}})

        self.assertEqual(env["GHOSTCHIMERA_MODEL_PROVIDER"], "codex_cli")
        self.assertEqual(env["CODEX_MODEL"], "gpt-5.1-codex")
        serialized = json.dumps(env)
        self.assertNotIn("auth", serialized.lower())
        self.assertNotIn("token", serialized.lower())

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

    def test_api_key_connect_route_returns_provider_setup_url(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth/connect")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth/connect",
                "headers": {},
                "body": json.dumps({"provider": "groq", "method": "api_key", "launch": True}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "manual_secret_entry")
        self.assertIn("console.groq.com", payload["auth_url"])
        self.assertTrue(payload["policy"]["api_key_only_provider"])
        self.assertFalse(payload["policy"]["token_files_read"])

    @mock.patch("ghostchimera.control_plane.console.get_codex_cli_status")
    def test_oauth_connect_route_uses_codex_cli_status_without_secret(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = CodexCliStatus(
            available=True,
            logged_in=True,
            command="codex",
            detail="Logged in using ChatGPT",
        )
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
        self.assertEqual(payload["status"], "connected")
        self.assertTrue(payload["runtime_activation_supported"])
        self.assertEqual(payload["activation_provider"], "codex_cli")
        self.assertFalse(payload["raw_secret_returned"])
        self.assertTrue(payload["policy"]["no_browser_cookie_scraping"])
        self.assertFalse(payload["policy"]["token_files_read"])

    @mock.patch("ghostchimera.control_plane.console.launch_codex_login_flow")
    @mock.patch("ghostchimera.control_plane.console.get_codex_cli_status")
    def test_oauth_connect_route_can_launch_official_codex_login(
        self,
        status_mock: mock.Mock,
        launch_mock: mock.Mock,
    ) -> None:
        status_mock.return_value = CodexCliStatus(
            available=True,
            logged_in=False,
            command="codex",
            detail="Not logged in",
        )
        launch_mock.return_value = CodexCliLoginLaunch(
            launched=True,
            command="codex login --device-auth",
            detail="Codex login flow launched.",
            pid=1234,
        )
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth/connect")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth/connect",
                "headers": {},
                "body": json.dumps({"provider": "openai", "method": "oauth", "launch": True}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "needs_login")
        self.assertFalse(payload["runtime_activation_supported"])
        self.assertTrue(payload["login_launched"])
        self.assertEqual(payload["login_launch"]["pid"], 1234)
        self.assertFalse(payload["policy"]["token_files_read"])
        launch_mock.assert_called_once_with()

    @mock.patch("ghostchimera.control_plane.console.get_codex_cli_status")
    def test_oauth_cannot_be_made_active_without_codex_login(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = CodexCliStatus(
            available=True,
            logged_in=False,
            command="codex",
            detail="Not logged in",
        )
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
        self.assertIn("Codex CLI is not logged in", payload["error"])
        self.assertNotIn("oauth-secret", json.dumps(payload))

    @mock.patch("ghostchimera.control_plane.console.start_openrouter_pkce")
    def test_openrouter_oauth_connect_returns_pkce_auth_url(self, launch_mock: mock.Mock) -> None:
        launch_mock.return_value = OAuthLaunchResult(
            ok=True,
            provider="openrouter",
            status="authorization_pending",
            message="started",
            auth_url="https://openrouter.ai/auth?callback_url=http%3A%2F%2F127.0.0.1%3A8766",
            pending_id="pending-1",
            runtime_activation_supported=True,
            activation_provider="openrouter",
        )
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth/connect")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth/connect",
                "headers": {"host": "127.0.0.1:8766"},
                "body": json.dumps({"provider": "openrouter", "method": "oauth", "launch": True}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "authorization_pending")
        self.assertEqual(payload["activation_provider"], "openrouter")
        self.assertIn("openrouter.ai/auth", payload["auth_url"])
        self.assertFalse(payload["raw_secret_returned"])
        self.assertFalse(payload["policy"]["token_files_read"])
        launch_mock.assert_called_once()

    @mock.patch("ghostchimera.control_plane.console.exchange_openrouter_code")
    def test_openrouter_callback_stores_key_write_only(self, exchange_mock: mock.Mock) -> None:
        exchange_mock.return_value = OAuthExchangeResult(
            ok=True,
            provider="openrouter",
            api_key="sk-or-oauth-secret",
            status="connected",
            message="connected",
        )
        with tempfile.TemporaryDirectory(prefix="ghostchimera-openrouter-oauth-") as tmp:
            config_path = Path(tmp) / "config.json"
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp, config_path=config_path)
            route = server.routes.find("GET", "/api/console/provider-auth/openrouter/callback")
            self.assertIsNotNone(route)

            response = route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/provider-auth/openrouter/callback",
                    "headers": {},
                    "body": "",
                    "query": {"state": "state-1", "code": "code-1"},
                }
            )

            body = response.body if isinstance(response.body, str) else response.body.decode()
            self.assertEqual(response.status, 200)
            self.assertIn("OpenRouter connected", body)
            self.assertNotIn("sk-or-oauth-secret", body)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["model"]["provider"], "openrouter")
            self.assertEqual(saved["model"]["api_key"], "sk-or-oauth-secret")

    @mock.patch("ghostchimera.control_plane.console.start_huggingface_device_flow")
    def test_huggingface_oauth_connect_returns_device_code(self, launch_mock: mock.Mock) -> None:
        launch_mock.return_value = OAuthLaunchResult(
            ok=True,
            provider="huggingface",
            status="authorization_pending",
            message="started",
            auth_url="https://huggingface.co/oauth/device",
            verification_uri="https://huggingface.co/oauth/device",
            user_code="ABCD-1234",
            pending_id="hf-pending",
            runtime_activation_supported=True,
            activation_provider="huggingface",
        )
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/provider-auth/connect")
        self.assertIsNotNone(route)

        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/provider-auth/connect",
                "headers": {},
                "body": json.dumps({"provider": "huggingface", "method": "oauth", "launch": True}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["user_code"], "ABCD-1234")
        self.assertTrue(payload["poll_supported"])
        self.assertFalse(payload["policy"]["token_files_read"])

    @mock.patch("ghostchimera.control_plane.console.poll_huggingface_device_flow")
    def test_huggingface_oauth_poll_stores_token_write_only(self, poll_mock: mock.Mock) -> None:
        poll_mock.return_value = OAuthExchangeResult(
            ok=True,
            provider="huggingface",
            api_key="hf_oauth_secret",
            status="connected",
            message="connected",
        )
        with tempfile.TemporaryDirectory(prefix="ghostchimera-hf-oauth-") as tmp:
            config_path = Path(tmp) / "config.json"
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp, config_path=config_path)
            route = server.routes.find("POST", "/api/console/provider-auth/oauth/poll")
            self.assertIsNotNone(route)

            payload = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/provider-auth/oauth/poll",
                    "headers": {},
                    "body": json.dumps({"provider": "huggingface", "pending_id": "pending-1"}),
                    "query": {},
                }
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["model"]["provider"], "huggingface")
            self.assertNotIn("hf_oauth_secret", json.dumps(payload))
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["model"]["api_key"], "hf_oauth_secret")

    @mock.patch("ghostchimera.control_plane.console.get_codex_cli_status")
    def test_oauth_active_maps_openai_to_codex_cli_bridge(self, status_mock: mock.Mock) -> None:
        status_mock.return_value = CodexCliStatus(
            available=True,
            logged_in=True,
            command="codex",
            detail="Logged in using ChatGPT",
        )
        with tempfile.TemporaryDirectory(prefix="ghostchimera-codex-oauth-") as tmp:
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
                            "provider": "openai",
                            "method": "oauth",
                            "model": "gpt-5.1-codex",
                            "make_active": True,
                        }
                    ),
                    "query": {},
                }
            )

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["model"]["provider"], "codex_cli")
            self.assertEqual(payload["model"]["model"], "gpt-5.1-codex")
            serialized = json.dumps(payload)
            self.assertNotIn("oauth-secret", serialized)


if __name__ == "__main__":
    unittest.main()
