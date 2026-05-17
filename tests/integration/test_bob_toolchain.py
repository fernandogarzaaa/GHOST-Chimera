"""Integration tests for IBM Bob developer toolchain.

Tests the end-to-end workflows of Bob's developer tools working together.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

# Add project root and scripts to path
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from bob_accelerator import (  # noqa: E402
    detect_bob_tools,
    generate_report,
)
from bob_delivery_package import generate_delivery_package  # noqa: E402
from coverage_report import analyze_coverage, format_markdown_report  # noqa: E402
from generate_test_scaffold import (  # noqa: E402
    analyze_source_file,
    generate_test_scaffold,
)
from validate_config import format_json_output, format_text, parse_env_file, validate_config  # noqa: E402


class TestBobAcceleratorToDeliveryPackage:
    """Test the Bob accelerator to delivery package pipeline."""

    def test_accelerator_detects_all_bob_tools(self):
        """Test that bob_accelerator detects all current Bob tools."""
        tools_data = detect_bob_tools()

        assert tools_data["installed_count"] >= 12, "Should detect at least 12 Bob tools"

        # Verify specific tools are detected
        tool_names = [tool["name"] for tool in tools_data["installed_tools"]]

        expected_tools = [
            "bob_accelerator.py",
            "coverage_report.py",
            "bob_delivery_package.py",
            "generate_changelog.py",
            "validate_config.py",
            "audit_dependencies.py",
            "generate_test_scaffold.py",
            "generate_api_reference.py",
            "generate_sbom.py",
            "dependency_graph.py",
            "analyze_logs.py",
            "dev_env.py",
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Should detect {expected}"

    def test_delivery_package_includes_all_tools(self):
        """Test that delivery package includes all Bob tools."""
        package = generate_delivery_package(format_type="json")

        assert isinstance(package, dict), "JSON format should return dict"
        assert "bob_tools" in package, "Should include bob_tools section"

        tools = package["bob_tools"]["tools"]
        tool_names = [tool["name"] for tool in tools]

        # Verify all key tools are included (using friendly names from bob_delivery_package.py)
        expected_tools = [
            "Bob Accelerator",
            "Coverage Reporter",
            "Delivery Package Generator",
            "Changelog Generator",
            "Configuration Validator",
            "Dependency Auditor",
            "Test Scaffold Generator",
            "API Reference Generator",
            "SBOM-lite Generator",
            "Dependency Graph Visualizer",
            "Debug Logging Analyzer",
            "Dev Environment Manager",
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Delivery package should include {expected}"

    def test_delivery_package_includes_verification_commands(self):
        """Test that delivery package includes verification commands."""
        package_md = generate_delivery_package(format_type="markdown")

        assert isinstance(package_md, str), "Markdown format should return string"

        # Verify key verification commands are present
        assert "python scripts/bob_accelerator.py" in package_md
        assert "python scripts/coverage_report.py" in package_md
        assert "python scripts/generate_changelog.py" in package_md
        assert "python scripts/validate_config.py" in package_md
        assert "python scripts/audit_dependencies.py" in package_md
        assert "python scripts/generate_test_scaffold.py" in package_md
        assert "python scripts/bob_delivery_package.py" in package_md

        # Verify test commands are present
        assert "pytest" in package_md
        assert "test_bob_accelerator.py" in package_md
        assert "test_generate_test_scaffold.py" in package_md

    def test_full_accelerator_report_generation(self):
        """Test full bob_accelerator report generation."""
        report_str = generate_report(format_type="json")

        # JSON format returns a string, not a dict
        assert isinstance(report_str, str), "JSON format should return string"
        assert len(report_str) > 100, "Report should have substantial content"

        # Parse the JSON to verify it's valid
        report = json.loads(report_str)

        # Verify report is a dict with content
        assert isinstance(report, dict)
        assert len(report) >= 3, "Report should have multiple sections"

        # Verify key metadata fields exist
        assert "generated_at" in report
        assert "generated_by" in report


class TestCoverageReportWorkflow:
    """Test coverage report generation workflow."""

    def test_coverage_report_markdown_generation(self):
        """Test coverage report markdown generation."""
        coverage_data = analyze_coverage()
        markdown = format_markdown_report(coverage_data)

        # Verify structure (actual keys from coverage_report.py)
        assert "total_modules" in coverage_data
        assert "tested_count" in coverage_data
        assert "untested_count" in coverage_data
        assert "tested" in coverage_data
        assert "untested" in coverage_data
        assert "coverage_ratio" in coverage_data

        # Verify counts are reasonable
        assert coverage_data["total_modules"] > 0
        assert coverage_data["tested_count"] >= 0
        assert 0 <= coverage_data["coverage_ratio"] <= 1.0

        # Verify tested/untested lists have expected structure
        if coverage_data["tested"]:
            first_tested = coverage_data["tested"][0]
            assert "module" in first_tested
            assert "source" in first_tested
            assert "test" in first_tested

        if coverage_data["untested"]:
            first_untested = coverage_data["untested"][0]
            assert "module" in first_untested
            assert "source" in first_untested

        assert "# Test Coverage Report" in markdown
        assert "Total Source Modules" in markdown
        assert "Coverage Ratio" in markdown
        if coverage_data["untested"]:
            assert "Untested Modules" in markdown

    def test_coverage_report_includes_source_and_test_counts(self):
        """Test that coverage report includes accurate counts."""
        coverage_data = analyze_coverage()

        # Verify counts add up
        tested_count = coverage_data["tested_count"]
        untested_count = coverage_data["untested_count"]

        # Total modules should equal tested + untested
        assert coverage_data["total_modules"] == tested_count + untested_count


class TestConfigurationValidationWorkflow:
    """Test configuration validation workflow."""

    def test_safe_production_config_passes(self, tmp_path):
        """Test that a safe production config passes validation."""
        # Create a safe production config
        config_content = """GHOSTCHIMERA_DEPLOYMENT_MODE=production
GHOSTCHIMERA_EXTERNAL_ISOLATION=container
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=0
GHOSTCHIMERA_CONSOLE_AUTH_TOKEN=prod-test-token-12345
VULTR_INFERENCE_API_KEY=vultr-test-key-67890
VULTR_INFERENCE_MODEL=llama-3.1-70b
VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1
"""
        config_path = tmp_path / "safe_config.env"
        config_path.write_text(config_content)

        env_vars = parse_env_file(config_path)
        result = validate_config(env_vars, production_mode=True)

        assert isinstance(result, dict)
        assert "valid" in result
        assert "errors" in result
        assert "warnings" in result
        assert result["valid"] is True
        assert result["errors"] == []

    def test_unsafe_production_config_fails(self, tmp_path):
        """Test that an unsafe production config fails validation."""
        # Create an unsafe production config (missing safety settings)
        config_content = """GHOSTCHIMERA_DEPLOYMENT_MODE=production
GHOSTCHIMERA_EXTERNAL_ISOLATION=host
GHOSTCHIMERA_SECURITY_REVIEWED=0
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=0
GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=1
GHOSTCHIMERA_CONSOLE_AUTH_TOKEN=replace-with-token
"""
        config_path = tmp_path / "unsafe_config.env"
        config_path.write_text(config_content)

        env_vars = parse_env_file(config_path)
        result = validate_config(env_vars, production_mode=True)

        assert isinstance(result, dict)
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("GHOSTCHIMERA_EXTERNAL_ISOLATION" in error for error in result["errors"])
        assert any("GHOSTCHIMERA_SECURITY_REVIEWED" in error for error in result["errors"])

    def test_secrets_are_redacted_in_output(self, tmp_path):
        """Test that secrets are redacted in validation output."""
        config_content = """GHOSTCHIMERA_DEPLOYMENT_MODE=production
GHOSTCHIMERA_EXTERNAL_ISOLATION=container
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=0
GHOSTCHIMERA_CONSOLE_AUTH_TOKEN=console-secret-key-should-not-appear
VULTR_INFERENCE_API_KEY=vultr-secret-key-should-not-appear
VULTR_INFERENCE_MODEL=llama-3.1-70b
VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1
"""
        config_path = tmp_path / "config_with_secrets.env"
        config_path.write_text(config_content)

        env_vars = parse_env_file(config_path)
        result = validate_config(env_vars, production_mode=False)

        # Convert result to JSON/text to check for secrets
        result_json_str = format_json_output(result)
        result_text = format_text(result)

        # Verify secrets are not in the output
        assert "console-secret-key-should-not-appear" not in result_json_str
        assert "vultr-secret-key-should-not-appear" not in result_json_str
        assert "console-secret-key-should-not-appear" not in result_text
        assert "vultr-secret-key-should-not-appear" not in result_text

        # Verify redaction markers are present
        assert "REDACTED" in result_json_str or "[NOT SET]" in result_json_str
        assert "REDACTED" in result_text


class TestScaffoldGenerationWorkflow:
    """Test test scaffold generation workflow."""

    def test_scaffold_generation_for_mixed_module(self, tmp_path):
        """Test scaffold generation for a module with mixed public/private symbols."""
        # Create a temporary source module
        source_content = '''"""Test module for scaffold generation."""

def public_function(arg1, arg2):
    """A public function."""
    return arg1 + arg2

def _private_function():
    """A private function that should be skipped."""
    pass

async def async_public_function(data):
    """An async public function."""
    return data

class PublicClass:
    """A public class."""

    def __init__(self, value):
        """Initialize the class."""
        self.value = value

    def public_method(self):
        """A public method."""
        return self.value

    def _private_method(self):
        """A private method that should be skipped."""
        pass

class _PrivateClass:
    """A private class that should be skipped."""
    pass
'''
        source_path = tmp_path / "test_source.py"
        source_path.write_text(source_content)

        # Analyze the source file
        analysis = analyze_source_file(source_path)

        # Verify analysis results
        assert len(analysis["functions"]) == 2  # public_function, async_public_function
        assert len(analysis["classes"]) == 1  # PublicClass

        func_names = [f["name"] for f in analysis["functions"]]
        assert "public_function" in func_names
        assert "async_public_function" in func_names
        assert "_private_function" not in func_names

        class_names = [c["name"] for c in analysis["classes"]]
        assert "PublicClass" in class_names
        assert "_PrivateClass" not in class_names

        # Verify PublicClass methods
        public_class = analysis["classes"][0]
        method_names = [m["name"] for m in public_class["methods"]]
        assert "public_method" in method_names
        assert "_private_method" not in method_names

    def test_generated_scaffold_is_valid_python(self, tmp_path):
        """Test that generated scaffold is valid Python and compiles."""
        # Create a simple source module
        source_content = '''"""Simple test module."""

def test_function(x):
    """A test function."""
    return x * 2

class TestClass:
    """A test class."""

    def test_method(self):
        """A test method."""
        return 42
'''
        source_path = tmp_path / "simple_source.py"
        source_path.write_text(source_content)

        # Generate scaffold
        analysis = analyze_source_file(source_path)
        scaffold = generate_test_scaffold(analysis, source_path)

        # Verify scaffold is valid Python
        try:
            ast.parse(scaffold)
        except SyntaxError as e:
            pytest.fail(f"Generated scaffold is not valid Python: {e}")

        # Verify scaffold contains expected elements
        assert "import pytest" in scaffold
        assert "def test_test_function():" in scaffold
        assert "class TestTestClass:" in scaffold
        assert "def test_test_method(" in scaffold

    def test_scaffold_imports_public_symbols(self, tmp_path):
        """Test that scaffold imports expected public symbols."""
        source_content = '''"""Module with public symbols."""

def func_a():
    pass

def func_b():
    pass

class ClassA:
    pass
'''
        source_path = tmp_path / "symbols_source.py"
        source_path.write_text(source_content)

        analysis = analyze_source_file(source_path)
        scaffold = generate_test_scaffold(analysis, source_path)

        # Verify imports section includes the public symbols
        assert "func_a" in scaffold
        assert "func_b" in scaffold
        assert "ClassA" in scaffold

    def test_scaffold_does_not_include_private_symbols(self, tmp_path):
        """Test that scaffold does not include private symbols."""
        source_content = '''"""Module with private symbols."""

def public_func():
    pass

def _private_func():
    pass

class PublicClass:
    def public_method(self):
        pass

    def _private_method(self):
        pass

class _PrivateClass:
    pass
'''
        source_path = tmp_path / "private_source.py"
        source_path.write_text(source_content)

        analysis = analyze_source_file(source_path)
        scaffold = generate_test_scaffold(analysis, source_path)

        # Verify private symbols are not in the scaffold
        assert "_private_func" not in scaffold
        assert "_PrivateClass" not in scaffold
        assert "_private_method" not in scaffold

        # Verify public symbols are present
        assert "public_func" in scaffold
        assert "PublicClass" in scaffold
        assert "public_method" in scaffold


class TestBobToolchainIntegration:
    """Test integration between multiple Bob tools."""

    def test_coverage_report_feeds_into_test_scaffold_generation(self, tmp_path):
        """Test that coverage report can identify targets for test scaffold generation."""
        # Get coverage data
        coverage_data = analyze_coverage()

        # Verify we have untested modules
        assert len(coverage_data["untested"]) > 0, "Should have untested modules"

        analyzable_target_found = False
        for untested_module in coverage_data["untested"]:
            source_path = Path(ROOT) / untested_module["source"]

            if not source_path.exists() or source_path.suffix != ".py":
                continue

            analysis = analyze_source_file(source_path)
            assert "functions" in analysis
            assert "classes" in analysis

            if analysis["functions"] or analysis["classes"]:
                scaffold = generate_test_scaffold(analysis, source_path)
                ast.parse(scaffold)
                analyzable_target_found = True
                break

        assert analyzable_target_found, "Expected at least one untested module that can generate a scaffold"

    def test_bob_tools_are_self_documenting(self):
        """Test that Bob tools appear in their own reports."""
        # Generate delivery package
        package = generate_delivery_package(format_type="json")

        # Verify Bob tools are documented
        tools = package["bob_tools"]["tools"]
        tool_names = [tool["name"] for tool in tools]

        # Bob tools should document themselves (using friendly names)
        assert "Bob Accelerator" in tool_names
        assert "Coverage Reporter" in tool_names
        assert "Delivery Package Generator" in tool_names


# Made with Bob
