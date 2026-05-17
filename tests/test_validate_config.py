"""
Tests for Configuration Validator.

Tests the configuration validation tool with fixture env files.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.validate_config import (  # noqa: E402
    format_json_output,
    format_text,
    parse_env_file,
    redact_secret,
    validate_config,
)


class TestEnvFileParsing:
    """Test .env file parsing."""

    def test_parse_env_file_empty(self):
        """Test parsing an empty env file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            result = parse_env_file(temp_path)
            assert result == {}
        finally:
            temp_path.unlink()

    def test_parse_env_file_simple(self):
        """Test parsing a simple env file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY1=value1\n")
            f.write("KEY2=value2\n")
            temp_path = Path(f.name)

        try:
            result = parse_env_file(temp_path)
            assert result["KEY1"] == "value1"
            assert result["KEY2"] == "value2"
        finally:
            temp_path.unlink()

    def test_parse_env_file_with_comments(self):
        """Test parsing env file with comments."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("KEY1=value1\n")
            f.write("# Another comment\n")
            f.write("KEY2=value2\n")
            temp_path = Path(f.name)

        try:
            result = parse_env_file(temp_path)
            assert result["KEY1"] == "value1"
            assert result["KEY2"] == "value2"
            assert len(result) == 2
        finally:
            temp_path.unlink()

    def test_parse_env_file_with_empty_lines(self):
        """Test parsing env file with empty lines."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY1=value1\n")
            f.write("\n")
            f.write("KEY2=value2\n")
            temp_path = Path(f.name)

        try:
            result = parse_env_file(temp_path)
            assert result["KEY1"] == "value1"
            assert result["KEY2"] == "value2"
        finally:
            temp_path.unlink()

    def test_parse_env_file_nonexistent(self):
        """Test parsing a nonexistent env file."""
        result = parse_env_file(Path("/nonexistent/file.env"))
        assert result == {}


class TestSecretRedaction:
    """Test secret redaction."""

    def test_redact_secret_empty(self):
        """Test redacting an empty secret."""
        assert redact_secret("") == "[NOT SET]"

    def test_redact_secret_short(self):
        """Test redacting a short secret."""
        assert redact_secret("abc") == "[REDACTED]"
        assert redact_secret("ab") == "[REDACTED]"

    def test_redact_secret_long(self):
        """Test redacting a long secret."""
        result = redact_secret("abcdefghijk")
        assert result.startswith("ab...")
        assert result.endswith("jk [REDACTED]")
        assert "cdefghi" not in result

    def test_redact_secret_never_shows_full_value(self):
        """Test that redaction never shows the full secret value."""
        secret = "my_secret_api_key_12345"
        result = redact_secret(secret)
        assert secret not in result
        assert "[REDACTED]" in result


class TestConfigValidation:
    """Test configuration validation logic."""

    def test_validate_config_empty(self):
        """Test validation with no environment variables."""
        result = validate_config({})

        assert result["valid"] is True  # No errors in non-production mode
        assert len(result["warnings"]) > 0
        assert len(result["checks"]) > 0
        assert any(check["name"] == "GHOSTCHIMERA_MODEL_PROVIDER" for check in result["checks"])

    def test_validate_config_production_safe(self):
        """Test validation with safe production config."""
        env_vars = {
            "GHOSTCHIMERA_MODEL_PROVIDER": "vultr",
            "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "secret_token_here",
            "VULTR_INFERENCE_API_KEY": "vultr_key_here",
            "VULTR_INFERENCE_MODEL": "llama-3.1-70b",
            "VULTR_INFERENCE_BASE_URL": "https://api.vultrinference.com/v1",
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_config_production_unsafe(self):
        """Test validation with unsafe production config."""
        env_vars = {
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "false",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "false",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "false",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "true",
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("EXTERNAL_ISOLATION" in error for error in result["errors"])
        assert any("SECURITY_REVIEWED" in error for error in result["errors"])
        assert any("HUMAN_APPROVAL" in error for error in result["errors"])
        assert any("UNTRUSTED_INPUTS" in error for error in result["errors"])

    def test_validate_config_secrets_never_printed(self):
        """Test that secrets are never printed in validation results."""
        env_vars = {
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "super_secret_token_12345",
            "VULTR_INFERENCE_API_KEY": "vultr_secret_key_67890",
        }

        result = validate_config(env_vars)

        # Check that secrets are not in the results
        result_str = json.dumps(result)
        assert "super_secret_token_12345" not in result_str
        assert "vultr_secret_key_67890" not in result_str

        # Check that redacted values are present
        assert any("[REDACTED]" in str(check["value"]) for check in result["checks"])

    def test_validate_config_missing_token_in_production(self):
        """Test that missing console token fails in production."""
        env_vars = {
            "GHOSTCHIMERA_MODEL_PROVIDER": "vultr",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            # Missing GHOSTCHIMERA_CONSOLE_AUTH_TOKEN
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is False
        assert any("CONSOLE_AUTH_TOKEN" in error for error in result["errors"])

    def test_validate_config_placeholder_token_fails_in_production(self):
        """Test that example tokens fail production validation."""
        env_vars = {
            "GHOSTCHIMERA_MODEL_PROVIDER": "vultr",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "replace-with-long-random-demo-token",
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is False
        assert any("placeholder" in error for error in result["errors"])

    def test_validate_config_missing_provider_fails_in_production(self):
        """Test that production config requires an explicit provider selection."""
        env_vars = {
            "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "secret_token_here",
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is False
        assert any("MODEL_PROVIDER" in error for error in result["errors"])

    def test_validate_config_openai_requires_api_key_and_model(self):
        """Test provider-specific validation for OpenAI production config."""
        env_vars = {
            "GHOSTCHIMERA_MODEL_PROVIDER": "openai",
            "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
            "GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS": "0",
            "GHOSTCHIMERA_CONSOLE_AUTH_TOKEN": "secret_token_here",
            "OPENAI_MODEL": "gpt-4o-mini",
        }

        result = validate_config(env_vars, production_mode=True)

        assert result["valid"] is False
        assert any(error == "OpenAI API key not set" for error in result["errors"])


class TestConfigFormatting:
    """Test configuration validation output formatting."""

    def test_format_text_valid(self):
        """Test text formatting for valid config."""
        results = {
            "valid": True,
            "errors": [],
            "warnings": ["Some warning"],
            "checks": [{"name": "TEST_VAR", "value": "test_value", "status": "OK"}],
        }

        output = format_text(results)

        assert "VALID" in output
        assert "TEST_VAR" in output
        assert "test_value" in output
        assert "Some warning" in output

    def test_format_text_invalid(self):
        """Test text formatting for invalid config."""
        results = {
            "valid": False,
            "errors": ["Critical error"],
            "warnings": [],
            "checks": [{"name": "TEST_VAR", "value": "[NOT SET]", "status": "ERROR"}],
        }

        output = format_text(results)

        assert "INVALID" in output
        assert "Critical error" in output

    def test_format_json_output(self):
        """Test JSON formatting."""
        results = {
            "valid": True,
            "errors": [],
            "warnings": ["Warning"],
            "checks": [{"name": "TEST", "value": "value", "status": "OK"}],
        }

        output = format_json_output(results)
        parsed = json.loads(output)

        assert parsed["valid"] is True
        assert len(parsed["warnings"]) == 1
        assert len(parsed["checks"]) == 1


class TestConfigValidatorIntegration:
    """Test configuration validator integration."""

    def test_validator_with_fixture_env_file(self):
        """Test validator with a complete fixture env file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# Ghost Chimera Production Config\n")
            f.write("GHOSTCHIMERA_MODEL_PROVIDER=vultr\n")
            f.write("GHOSTCHIMERA_DEPLOYMENT_MODE=production\n")
            f.write("GHOSTCHIMERA_EXTERNAL_ISOLATION=container\n")
            f.write("GHOSTCHIMERA_SECURITY_REVIEWED=1\n")
            f.write("GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1\n")
            f.write("GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=0\n")
            f.write("GHOSTCHIMERA_CONSOLE_AUTH_TOKEN=test_token_12345\n")
            f.write("VULTR_INFERENCE_API_KEY=vultr_key_67890\n")
            f.write("VULTR_INFERENCE_MODEL=llama-3.1-70b\n")
            f.write("VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1\n")
            temp_path = Path(f.name)

        try:
            env_vars = parse_env_file(temp_path)
            result = validate_config(env_vars, production_mode=True)

            assert result["valid"] is True
            assert len(result["errors"]) == 0

            # Verify secrets are redacted
            result_str = json.dumps(result)
            assert "test_token_12345" not in result_str
            assert "vultr_key_67890" not in result_str
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Made with Bob
