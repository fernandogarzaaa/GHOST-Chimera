"""Tests for IBM Bob Accelerator tools.

These tests verify that Bob's developer productivity tools work correctly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestBobAccelerator(unittest.TestCase):
    """Test the Bob Accelerator report tool."""

    def test_bob_accelerator_runs(self):
        """Test that bob_accelerator.py runs without errors."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bob_accelerator.py"), "--format", "json"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, f"Bob accelerator failed: {result.stderr}")

        # Verify JSON output is valid
        data = json.loads(result.stdout)
        self.assertIn("generated_by", data)
        self.assertIn("sections", data)
        self.assertIn("quick_wins", data)

    def test_bob_accelerator_text_format(self):
        """Test that bob_accelerator.py produces text output."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bob_accelerator.py")],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("IBM Bob", result.stdout)
        self.assertIn("System Readiness", result.stdout)

    def test_bob_accelerator_section_filter(self):
        """Test that bob_accelerator.py can run specific sections."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bob_accelerator.py"), "--section", "system"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("System Readiness", result.stdout)

    def test_bob_tools_section_reports_dynamic_total(self):
        """Test that the Bob tools section reports the current tool catalog."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "bob_accelerator.py"), "--section", "bob_tools"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Installed Tools: 12/12", result.stdout)
        self.assertIn("generate_test_scaffold.py", result.stdout)
        self.assertIn("generate_api_reference.py", result.stdout)


class TestCoverageReport(unittest.TestCase):
    """Test the coverage report tool."""

    def test_coverage_report_runs(self):
        """Test that coverage_report.py runs without errors."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "coverage_report.py")],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        # May return 1 if coverage is low, but should not crash
        self.assertIn(result.returncode, [0, 1])
        self.assertIn("Test Coverage Report", result.stdout)

    def test_coverage_report_markdown(self):
        """Test that coverage_report.py produces markdown output."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "coverage_report.py"), "--format", "markdown"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertIn(result.returncode, [0, 1])
        self.assertIn("# Test Coverage Report", result.stdout)
        self.assertIn("Coverage Ratio:", result.stdout)


class TestADRSystem(unittest.TestCase):
    """Test the ADR system."""

    def test_adr_directory_exists(self):
        """Test that ADR directory was created."""
        adr_dir = ROOT / "docs" / "adr"
        self.assertTrue(adr_dir.exists())
        self.assertTrue(adr_dir.is_dir())

    def test_adr_readme_exists(self):
        """Test that ADR README exists."""
        readme = ROOT / "docs" / "adr" / "README.md"
        self.assertTrue(readme.exists())
        content = readme.read_text(encoding="utf-8")
        self.assertIn("Architecture Decision Records", content)

    def test_adr_template_exists(self):
        """Test that ADR template exists."""
        template = ROOT / "docs" / "adr" / "template.md"
        self.assertTrue(template.exists())
        content = template.read_text(encoding="utf-8")
        self.assertIn("ADR-NNN", content)
        self.assertIn("Context", content)
        self.assertIn("Decision", content)
        self.assertIn("Consequences", content)

    def test_first_adr_exists(self):
        """Test that first ADR was created."""
        adr_001 = ROOT / "docs" / "adr" / "001-chimera-pilot-scheduling.md"
        self.assertTrue(adr_001.exists())
        content = adr_001.read_text(encoding="utf-8")
        self.assertIn("Chimera Pilot", content)
        self.assertIn("Status:** Accepted", content)


class TestBobDocumentation(unittest.TestCase):
    """Test Bob workflow documentation."""

    def test_bob_workflow_doc_exists(self):
        """Test that Bob workflow documentation exists."""
        doc = ROOT / "docs" / "IBM_BOB_WORKFLOW.md"
        self.assertTrue(doc.exists())
        content = doc.read_text(encoding="utf-8")
        self.assertIn("IBM Bob", content)
        self.assertIn("Delivery Accelerator", content)
        self.assertIn("bob_accelerator.py", content)


if __name__ == "__main__":
    unittest.main()

# Made with Bob
