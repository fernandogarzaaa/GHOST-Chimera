"""Performance regression tests for IBM Bob developer toolchain.

These tests establish baseline performance metrics for Bob's developer tools
to catch obvious slowdowns without being flaky on Windows or slower machines.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add project root and scripts to path
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from bob_accelerator import generate_report
from bob_delivery_package import generate_delivery_package
from coverage_report import analyze_coverage
from generate_test_scaffold import analyze_source_file, generate_test_scaffold


class TestCoverageReportPerformance:
    """Performance tests for coverage report analysis."""

    def test_coverage_report_analysis_performance(self):
        """Test that coverage report analysis completes in reasonable time."""
        # Generous threshold: 10 seconds
        max_duration = 10.0

        start_time = time.perf_counter()
        result = analyze_coverage()
        end_time = time.perf_counter()

        duration = end_time - start_time

        # Verify result has expected structure
        assert isinstance(result, dict), "Coverage report should return a dict"
        assert "total_modules" in result, "Should include total_modules"
        assert "tested_count" in result, "Should include tested_count"
        assert "coverage_ratio" in result, "Should include coverage_ratio"

        # Verify performance
        assert duration < max_duration, (
            f"Coverage report analysis took {duration:.2f}s, "
            f"expected under {max_duration}s"
        )

        # Print timing for visibility
        print(f"\n[PASS] Coverage report analysis: {duration:.2f}s (threshold: {max_duration}s)")


class TestBobAcceleratorPerformance:
    """Performance tests for Bob accelerator report generation."""

    def test_bob_accelerator_json_report_performance(self):
        """Test that Bob accelerator JSON report generation completes in reasonable time."""
        # Generous threshold: 20 seconds
        max_duration = 20.0

        start_time = time.perf_counter()
        result = generate_report(format_type="json")
        end_time = time.perf_counter()

        duration = end_time - start_time

        # Verify result has expected structure
        assert isinstance(result, str), "JSON report should return a string"
        assert len(result) > 100, "Report should have substantial content"
        assert "generated_at" in result, "Should include timestamp"

        # Verify performance
        assert duration < max_duration, (
            f"Bob accelerator JSON report took {duration:.2f}s, "
            f"expected under {max_duration}s"
        )

        # Print timing for visibility
        print(f"\n[PASS] Bob accelerator JSON report: {duration:.2f}s (threshold: {max_duration}s)")


class TestDeliveryPackagePerformance:
    """Performance tests for delivery package generation."""

    def test_delivery_package_markdown_generation_performance(self):
        """Test that delivery package markdown generation completes in reasonable time."""
        # Generous threshold: 20 seconds
        max_duration = 20.0

        start_time = time.perf_counter()
        result = generate_delivery_package(format_type="markdown")
        end_time = time.perf_counter()

        duration = end_time - start_time

        # Verify result has expected structure
        assert isinstance(result, str), "Markdown package should return a string"
        assert len(result) > 500, "Package should have substantial content"
        assert "Bob" in result, "Should mention Bob"
        assert "Tools" in result or "tools" in result, "Should mention tools"

        # Verify performance
        assert duration < max_duration, (
            f"Delivery package markdown generation took {duration:.2f}s, "
            f"expected under {max_duration}s"
        )

        # Print timing for visibility
        print(f"\n[PASS] Delivery package markdown: {duration:.2f}s (threshold: {max_duration}s)")


class TestScaffoldGenerationPerformance:
    """Performance tests for test scaffold generation."""

    def test_test_scaffold_generation_performance(self, tmp_path):
        """Test that test scaffold generation completes in reasonable time."""
        # Generous threshold: 5 seconds
        max_duration = 5.0

        # Create a temporary source module with various symbols
        source_content = '''"""Test module for performance testing."""

def public_function_1(arg1, arg2):
    """A public function."""
    return arg1 + arg2

def public_function_2(data):
    """Another public function."""
    return data * 2

async def async_public_function(value):
    """An async public function."""
    return value

def _private_function():
    """A private function."""
    pass

class PublicClass1:
    """A public class."""

    def __init__(self, value):
        """Initialize."""
        self.value = value

    def public_method_1(self):
        """A public method."""
        return self.value

    def public_method_2(self, x):
        """Another public method."""
        return self.value + x

    def _private_method(self):
        """A private method."""
        pass

class PublicClass2:
    """Another public class."""

    def method_a(self):
        """Method A."""
        pass

    def method_b(self):
        """Method B."""
        pass

class _PrivateClass:
    """A private class."""
    pass
'''
        source_path = tmp_path / "perf_test_source.py"
        source_path.write_text(source_content)

        # Time the analysis and generation
        start_time = time.perf_counter()

        # Analyze source file
        analysis = analyze_source_file(source_path)

        # Generate scaffold
        scaffold = generate_test_scaffold(analysis, source_path)

        end_time = time.perf_counter()

        duration = end_time - start_time

        # Verify analysis results
        assert isinstance(analysis, dict), "Analysis should return a dict"
        assert "functions" in analysis, "Should include functions"
        assert "classes" in analysis, "Should include classes"
        assert len(analysis["functions"]) >= 3, "Should find public functions"
        assert len(analysis["classes"]) >= 2, "Should find public classes"

        # Verify scaffold results
        assert isinstance(scaffold, str), "Scaffold should return a string"
        assert len(scaffold) > 100, "Scaffold should have content"
        assert "import pytest" in scaffold, "Should include pytest import"

        # Verify performance
        assert duration < max_duration, (
            f"Test scaffold generation took {duration:.2f}s, "
            f"expected under {max_duration}s"
        )

        # Print timing for visibility
        print(f"\n[PASS] Test scaffold generation: {duration:.2f}s (threshold: {max_duration}s)")


class TestBobToolchainOverallPerformance:
    """Overall performance test for the complete Bob toolchain."""

    def test_bob_toolchain_overall_performance(self, tmp_path):
        """Test that running all Bob tools sequentially completes in reasonable time."""
        # Generous threshold: 60 seconds for all operations
        max_duration = 60.0

        timings = {}

        # Overall start time
        overall_start = time.perf_counter()

        # 1. Coverage report
        start = time.perf_counter()
        coverage_result = analyze_coverage()
        timings["coverage_report"] = time.perf_counter() - start
        assert isinstance(coverage_result, dict)

        # 2. Bob accelerator report
        start = time.perf_counter()
        accelerator_result = generate_report(format_type="json")
        timings["bob_accelerator"] = time.perf_counter() - start
        assert isinstance(accelerator_result, str)

        # 3. Delivery package
        start = time.perf_counter()
        package_result = generate_delivery_package(format_type="markdown")
        timings["delivery_package"] = time.perf_counter() - start
        assert isinstance(package_result, str)

        # 4. Test scaffold generation
        source_content = '''"""Test module."""
def test_func():
    pass

class TestClass:
    def test_method(self):
        pass
'''
        source_path = tmp_path / "test_source.py"
        source_path.write_text(source_content)

        start = time.perf_counter()
        analysis = analyze_source_file(source_path)
        scaffold = generate_test_scaffold(analysis, source_path)
        timings["test_scaffold"] = time.perf_counter() - start
        assert isinstance(scaffold, str)

        # Overall end time
        overall_duration = time.perf_counter() - overall_start

        # Verify overall performance
        assert overall_duration < max_duration, (
            f"Bob toolchain overall execution took {overall_duration:.2f}s, "
            f"expected under {max_duration}s. "
            f"Individual timings: {timings}"
        )

        # Print detailed timing breakdown
        print(f"\n[PASS] Bob toolchain overall: {overall_duration:.2f}s (threshold: {max_duration}s)")
        print(f"  - Coverage report: {timings['coverage_report']:.2f}s")
        print(f"  - Bob accelerator: {timings['bob_accelerator']:.2f}s")
        print(f"  - Delivery package: {timings['delivery_package']:.2f}s")
        print(f"  - Test scaffold: {timings['test_scaffold']:.2f}s")

# Made with Bob
