"""Unit tests for model provider routing."""

import os
import unittest

from ghostchimera.model_layer.openai_compatible_providers import (
    CohereProvider,
    DeepSeekProvider,
    GroqProvider,
    MistralProvider,
    OllamaProvider,
    OpenRouterProvider,
    TogetherProvider,
    XAIProvider,
)
from ghostchimera.model_layer.providers import (
    PROVIDERS,
    TEXT_PROVIDERS,
    AnthropicProvider,
    BaseProvider,
    OpenAIProvider,
    get_provider,
    register_text_provider,
)


class BaseProviderTests(unittest.TestCase):
    def test_default_name(self):
        self.assertEqual(BaseProvider.name, "base")

    def test_default_available_false(self):
        self.assertFalse(BaseProvider.available)


class OpenAIProviderTests(unittest.TestCase):
    def test_creation_without_key_is_unavailable(self):
        orig_key = None
        import os
        orig_key = os.environ.get("OPENAI_API_KEY")
        os.environ.pop("OPENAI_API_KEY", None)
        try:
            p = OpenAIProvider()
            self.assertFalse(p.available)
            self.assertEqual(p.model, "gpt-3.5-turbo")
        finally:
            if orig_key:
                os.environ["OPENAI_API_KEY"] = orig_key

    def test_valid_key_makes_available(self):
        import os
        os.environ["OPENAI_API_KEY"] = "sk-test1234"
        try:
            p = OpenAIProvider()
            self.assertTrue(p.available)
            self.assertEqual(p.api_key, "sk-test1234")
            self.assertEqual(p.model, "gpt-3.5-turbo")
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_validate_config_ok(self):
        os.environ["OPENAI_API_KEY"] = "sk-test1234"
        try:
            p = OpenAIProvider()
            errors = p.validate_config()
            self.assertEqual(errors, [])
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_validate_config_missing_key(self):
        os_environ_orig = os.environ.pop("OPENAI_API_KEY", None)
        p = OpenAIProvider()
        errors = p.validate_config()
        self.assertIn("OPENAI_API_KEY is not set", errors)
        if os_environ_orig:
            os.environ["OPENAI_API_KEY"] = os_environ_orig

    def test_to_dict(self):
        os.environ["OPENAI_API_KEY"] = "sk-test1234"
        try:
            p = OpenAIProvider()
            d = p.to_dict()
            self.assertEqual(d["name"], "openai")
            self.assertTrue(d["available"])
            self.assertIn("model", d)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    def test_sanitize_key_normal(self):
        self.assertEqual(OpenAIProvider._sanitize_key("sk-1234567890abcdef"), "sk-1****")

    def test_sanitize_key_short(self):
        self.assertEqual(OpenAIProvider._sanitize_key("sk"), "***")

    def test_chat_without_key_raises(self):
        os_environ_orig = os.environ.pop("OPENAI_API_KEY", None)
        p = OpenAIProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")
        if os_environ_orig:
            os.environ["OPENAI_API_KEY"] = os_environ_orig


class AnthropicProviderTests(unittest.TestCase):
    def test_creation_without_key_is_unavailable(self):
        orig = os.environ.pop("ANTHROPIC_API_KEY", None)
        p = AnthropicProvider()
        self.assertFalse(p.available)
        if orig:
            os.environ["ANTHROPIC_API_KEY"] = orig

    def test_valid_key_makes_available(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test1234"
        try:
            p = AnthropicProvider()
            self.assertTrue(p.available)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_to_dict(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test1234"
        try:
            p = AnthropicProvider()
            d = p.to_dict()
            self.assertEqual(d["name"], "anthropic")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_chat_without_key_raises(self):
        os_environ_orig = os.environ.pop("ANTHROPIC_API_KEY", None)
        p = AnthropicProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")
        if os_environ_orig:
            os.environ["ANTHROPIC_API_KEY"] = os_environ_orig


class ProviderRegistryTests(unittest.TestCase):
    def tearDown(self):
        """
        Remove OpenAI and Anthropic API key environment variables to restore a clean environment after each test.

        This deletes the "OPENAI_API_KEY" and "ANTHROPIC_API_KEY" keys from os.environ if they exist.
        """
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def test_get_provider_openai(self):
        os.environ["OPENAI_API_KEY"] = "sk-test1234"
        p = get_provider("openai")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "openai")

    def test_get_provider_anthropic(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test1234"
        p = get_provider("anthropic")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "anthropic")

    def test_get_provider_unknown_returns_none(self):
        p = get_provider("nonexistent_provider")
        self.assertIsNone(p)

    def test_get_provider_invalid_key_format(self):
        os.environ["OPENAI_API_KEY"] = "not-a-key"
        p = get_provider("openai")
        self.assertIsNotNone(p)
        self.assertTrue(p.available)  # has a non-empty key
        errors = p.validate_config()
        self.assertTrue(any("not look like a valid OpenAI key" in e for e in errors))

    def test_register_text_provider(self):
        class CustomProvider(BaseProvider):
            name = "custom"
            available = True

            def chat(self, system_message: str, user_message: str) -> str:
                """
                Return a chat response for the given system and user messages.

                Parameters:
                    system_message (str): System prompt or context for the response.
                    user_message (str): User message to which the provider should respond.

                Returns:
                    response (str): The provider's chat response.
                """
                return "custom response"

        register_text_provider("custom", CustomProvider)
        try:
            p = get_provider("custom")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "custom")
            # Verify it's in both registries
            self.assertIn("custom", PROVIDERS)
            self.assertIn("custom", TEXT_PROVIDERS)
        finally:
            PROVIDERS.pop("custom", None)
            TEXT_PROVIDERS.pop("custom", None)


class PROVIDERSAndTEXT_PROVIDERSTests(unittest.TestCase):
    def test_all_standard_providers_registered(self):
        self.assertIn("openai", PROVIDERS)
        self.assertIn("anthropic", PROVIDERS)
        self.assertIn("llamacpp", PROVIDERS)
        self.assertIn("minimind", PROVIDERS)

    def test_text_providers_match(self):
        self.assertEqual(set(PROVIDERS.keys()), set(TEXT_PROVIDERS.keys()))

    def test_new_providers_in_registry(self):
        for name in ("groq", "xai", "mistral", "deepseek", "together", "openrouter", "ollama", "cohere"):
            self.assertIn(name, PROVIDERS, f"Expected '{name}' in PROVIDERS")
            self.assertIn(name, TEXT_PROVIDERS, f"Expected '{name}' in TEXT_PROVIDERS")


# ---------------------------------------------------------------------------
# New provider tests — Groq
# ---------------------------------------------------------------------------


class GroqProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("GROQ_API_KEY", None)

    def tearDown(self):
        os.environ.pop("GROQ_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = GroqProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "llama-3.3-70b-versatile")

    def test_valid_key_makes_available(self):
        os.environ["GROQ_API_KEY"] = "gsk_test"
        p = GroqProvider()
        self.assertTrue(p.available)
        self.assertEqual(p.api_key, "gsk_test")

    def test_validate_config_missing_key(self):
        p = GroqProvider()
        errors = p.validate_config()
        self.assertTrue(any("GROQ_API_KEY" in e for e in errors))

    def test_validate_config_ok(self):
        os.environ["GROQ_API_KEY"] = "gsk_test"
        p = GroqProvider()
        self.assertEqual(p.validate_config(), [])

    def test_to_dict(self):
        os.environ["GROQ_API_KEY"] = "gsk_test"
        p = GroqProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "groq")
        self.assertTrue(d["available"])
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = GroqProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# xAI (Grok)
# ---------------------------------------------------------------------------


class XAIProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("XAI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("XAI_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = XAIProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "grok-3-mini")

    def test_valid_key_makes_available(self):
        os.environ["XAI_API_KEY"] = "xai-test"
        p = XAIProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = XAIProvider()
        errors = p.validate_config()
        self.assertTrue(any("XAI_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["XAI_API_KEY"] = "xai-test"
        p = XAIProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "xai")
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = XAIProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Mistral
# ---------------------------------------------------------------------------


class MistralProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("MISTRAL_API_KEY", None)

    def tearDown(self):
        os.environ.pop("MISTRAL_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = MistralProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "mistral-small-latest")

    def test_valid_key_makes_available(self):
        os.environ["MISTRAL_API_KEY"] = "mis-test"
        p = MistralProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = MistralProvider()
        errors = p.validate_config()
        self.assertTrue(any("MISTRAL_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["MISTRAL_API_KEY"] = "mis-test"
        p = MistralProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "mistral")

    def test_chat_without_key_raises(self):
        p = MistralProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# DeepSeek
# ---------------------------------------------------------------------------


class DeepSeekProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)

    def tearDown(self):
        os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = DeepSeekProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "deepseek-chat")

    def test_valid_key_makes_available(self):
        os.environ["DEEPSEEK_API_KEY"] = "dsk-test"
        p = DeepSeekProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = DeepSeekProvider()
        errors = p.validate_config()
        self.assertTrue(any("DEEPSEEK_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["DEEPSEEK_API_KEY"] = "dsk-test"
        p = DeepSeekProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "deepseek")

    def test_chat_without_key_raises(self):
        p = DeepSeekProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Together AI
# ---------------------------------------------------------------------------


class TogetherProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("TOGETHER_API_KEY", None)

    def tearDown(self):
        os.environ.pop("TOGETHER_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = TogetherProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "meta-llama/Llama-3-70b-chat-hf")

    def test_valid_key_makes_available(self):
        os.environ["TOGETHER_API_KEY"] = "tog-test"
        p = TogetherProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = TogetherProvider()
        errors = p.validate_config()
        self.assertTrue(any("TOGETHER_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["TOGETHER_API_KEY"] = "tog-test"
        p = TogetherProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "together")

    def test_chat_without_key_raises(self):
        p = TogetherProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------


class OpenRouterProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("OPENROUTER_API_KEY", None)

    def tearDown(self):
        os.environ.pop("OPENROUTER_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = OpenRouterProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "openai/gpt-4o-mini")

    def test_valid_key_makes_available(self):
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        p = OpenRouterProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = OpenRouterProvider()
        errors = p.validate_config()
        self.assertTrue(any("OPENROUTER_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        p = OpenRouterProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "openrouter")

    def test_extra_headers_present(self):
        """OpenRouter requires HTTP-Referer and X-Title headers."""
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        p = OpenRouterProvider()
        headers = p._build_headers()
        self.assertIn("HTTP-Referer", headers)
        self.assertIn("X-Title", headers)
        self.assertEqual(headers["X-Title"], "Ghost Chimera")

    def test_chat_without_key_raises(self):
        p = OpenRouterProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Ollama (local — always available by default, no key)
# ---------------------------------------------------------------------------


class OllamaProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("OLLAMA_BASE_URL", None)
        os.environ.pop("OLLAMA_MODEL", None)

    def tearDown(self):
        os.environ.pop("OLLAMA_BASE_URL", None)
        os.environ.pop("OLLAMA_MODEL", None)

    def test_available_by_default(self):
        p = OllamaProvider()
        self.assertTrue(p.available)
        self.assertEqual(p.model, "llama3.2")

    def test_custom_base_url(self):
        os.environ["OLLAMA_BASE_URL"] = "http://myhost:11434"
        p = OllamaProvider()
        self.assertEqual(p._base_url, "http://myhost:11434")

    def test_custom_model_via_env(self):
        os.environ["OLLAMA_MODEL"] = "mistral"
        p = OllamaProvider()
        self.assertEqual(p.model, "mistral")

    def test_to_dict_has_base_url(self):
        p = OllamaProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "ollama")
        self.assertIn("base_url", d)
        self.assertIn("model", d)

    def test_validate_config_unreachable_server_returns_note(self):
        # Point at a port that won't be open in CI
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:19999"
        p = OllamaProvider()
        notes = p.validate_config()
        # Should return a non-empty list describing the reachability issue
        self.assertTrue(len(notes) > 0)
        self.assertTrue(any("unreachable" in n.lower() or "19999" in n for n in notes))


# ---------------------------------------------------------------------------
# Cohere
# ---------------------------------------------------------------------------


class CohereProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("COHERE_API_KEY", None)

    def tearDown(self):
        os.environ.pop("COHERE_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = CohereProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "command-r-plus")

    def test_valid_key_makes_available(self):
        os.environ["COHERE_API_KEY"] = "co-test"
        p = CohereProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = CohereProvider()
        errors = p.validate_config()
        self.assertTrue(any("COHERE_API_KEY" in e for e in errors))

    def test_validate_config_ok(self):
        os.environ["COHERE_API_KEY"] = "co-test"
        p = CohereProvider()
        self.assertEqual(p.validate_config(), [])

    def test_to_dict(self):
        os.environ["COHERE_API_KEY"] = "co-test"
        p = CohereProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "cohere")
        self.assertTrue(d["available"])
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = CohereProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# get_provider integration tests for new providers
# ---------------------------------------------------------------------------


class NewProviderRegistryTests(unittest.TestCase):
    def test_get_provider_groq(self):
        os.environ["GROQ_API_KEY"] = "gsk_test"
        try:
            p = get_provider("groq")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "groq")
        finally:
            os.environ.pop("GROQ_API_KEY", None)

    def test_get_provider_xai(self):
        os.environ["XAI_API_KEY"] = "xai-test"
        try:
            p = get_provider("xai")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "xai")
        finally:
            os.environ.pop("XAI_API_KEY", None)

    def test_get_provider_mistral(self):
        os.environ["MISTRAL_API_KEY"] = "mis-test"
        try:
            p = get_provider("mistral")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "mistral")
        finally:
            os.environ.pop("MISTRAL_API_KEY", None)

    def test_get_provider_deepseek(self):
        os.environ["DEEPSEEK_API_KEY"] = "dsk-test"
        try:
            p = get_provider("deepseek")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "deepseek")
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_get_provider_together(self):
        os.environ["TOGETHER_API_KEY"] = "tog-test"
        try:
            p = get_provider("together")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "together")
        finally:
            os.environ.pop("TOGETHER_API_KEY", None)

    def test_get_provider_openrouter(self):
        os.environ["OPENROUTER_API_KEY"] = "sk-or-test"
        try:
            p = get_provider("openrouter")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "openrouter")
        finally:
            os.environ.pop("OPENROUTER_API_KEY", None)

    def test_get_provider_ollama(self):
        p = get_provider("ollama")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "ollama")

    def test_get_provider_cohere(self):
        os.environ["COHERE_API_KEY"] = "co-test"
        try:
            p = get_provider("cohere")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "cohere")
        finally:
            os.environ.pop("COHERE_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
