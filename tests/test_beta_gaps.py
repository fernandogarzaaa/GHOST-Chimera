"""Tests for all 10 OpenClaw gap-closure components (v0.3.0-beta).

Covers:
  Gap 1  — Media provider interfaces
  Gap 2  — Approval flow + new HookName entries
  Gap 3  — Tool result middleware pipeline
  Gap 4  — Skill metadata enrichment
  Gap 5  — BackgroundService + ServiceRegistry
  Gap 6  — HTTP route registry in GatewayServer
  Gap 7  — Plugin manifest format
  Gap 8  — ExternalAuthProvider + CredentialPool.register_auth_provider
  Gap 9  — SSRF / network policy dispatcher + PilotPolicy.allowed_hosts
  Gap 10 — PROVIDERS split by type
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Gap 1 — Media provider interfaces
# ---------------------------------------------------------------------------


class MediaProviderTests(unittest.TestCase):
    def test_stdlib_web_fetch_import(self) -> None:
        from ghostchimera.model_layer.media_providers import StdlibWebFetchProvider
        p = StdlibWebFetchProvider()
        self.assertTrue(p.available)

    def test_openai_image_provider_requires_key(self) -> None:
        from ghostchimera.model_layer.media_providers import OpenAIImageProvider
        with patch.dict(os.environ, {}, clear=True):
            p = OpenAIImageProvider()
        self.assertFalse(p.available)
        self.assertIn("OPENAI_API_KEY", p.validate_config()[0])

    def test_openai_speech_provider_requires_key(self) -> None:
        from ghostchimera.model_layer.media_providers import OpenAISpeechProvider
        with patch.dict(os.environ, {}, clear=True):
            p = OpenAISpeechProvider()
        self.assertFalse(p.available)

    def test_openai_vision_provider_requires_key(self) -> None:
        from ghostchimera.model_layer.media_providers import OpenAIVisionProvider
        with patch.dict(os.environ, {}, clear=True):
            p = OpenAIVisionProvider()
        self.assertFalse(p.available)

    def test_get_media_provider_known(self) -> None:
        from ghostchimera.model_layer.media_providers import get_media_provider
        p = get_media_provider("web_fetch", "stdlib_web_fetch")
        self.assertIsNotNone(p)

    def test_get_media_provider_unknown_returns_none(self) -> None:
        from ghostchimera.model_layer.media_providers import get_media_provider
        result = get_media_provider("image_generation", "nonexistent_provider")
        self.assertIsNone(result)

    def test_register_media_provider(self) -> None:
        from ghostchimera.model_layer.media_providers import (
            MEDIA_PROVIDERS,
            WebSearchProvider,
            get_media_provider,
            register_media_provider,
        )

        class MySearch(WebSearchProvider):
            name = "test_search"
            def __init__(self, profile=None): self.available = True
            def search(self, query, **kwargs): return []

        register_media_provider("web_search", "test_search", MySearch)
        result = get_media_provider("web_search", "test_search")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, MySearch)
        # cleanup
        del MEDIA_PROVIDERS["web_search"]["test_search"]

    def test_image_result_ok(self) -> None:
        from ghostchimera.model_layer.media_providers import ImageResult
        self.assertTrue(ImageResult(url="https://example.com/img.png").ok)
        self.assertFalse(ImageResult().ok)

    def test_web_fetch_result_ok(self) -> None:
        from ghostchimera.model_layer.media_providers import WebFetchResult
        self.assertTrue(WebFetchResult(url="x", status_code=200).ok)
        self.assertFalse(WebFetchResult(url="x", status_code=404).ok)


# ---------------------------------------------------------------------------
# Gap 2 — Approval flow + new HookName entries
# ---------------------------------------------------------------------------


class ApprovalFlowTests(unittest.TestCase):
    def test_auto_approve_handler(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalRequest, AutoApproveHandler
        handler = AutoApproveHandler()
        result = handler.handle(ApprovalRequest(tool_name="shell", arguments={"cmd": "ls"}))
        self.assertTrue(result.approved)

    def test_auto_deny_handler(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalRequest, AutoDenyHandler
        handler = AutoDenyHandler()
        result = handler.handle(ApprovalRequest(tool_name="shell", arguments={}))
        self.assertFalse(result.approved)

    def test_trusted_tool_bypasses_deny(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalPolicy, ApprovalRequest, AutoDenyHandler
        policy = ApprovalPolicy()
        handler = AutoDenyHandler(policy)
        result = handler.handle(ApprovalRequest(tool_name="read_file"))
        self.assertTrue(result.approved)  # read_file is trusted by default

    def test_blocked_tool_denied(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalPolicy, ApprovalRequest, AutoApproveHandler
        policy = ApprovalPolicy()
        handler = AutoApproveHandler(policy)
        result = handler.handle(ApprovalRequest(tool_name="delete_all"))
        self.assertFalse(result.approved)  # matches "delete_*" blocked pattern

    def test_callback_handler_approval(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalRequest, CallbackApprovalHandler
        handler = CallbackApprovalHandler(callback=lambda req: True)
        result = handler.handle(ApprovalRequest(tool_name="shell"))
        self.assertTrue(result.approved)

    def test_approval_policy_glob(self) -> None:
        from ghostchimera.safety_layer.approval import ApprovalPolicy
        policy = ApprovalPolicy()
        policy.add_trusted("my_tool_*")
        self.assertEqual(policy.classify("my_tool_alpha"), "trusted")
        self.assertEqual(policy.classify("other_tool"), "requires_approval")

    def test_approve_convenience(self) -> None:
        from ghostchimera.safety_layer import approval

        # override default handler to auto-approve
        from ghostchimera.safety_layer.approval import AutoApproveHandler, set_default_handler
        set_default_handler(AutoApproveHandler())
        result = approval.approve("shell", {"cmd": "ls"})
        self.assertTrue(result.approved)

    def test_new_hook_names_exist(self) -> None:
        from ghostchimera.chimera_pilot.hooks import HookName
        self.assertEqual(HookName.BEFORE_TOOL_CALL, "before_tool_call")
        self.assertEqual(HookName.AFTER_TOOL_CALL, "after_tool_call")
        self.assertEqual(HookName.LLM_INPUT, "llm_input")
        self.assertEqual(HookName.LLM_OUTPUT, "llm_output")

    def test_hook_registry_fires_new_hooks(self) -> None:
        from ghostchimera.chimera_pilot.hooks import HookName, HookRegistry
        registry = HookRegistry()
        fired = []
        registry.register_hook(HookName.BEFORE_TOOL_CALL, lambda **kw: fired.append(kw))
        registry.fire(HookName.BEFORE_TOOL_CALL, tool_name="shell", arguments={}, session_id="s1", requester="agent")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["tool_name"], "shell")


# ---------------------------------------------------------------------------
# Gap 3 — Tool result middleware pipeline
# ---------------------------------------------------------------------------


class ToolMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import reset_default_chain
        reset_default_chain()

    def test_truncate_middleware(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import TruncateMiddleware
        mw = TruncateMiddleware(max_chars=10)
        result = mw.transform("shell", "hello world!", {})
        self.assertIn("[truncated", result)
        self.assertLessEqual(len(result), 60)  # truncated message appended

    def test_truncate_short_string_unchanged(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import TruncateMiddleware
        mw = TruncateMiddleware(max_chars=100)
        result = mw.transform("shell", "hello", {})
        self.assertEqual(result, "hello")

    def test_json_normalizer(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import JsonNormalizerMiddleware
        mw = JsonNormalizerMiddleware()
        result = mw.transform("tool", {"key": "value"}, {})
        self.assertIsInstance(result, str)
        self.assertIn("key", result)

    def test_error_wrapper(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import ErrorWrapperMiddleware
        mw = ErrorWrapperMiddleware()
        exc = ValueError("bad input")
        result = mw.transform("tool", exc, {})
        self.assertIn("Tool error", result)
        self.assertIn("ValueError", result)

    def test_chain_runs_in_order(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import ToolMiddlewareChain, ToolResultMiddleware
        order = []

        class A(ToolResultMiddleware):
            name = "a"
            def transform(self, t, r, ctx):
                order.append("a")
                return r + "A"

        class B(ToolResultMiddleware):
            name = "b"
            def transform(self, t, r, ctx):
                order.append("b")
                return r + "B"

        chain = ToolMiddlewareChain()
        chain.add(A())
        chain.add(B())
        result = chain.run("tool", "x")
        self.assertEqual(result, "xAB")
        self.assertEqual(order, ["a", "b"])

    def test_chain_exception_does_not_propagate(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import ToolMiddlewareChain, ToolResultMiddleware

        class Exploder(ToolResultMiddleware):
            name = "exploder"
            def transform(self, t, r, ctx):
                raise RuntimeError("boom")

        chain = ToolMiddlewareChain()
        chain.add(Exploder())
        # Should not raise — returns original value
        result = chain.run("tool", "input")
        self.assertEqual(result, "input")

    def test_default_chain_singleton(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import get_default_chain
        c1 = get_default_chain()
        c2 = get_default_chain()
        self.assertIs(c1, c2)
        self.assertGreater(len(c1), 0)  # pre-populated

    def test_toolset_manager_register_middleware(self) -> None:
        from ghostchimera.chimera_pilot.tool_middleware import ToolResultMiddleware, get_default_chain
        from ghostchimera.chimera_pilot.toolsets import ToolsetManager

        class TestMW(ToolResultMiddleware):
            name = "test_mw"
            def transform(self, t, r, ctx):
                return r

        manager = ToolsetManager()
        before = len(get_default_chain())
        manager.register_result_middleware(TestMW())
        self.assertEqual(len(get_default_chain()), before + 1)


# ---------------------------------------------------------------------------
# Gap 4 — Skill metadata enrichment
# ---------------------------------------------------------------------------


class SkillMetadataTests(unittest.TestCase):
    def test_skill_default_metadata(self) -> None:
        from ghostchimera.skill_layer.base import Skill

        class MySkill(Skill):
            name = "my_skill"
            description = "Test"
            actions = ["run"]
            requires_env = ["MY_API_KEY"]
            requires_bins = ["git"]
            version = "1.2.3"
            primary_env = "MY_API_KEY"

            def run(self, task): return "ok"

        skill = MySkill()
        self.assertEqual(skill.version, "1.2.3")
        self.assertEqual(skill.primary_env, "MY_API_KEY")

    def test_check_requirements_missing_env(self) -> None:
        from ghostchimera.skill_layer.base import Skill

        class MySkill(Skill):
            name = "env_skill"
            requires_env = ["NONEXISTENT_VAR_XYZ123"]
            def run(self, task): return None

        with patch.dict(os.environ, {}, clear=True):
            problems = MySkill().check_requirements()
        self.assertTrue(any("NONEXISTENT_VAR_XYZ123" in p for p in problems))

    def test_check_requirements_missing_bin(self) -> None:
        from ghostchimera.skill_layer.base import Skill

        class MySkill(Skill):
            name = "bin_skill"
            requires_bins = ["nonexistent_binary_xyz123"]
            def run(self, task): return None

        problems = MySkill().check_requirements()
        self.assertTrue(any("nonexistent_binary_xyz123" in p for p in problems))

    def test_check_requirements_all_ok(self) -> None:
        from ghostchimera.skill_layer.base import Skill

        class MySkill(Skill):
            name = "ok_skill"
            requires_env: list = []
            requires_bins: list = []
            def run(self, task): return None

        problems = MySkill().check_requirements()
        self.assertEqual(problems, [])


# ---------------------------------------------------------------------------
# Gap 5 — BackgroundService + ServiceRegistry
# ---------------------------------------------------------------------------


class BackgroundServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import reset_registry
        reset_registry()

    def _make_service(self, sid: str, ok: bool = True):
        from ghostchimera.chimera_pilot.service_registry import BackgroundService, ServiceHealth

        class _Svc(BackgroundService):
            service_id = sid
            service_name = f"Service {sid}"
            _started = False
            _stopped = False

            def start(self) -> None:
                self._started = True

            def stop(self) -> None:
                self._stopped = True

            def probe(self) -> ServiceHealth:
                return ServiceHealth(ok=ok, state="running" if self._started else "stopped")

        return _Svc()

    def test_register_and_get(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import get_registry
        svc = self._make_service("test_a")
        reg = get_registry()
        reg.register(svc)
        found = reg.get("test_a")
        self.assertIs(found, svc)

    def test_start_stop_all(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import get_registry
        svc = self._make_service("test_b")
        reg = get_registry()
        reg.register(svc)
        results = reg.start_all()
        self.assertTrue(results["test_b"])
        self.assertTrue(svc._started)
        reg.stop_all()
        self.assertTrue(svc._stopped)

    def test_probe_all(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import get_registry
        svc = self._make_service("test_c", ok=True)
        reg = get_registry()
        reg.register(svc)
        reg.start_all()
        health = reg.probe_all()
        self.assertIn("test_c", health)
        self.assertTrue(health["test_c"].ok)

    def test_deregister(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import get_registry
        svc = self._make_service("test_d")
        reg = get_registry()
        reg.register(svc)
        self.assertTrue(reg.deregister("test_d"))
        self.assertIsNone(reg.get("test_d"))

    def test_cron_scheduler_implements_background_service(self) -> None:
        from ghostchimera.chimera_pilot.service_registry import BackgroundService
        try:
            from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler
            self.assertTrue(issubclass(CronScheduler, BackgroundService))
        except ImportError:
            self.skipTest("croniter not installed")

    def test_cron_scheduler_probe(self) -> None:
        try:
            from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler
        except ImportError:
            self.skipTest("croniter not installed")
        sched = CronScheduler()
        health = sched.probe()
        self.assertFalse(health.ok)  # not started yet
        self.assertIn("job_count", health.details)


# ---------------------------------------------------------------------------
# Gap 6 — HTTP route registry
# ---------------------------------------------------------------------------


class HttpRouteRegistryTests(unittest.TestCase):
    def test_register_and_find_route(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import HttpRouteRegistry

        registry = HttpRouteRegistry()
        registry.register("/test", lambda ctx: {"ok": True}, method="GET", auth="open")

        route = registry.find("GET", "/test")
        self.assertIsNotNone(route)
        self.assertEqual(route.path, "/test")

    def test_route_not_found(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import HttpRouteRegistry
        registry = HttpRouteRegistry()
        self.assertIsNone(registry.find("GET", "/missing"))

    def test_method_filter(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import HttpRouteRegistry
        registry = HttpRouteRegistry()
        registry.register("/post-only", lambda ctx: {}, method="POST", auth="open")
        self.assertIsNone(registry.find("GET", "/post-only"))
        self.assertIsNotNone(registry.find("POST", "/post-only"))

    def test_prefix_matching(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import HttpRouteRegistry
        registry = HttpRouteRegistry()
        registry.register("/api/", lambda ctx: {}, prefix=True, auth="open")
        self.assertIsNotNone(registry.find("GET", "/api/anything"))
        self.assertIsNone(registry.find("GET", "/other"))

    def test_open_auth_always_passes(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import HttpRoute, HttpRouteRegistry
        registry = HttpRouteRegistry()
        route = HttpRoute(path="/open", handler=lambda ctx: {}, auth="open")
        self.assertTrue(registry.check_auth(route, {}))

    def test_gateway_server_has_builtin_routes(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import GatewayServer
        server = GatewayServer()
        routes = server.routes.list_all()
        paths = [r["path"] for r in routes]
        self.assertIn("/health", paths)
        self.assertIn("/status", paths)

    def test_gateway_server_register_route(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import GatewayServer
        server = GatewayServer()
        server.register_route("/custom", lambda ctx: {"custom": True}, method="GET", auth="open")
        route = server.routes.find("GET", "/custom")
        self.assertIsNotNone(route)
        result = route.handler({})
        self.assertTrue(result["custom"])

    def test_gateway_server_implements_background_service(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import GatewayServer
        from ghostchimera.chimera_pilot.service_registry import BackgroundService
        self.assertTrue(issubclass(GatewayServer, BackgroundService))

    def test_gateway_server_probe_not_running(self) -> None:
        from ghostchimera.chimera_pilot.gateway_server import GatewayServer
        server = GatewayServer()
        health = server.probe()
        self.assertFalse(health.ok)  # not started


# ---------------------------------------------------------------------------
# Gap 7 — Plugin manifest format
# ---------------------------------------------------------------------------


class PluginManifestTests(unittest.TestCase):
    def _make_manifest_file(self, tmp_dir: Path, data: dict) -> Path:
        plugin_dir = tmp_dir / data["id"]
        plugin_dir.mkdir(parents=True)
        manifest_file = plugin_dir / "plugin.json"
        with open(manifest_file, "w") as f:
            json.dump(data, f)
        return plugin_dir

    def test_from_dict(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginManifest
        m = PluginManifest.from_dict({
            "id": "test-plugin",
            "name": "Test Plugin",
            "version": "1.0.0",
            "contracts": {"tools": ["tool_a", "tool_b"]},
        })
        self.assertEqual(m.id, "test-plugin")
        self.assertEqual(m.contracts.tools, ["tool_a", "tool_b"])

    def test_enable_disable(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginManifest
        m = PluginManifest.from_dict({"id": "p1", "name": "P1"})
        self.assertFalse(m.is_active)
        m.enable()
        self.assertTrue(m.is_active)
        m.disable()
        self.assertFalse(m.is_active)

    def test_check_env_requirements(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginManifest
        m = PluginManifest.from_dict({
            "id": "env-plugin",
            "name": "Env Plugin",
            "setup": {"providers": [{"id": "my_provider", "envVars": ["MY_SECRET_VAR_XYZ"]}]},
        })
        with patch.dict(os.environ, {}, clear=True):
            problems = m.check_env_requirements()
        self.assertTrue(any("MY_SECRET_VAR_XYZ" in p for p in problems))

    def test_loader_discover_empty_dir(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginLoader, reset_loader
        reset_loader()
        with tempfile.TemporaryDirectory() as tmp:
            loader = PluginLoader(plugins_dir=tmp)
            manifests = loader.discover()
        self.assertEqual(manifests, [])

    def test_loader_discover_valid_plugin(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginLoader, reset_loader
        reset_loader()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._make_manifest_file(tmp_path, {"id": "my-plugin", "name": "My Plugin", "version": "0.1.0"})
            loader = PluginLoader(plugins_dir=tmp_path)
            manifests = loader.discover()
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].id, "my-plugin")

    def test_loader_enable_disable(self) -> None:
        from ghostchimera.chimera_pilot.plugin_manifest import PluginLoader, reset_loader
        reset_loader()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._make_manifest_file(tmp_path, {"id": "toggle-plugin", "name": "Toggle"})
            loader = PluginLoader(plugins_dir=tmp_path)
            loader.discover()
            self.assertFalse(loader.get("toggle-plugin").is_active)
            loader.enable("toggle-plugin")
            self.assertTrue(loader.get("toggle-plugin").is_active)
            loader.disable("toggle-plugin")
            self.assertFalse(loader.get("toggle-plugin").is_active)


# ---------------------------------------------------------------------------
# Gap 8 — ExternalAuthProvider + CredentialPool integration
# ---------------------------------------------------------------------------


class ExternalAuthProviderTests(unittest.TestCase):
    def test_abstract_interface_exists(self) -> None:
        from ghostchimera.model_layer.auth_profiles import ExternalAuthProvider
        # Should not be directly instantiable
        with self.assertRaises(TypeError):
            ExternalAuthProvider()  # type: ignore

    def test_concrete_external_auth_provider(self) -> None:
        from ghostchimera.model_layer.auth_profiles import AuthProfile, ExternalAuthProvider, OAuthCredential

        class MyAuth(ExternalAuthProvider):
            provider_id = "my_service"

            def authorize(self, scope=""):
                return AuthProfile(provider="my_service", auth_kind="oauth", oauth_token="tok123")

            def refresh(self, credential):
                return OAuthCredential(
                    token="tok_refreshed",
                    expires_at=time.time() + 3600,
                )

        auth = MyAuth()
        profile = auth.authorize()
        self.assertEqual(profile.oauth_token, "tok123")

    def test_credential_pool_register_auth_provider(self) -> None:
        from ghostchimera.chimera_pilot.credential_pool import CredentialPool
        from ghostchimera.model_layer.auth_profiles import AuthProfile, ExternalAuthProvider, OAuthCredential

        class FakeAuth(ExternalAuthProvider):
            provider_id = "fake"
            def authorize(self, scope=""): return AuthProfile(provider="fake")
            def refresh(self, cred):
                return OAuthCredential(token="refreshed!", expires_at=time.time() + 3600)

        pool = CredentialPool()
        pool.add_credential("fake", api_key="", oauth_token="expired_token",
                            expires_at=time.time() - 1)
        pool.register_auth_provider("fake", FakeAuth())
        new_entry = pool.refresh_credential("fake")
        self.assertIsNotNone(new_entry)
        self.assertEqual(new_entry.oauth_token, "refreshed!")

    def test_refresh_credential_no_provider_returns_none(self) -> None:
        from ghostchimera.chimera_pilot.credential_pool import CredentialPool
        pool = CredentialPool()
        pool.add_credential("no_auth", api_key="key")
        result = pool.refresh_credential("no_auth")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Gap 9 — SSRF / network policy dispatcher
# ---------------------------------------------------------------------------


class SSRFPolicyTests(unittest.TestCase):
    def test_block_private_loopback(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy(block_private_ranges=True)
        permitted, reason = policy.is_permitted("http://127.0.0.1/api")
        self.assertFalse(permitted)
        self.assertIn("loopback", reason.lower())

    def test_allow_listed_host(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy()
        policy.allow_host("api.openai.com")
        permitted, reason = policy.is_permitted("https://api.openai.com/v1/models")
        self.assertTrue(permitted)

    def test_denied_host(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy(default_allow=True)
        policy.deny_host("evil.example.com")
        permitted, reason = policy.is_permitted("https://evil.example.com/hack")
        self.assertFalse(permitted)

    def test_default_deny_unmatched(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy(default_allow=False)
        permitted, _ = policy.is_permitted("https://unknown.host.example.com/")
        self.assertFalse(permitted)

    def test_allow_all(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy(allow_all=True)
        permitted, _ = policy.is_permitted("https://anything.example.com/")
        self.assertTrue(permitted)

    def test_glob_pattern(self) -> None:
        from ghostchimera.safety_layer.ssrf import SSRFPolicy
        policy = SSRFPolicy()
        policy.allow_host("*.openai.com")
        permitted, _ = policy.is_permitted("https://api.openai.com/v1")
        self.assertTrue(permitted)
        permitted2, _ = policy.is_permitted("https://evil.com/v1")
        self.assertFalse(permitted2)

    def test_ssrf_violation_raised(self) -> None:
        from ghostchimera.safety_layer.ssrf import NetworkDispatcher, SSRFPolicy, SSRFViolation
        policy = SSRFPolicy(default_allow=False)
        dispatcher = NetworkDispatcher(policy)
        with self.assertRaises(SSRFViolation):
            dispatcher.fetch("https://blocked.example.com/api")

    def test_pilot_policy_allowed_hosts(self) -> None:
        from ghostchimera.chimera_pilot.policy import PilotPolicy
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
        policy = PilotPolicy(allow_network=True, allowed_hosts=("api.openai.com",))
        # Non-blocked URL from allowed host — should pass
        task = TaskSpec.create(
            kind=TaskKind.WEB_RESEARCH,
            objective="search",
            inputs={"url": "https://api.openai.com/v1/models"},
            requires_network=True,
        )
        policy.validate(task)  # should not raise

    def test_pilot_policy_blocks_disallowed_host(self) -> None:
        from ghostchimera.chimera_pilot.policy import PilotPolicy
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
        policy = PilotPolicy(allow_network=True, allowed_hosts=("api.openai.com",))
        task = TaskSpec.create(
            kind=TaskKind.WEB_RESEARCH,
            objective="search",
            inputs={"url": "https://evil.example.com/steal"},
            requires_network=True,
        )
        with self.assertRaises(PermissionError):
            policy.validate(task)


# ---------------------------------------------------------------------------
# Gap 10 — PROVIDERS split by type
# ---------------------------------------------------------------------------


class ProvidersSplitTests(unittest.TestCase):
    def test_text_providers_contains_known(self) -> None:
        from ghostchimera.model_layer.providers import PROVIDERS, TEXT_PROVIDERS
        self.assertIn("openai", TEXT_PROVIDERS)
        self.assertIn("anthropic", TEXT_PROVIDERS)
        # PROVIDERS is the canonical source; TEXT_PROVIDERS must be a subset
        for name in TEXT_PROVIDERS:
            self.assertIn(name, PROVIDERS)

    def test_register_text_provider(self) -> None:
        from ghostchimera.model_layer.providers import PROVIDERS, TEXT_PROVIDERS, BaseProvider, register_text_provider

        class MyProvider(BaseProvider):
            name = "my_custom_llm"
            def chat(self, system_message, user_message): return "ok"

        register_text_provider("my_custom_llm", MyProvider)
        self.assertIn("my_custom_llm", TEXT_PROVIDERS)
        self.assertIn("my_custom_llm", PROVIDERS)
        # cleanup
        del TEXT_PROVIDERS["my_custom_llm"]
        del PROVIDERS["my_custom_llm"]

    def test_media_providers_structure(self) -> None:
        from ghostchimera.model_layer.media_providers import MEDIA_PROVIDERS
        required_types = {"image_generation", "speech", "web_search", "web_fetch",
                          "media_understanding", "document_extractor"}
        self.assertTrue(required_types.issubset(set(MEDIA_PROVIDERS.keys())))


if __name__ == "__main__":
    unittest.main()
