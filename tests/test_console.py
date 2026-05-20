"""Tests for the browser-based Ghost Console control surface."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.chimera_pilot.gateway_server import GatewayServer, HttpResponse
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.control_plane.cli import _main
from ghostchimera.control_plane.console import _default_run_objective, register_console_routes, run_console
from ghostchimera.memory_layer.store import MemoryStore
from ghostchimera.model_layer.model_discovery import save_model_discovery_cache
from ghostchimera.tool_layer.browser_workspace import AgentBrowserWorkspace


class FakeBrowserWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def status(self) -> dict[str, object]:
        return {"available": True, "binary": "agent-browser", "detail": "ready"}

    def open(self, url: str, *, session: str = "default") -> dict[str, object]:
        self.calls.append(("open", {"url": url, "session": session}))
        return {"ok": True, "action": "open", "url": url, "session": session}

    def snapshot(self, *, url: str = "", session: str = "default", interactive: bool = True) -> dict[str, object]:
        self.calls.append(("snapshot", {"url": url, "session": session}))
        return {"ok": True, "action": "snapshot", "output": "@e1 [heading] Example", "session": session}


class FakeModelProvider:
    def validate_config(self) -> list[str]:
        return []

    def chat(self, system_message: str, user_message: str) -> str:
        return "OK compatible"


class ConsoleRouteTests(unittest.TestCase):
    def test_console_registers_browser_ui_and_status_routes(self) -> None:
        server = GatewayServer()
        register_console_routes(server)

        root = server.routes.find("GET", "/")
        status = server.routes.find("GET", "/api/console/status")

        self.assertIsNotNone(root)
        self.assertIsNotNone(status)
        self.assertEqual(root.auth, "open")
        self.assertEqual(status.auth, "open")

        root_response = root.handler({"method": "GET", "path": "/", "headers": {}, "body": "", "query": {}})
        self.assertIsInstance(root_response, HttpResponse)
        self.assertEqual(root_response.content_type, "text/html; charset=utf-8")
        self.assertIn("Ghost Console", root_response.body)

        status_payload = status.handler(
            {"method": "GET", "path": "/api/console/status", "headers": {}, "body": "", "query": {}}
        )
        self.assertTrue(status_payload["ok"])
        self.assertIn("gateway", status_payload)
        self.assertIn("autonomy", status_payload)
        self.assertIn("profiles", status_payload)

    def test_console_browser_route_exposes_existing_https_fetch_tool(self) -> None:
        calls: list[str] = []

        def fetcher(url: str) -> str:
            calls.append(url)
            return "<title>Example</title>"

        server = GatewayServer()
        register_console_routes(server, fetch_url=fetcher)
        route = server.routes.find("POST", "/api/console/browser/fetch")
        self.assertIsNotNone(route)

        missing = route.handler(
            {"method": "POST", "path": "/api/console/browser/fetch", "headers": {}, "body": "{}", "query": {}}
        )
        self.assertFalse(missing["ok"])
        self.assertIn("url", missing["error"])

        result = route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/fetch",
                "headers": {},
                "body": json.dumps({"url": "https://example.com"}),
                "query": {},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], "<title>Example</title>")
        self.assertEqual(calls, ["https://example.com"])

    def test_console_registers_browser_workspace_routes(self) -> None:
        workspace = FakeBrowserWorkspace()
        server = GatewayServer()
        register_console_routes(server, browser_workspace=workspace)

        status_route = server.routes.find("GET", "/api/console/browser/status")
        open_route = server.routes.find("POST", "/api/console/browser/open")
        snapshot_route = server.routes.find("POST", "/api/console/browser/snapshot")

        self.assertIsNotNone(status_route)
        self.assertIsNotNone(open_route)
        self.assertIsNotNone(snapshot_route)
        self.assertTrue(
            status_route.handler(
                {"method": "GET", "path": "/api/console/browser/status", "headers": {}, "body": "", "query": {}}
            )["available"]
        )

        opened = open_route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/open",
                "headers": {},
                "body": json.dumps({"url": "https://example.com", "session": "demo"}),
                "query": {},
            }
        )
        self.assertTrue(opened["ok"])

        snapshot = snapshot_route.handler(
            {
                "method": "POST",
                "path": "/api/console/browser/snapshot",
                "headers": {},
                "body": json.dumps({"url": "https://example.com", "session": "demo"}),
                "query": {},
            }
        )
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["output"], "@e1 [heading] Example")
        self.assertEqual(workspace.calls[0][0], "open")
        self.assertEqual(workspace.calls[1][0], "snapshot")

    def test_console_registers_path_synthesis_routes(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-path-") as tmp:
            config_path = Path(tmp) / "config.json"
            register_console_routes(server, state_dir=tmp, config_path=config_path)

            profiles_route = server.routes.find("GET", "/api/console/paths")
            synthesize_route = server.routes.find("POST", "/api/console/paths/synthesize")
            confirm_route = server.routes.find("POST", "/api/console/paths/confirm-minimind")
            active_route = server.routes.find("GET", "/api/console/paths/active")
            save_route = server.routes.find("POST", "/api/console/paths/active")

            self.assertIsNotNone(profiles_route)
            self.assertIsNotNone(synthesize_route)
            self.assertIsNotNone(confirm_route)
            self.assertIsNotNone(active_route)
            self.assertIsNotNone(save_route)

            profiles = profiles_route.handler(
                {"method": "GET", "path": "/api/console/paths", "headers": {}, "body": "", "query": {}}
            )
            self.assertTrue(profiles["ok"])
            profile_ids = {profile["id"] for profile in profiles["profiles"]}
            self.assertIn("ai-engineer-proxy", profile_ids)
            self.assertIn("marketing-specialist", profile_ids)
            self.assertIn("trader-path", profile_ids)
            self.assertIn("crypto-trader-path", profile_ids)
            marketing = next(profile for profile in profiles["profiles"] if profile["id"] == "marketing-specialist")
            self.assertIn("campaign_assets", marketing["personalization_sources"])

            synthesized = synthesize_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/paths/synthesize",
                    "headers": {},
                    "body": json.dumps(
                        {"profile_id": "virtual-assistant", "preferences": {"training_mode": "dataset_generation"}}
                    ),
                    "query": {},
                }
            )
            self.assertTrue(synthesized["ok"])
            self.assertEqual(synthesized["path"]["role"]["id"], "virtual-assistant")
            self.assertEqual(synthesized["path"]["ghost_blueprint"]["concept"], "personalized AI operator proxy")
            self.assertIn("personal_admin", synthesized["path"]["ghost_blueprint"]["can_operate"])
            self.assertIn("minimind_intake", synthesized["path"])

            confirmed = confirm_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/paths/confirm-minimind",
                    "headers": {},
                    "body": json.dumps(
                        {"profile_id": "ai-engineer-proxy", "preferences": {"training_mode": "dataset_generation"}}
                    ),
                    "query": {},
                }
            )
            self.assertTrue(confirmed["ok"])
            self.assertTrue(confirmed["minimind_intake"]["will_generate_open_source_dataset"])

            saved = save_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/paths/active",
                    "headers": {},
                    "body": json.dumps(
                        {"profile_id": "ai-engineer-proxy", "preferences": {"training_mode": "rag-first"}}
                    ),
                    "query": {},
                }
            )
            active = active_route.handler(
                {"method": "GET", "path": "/api/console/paths/active", "headers": {}, "body": "", "query": {}}
            )
            self.assertTrue(saved["ok"])
            self.assertEqual(active["path"]["profile_id"], "ai-engineer-proxy")

    def test_console_registers_github_routes(self) -> None:
        server = GatewayServer()
        register_console_routes(server)

        status_route = server.routes.find("GET", "/api/console/github/status")
        device_start_route = server.routes.find("POST", "/api/console/github/device/start")
        device_poll_route = server.routes.find("POST", "/api/console/github/device/poll")
        logout_route = server.routes.find("POST", "/api/console/github/logout")
        self_evolution_route = server.routes.find("POST", "/api/console/github/self-evolution/preview")
        plan_route = server.routes.find("POST", "/api/console/github/plan")
        policy_route = server.routes.find("POST", "/api/console/github/policy-simulate")

        self.assertIsNotNone(status_route)
        self.assertIsNotNone(device_start_route)
        self.assertIsNotNone(device_poll_route)
        self.assertIsNotNone(logout_route)
        self.assertIsNotNone(self_evolution_route)
        self.assertIsNotNone(plan_route)
        self.assertIsNotNone(policy_route)

        with patch.dict("os.environ", {"GHOSTCHIMERA_GITHUB_CLIENT_ID": "", "GITHUB_CLIENT_ID": ""}, clear=False):
            status = status_route.handler(
                {"method": "GET", "path": "/api/console/github/status", "headers": {}, "body": "", "query": {}}
            )
            start = device_start_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/github/device/start",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
        self.assertTrue(status["ok"])
        self.assertIn(status["auth_mode"], {"token", "gh-cli"})
        self.assertIn("self_evolution_policy", status)

        self.assertFalse(start["ok"])
        self.assertIn("GHOSTCHIMERA_GITHUB_CLIENT_ID", start["setup"])

        preview = self_evolution_route.handler(
            {
                "method": "POST",
                "path": "/api/console/github/self-evolution/preview",
                "headers": {},
                "body": json.dumps({"materials": ["mcp_servers"], "repos": ["owner/repo"]}),
                "query": {},
            }
        )
        self.assertTrue(preview["ok"])
        self.assertTrue(preview["requires_user_approval"])
        self.assertIn("training on unknown-license material", preview["blocked_actions"])

        planned = plan_route.handler(
            {
                "method": "POST",
                "path": "/api/console/github/plan",
                "headers": {},
                "body": json.dumps({"repo": "owner/repo", "issue": 42, "title": "Fix CI"}),
                "query": {},
            }
        )
        self.assertTrue(planned["ok"])
        self.assertIn("owner/repo#42", planned["objective"])

        policy = policy_route.handler(
            {
                "method": "POST",
                "path": "/api/console/github/policy-simulate",
                "headers": {},
                "body": json.dumps({"action": {"action": "push_branch", "autonomous": True}, "controls": {}}),
                "query": {},
            }
        )
        self.assertFalse(policy["allowed"])

    def test_console_config_route_persists_provider_without_echoing_secret(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-config-ui-") as tmp:
            config_path = Path(tmp) / "config.json"
            register_console_routes(server, state_dir=tmp, config_path=config_path)
            config_route = server.routes.find("GET", "/api/console/config")
            save_route = server.routes.find("POST", "/api/console/config")

            self.assertIsNotNone(config_route)
            self.assertIsNotNone(save_route)

            saved = save_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/config",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "provider": "vultr",
                            "model": "llama-3.1-70b",
                            "base_url": "https://api.vultrinference.com/v1/chat/completions",
                            "api_key": "vultr_secret_key_12345",
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(saved["ok"])
            self.assertTrue(saved["model"]["api_key_configured"])
            self.assertNotIn("vultr_secret_key_12345", json.dumps(saved))
            self.assertEqual(saved["env_preview"]["VULTR_INFERENCE_API_KEY"], "vu...45")
            self.assertTrue((Path(tmp) / ".env").exists())

            loaded = config_route.handler(
                {"method": "GET", "path": "/api/console/config", "headers": {}, "body": "", "query": {}}
            )
            self.assertEqual(loaded["model"]["provider"], "vultr")
            self.assertTrue(loaded["security"]["secrets_are_write_only"])

            rejected = save_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/config",
                    "headers": {},
                    "body": json.dumps({"provider": "not-a-provider", "model": "x"}),
                    "query": {},
                }
            )
            self.assertFalse(rejected["ok"])

            invalid_url = save_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/config",
                    "headers": {},
                    "body": json.dumps({"provider": "vultr", "base_url": "file:///tmp/secret"}),
                    "query": {},
                }
            )
            self.assertFalse(invalid_url["ok"])

            cleared = save_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/config",
                    "headers": {},
                    "body": json.dumps({"provider": "vultr", "clear_api_key": True}),
                    "query": {},
                }
            )
            self.assertTrue(cleared["ok"])
            self.assertFalse(cleared["model"]["api_key_configured"])

    def test_console_model_discovery_routes_cache_and_select_models(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-model-discovery-") as tmp:
            config_path = Path(tmp) / "config.json"
            register_console_routes(server, state_dir=tmp, config_path=config_path)
            list_route = server.routes.find("GET", "/api/console/models/discovery")
            refresh_route = server.routes.find("POST", "/api/console/models/discovery/refresh")
            select_route = server.routes.find("POST", "/api/console/models/discovery/select")
            ping_route = server.routes.find("POST", "/api/console/models/discovery/ping")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(refresh_route)
            self.assertIsNotNone(select_route)
            self.assertIsNotNone(ping_route)

            with patch("ghostchimera.control_plane.console.refresh_model_discovery") as refresh:
                refresh.return_value = {"ok": True, "models": [], "sources": {"openrouter": {"ok": True}}}
                refreshed = refresh_route.handler(
                    {
                        "method": "POST",
                        "path": "/api/console/models/discovery/refresh",
                        "headers": {},
                        "body": json.dumps({"sources": ["openrouter"]}),
                        "query": {},
                    }
                )
            self.assertTrue(refreshed["ok"])
            refresh.assert_called_once()

            save_model_discovery_cache(
                tmp,
                {
                    "version": 1,
                    "sources": {"openrouter": {"ok": True, "source": "openrouter", "count": 1}},
                    "models": {
                        "openrouter": [
                            {
                                "source": "openrouter",
                                "provider": "openrouter",
                                "model_id": "openai/gpt-4o-mini",
                                "display_name": "GPT-4o mini",
                                "description": "Fast compatible model.",
                                "compatibility_status": "needs_key",
                                "capability_badges": ["text", "low-cost"],
                                "modalities": ["text"],
                                "raw_metadata": {},
                            }
                        ]
                    },
                },
            )
            listed = list_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/models/discovery",
                    "headers": {},
                    "body": "",
                    "query": {"capabilities": "low-cost"},
                }
            )
            self.assertTrue(listed["ok"])
            self.assertEqual(listed["model_count"], 1)

            selected = select_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/models/discovery/select",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "source": "openrouter",
                            "provider": "openrouter",
                            "model_id": "openai/gpt-4o-mini",
                        }
                    ),
                    "query": {},
                }
            )
            self.assertFalse(selected["ok"])
            self.assertTrue(selected["admission_required"])
            record_id = selected["admission_record"]["id"]
            approved = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/approve").handler(
                {
                    "method": "POST",
                    "path": f"/api/console/capability-admission/{record_id}/approve",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            activated = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/activate").handler(
                {
                    "method": "POST",
                    "path": f"/api/console/capability-admission/{record_id}/activate",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(approved["ok"])
            self.assertTrue(activated["ok"])

            selected = select_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/models/discovery/select",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "source": "openrouter",
                            "provider": "openrouter",
                            "model_id": "openai/gpt-4o-mini",
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(selected["ok"])
            self.assertEqual(selected["model"]["provider"], "openrouter")
            self.assertEqual(selected["model"]["model"], "openai/gpt-4o-mini")
            self.assertFalse(selected["model"]["api_key_configured"])
            self.assertTrue(selected["security"]["secrets_are_write_only"])
            self.assertEqual(selected["admission_record"]["status"], "active")

            with patch("ghostchimera.control_plane.console.get_provider", return_value=FakeModelProvider()):
                pinged = ping_route.handler(
                    {
                        "method": "POST",
                        "path": "/api/console/models/discovery/ping",
                        "headers": {},
                        "body": json.dumps({"provider": "openrouter", "model_id": "openai/gpt-4o-mini"}),
                        "query": {},
                    }
                )
            self.assertTrue(pinged["ok"])
            self.assertEqual(pinged["reply_preview"], "OK compatible")
            self.assertFalse(pinged["raw_secret_values_returned"])

    def test_console_static_ui_exposes_path_synthesizer(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
        app = (root / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('data-tab="operator"', html)
        self.assertIn('data-tab="path"', html)
        self.assertIn('data-tab="github"', html)
        self.assertIn('data-tab="thinking"', html)
        self.assertIn('data-tab="rag-builder"', html)
        self.assertIn('data-tab="mcp"', html)
        self.assertIn('data-tab="evolution"', html)
        self.assertIn('data-tab="activity"', html)
        self.assertIn('data-tab="latency"', html)
        self.assertIn('data-tab="config"', html)
        self.assertIn("operatorCards", html)
        self.assertIn("setupSteps", html)
        self.assertIn("learningSourceList", html)
        self.assertIn("evolutionCandidateList", html)
        self.assertIn("activityTimeline", html)
        self.assertIn("latencyCards", html)
        self.assertIn("latencyRoutes", html)
        self.assertIn("pathProfile", html)
        self.assertIn("pathConfirmMiniMind", html)
        self.assertIn("configProvider", html)
        self.assertIn("configApiKey", html)
        self.assertIn("modelDiscoveryGrid", html)
        self.assertIn("modelDiscoveryRefresh", html)
        self.assertIn("pathSave", html)
        self.assertIn("githubRepo", html)
        self.assertIn("githubDeviceStart", html)
        self.assertIn("ragBuildPlan", html)
        self.assertIn("mcpEnable", html)
        self.assertIn("discoverSkills", html)
        self.assertIn("githubSelfEvolutionPreview", html)
        self.assertIn("thinkingGraph", html)
        self.assertIn("/api/console/paths", app)
        self.assertIn("/api/console/paths/synthesize", app)
        self.assertIn("/api/console/paths/confirm-minimind", app)
        self.assertIn("/api/console/paths/active", app)
        self.assertIn("Learns from:", app)
        self.assertIn("Operates:", app)
        self.assertIn("/api/console/rag/builder", app)
        self.assertIn("/api/console/mcp/chimeralang/enable", app)
        self.assertIn("/api/console/skills/discover", app)
        self.assertIn("/api/console/github/status", app)
        self.assertIn("/api/console/github/device/start", app)
        self.assertIn("/api/console/github/self-evolution/preview", app)
        self.assertIn("/api/console/github/plan", app)
        self.assertIn("/api/console/thinking", app)
        self.assertIn("/api/console/config", app)
        self.assertIn("/api/console/models/discovery", app)
        self.assertIn("/api/console/models/discovery/refresh", app)
        self.assertIn("/api/console/models/discovery/select", app)
        self.assertIn("/api/console/models/discovery/ping", app)
        self.assertIn("/api/console/operator/summary", app)
        self.assertIn("/api/console/operator/timeline", app)
        self.assertIn("/api/console/operator/latency", app)
        self.assertIn("/api/console/operator/readiness", app)
        self.assertIn("/api/console/evolution/sources", app)
        self.assertIn("/api/console/evolution/candidates", app)
        self.assertIn("Use the Config tab", app)
        self.assertIn("Promise.allSettled", app)

    def test_console_operator_summary_and_timeline_routes(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-operator-") as tmp:
            register_console_routes(server, state_dir=tmp, config_path=Path(tmp) / "config.json")
            summary_route = server.routes.find("GET", "/api/console/operator/summary")
            readiness_route = server.routes.find("POST", "/api/console/operator/readiness")
            timeline_route = server.routes.find("GET", "/api/console/operator/timeline")

            self.assertIsNotNone(summary_route)
            self.assertIsNotNone(readiness_route)
            self.assertIsNotNone(timeline_route)

            summary = summary_route.handler(
                {"method": "GET", "path": "/api/console/operator/summary", "headers": {}, "body": "", "query": {}}
            )
            self.assertTrue(summary["ok"])
            self.assertIn("cards", summary)
            self.assertIn("evolution", summary)
            self.assertIn("production_readiness", summary)
            self.assertEqual(summary["production_readiness"]["status"], "review")
            self.assertTrue(any("trust eval baseline" in warning for warning in summary["warnings"]))
            self.assertTrue(summary["secret_policy"]["secrets_are_write_only"])

            readiness = readiness_route.handler(
                {"method": "POST", "path": "/api/console/operator/readiness", "headers": {}, "body": "{}", "query": {}}
            )
            self.assertTrue(readiness["ok"])

            timeline = timeline_route.handler(
                {"method": "GET", "path": "/api/console/operator/timeline", "headers": {}, "body": "", "query": {}}
            )
            self.assertTrue(timeline["ok"])
            self.assertGreaterEqual(len(timeline["events"]), 1)
            self.assertEqual(timeline["events"][-1]["event_type"], "readiness_check_run")

    def test_console_latency_route_records_api_calls(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-latency-route-") as tmp:
            register_console_routes(server, state_dir=tmp, config_path=Path(tmp) / "config.json")
            status_route = server.routes.find("GET", "/api/console/status")
            latency_route = server.routes.find("GET", "/api/console/operator/latency")

            self.assertIsNotNone(status_route)
            self.assertIsNotNone(latency_route)
            status_route.handler(
                {"method": "GET", "path": "/api/console/status", "headers": {}, "body": "", "query": {}}
            )
            payload = latency_route.handler(
                {"method": "GET", "path": "/api/console/operator/latency", "headers": {}, "body": "", "query": {}}
            )

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["event_count"], 1)
        self.assertIn("p95_ms", payload)
        self.assertTrue(any(route["route"] == "/api/console/status" for route in payload["routes"]))

    def test_console_evolution_source_lifecycle_redacts_secrets(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-evolution-") as tmp:
            register_console_routes(server, state_dir=tmp, config_path=Path(tmp) / "config.json")
            create_route = server.routes.find("POST", "/api/console/evolution/sources")
            approve_route = server.routes.find("POST", "/api/console/evolution/sources/source-id/approve")
            revoke_route = server.routes.find("POST", "/api/console/evolution/sources/source-id/revoke")

            self.assertIsNotNone(create_route)
            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/sources",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "id": "source-id",
                            "source_type": "github_repo",
                            "label": "owner/repo",
                            "uri": "https://github.com/owner/repo",
                            "provenance": {"api_key": "should-not-leak"},
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            self.assertNotIn("should-not-leak", json.dumps(created))
            self.assertEqual(created["source"]["provenance"]["api_key"], "[redacted]")

            approved = approve_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/sources/source-id/approve",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(approved["ok"])
            self.assertEqual(approved["source"]["consent_status"], "approved")

            revoked = revoke_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/sources/source-id/revoke",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(revoked["ok"])
            self.assertEqual(revoked["source"]["consent_status"], "revoked")

    def test_console_evolution_candidate_requires_review_before_promotion(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-candidate-") as tmp:
            register_console_routes(server, state_dir=tmp, config_path=Path(tmp) / "config.json")
            create_route = server.routes.find("POST", "/api/console/evolution/candidates")
            promote_route = server.routes.find("POST", "/api/console/evolution/candidates/candidate-id/promote")
            review_route = server.routes.find("POST", "/api/console/evolution/candidates/candidate-id/review")

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/candidates",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "id": "candidate-id",
                            "candidate_type": "skill_scaffold",
                            "title": "owner/repo",
                            "metadata": {"token": "hidden"},
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            self.assertNotIn("hidden", json.dumps(created))

            blocked = promote_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/candidates/candidate-id/promote",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertFalse(blocked["ok"])

            reviewed = review_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/candidates/candidate-id/review",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(reviewed["ok"])

            promoted = promote_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/candidates/candidate-id/promote",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertFalse(promoted["ok"])
            self.assertTrue(promoted["admission_required"])
            record_id = promoted["admission_record"]["id"]
            approved = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/approve").handler(
                {
                    "method": "POST",
                    "path": f"/api/console/capability-admission/{record_id}/approve",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            activated = server.routes.find("POST", f"/api/console/capability-admission/{record_id}/activate").handler(
                {
                    "method": "POST",
                    "path": f"/api/console/capability-admission/{record_id}/activate",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(approved["ok"])
            self.assertTrue(activated["ok"])

            promoted = promote_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/evolution/candidates/candidate-id/promote",
                    "headers": {},
                    "body": "{}",
                    "query": {},
                }
            )
            self.assertTrue(promoted["ok"])
            self.assertEqual(promoted["candidate"]["status"], "promoted")

    def test_console_registers_thinking_trace_route(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-thinking-") as tmp:
            register_console_routes(server, state_dir=tmp)
            route = server.routes.find("GET", "/api/console/thinking")

            self.assertIsNotNone(route)
            payload = route.handler(
                {"method": "GET", "path": "/api/console/thinking", "headers": {}, "body": "", "query": {}}
            )

        self.assertTrue(payload["ok"])
        self.assertIn("explainability trace", payload["note"])
        self.assertGreaterEqual(len(payload["nodes"]), 8)
        self.assertGreaterEqual(len(payload["edges"]), 7)
        self.assertIn("active_path", payload)

    def test_console_registers_capabilities_route(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("GET", "/api/console/capabilities")

        self.assertIsNotNone(route)
        payload = route.handler(
            {"method": "GET", "path": "/api/console/capabilities", "headers": {}, "body": "", "query": {}}
        )

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["capability_count"], 10)
        self.assertIn("OpenAI Codex", payload["benchmarks"])

    def test_console_registers_pr_review_route(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("POST", "/api/console/review-pr")

        self.assertIsNotNone(route)
        payload = route.handler(
            {
                "method": "POST",
                "path": "/api/console/review-pr",
                "headers": {},
                "body": json.dumps({"base": "HEAD", "head": "HEAD"}),
                "query": {},
            }
        )

        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["file_count"], 0)

    def test_console_browser_workspace_degrades_when_agent_browser_is_missing(self) -> None:
        workspace = AgentBrowserWorkspace(binary="definitely-missing-agent-browser")
        server = GatewayServer()
        register_console_routes(server, browser_workspace=workspace)

        route = server.routes.find("GET", "/api/console/browser/status")
        self.assertIsNotNone(route)
        payload = route.handler(
            {"method": "GET", "path": "/api/console/browser/status", "headers": {}, "body": "", "query": {}}
        )

        self.assertFalse(payload["available"])
        self.assertIn("agent-browser binary not found", payload["detail"])

    def test_console_run_route_validates_objective_and_delegates_to_runner(self) -> None:
        calls: list[str] = []

        def runner(objective: str) -> dict[str, object]:
            calls.append(objective)
            return {"ok": True, "executions": [{"objective": objective, "ok": True}]}

        server = GatewayServer()
        register_console_routes(server, run_objective=runner)
        route = server.routes.find("POST", "/api/console/run")
        self.assertIsNotNone(route)

        missing = route.handler(
            {"method": "POST", "path": "/api/console/run", "headers": {}, "body": "{}", "query": {}}
        )
        self.assertFalse(missing["ok"])
        self.assertIn("objective", missing["error"])
        self.assertEqual(calls, [])

        result = route.handler(
            {
                "method": "POST",
                "path": "/api/console/run",
                "headers": {},
                "body": json.dumps({"objective": "summarize runtime status"}),
                "query": {},
            }
        )
        self.assertTrue(result["ok"])
        self.assertEqual(calls, ["summarize runtime status"])
        self.assertEqual(result["executions"][0]["objective"], "summarize runtime status")

    def test_console_autonomy_route_persists_true_autonomy_toggle(self) -> None:
        with (
            patch("ghostchimera.control_plane.console.load_config", return_value={"autonomy": {"level": "supervised"}}),
            patch("ghostchimera.control_plane.console.save_config") as save_config,
        ):
            server = GatewayServer()
            register_console_routes(server)
            route = server.routes.find("POST", "/api/console/autonomy")
            self.assertIsNotNone(route)
            result = route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy",
                    "headers": {},
                    "body": json.dumps(
                        {"level": "autonomous", "true_autonomy_desktop": True, "personal_context": True}
                    ),
                    "query": {},
                }
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["autonomy"]["config"]["true_autonomy_desktop"])
            saved = save_config.call_args.args[0]
            self.assertTrue(saved["autonomy"]["true_autonomy_desktop"])

    def test_default_run_objective_enables_true_autonomy_desktop_kernel(self) -> None:
        class _Execution:
            def __init__(self, objective: str) -> None:
                self._objective = objective

            def to_dict(self) -> dict[str, object]:
                return {"ok": True, "objective": self._objective}

        class _Kernel:
            def run(self, objective: str) -> list[_Execution]:
                return [_Execution(objective)]

        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-config-") as tmp:
            env = GhostChimeraConfig.from_env()
            config = GhostChimeraConfig(
                state_dir=Path(tmp),
                memory_db=Path(tmp) / "memory.sqlite3",
                audit_file=Path(tmp) / "audit.json",
                policy=env.policy,
                local_model_path="",
                local_model_profile="tiny",
                local_model_gpu_layers=0,
                autonomy_level="supervised",
            )
            with (
                patch(
                    "ghostchimera.control_plane.console.get_autonomy_config",
                    return_value={
                        "level": "autonomous",
                        "true_autonomy_desktop": True,
                        "desktop_max_live_actions": 42,
                        "personal_context": True,
                    },
                ),
                patch("ghostchimera.control_plane.console.load_config", return_value={"autonomy": {}}),
                patch("ghostchimera.control_plane.console.GhostChimeraConfig.from_env", return_value=config),
                patch(
                    "ghostchimera.control_plane.console.ChimeraPilotKernel.default", return_value=_Kernel()
                ) as factory,
            ):
                result = _default_run_objective("open settings and configure sync")
                self.assertTrue(result["ok"])
                kwargs = factory.call_args.kwargs
                self.assertTrue(kwargs["allow_desktop_control"])
                self.assertTrue(kwargs["enable_live_desktop"])
                self.assertEqual(kwargs["ghost_mode"], "possess")
                self.assertEqual(kwargs["desktop_max_live_actions"], 42)
                self.assertTrue(kwargs["enable_personal_context"])

    def test_console_registers_autonomy_job_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            list_route = server.routes.find("GET", "/api/console/autonomy/jobs")
            create_route = server.routes.find("POST", "/api/console/autonomy/jobs")
            detail_route = server.routes.find("GET", "/api/console/autonomy/jobs/job-missing")
            cancel_route = server.routes.find("POST", "/api/console/autonomy/jobs/job-missing/cancel")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(create_route)
            self.assertIsNotNone(detail_route)
            self.assertIsNotNone(cancel_route)

            listed = list_route.handler(
                {"method": "GET", "path": "/api/console/autonomy/jobs", "headers": {}, "body": "", "query": {}}
            )
            self.assertIn("available_jobs", listed)
            self.assertEqual(listed["history"], [])

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/jobs",
                    "headers": {},
                    "body": json.dumps({"job": "repair-preview", "profile": "supervised", "execute": False}),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            self.assertEqual(created["job"]["status"], "preview")

            rejected = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/jobs",
                    "headers": {},
                    "body": json.dumps({"job": "test-regression", "profile": "supervised", "execute": True}),
                    "query": {},
                }
            )
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["type"], "policy")

    def test_console_registers_schedule_routes_that_use_autonomy_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            list_route = server.routes.find("GET", "/api/console/autonomy/schedules")
            create_route = server.routes.find("POST", "/api/console/autonomy/schedules")

            self.assertIsNotNone(list_route)
            self.assertIsNotNone(create_route)

            created = create_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/autonomy/schedules",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "name": "daily audit",
                            "cron_expression": "0 9 * * *",
                            "job": "self-audit",
                            "profile": "autonomous",
                            "enabled": False,
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(created["ok"])
            schedule_id = created["schedule"]["id"]

            run_now = server.routes.find("POST", f"/api/console/autonomy/schedules/{schedule_id}/run-now")
            self.assertIsNotNone(run_now)
            result = run_now.handler(
                {
                    "method": "POST",
                    "path": f"/api/console/autonomy/schedules/{schedule_id}/run-now",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["job"]["name"], "self-audit")

            disabled = list_route.handler(
                {"method": "GET", "path": "/api/console/autonomy/schedules", "headers": {}, "body": "", "query": {}}
            )
            self.assertEqual(disabled["schedules"][0]["enabled"], False)

    def test_console_registers_operator_workspace_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-workspace-") as tmp:
            server = GatewayServer()
            register_console_routes(server, state_dir=tmp)

            workspace_route = server.routes.find("GET", "/api/console/workspace")
            evidence_route = server.routes.find("POST", "/api/console/workspace/evidence")
            reflection_route = server.routes.find("POST", "/api/console/workspace/reflections")
            goal_route = server.routes.find("POST", "/api/console/workspace/goals")
            sync_route = server.routes.find("POST", "/api/console/workspace/sync-memory")

            self.assertIsNotNone(workspace_route)
            self.assertIsNotNone(evidence_route)
            self.assertIsNotNone(reflection_route)
            self.assertIsNotNone(goal_route)
            self.assertIsNotNone(sync_route)

            initial = workspace_route.handler(
                {"method": "GET", "path": "/api/console/workspace", "headers": {}, "body": "", "query": {}}
            )
            self.assertTrue(initial["ok"])
            self.assertIn("no_subjective_consciousness", initial["self_model"]["limits"])

            evidence = evidence_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/workspace/evidence",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "source": "operator",
                            "content": "console workspace route works and state visible",
                            "confidence": 0.93,
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(evidence["ok"])

            reflection = reflection_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/workspace/reflections",
                    "headers": {},
                    "body": json.dumps(
                        {"action": "inspected console", "outcome": "workspace state visible", "confidence": 0.9}
                    ),
                    "query": {},
                }
            )
            self.assertTrue(reflection["ok"])

            goal = goal_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/workspace/goals",
                    "headers": {},
                    "body": json.dumps({"name": "operator_visibility", "description": "show evidence and uncertainty"}),
                    "query": {},
                }
            )
            self.assertTrue(goal["ok"])

            memory_db = f"{tmp}/memory.sqlite3"
            sync = sync_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/workspace/sync-memory",
                    "headers": {},
                    "body": json.dumps({"memory_db": memory_db, "min_confidence": 0.9}),
                    "query": {},
                }
            )
            self.assertTrue(sync["ok"])
            snapshot = workspace_route.handler(
                {"method": "GET", "path": "/api/console/workspace", "headers": {}, "body": "", "query": {}}
            )
            results = MemoryStore(memory_db).search("workspace state visible", limit=5)

        self.assertEqual(snapshot["working_memory"]["evidence"][0]["source"], "operator")
        self.assertEqual(snapshot["working_memory"]["reflections"][0]["outcome"], "workspace state visible")
        self.assertEqual(snapshot["self_model"]["goals"]["operator_visibility"], "show evidence and uncertainty")
        self.assertEqual(sync["synced"], 2)
        self.assertEqual({item["metadata"]["workspace_type"] for item in results}, {"evidence", "reflection"})

    def test_console_registers_memory_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-memory-") as tmp:
            base = Path(tmp)
            env = GhostChimeraConfig.from_env()
            config = GhostChimeraConfig(
                state_dir=base,
                memory_db=base / "memory.sqlite3",
                audit_file=base / "audit.json",
                policy=env.policy,
                local_model_path="",
                local_model_profile="tiny",
                local_model_gpu_layers=0,
                autonomy_level="supervised",
            )
            server = GatewayServer(config=config)
            register_console_routes(server, state_dir=tmp)

            status_route = server.routes.find("GET", "/api/console/memory/status")
            ingest_route = server.routes.find("POST", "/api/console/memory/ingest")
            search_route = server.routes.find("POST", "/api/console/memory/search")
            self.assertIsNotNone(status_route)
            self.assertIsNotNone(ingest_route)
            self.assertIsNotNone(search_route)

            ingested = ingest_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/memory/ingest",
                    "headers": {},
                    "body": json.dumps({"source": "notes", "content": "Remember to file taxes by April."}),
                    "query": {},
                }
            )
            self.assertTrue(ingested["ok"])

            searched = search_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/memory/search",
                    "headers": {},
                    "body": json.dumps({"query": "taxes", "limit": 3}),
                    "query": {},
                }
            )
            self.assertTrue(searched["ok"])
            self.assertTrue(searched["results"])

    def test_console_registers_email_file_ingest_and_training_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-ingest-") as tmp:
            base = Path(tmp)
            env = GhostChimeraConfig.from_env()
            config = GhostChimeraConfig(
                state_dir=base,
                memory_db=base / "memory.sqlite3",
                audit_file=base / "audit.json",
                policy=env.policy,
                local_model_path="",
                local_model_profile="tiny",
                local_model_gpu_layers=0,
                autonomy_level="supervised",
            )
            server = GatewayServer(config=config)
            register_console_routes(server, state_dir=tmp)

            # New routes exist
            email_route = server.routes.find("POST", "/api/console/memory/ingest-email")
            file_route = server.routes.find("POST", "/api/console/memory/ingest-file")
            teach_route = server.routes.find("POST", "/api/console/training/teach")
            train_status_route = server.routes.find("GET", "/api/console/training/status")
            self.assertIsNotNone(email_route)
            self.assertIsNotNone(file_route)
            self.assertIsNotNone(teach_route)
            self.assertIsNotNone(train_status_route)

            # Ingest a raw email
            raw_email = (
                "From: alice@example.com\r\nTo: bob@example.com\r\n"
                "Subject: Tech stack\r\nDate: Mon, 01 Jan 2024 10:00:00 +0000\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n\r\nWe use FastAPI."
            )
            r = email_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/memory/ingest-email",
                    "headers": {},
                    "body": json.dumps({"raw": raw_email}),
                    "query": {},
                }
            )
            self.assertTrue(r["ok"])
            self.assertEqual(r["ingested"], 1)

            # Ingest a text file
            txt = base / "notes.txt"
            txt.write_text("Ghost is local-first.", encoding="utf-8")
            r2 = file_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/memory/ingest-file",
                    "headers": {},
                    "body": json.dumps({"path": str(txt)}),
                    "query": {},
                }
            )
            self.assertTrue(r2["ok"])
            self.assertGreaterEqual(r2["ingested"], 1)

            # Teach Ghost
            r3 = teach_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/training/teach",
                    "headers": {},
                    "body": json.dumps({"prompt": "What is Ghost?", "response": "A local-first agent."}),
                    "query": {},
                }
            )
            self.assertTrue(r3["ok"])
            self.assertGreaterEqual(r3["dataset_count"], 1)

            # Training status
            r4 = train_status_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/training/status",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            self.assertTrue(r4["ok"])
            self.assertIn("dataset_count", r4["status"])
            self.assertGreaterEqual(r4["status"]["dataset_count"], 1)

    def test_console_registers_personal_minimind_routes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-console-minimind-") as tmp:
            base = Path(tmp)
            env = GhostChimeraConfig.from_env()
            config = GhostChimeraConfig(
                state_dir=base,
                memory_db=base / "memory.sqlite3",
                audit_file=base / "audit.json",
                policy=env.policy,
                local_model_path="",
                local_model_profile="tiny",
                local_model_gpu_layers=0,
                autonomy_level="supervised",
            )
            server = GatewayServer(config=config)
            register_console_routes(server, state_dir=tmp)

            status_route = server.routes.find("GET", "/api/console/minimind/personal/status")
            consent_route = server.routes.find("POST", "/api/console/minimind/personal/consent")
            bootstrap_route = server.routes.find("POST", "/api/console/minimind/personal/bootstrap")
            handoff_route = server.routes.find("POST", "/api/console/minimind/personal/handoff")
            self.assertIsNotNone(status_route)
            self.assertIsNotNone(consent_route)
            self.assertIsNotNone(bootstrap_route)
            self.assertIsNotNone(handoff_route)

            initial = status_route.handler(
                {
                    "method": "GET",
                    "path": "/api/console/minimind/personal/status",
                    "headers": {},
                    "body": "",
                    "query": {},
                }
            )
            self.assertFalse(initial["status"]["enabled"])

            note = base / "notes.txt"
            note.write_text("Follow-up: prepare public beta release v0.4.0.", encoding="utf-8")
            consent = consent_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/minimind/personal/consent",
                    "headers": {},
                    "body": json.dumps(
                        {
                            "admin_controls": True,
                            "allow_system_specs": True,
                            "allow_files": True,
                            "allow_email": False,
                            "allow_machine_crawl": True,
                            "allow_email_crawl": False,
                            "allow_autonomy": True,
                            "allow_training": True,
                            "file_paths": [str(note)],
                            "crawl_roots": [str(base)],
                        }
                    ),
                    "query": {},
                }
            )
            self.assertTrue(consent["ok"])
            self.assertTrue(consent["consent"]["allow_machine_crawl"])

            bootstrapped = bootstrap_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/minimind/personal/bootstrap",
                    "headers": {},
                    "body": json.dumps({"include_system_specs": True, "max_files": 10}),
                    "query": {},
                }
            )
            self.assertTrue(bootstrapped["ok"])
            self.assertTrue(bootstrapped["crawl"]["enabled"])
            self.assertGreaterEqual(bootstrapped["bootstrap"]["dataset_records"], 1)

            handoff = handoff_route.handler(
                {
                    "method": "POST",
                    "path": "/api/console/minimind/personal/handoff",
                    "headers": {},
                    "body": json.dumps({"objective": "What beta release work is pending?"}),
                    "query": {},
                }
            )
            self.assertTrue(handoff["ok"])
            self.assertIn("primary_model_prompt", handoff)

    def test_console_readiness_route_returns_release_runbook(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("GET", "/api/console/readiness")

        self.assertIsNotNone(route)
        payload = route.handler(
            {"method": "GET", "path": "/api/console/readiness", "headers": {}, "body": "", "query": {}}
        )

        commands = [check["command"] for check in payload["checks"]]
        self.assertIn("python scripts/validate_release.py", commands)
        self.assertIn("python -m ghostchimera.evals run --suite safety", commands)
        self.assertIn("python -m ghostchimera.evals run --suite user-journey", commands)
        self.assertIn("python scripts/smoke_installed_wheel.py", commands)
        self.assertIn("python scripts/smoke_installed_wheel.py --extras gateway", commands)
        self.assertIn("ghostchimera workspace show", commands)


class ConsoleCliTests(unittest.TestCase):
    def test_cli_delegates_top_level_parallel_commands_from_sys_argv(self) -> None:
        with (
            patch.object(sys, "argv", ["ghostchimera", "run", "inspect status", "--parallel", "1"]),
            patch("ghostchimera.control_plane.parallel_cli._main", return_value=0) as parallel_main,
        ):
            result = _main()

        self.assertEqual(result, 0)
        parallel_main.assert_called_once_with(["run", "inspect status", "--parallel", "1"])

    def test_cli_delegates_top_level_batch_command_from_sys_argv(self) -> None:
        with (
            patch.object(sys, "argv", ["ghostchimera", "batch", "objectives.jsonl", "--workers", "2"]),
            patch("ghostchimera.control_plane.parallel_cli._main", return_value=0) as parallel_main,
        ):
            result = _main()

        self.assertEqual(result, 0)
        parallel_main.assert_called_once_with(["batch", "objectives.jsonl", "--workers", "2"])

    def test_cli_does_not_delegate_nested_autonomy_run_to_parallel_cli(self) -> None:
        with (
            patch("ghostchimera.control_plane.parallel_cli._main", return_value=99) as parallel_main,
            patch("ghostchimera.control_plane.cli._run_autonomy_cli", return_value=0) as autonomy_main,
        ):
            result = _main(["autonomy", "run", "repair-preview"])

        self.assertEqual(result, 0)
        parallel_main.assert_not_called()
        autonomy_main.assert_called_once()

    def test_run_console_registers_routes_without_blocking(self) -> None:
        server = run_console(host="127.0.0.1", port=0, http_port=0, open_browser=False, block=False)
        try:
            self.assertIsNotNone(server.routes.find("GET", "/"))
            self.assertIsNotNone(server.routes.find("GET", "/api/console/status"))
        finally:
            server.stop()

    def test_console_token_route_advertises_auth_state(self) -> None:
        # Without token: auth_enabled is False
        server = GatewayServer()
        register_console_routes(server)
        token_route = server.routes.find("GET", "/api/console/token")
        self.assertIsNotNone(token_route)
        self.assertEqual(token_route.auth, "open")
        payload = token_route.handler(
            {"method": "GET", "path": "/api/console/token", "headers": {}, "body": "", "query": {}}
        )
        self.assertFalse(payload["auth_enabled"])

        # With token: auth_enabled is True, and API routes require the token
        server2 = GatewayServer()
        register_console_routes(server2, console_token="test-secret")
        token_route2 = server2.routes.find("GET", "/api/console/token")
        self.assertEqual(token_route2.auth, "open")
        payload2 = token_route2.handler(
            {"method": "GET", "path": "/api/console/token", "headers": {}, "body": "", "query": {}}
        )
        self.assertTrue(payload2["auth_enabled"])

        # API routes should require token auth
        status_route = server2.routes.find("GET", "/api/console/status")
        self.assertIsNotNone(status_route)
        self.assertEqual(status_route.auth, "token")
        self.assertEqual(status_route.token, "test-secret")

    def test_cli_console_dispatches_auth_token_to_run_console(self) -> None:
        with patch("ghostchimera.control_plane.console.run_console") as mocked:
            mocked.return_value = object()
            result = _main(["console", "--no-open", "--auth-token", "mysecret"])

        self.assertEqual(result, 0)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["auth_token"], "mysecret")

    def test_cli_console_dispatches_to_run_console(self) -> None:
        with patch("ghostchimera.control_plane.console.run_console") as mocked:
            mocked.return_value = object()
            result = _main(
                [
                    "console",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "9001",
                    "--http-port",
                    "9002",
                    "--state-dir",
                    "C:/tmp/ghost-state",
                    "--no-open",
                ]
            )

        self.assertEqual(result, 0)
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["host"], "127.0.0.1")
        self.assertEqual(kwargs["port"], 9001)
        self.assertEqual(kwargs["http_port"], 9002)
        self.assertEqual(kwargs["state_dir"], "C:/tmp/ghost-state")
        self.assertFalse(kwargs["open_browser"])
        self.assertTrue(kwargs["block"])

    def test_console_skills_route_returns_skill_list(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        route = server.routes.find("GET", "/api/console/skills")
        self.assertIsNotNone(route)
        result = route.handler({"method": "GET", "path": "/api/console/skills", "headers": {}, "body": "", "query": {}})
        self.assertIn("ok", result)
        self.assertIn("skills", result)
        self.assertIsInstance(result["skills"], list)

    def test_console_skills_discovery_can_generate_compatibility_skill(self) -> None:
        server = GatewayServer()
        with (
            tempfile.TemporaryDirectory(prefix="ghostchimera-skill-discovery-") as tmp,
            patch.dict("os.environ", {"GHOSTCHIMERA_SKILLS_DIR": str(Path(tmp) / "skills")}, clear=False),
        ):
            register_console_routes(server, state_dir=tmp)
            route = server.routes.find("POST", "/api/console/skills/discover")
            self.assertIsNotNone(route)
            with patch(
                "ghostchimera.integrations.github_client.GitHubClient.get_json",
                return_value={
                    "items": [
                        {
                            "full_name": "octo-org/sample-skill",
                            "html_url": "https://github.com/octo-org/sample-skill",
                            "description": "sample skill",
                            "language": "Python",
                            "stargazers_count": 42,
                            "default_branch": "main",
                        }
                    ]
                },
            ):
                result = route.handler(
                    {
                        "method": "POST",
                        "path": "/api/console/skills/discover",
                        "headers": {},
                        "body": json.dumps({"query": "sample skill", "install": True, "limit": 1}),
                        "query": {},
                    }
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["installed_count"], 1)
            self.assertTrue(Path(result["installed"][0]["path"]).exists())

    def test_console_registers_rag_builder_and_mcp_routes(self) -> None:
        server = GatewayServer()
        register_console_routes(server)
        rag_status = server.routes.find("GET", "/api/console/rag/builder/status")
        rag_build = server.routes.find("POST", "/api/console/rag/builder")
        mcp_status = server.routes.find("GET", "/api/console/mcp/status")
        self.assertIsNotNone(rag_status)
        self.assertIsNotNone(rag_build)
        self.assertIsNotNone(mcp_status)
        rag_status_payload = rag_status.handler(
            {"method": "GET", "path": "/api/console/rag/builder/status", "headers": {}, "body": "", "query": {}}
        )
        self.assertTrue(rag_status_payload["ok"])
        self.assertIn("status", rag_status_payload)
        mcp_status_payload = mcp_status.handler(
            {"method": "GET", "path": "/api/console/mcp/status", "headers": {}, "body": "", "query": {}}
        )
        self.assertTrue(mcp_status_payload["ok"])
        self.assertIn("registered", mcp_status_payload)
        self.assertIn("enabled", mcp_status_payload)

    def test_index_html_includes_skills_tab(self) -> None:
        from pathlib import Path

        html_path = Path(__file__).parent.parent / "ghostchimera" / "control_plane" / "static" / "index.html"
        if not html_path.exists():
            self.skipTest("index.html not found")
        html = html_path.read_text(encoding="utf-8")
        self.assertIn("tab-skills", html)
        self.assertIn("Skills", html)
        self.assertIn("tab-rag-builder", html)
        self.assertIn("tab-mcp", html)


if __name__ == "__main__":
    unittest.main()
