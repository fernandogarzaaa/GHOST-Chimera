"""Unit tests for model provider routing."""

import os
import unittest

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


if __name__ == "__main__":
    unittest.main()
