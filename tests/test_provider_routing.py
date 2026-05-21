"""Unit tests for model provider routing."""

import os
import unittest

from ghostchimera.model_layer.openai_compatible_providers import (
    AI21Provider,
    CerebrasProvider,
    CohereProvider,
    DeepInfraProvider,
    DeepSeekProvider,
    FireworksProvider,
    GlmProvider,
    GroqProvider,
    HuggingFaceProvider,
    LMStudioProvider,
    MistralProvider,
    MoonshotProvider,
    NvidiaProvider,
    OllamaProvider,
    OpenRouterProvider,
    PerplexityProvider,
    QwenProvider,
    StepFunProvider,
    TogetherProvider,
    VeniceProvider,
    VolcengineProvider,
    VultrInferenceProvider,
    XAIProvider,
)
from ghostchimera.model_layer.providers import (
    PROVIDERS,
    TEXT_PROVIDERS,
    AnthropicProvider,
    BaseProvider,
    CodexCliProvider,
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
        self.assertIn("codex_cli", PROVIDERS)
        self.assertIn("llamacpp", PROVIDERS)
        self.assertIn("minimind", PROVIDERS)

    def test_text_providers_match(self):
        self.assertEqual(set(PROVIDERS.keys()), set(TEXT_PROVIDERS.keys()))

    def test_new_providers_in_registry(self):
        expected = {
            "groq": GroqProvider,
            "codex_cli": CodexCliProvider,
            "xai": XAIProvider,
            "mistral": MistralProvider,
            "deepseek": DeepSeekProvider,
            "together": TogetherProvider,
            "openrouter": OpenRouterProvider,
            "ollama": OllamaProvider,
            "cohere": CohereProvider,
            "perplexity": PerplexityProvider,
            "fireworks": FireworksProvider,
            "cerebras": CerebrasProvider,
            "ai21": AI21Provider,
            "huggingface": HuggingFaceProvider,
            "nvidia": NvidiaProvider,
            "moonshot": MoonshotProvider,
            "deepinfra": DeepInfraProvider,
            "qwen": QwenProvider,
            "volcengine": VolcengineProvider,
            "stepfun": StepFunProvider,
            "glm": GlmProvider,
            "venice": VeniceProvider,
            "lmstudio": LMStudioProvider,
            "vultr": VultrInferenceProvider,
        }
        for name, cls in expected.items():
            self.assertIn(name, PROVIDERS, f"Expected '{name}' in PROVIDERS")
            self.assertIs(PROVIDERS[name], cls, f"PROVIDERS['{name}'] should be {cls.__name__}")
            self.assertIn(name, TEXT_PROVIDERS, f"Expected '{name}' in TEXT_PROVIDERS")
            self.assertIs(TEXT_PROVIDERS[name], cls, f"TEXT_PROVIDERS['{name}'] should be {cls.__name__}")


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


# ---------------------------------------------------------------------------
# Perplexity
# ---------------------------------------------------------------------------


class PerplexityProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("PERPLEXITY_API_KEY", None)

    def tearDown(self):
        os.environ.pop("PERPLEXITY_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = PerplexityProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "llama-3.1-sonar-small-128k-online")

    def test_valid_key_makes_available(self):
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"
        p = PerplexityProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = PerplexityProvider()
        errors = p.validate_config()
        self.assertTrue(any("PERPLEXITY_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"
        p = PerplexityProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "perplexity")
        self.assertTrue(d["available"])
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = PerplexityProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Fireworks AI
# ---------------------------------------------------------------------------


class FireworksProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FIREWORKS_API_KEY", None)

    def tearDown(self):
        os.environ.pop("FIREWORKS_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = FireworksProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "accounts/fireworks/models/llama-v3p1-70b-instruct")

    def test_valid_key_makes_available(self):
        os.environ["FIREWORKS_API_KEY"] = "fw-test"
        p = FireworksProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = FireworksProvider()
        errors = p.validate_config()
        self.assertTrue(any("FIREWORKS_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["FIREWORKS_API_KEY"] = "fw-test"
        p = FireworksProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "fireworks")
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = FireworksProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Cerebras
# ---------------------------------------------------------------------------


class CerebrasProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CEREBRAS_API_KEY", None)

    def tearDown(self):
        os.environ.pop("CEREBRAS_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = CerebrasProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "llama3.1-70b")

    def test_valid_key_makes_available(self):
        os.environ["CEREBRAS_API_KEY"] = "csk-test"
        p = CerebrasProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = CerebrasProvider()
        errors = p.validate_config()
        self.assertTrue(any("CEREBRAS_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["CEREBRAS_API_KEY"] = "csk-test"
        p = CerebrasProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "cerebras")
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = CerebrasProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# AI21 Labs
# ---------------------------------------------------------------------------


class AI21ProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("AI21_API_KEY", None)

    def tearDown(self):
        os.environ.pop("AI21_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = AI21Provider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "jamba-1.5-mini")

    def test_valid_key_makes_available(self):
        os.environ["AI21_API_KEY"] = "ai21-test"
        p = AI21Provider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = AI21Provider()
        errors = p.validate_config()
        self.assertTrue(any("AI21_API_KEY" in e for e in errors))

    def test_validate_config_ok(self):
        os.environ["AI21_API_KEY"] = "ai21-test"
        p = AI21Provider()
        self.assertEqual(p.validate_config(), [])

    def test_to_dict(self):
        os.environ["AI21_API_KEY"] = "ai21-test"
        p = AI21Provider()
        d = p.to_dict()
        self.assertEqual(d["name"], "ai21")
        self.assertTrue(d["available"])
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = AI21Provider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# get_provider integration for new providers
# ---------------------------------------------------------------------------


class AdditionalProviderRegistryTests(unittest.TestCase):
    def test_get_provider_perplexity(self):
        os.environ["PERPLEXITY_API_KEY"] = "pplx-test"
        try:
            p = get_provider("perplexity")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "perplexity")
        finally:
            os.environ.pop("PERPLEXITY_API_KEY", None)

    def test_get_provider_fireworks(self):
        os.environ["FIREWORKS_API_KEY"] = "fw-test"
        try:
            p = get_provider("fireworks")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "fireworks")
        finally:
            os.environ.pop("FIREWORKS_API_KEY", None)

    def test_get_provider_cerebras(self):
        os.environ["CEREBRAS_API_KEY"] = "csk-test"
        try:
            p = get_provider("cerebras")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "cerebras")
        finally:
            os.environ.pop("CEREBRAS_API_KEY", None)

    def test_get_provider_ai21(self):
        os.environ["AI21_API_KEY"] = "ai21-test"
        try:
            p = get_provider("ai21")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "ai21")
        finally:
            os.environ.pop("AI21_API_KEY", None)


# ---------------------------------------------------------------------------
# HuggingFace
# ---------------------------------------------------------------------------


class HuggingFaceProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("HF_TOKEN", None)

    def tearDown(self):
        os.environ.pop("HF_TOKEN", None)

    def test_no_key_is_unavailable(self):
        p = HuggingFaceProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "meta-llama/Llama-3.3-70B-Instruct")

    def test_valid_key_makes_available(self):
        os.environ["HF_TOKEN"] = "hf_test"
        p = HuggingFaceProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = HuggingFaceProvider()
        errors = p.validate_config()
        self.assertTrue(any("HF_TOKEN" in e for e in errors))

    def test_to_dict(self):
        os.environ["HF_TOKEN"] = "hf_test"
        p = HuggingFaceProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "huggingface")
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = HuggingFaceProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# NVIDIA NIM
# ---------------------------------------------------------------------------


class NvidiaProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("NVIDIA_API_KEY", None)

    def tearDown(self):
        os.environ.pop("NVIDIA_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = NvidiaProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "meta/llama-3.1-70b-instruct")

    def test_valid_key_makes_available(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test"
        p = NvidiaProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = NvidiaProvider()
        errors = p.validate_config()
        self.assertTrue(any("NVIDIA_API_KEY" in e for e in errors))

    def test_to_dict(self):
        os.environ["NVIDIA_API_KEY"] = "nvapi-test"
        p = NvidiaProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "nvidia")
        self.assertIn("model", d)

    def test_chat_without_key_raises(self):
        p = NvidiaProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Moonshot
# ---------------------------------------------------------------------------


class MoonshotProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("MOONSHOT_API_KEY", None)

    def tearDown(self):
        os.environ.pop("MOONSHOT_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = MoonshotProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "moonshot-v1-8k")

    def test_valid_key_makes_available(self):
        os.environ["MOONSHOT_API_KEY"] = "ms-test"
        p = MoonshotProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = MoonshotProvider()
        errors = p.validate_config()
        self.assertTrue(any("MOONSHOT_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = MoonshotProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# DeepInfra
# ---------------------------------------------------------------------------


class DeepInfraProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DEEPINFRA_API_KEY", None)

    def tearDown(self):
        os.environ.pop("DEEPINFRA_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = DeepInfraProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "meta-llama/Meta-Llama-3.1-70B-Instruct")

    def test_valid_key_makes_available(self):
        os.environ["DEEPINFRA_API_KEY"] = "di-test"
        p = DeepInfraProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = DeepInfraProvider()
        errors = p.validate_config()
        self.assertTrue(any("DEEPINFRA_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = DeepInfraProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Qwen / DashScope
# ---------------------------------------------------------------------------


class QwenProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DASHSCOPE_API_KEY", None)

    def tearDown(self):
        os.environ.pop("DASHSCOPE_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = QwenProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "qwen-turbo")

    def test_valid_key_makes_available(self):
        os.environ["DASHSCOPE_API_KEY"] = "sk-ds-test"
        p = QwenProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = QwenProvider()
        errors = p.validate_config()
        self.assertTrue(any("DASHSCOPE_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = QwenProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Volcengine / Doubao
# ---------------------------------------------------------------------------


class VolcengineProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ARK_API_KEY", None)

    def tearDown(self):
        os.environ.pop("ARK_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = VolcengineProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "doubao-pro-4k")

    def test_valid_key_makes_available(self):
        os.environ["ARK_API_KEY"] = "ark-test"
        p = VolcengineProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = VolcengineProvider()
        errors = p.validate_config()
        self.assertTrue(any("ARK_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = VolcengineProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# StepFun
# ---------------------------------------------------------------------------


class StepFunProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("STEPFUN_API_KEY", None)

    def tearDown(self):
        os.environ.pop("STEPFUN_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = StepFunProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "step-1-8k")

    def test_valid_key_makes_available(self):
        os.environ["STEPFUN_API_KEY"] = "sf-test"
        p = StepFunProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = StepFunProvider()
        errors = p.validate_config()
        self.assertTrue(any("STEPFUN_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = StepFunProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# GLM / ZhipuAI
# ---------------------------------------------------------------------------


class GlmProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ZHIPUAI_API_KEY", None)

    def tearDown(self):
        os.environ.pop("ZHIPUAI_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = GlmProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "glm-4-flash")

    def test_valid_key_makes_available(self):
        os.environ["ZHIPUAI_API_KEY"] = "zp-test"
        p = GlmProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = GlmProvider()
        errors = p.validate_config()
        self.assertTrue(any("ZHIPUAI_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = GlmProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# Venice AI
# ---------------------------------------------------------------------------


class VeniceProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("VENICE_API_KEY", None)

    def tearDown(self):
        os.environ.pop("VENICE_API_KEY", None)

    def test_no_key_is_unavailable(self):
        p = VeniceProvider()
        self.assertFalse(p.available)
        self.assertEqual(p.model, "llama-3.3-70b")

    def test_valid_key_makes_available(self):
        os.environ["VENICE_API_KEY"] = "vc-test"
        p = VeniceProvider()
        self.assertTrue(p.available)

    def test_validate_config_missing_key(self):
        p = VeniceProvider()
        errors = p.validate_config()
        self.assertTrue(any("VENICE_API_KEY" in e for e in errors))

    def test_chat_without_key_raises(self):
        p = VeniceProvider()
        with self.assertRaises(RuntimeError):
            p.chat("system", "user")


# ---------------------------------------------------------------------------
# LM Studio (local)
# ---------------------------------------------------------------------------


class LMStudioProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("LMSTUDIO_BASE_URL", None)
        os.environ.pop("LMSTUDIO_MODEL", None)

    def tearDown(self):
        os.environ.pop("LMSTUDIO_BASE_URL", None)
        os.environ.pop("LMSTUDIO_MODEL", None)

    def test_available_by_default(self):
        p = LMStudioProvider()
        self.assertTrue(p.available)

    def test_default_model(self):
        p = LMStudioProvider()
        self.assertEqual(p.model, "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF")

    def test_custom_base_url(self):
        os.environ["LMSTUDIO_BASE_URL"] = "http://localhost:5678"
        p = LMStudioProvider()
        self.assertIn("5678", p._base_url)

    def test_to_dict_has_base_url(self):
        p = LMStudioProvider()
        d = p.to_dict()
        self.assertEqual(d["name"], "lmstudio")
        self.assertIn("base_url", d)

    def test_validate_config_unreachable_server_returns_note(self):
        p = LMStudioProvider()
        notes = p.validate_config()
        # LM Studio is not running in CI; expect a note, not a hard error
        self.assertIsInstance(notes, list)


# ---------------------------------------------------------------------------
# Vultr Serverless Inference
# ---------------------------------------------------------------------------


class VultrInferenceProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("VULTR_INFERENCE_API_KEY", None)
        os.environ.pop("VULTR_INFERENCE_MODEL", None)
        os.environ.pop("VULTR_INFERENCE_BASE_URL", None)

    def tearDown(self):
        os.environ.pop("VULTR_INFERENCE_API_KEY", None)
        os.environ.pop("VULTR_INFERENCE_MODEL", None)
        os.environ.pop("VULTR_INFERENCE_BASE_URL", None)

    def test_missing_env_fails_closed(self):
        p = VultrInferenceProvider()

        self.assertFalse(p.available)
        self.assertIn("VULTR_INFERENCE_API_KEY is not set", p.validate_config())
        self.assertIn("VULTR_INFERENCE_MODEL must be non-empty", p.validate_config())
        self.assertIn("VULTR_INFERENCE_BASE_URL is not set", p.validate_config())

    def test_env_config_makes_provider_available(self):
        os.environ["VULTR_INFERENCE_API_KEY"] = "vultr-test-key"
        os.environ["VULTR_INFERENCE_MODEL"] = "test-model"
        os.environ["VULTR_INFERENCE_BASE_URL"] = "https://api.vultrinference.com/v1/chat/completions"

        p = VultrInferenceProvider()

        self.assertTrue(p.available)
        self.assertEqual(p.model, "test-model")
        self.assertEqual(p._base_url, "https://api.vultrinference.com/v1/chat/completions")
        self.assertEqual(p.validate_config(), [])

    def test_to_dict_does_not_leak_secret_or_endpoint(self):
        os.environ["VULTR_INFERENCE_API_KEY"] = "vultr-secret-value"
        os.environ["VULTR_INFERENCE_MODEL"] = "test-model"
        os.environ["VULTR_INFERENCE_BASE_URL"] = "https://api.vultrinference.com/v1/chat/completions"

        payload = VultrInferenceProvider().to_dict()

        self.assertEqual(payload["name"], "vultr")
        self.assertTrue(payload["available"])
        self.assertEqual(payload["model"], "test-model")
        self.assertTrue(payload["base_url_configured"])
        self.assertNotIn("vultr-secret-value", repr(payload))
        self.assertNotIn("api.vultrinference.com", repr(payload))


# ---------------------------------------------------------------------------
# Tier-5 get_provider integration
# ---------------------------------------------------------------------------


class Tier5ProviderRegistryTests(unittest.TestCase):
    def _check(self, name: str, env_key: str, env_val: str) -> None:
        os.environ[env_key] = env_val
        try:
            p = get_provider(name)
            self.assertIsNotNone(p)
            self.assertEqual(p.name, name)
        finally:
            os.environ.pop(env_key, None)

    def test_huggingface(self):
        self._check("huggingface", "HF_TOKEN", "hf_test")

    def test_nvidia(self):
        self._check("nvidia", "NVIDIA_API_KEY", "nvapi-test")

    def test_moonshot(self):
        self._check("moonshot", "MOONSHOT_API_KEY", "ms-test")

    def test_deepinfra(self):
        self._check("deepinfra", "DEEPINFRA_API_KEY", "di-test")

    def test_qwen(self):
        self._check("qwen", "DASHSCOPE_API_KEY", "sk-ds-test")

    def test_volcengine(self):
        self._check("volcengine", "ARK_API_KEY", "ark-test")

    def test_stepfun(self):
        self._check("stepfun", "STEPFUN_API_KEY", "sf-test")

    def test_glm(self):
        self._check("glm", "ZHIPUAI_API_KEY", "zp-test")

    def test_venice(self):
        self._check("venice", "VENICE_API_KEY", "vc-test")

    def test_lmstudio(self):
        p = get_provider("lmstudio")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "lmstudio")

    def test_vultr(self):
        os.environ["VULTR_INFERENCE_API_KEY"] = "vultr-test-key"
        os.environ["VULTR_INFERENCE_MODEL"] = "test-model"
        os.environ["VULTR_INFERENCE_BASE_URL"] = "https://api.vultrinference.com/v1/chat/completions"
        try:
            p = get_provider("vultr")
            self.assertIsNotNone(p)
            self.assertEqual(p.name, "vultr")
            self.assertTrue(p.available)
        finally:
            os.environ.pop("VULTR_INFERENCE_API_KEY", None)
            os.environ.pop("VULTR_INFERENCE_MODEL", None)
            os.environ.pop("VULTR_INFERENCE_BASE_URL", None)


if __name__ == "__main__":
    unittest.main()
