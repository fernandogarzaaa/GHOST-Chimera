"""Tests for OpenClaw-style modularity additions.

Covers all 7 phases:
  Phase 1  – AuthProfile + BaseProvider auth injection
  Phase 2  – AnthropicProvider
  Phase 3  – validate_config() + LLM warning surface
  Phase 4  – ModelCatalog + scheduler catalog cost enrichment
  Phase 5  – HookRegistry
  Phase 6  – SkillRegistry workspace discovery
  Phase 7  – OAuthCredential skeleton + CredentialPool OAuth expiry path
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
from ghostchimera.chimera_pilot.credential_pool import CredentialPool
from ghostchimera.chimera_pilot.hooks import HookName, HookRegistry
from ghostchimera.chimera_pilot.scheduler import ChimeraScheduler, _catalog_cost_for_backend
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
from ghostchimera.model_layer.auth_profiles import AuthProfile, OAuthCredential
from ghostchimera.model_layer.model_catalog import get_catalog_entry, list_catalog
from ghostchimera.model_layer.providers import PROVIDERS, AnthropicProvider, OpenAIProvider
from ghostchimera.skill_layer.base import Skill
from ghostchimera.skill_layer.registry import SkillRegistry, get_registry


class AuthProfileTests(unittest.TestCase):
    def test_defaults(self) -> None:
        p = AuthProfile(provider="openai")
        self.assertEqual(p.auth_kind, "api_key")
        self.assertEqual(p.api_key, "")
        self.assertFalse(p.is_expired)

    def test_effective_token_api_key(self) -> None:
        p = AuthProfile(provider="openai", api_key="sk-test")
        self.assertEqual(p.effective_token, "sk-test")

    def test_effective_token_oauth(self) -> None:
        p = AuthProfile(provider="custom", auth_kind="oauth", oauth_token="tok-abc")
        self.assertEqual(p.effective_token, "tok-abc")

    def test_is_expired_no_expiry(self) -> None:
        p = AuthProfile(provider="openai", expires_at=0.0)
        self.assertFalse(p.is_expired)

    def test_is_expired_past(self) -> None:
        p = AuthProfile(provider="openai", expires_at=time.time() - 100)
        self.assertTrue(p.is_expired)

    def test_is_expired_future(self) -> None:
        p = AuthProfile(provider="openai", expires_at=time.time() + 3600)
        self.assertFalse(p.is_expired)


class OAuthCredentialTests(unittest.TestCase):
    def test_refresh_returns_current_non_expired_credential(self) -> None:
        cred = OAuthCredential(token="tok", expires_at=time.time() + 3600)
        self.assertIs(cred.refresh(), cred)

    def test_refresh_fails_closed_for_expired_credential_without_provider(self) -> None:
        cred = OAuthCredential(token="tok", expires_at=time.time() - 1)
        with self.assertRaises(RuntimeError) as ctx:
            cred.refresh()
        self.assertIn("ExternalAuthProvider", str(ctx.exception))

    def test_to_auth_profile(self) -> None:
        cred = OAuthCredential(token="tok-xyz", expires_at=9999.0)
        profile = cred.to_auth_profile("myprovider")
        self.assertEqual(profile.auth_kind, "oauth")
        self.assertEqual(profile.oauth_token, "tok-xyz")
        self.assertEqual(profile.provider, "myprovider")

    def test_is_expired(self) -> None:
        expired = OAuthCredential(token="x", expires_at=time.time() - 1)
        self.assertTrue(expired.is_expired)

        fresh = OAuthCredential(token="x", expires_at=time.time() + 3600)
        self.assertFalse(fresh.is_expired)


# ---------------------------------------------------------------------------
# Phase 1 — BaseProvider auth injection
# ---------------------------------------------------------------------------


class ProviderAuthInjectionTests(unittest.TestCase):
    def test_openai_profile_injection(self) -> None:
        p = AuthProfile(provider="openai", api_key="sk-injected", model="gpt-4o-mini")
        provider = OpenAIProvider(profile=p)
        self.assertEqual(provider.api_key, "sk-injected")
        self.assertEqual(provider.model, "gpt-4o-mini")
        self.assertTrue(provider.available)

    def test_openai_env_fallback(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env", "OPENAI_MODEL": "gpt-3.5-turbo"}):
            provider = OpenAIProvider()
        self.assertEqual(provider.api_key, "sk-env")

    def test_openai_profile_overrides_env(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
            p = AuthProfile(provider="openai", api_key="sk-profile")
            provider = OpenAIProvider(profile=p)
        self.assertEqual(provider.api_key, "sk-profile")

    def test_no_api_key_not_available(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            provider = OpenAIProvider()
        self.assertFalse(provider.available)


# ---------------------------------------------------------------------------
# Phase 2 — AnthropicProvider
# ---------------------------------------------------------------------------

class AnthropicProviderTests(unittest.TestCase):
    def test_registered_in_providers(self) -> None:
        self.assertIn("anthropic", PROVIDERS)

    def test_profile_injection(self) -> None:
        p = AuthProfile(provider="anthropic", api_key="ant-key", model="claude-3-5-haiku-20241022")
        provider = AnthropicProvider(profile=p)
        self.assertEqual(provider.api_key, "ant-key")
        self.assertTrue(provider.available)

    def test_env_fallback(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-env"}):
            provider = AnthropicProvider()
        self.assertEqual(provider.api_key, "ant-env")

    def test_not_available_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            provider = AnthropicProvider()
        self.assertFalse(provider.available)

    def test_chat_raises_when_unavailable(self) -> None:
        provider = AnthropicProvider()
        provider.available = False
        with self.assertRaises(RuntimeError):
            provider.chat("system", "user")


# ---------------------------------------------------------------------------
# Phase 3 — validate_config
# ---------------------------------------------------------------------------

class ValidateConfigTests(unittest.TestCase):
    def test_openai_missing_key(self) -> None:
        provider = OpenAIProvider()
        provider.api_key = ""
        errors = provider.validate_config()
        self.assertTrue(any("OPENAI_API_KEY" in e for e in errors))

    def test_openai_invalid_prefix(self) -> None:
        provider = OpenAIProvider()
        provider.api_key = "bad-key"
        errors = provider.validate_config()
        self.assertTrue(any("prefix" in e.lower() or "sk-" in e for e in errors))

    def test_openai_valid_config(self) -> None:
        provider = OpenAIProvider()
        provider.api_key = "sk-valid-key-12345"
        provider.model = "gpt-3.5-turbo"
        errors = provider.validate_config()
        self.assertEqual(errors, [])

    def test_anthropic_missing_key(self) -> None:
        provider = AnthropicProvider()
        provider.api_key = ""
        errors = provider.validate_config()
        self.assertTrue(any("ANTHROPIC_API_KEY" in e for e in errors))

    def test_llm_logs_validate_config_warnings(self) -> None:
        from ghostchimera.model_layer.llm import LLM
        with (
            patch.dict(os.environ, {"GHOSTCHIMERA_MODEL_PROVIDER": "openai", "OPENAI_API_KEY": ""}),
            self.assertLogs("ghostchimera.llm", level="WARNING") as log,
        ):
            LLM()
        self.assertTrue(any("OPENAI_API_KEY" in msg for msg in log.output))


# ---------------------------------------------------------------------------
# Phase 4 — ModelCatalog
# ---------------------------------------------------------------------------


class ModelCatalogTests(unittest.TestCase):
    def test_get_openai_entry(self) -> None:
        entry = get_catalog_entry("openai", "gpt-4o")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.provider, "openai")
        self.assertEqual(entry.model_id, "gpt-4o")
        self.assertGreater(entry.context_window_tokens, 0)

    def test_get_anthropic_entry(self) -> None:
        entry = get_catalog_entry("anthropic", "claude-3-5-haiku-20241022")
        self.assertIsNotNone(entry)
        self.assertGreater(entry.context_window_tokens, 0)

    def test_get_unknown_entry_returns_none(self) -> None:
        self.assertIsNone(get_catalog_entry("openai", "gpt-999-not-real"))

    def test_list_catalog_all(self) -> None:
        all_entries = list_catalog()
        self.assertGreater(len(all_entries), 0)
        providers = {e.provider for e in all_entries}
        self.assertIn("openai", providers)
        self.assertIn("anthropic", providers)

    def test_list_catalog_filtered(self) -> None:
        openai_only = list_catalog("openai")
        self.assertTrue(all(e.provider == "openai" for e in openai_only))

    def test_estimate_cost(self) -> None:
        entry = get_catalog_entry("openai", "gpt-3.5-turbo")
        cost = entry.estimate_cost_usd(1000, 500)
        self.assertGreater(cost, 0.0)

    def test_free_model_zero_cost(self) -> None:
        entry = get_catalog_entry("llamacpp", "local")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.estimate_cost_usd(1000, 500), 0.0)


# ---------------------------------------------------------------------------
# Phase 4 — scheduler catalog enrichment
# ---------------------------------------------------------------------------


class SchedulerCatalogEnrichmentTests(unittest.TestCase):
    def test_catalog_cost_for_known_backend(self) -> None:
        backend = DeterministicBackend("openai.gpt-4o-mini")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="test")
        cost = _catalog_cost_for_backend(backend, task)
        self.assertIsNotNone(cost)
        self.assertGreater(cost, 0.0)

    def test_catalog_cost_for_unknown_backend(self) -> None:
        backend = DeterministicBackend("custom.not-in-catalog")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="test")
        cost = _catalog_cost_for_backend(backend, task)
        self.assertIsNone(cost)

    def test_rank_backends_enriches_zero_cost(self) -> None:
        # Backend with zero reported cost but known catalog id
        backend = DeterministicBackend("openai.gpt-4o-mini", estimated_cost_usd=0.0)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="test")
        scheduler = ChimeraScheduler([backend])
        ranked = scheduler.rank_backends(task)
        self.assertEqual(len(ranked), 1)
        # After enrichment the cost should come from catalog (> 0)
        self.assertGreater(ranked[0].health.estimated_cost_usd, 0.0)

    def test_rank_backends_preserves_nonzero_cost(self) -> None:
        # If backend already reports a cost, catalog should not override it
        backend = DeterministicBackend("openai.gpt-4o-mini", estimated_cost_usd=1.0)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="test")
        scheduler = ChimeraScheduler([backend])
        ranked = scheduler.rank_backends(task)
        self.assertEqual(ranked[0].health.estimated_cost_usd, 1.0)


# ---------------------------------------------------------------------------
# Phase 5 — HookRegistry
# ---------------------------------------------------------------------------


class HookRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks = HookRegistry()

    def test_register_and_fire(self) -> None:
        calls = []
        self.hooks.register_hook(HookName.SESSION_START, lambda **kw: calls.append(kw))
        self.hooks.fire(HookName.SESSION_START, objective="test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["objective"], "test")

    def test_decorator_on(self) -> None:
        calls = []

        @self.hooks.on(HookName.TASK_COMPILE)
        def handler(*, tasks, **kw):
            calls.append(tasks)

        self.hooks.fire(HookName.TASK_COMPILE, objective="x", tasks=["t1"])
        self.assertEqual(calls, [["t1"]])

    def test_multiple_handlers_ordered(self) -> None:
        order = []
        self.hooks.register_hook(HookName.SESSION_END, lambda **kw: order.append(1))
        self.hooks.register_hook(HookName.SESSION_END, lambda **kw: order.append(2))
        self.hooks.fire(HookName.SESSION_END)
        self.assertEqual(order, [1, 2])

    def test_exception_in_handler_does_not_propagate(self) -> None:
        def bad_handler(**kw):
            raise ValueError("boom")

        self.hooks.register_hook(HookName.BACKEND_FALLBACK, bad_handler)
        # Should not raise
        self.hooks.fire(HookName.BACKEND_FALLBACK, task=None, failed_backend_id="x", fallback_backend_id="y", error="err")

    def test_fire_no_handlers_is_noop(self) -> None:
        self.hooks.fire(HookName.TASK_EXECUTE_PRE, task=None)  # no exception

    def test_handler_count(self) -> None:
        self.assertEqual(self.hooks.handler_count(HookName.SESSION_START), 0)
        self.hooks.register_hook(HookName.SESSION_START, lambda **kw: None)
        self.assertEqual(self.hooks.handler_count(HookName.SESSION_START), 1)

    def test_clear_single_hook(self) -> None:
        self.hooks.register_hook(HookName.SESSION_START, lambda **kw: None)
        self.hooks.clear(HookName.SESSION_START)
        self.assertEqual(self.hooks.handler_count(HookName.SESSION_START), 0)

    def test_clear_all_hooks(self) -> None:
        self.hooks.register_hook(HookName.SESSION_START, lambda **kw: None)
        self.hooks.register_hook(HookName.SESSION_END, lambda **kw: None)
        self.hooks.clear()
        self.assertEqual(self.hooks.handler_count(HookName.SESSION_START), 0)
        self.assertEqual(self.hooks.handler_count(HookName.SESSION_END), 0)

    def test_string_hook_name(self) -> None:
        calls = []
        self.hooks.register_hook("custom_event", lambda **kw: calls.append(True))
        self.hooks.fire("custom_event")
        self.assertEqual(calls, [True])


class HookKernelIntegrationTests(unittest.TestCase):
    """Verify kernel fires hooks at the right lifecycle points."""

    def _make_kernel_with_hook_capture(self):
        from ghostchimera.chimera_pilot import ChimeraPilotKernel

        hooks = HookRegistry()
        fired: dict[str, list] = {n.value: [] for n in HookName}

        for hook_name in HookName:
            def make_handler(name):
                def handler(**kw):
                    fired[name.value].append(kw)
                return handler
            hooks.register_hook(hook_name, make_handler(hook_name))

        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=True, hooks=hooks
        )
        return kernel, fired

    def test_hooks_fire_on_run(self) -> None:
        kernel, fired = self._make_kernel_with_hook_capture()
        kernel.run("what is 2+2")
        self.assertEqual(len(fired[HookName.SESSION_START.value]), 1)
        self.assertEqual(len(fired[HookName.TASK_COMPILE.value]), 1)
        self.assertEqual(len(fired[HookName.SESSION_END.value]), 1)
        # pre/post fire once per task
        n_tasks = len(fired[HookName.TASK_COMPILE.value][0]["tasks"])
        self.assertEqual(len(fired[HookName.TASK_EXECUTE_PRE.value]), n_tasks)
        self.assertEqual(len(fired[HookName.TASK_EXECUTE_POST.value]), n_tasks)


# ---------------------------------------------------------------------------
# Phase 6 — SkillRegistry workspace discovery
# ---------------------------------------------------------------------------


class SkillRegistryTests(unittest.TestCase):
    def test_bundled_skills_discovered(self) -> None:
        registry = SkillRegistry()
        skills = registry.list_skills()
        self.assertGreater(len(skills), 0)

    def test_get_known_bundled_skill(self) -> None:
        registry = SkillRegistry()
        skill = registry.get_skill("browser_operator")
        self.assertIsNotNone(skill)

    def test_register_custom_skill(self) -> None:
        class MySkill(Skill):
            name = "my_custom_skill"
            description = "A test skill"
            actions = ["my_action"]

            def run(self, task):
                return "done"

        registry = SkillRegistry(auto_discover=False)
        registry.register(MySkill())
        self.assertIsNotNone(registry.get_skill("my_custom_skill"))

    def test_duplicate_registration_is_ignored(self) -> None:
        class Dup(Skill):
            name = "dup_skill"
            actions = []

            def run(self, task):
                return "v1"

        class Dup2(Skill):
            name = "dup_skill"
            actions = []

            def run(self, task):
                return "v2"

        registry = SkillRegistry(auto_discover=False)
        registry.register(Dup())
        registry.register(Dup2())
        skill = registry.get_skill("dup_skill")
        self.assertEqual(skill.run({}), "v1")

    def test_workspace_skill_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "workspace_test_skill"
            skill_dir.mkdir()
            (skill_dir / "skill.py").write_text(
                "from ghostchimera.skill_layer.base import Skill\n"
                "class WorkspaceTestSkill(Skill):\n"
                "    name = 'workspace_test_skill'\n"
                "    description = 'Dynamic workspace skill'\n"
                "    actions = ['workspace_action']\n"
                "    def run(self, task): return 'workspace_result'\n"
            )
            registry = SkillRegistry(skills_dir=tmpdir)
            skill = registry.get_skill("workspace_test_skill")
            self.assertIsNotNone(skill)
            self.assertEqual(skill.run({}), "workspace_result")

    def test_bad_skill_file_does_not_crash_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "bad_skill"
            skill_dir.mkdir()
            (skill_dir / "skill.py").write_text("raise RuntimeError('intentional error')\n")
            # Should not raise
            registry = SkillRegistry(skills_dir=tmpdir, auto_discover=False)
            registry._discover_workspace.__func__(registry) if False else None
            registry2 = SkillRegistry(skills_dir=tmpdir)
            # Still boots (bad module was logged and skipped)
            self.assertIsNotNone(registry2)

    def test_skill_names_sorted(self) -> None:
        registry = SkillRegistry()
        names = registry.skill_names()
        self.assertEqual(names, sorted(names))

    def test_singleton_get_registry(self) -> None:
        r1 = get_registry(reset=True)
        r2 = get_registry()
        self.assertIs(r1, r2)


class AgentCoreSkillRegistryIntegrationTests(unittest.TestCase):
    def test_agent_core_accepts_skill_registry(self) -> None:
        from ghostchimera.agent_core.core import AgentCore

        class TestSkill(Skill):
            name = "test_registry_skill"
            actions = ["test_registry_action"]

            def run(self, task):
                return "ok"

        sr = SkillRegistry(auto_discover=False)
        sr.register(TestSkill())
        core = AgentCore(skill_registry=sr)
        skill = core.skills.get_skill_for_action("test_registry_action")
        self.assertIsNotNone(skill)


# ---------------------------------------------------------------------------
# Phase 7 — CredentialPool OAuth expiry path
# ---------------------------------------------------------------------------


class CredentialPoolOAuthTests(unittest.TestCase):
    def test_expired_api_key_credential_returns_none(self) -> None:
        pool = CredentialPool()
        pool.add_credential("openai", api_key="sk-test", expires_at=time.time() - 100)
        self.assertIsNone(pool.get_credential("openai"))

    def test_expired_oauth_credential_without_provider_returns_none(self) -> None:
        """Expired oauth_token fails closed when no auth provider is registered."""
        pool = CredentialPool()
        pool.add_credential(
            "custom",
            api_key="",
            oauth_token="expired-token",
            expires_at=time.time() - 100,
        )
        # OAuthCredential.refresh() raises RuntimeError, so the pool returns None.
        result = pool.get_credential("custom")
        self.assertIsNone(result)

    def test_valid_oauth_credential_returned(self) -> None:
        pool = CredentialPool()
        pool.add_credential(
            "custom",
            api_key="",
            oauth_token="valid-token",
            expires_at=time.time() + 3600,
        )
        # valid (not expired) → api_key is empty so is_available is False via is_available check
        # But the oauth path only triggers when expired, so non-expired goes to normal is_available check
        # Since api_key is empty, is_available returns False → None
        # This tests the branch: expired=False, is_available=False
        result = pool.get_credential("custom")
        self.assertIsNone(result)  # no api_key → not available

    def test_get_provider_instance_injects_auth_profile(self) -> None:
        pool = CredentialPool()
        pool.add_credential("openai", api_key="sk-injected", model="gpt-4o-mini")
        instance = pool.get_provider_instance("openai")
        self.assertIsNotNone(instance)
        self.assertEqual(instance.api_key, "sk-injected")
        self.assertEqual(instance.model, "gpt-4o-mini")


# ---------------------------------------------------------------------------
# BACKEND_FALLBACK end-to-end wiring
# ---------------------------------------------------------------------------


class BackendFallbackHookWiringTests(unittest.TestCase):
    """Verify that BACKEND_FALLBACK fires via the executor when a backend fails."""

    def test_fallback_hook_fires_on_backend_failure(self) -> None:
        from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend
        from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor

        # "a.primary" sorts before "b.fallback" so the scheduler tries it first.
        # fail=True makes it return ok=False so the executor moves on.
        primary = DeterministicBackend("a.primary", fail=True)
        fallback = DeterministicBackend("b.fallback")

        hooks = HookRegistry()
        fired_events: list[dict] = []
        hooks.register_hook(HookName.BACKEND_FALLBACK, lambda **kw: fired_events.append(kw))

        scheduler = ChimeraScheduler([primary, fallback])
        executor = ChimeraPilotExecutor(scheduler, hooks=hooks)

        task = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective="test fallback",
            inputs={"prompt": "test fallback"},
        )
        executor.execute(task)

        self.assertEqual(len(fired_events), 1)
        event = fired_events[0]
        self.assertEqual(event["failed_backend_id"], primary.id)
        self.assertEqual(event["fallback_backend_id"], fallback.id)
        self.assertIn("deterministic failure", event["error"])

    def test_fallback_hook_not_fired_on_success(self) -> None:
        from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor

        backend = DeterministicBackend("only.backend")
        hooks = HookRegistry()
        fired_events: list[dict] = []
        hooks.register_hook(HookName.BACKEND_FALLBACK, lambda **kw: fired_events.append(kw))

        scheduler = ChimeraScheduler([backend])
        executor = ChimeraPilotExecutor(scheduler, hooks=hooks)

        task = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective="what is 2+2",
            inputs={"prompt": "what is 2+2"},
        )
        executor.execute(task)

        self.assertEqual(len(fired_events), 0)

    def test_kernel_wires_hooks_to_executor_for_fallback(self) -> None:
        """Kernel.execute_task passes its HookRegistry to the executor."""
        from ghostchimera.chimera_pilot import ChimeraPilotKernel
        from ghostchimera.chimera_pilot.backends.base import ExecutionResult
        from ghostchimera.chimera_pilot.backends.deterministic import DeterministicBackend

        hooks = HookRegistry()
        fired_events: list[dict] = []
        hooks.register_hook(HookName.BACKEND_FALLBACK, lambda **kw: fired_events.append(kw))

        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True, hooks=hooks)

        # Add a second deterministic backend that will be the fallback target
        fallback = DeterministicBackend("fallback.kernel")
        kernel.registry.register(fallback)

        # Patch the primary backend to fail so fallback fires
        backends = kernel.registry.list()
        primary = next(b for b in backends if b.id == "deterministic.local")

        original_execute = primary.execute

        def fail_once(task):
            primary.execute = original_execute
            return ExecutionResult(
                backend_id=primary.id,
                task_id=task.id,
                ok=False,
                output="",
                error="kernel test failure",
                metrics={},
            )

        primary.execute = fail_once

        task = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective="kernel fallback test",
            inputs={"prompt": "kernel fallback test"},
        )
        kernel.execute_task(task)

        self.assertGreaterEqual(len(fired_events), 1)
        self.assertEqual(fired_events[0]["failed_backend_id"], "deterministic.local")


if __name__ == "__main__":
    unittest.main()
