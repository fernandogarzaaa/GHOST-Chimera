"""Tests for GeminiProvider and GeminiBackend."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch


class TestGeminiProviderInit(unittest.TestCase):
    def test_no_key_unavailable(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = GeminiProvider()
        self.assertFalse(p.available)

    def test_key_sets_available(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "key-abc"}):
            p = GeminiProvider()
        self.assertTrue(p.available)
        self.assertEqual(p.api_key, "key-abc")

    def test_default_model(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "x"}, clear=False):
            os.environ.pop("GEMINI_MODEL", None)
            p = GeminiProvider()
        self.assertEqual(p.model, "gemini-2.0-flash-exp")

    def test_custom_model(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "x", "GEMINI_MODEL": "gemini-1.5-pro"}):
            p = GeminiProvider()
        self.assertEqual(p.model, "gemini-1.5-pro")

    def test_profile_injection(self):
        from ghostchimera.model_layer.auth_profiles import AuthProfile
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        profile = AuthProfile(provider="gemini", api_key="injected-key", model="gemini-1.5-flash")
        p = GeminiProvider(profile=profile)
        self.assertEqual(p.api_key, "injected-key")
        self.assertEqual(p.model, "gemini-1.5-flash")
        self.assertTrue(p.available)


class TestGeminiProviderValidateConfig(unittest.TestCase):
    def test_missing_key_error(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = GeminiProvider()
        errors = p.validate_config()
        self.assertTrue(any("GOOGLE_API_KEY" in e for e in errors))

    def test_no_errors_with_key(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "valid-key"}):
            p = GeminiProvider()
        self.assertEqual(p.validate_config(), [])


class TestGeminiProviderToDict(unittest.TestCase):
    def test_to_dict_shape(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()
        d = p.to_dict()
        self.assertIn("name", d)
        self.assertIn("available", d)
        self.assertIn("model", d)
        self.assertNotIn("api_key", d)


class TestGeminiProviderChat(unittest.TestCase):
    def test_chat_raises_when_unavailable(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = GeminiProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")

    def test_chat_calls_generate(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        p._generate = MagicMock(return_value="Hello!")
        result = p.chat("You are helpful.", "What is 2+2?")
        self.assertEqual(result, "Hello!")
        p._generate.assert_called_once()

    def test_chat_prepends_system_message(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        captured = []

        def mock_gen(contents, **kwargs):
            captured.append(contents)
            return "ok"

        p._generate = mock_gen
        p.chat("Be helpful.", "Tell me a joke.")
        self.assertTrue(len(captured) == 1)
        text = captured[0][0]["parts"][0]["text"]
        self.assertIn("Be helpful.", text)
        self.assertIn("Tell me a joke.", text)

    def test_chat_empty_system(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        captured = []

        def mock_gen(contents, **kwargs):
            captured.append(contents)
            return "ok"

        p._generate = mock_gen
        p.chat("", "Just the user message.")
        text = captured[0][0]["parts"][0]["text"]
        self.assertEqual(text, "Just the user message.")


class TestGeminiProviderLongContext(unittest.TestCase):
    def test_long_context_assembles_parts(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        captured = []

        def mock_gen(contents, **kwargs):
            captured.append(contents)
            return "Summary"

        p._generate = mock_gen
        documents = ["Doc A text.", "Doc B text.", "Doc C text."]
        result = p.chat_long_context("Summarise each doc.", documents=documents)
        self.assertEqual(result, "Summary")
        last_turn = captured[0][-1]
        # n documents + 1 instruction = 4 parts
        self.assertEqual(len(last_turn["parts"]), 4)

    def test_long_context_raises_when_unavailable(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = GeminiProvider()
        with self.assertRaises(RuntimeError):
            p.chat_long_context("Summarise.", documents=["text"])

    def test_long_context_with_history(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        captured = []

        def mock_gen(contents, **kwargs):
            captured.append(contents)
            return "ok"

        p._generate = mock_gen
        history = [
            {"role": "user", "parts": [{"text": "prior question"}]},
            {"role": "model", "parts": [{"text": "prior answer"}]},
        ]
        p.chat_long_context("New question.", documents=[], history=history)
        # history (2 turns) + new user turn = 3
        self.assertEqual(len(captured[0]), 3)


class TestGeminiProviderMultiAgentChat(unittest.TestCase):
    def test_builds_history(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        p._generate = MagicMock(return_value="Reply A")
        history: list = []
        reply, updated = p.multi_agent_chat(history, new_message="Hello")
        self.assertEqual(reply, "Reply A")
        self.assertEqual(updated[-1]["role"], "model")
        self.assertEqual(updated[-1]["parts"][0]["text"], "Reply A")

    def test_extends_existing_history(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        p._generate = MagicMock(return_value="Reply B")
        h = [{"role": "user", "parts": [{"text": "msg1"}]}, {"role": "model", "parts": [{"text": "resp1"}]}]
        _, updated = p.multi_agent_chat(h, new_message="msg2")
        # original 2 turns + new user turn + model reply = 4
        self.assertEqual(len(updated), 4)

    def test_raises_when_unavailable(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = GeminiProvider()
        with self.assertRaises(RuntimeError):
            p.multi_agent_chat([], new_message="test")

    def test_system_context_prepended(self):
        from ghostchimera.model_layer.gemini_provider import GeminiProvider

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            p = GeminiProvider()

        captured = []

        def mock_gen(contents, **kwargs):
            captured.append(list(contents))  # snapshot at call time
            return "ok"

        p._generate = mock_gen
        p.multi_agent_chat([], new_message="hi", system_context="System instructions here")
        # system context turn (user) + model ack + new message = 3
        self.assertEqual(len(captured[0]), 3)


class TestGeminiProviderRegistered(unittest.TestCase):
    def test_in_providers(self):
        from ghostchimera.model_layer.providers import PROVIDERS, TEXT_PROVIDERS

        self.assertIn("gemini", PROVIDERS)
        self.assertIn("gemini", TEXT_PROVIDERS)

    def test_get_provider(self):
        from ghostchimera.model_layer.providers import get_provider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            p = get_provider("gemini")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "gemini")


class TestGeminiModelCatalog(unittest.TestCase):
    def test_catalog_has_gemini_entries(self):
        from ghostchimera.model_layer.model_catalog import list_catalog

        entries = list_catalog("gemini")
        self.assertGreaterEqual(len(entries), 3)

    def test_flash_has_million_context(self):
        from ghostchimera.model_layer.model_catalog import get_catalog_entry

        entry = get_catalog_entry("gemini", "gemini-2.0-flash-exp")
        self.assertIsNotNone(entry)
        self.assertGreaterEqual(entry.context_window_tokens, 1_000_000)

    def test_pro_supports_vision(self):
        from ghostchimera.model_layer.model_catalog import get_catalog_entry

        entry = get_catalog_entry("gemini", "gemini-1.5-pro")
        self.assertIsNotNone(entry)
        self.assertTrue(entry.supports_vision)


class TestGeminiBackend(unittest.TestCase):
    def _backend_with_key(self):
        from ghostchimera.chimera_pilot.backends.gemini import GeminiBackend

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"}):
            return GeminiBackend()

    def test_probe_available_with_key(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake"}):
            backend = self._backend_with_key()
            health = backend.probe()
        self.assertTrue(health.available)

    def test_probe_unavailable_without_key(self):
        from ghostchimera.chimera_pilot.backends.gemini import GeminiBackend

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            backend = GeminiBackend()
        health = backend.probe()
        self.assertFalse(health.available)

    def test_can_run_reasoning(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            backend = self._backend_with_key()
        task = TaskSpec.create(
            kind=TaskKind.REASONING, objective="test", inputs={"prompt": "hi"}, requires_network=True
        )
        self.assertTrue(backend.can_run(task))

    def test_can_run_long_context_doc(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            backend = self._backend_with_key()
        task = TaskSpec.create(
            kind=TaskKind.LONG_CONTEXT_DOC,
            objective="summarise",
            inputs={"instruction": "summarise", "documents": ["doc1"]},
            requires_network=True,
        )
        self.assertTrue(backend.can_run(task))

    def test_cannot_run_python_task(self):
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            backend = self._backend_with_key()
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="run", inputs={"code": "print(1)"})
        self.assertFalse(backend.can_run(task))

    def test_execute_returns_error_without_key(self):
        from ghostchimera.chimera_pilot.backends.gemini import GeminiBackend
        from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            backend = GeminiBackend()
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="test", inputs={"prompt": "hi"})
        result = backend.execute(task)
        self.assertFalse(result.ok)

    def test_capabilities_max_context(self):
        from ghostchimera.chimera_pilot.backends.gemini import GeminiBackend

        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}):
            backend = GeminiBackend()
        self.assertEqual(backend.capabilities.max_context_tokens, 1_000_000)


class TestGeminiCompilerRouting(unittest.TestCase):
    def test_summarise_document_routes_to_long_context(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("Summarise document: annual report 2024")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.LONG_CONTEXT_DOC)

    def test_analyze_contract_routes_to_long_context(self):
        from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
        from ghostchimera.chimera_pilot.task_ir import TaskKind

        compiler = RuleBasedTaskCompiler()
        tasks = compiler.compile("Analyze contract: service agreement v3.pdf")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].kind, TaskKind.LONG_CONTEXT_DOC)


if __name__ == "__main__":
    unittest.main()
