"""Tests for IBM Bob Delivery Package Generator.

These tests verify that the delivery package generator works correctly.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestDeliveryPackageGenerator(unittest.TestCase):
    """Test the delivery package generator."""

    def test_delivery_package_runs(self):
        """Test that bob_delivery_package.py runs without errors."""
        with tempfile.TemporaryDirectory(prefix="bob-delivery-") as tmpdir:
            output_path = Path(tmpdir) / "test_package.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bob_delivery_package.py"),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0, f"Delivery package failed: {result.stderr}")
            self.assertTrue(output_path.exists())
            
            # Verify content
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("IBM Bob", content)
            self.assertIn("Delivery Package", content)
            self.assertIn("Repository Snapshot", content)

    def test_delivery_package_json_format(self):
        """Test that bob_delivery_package.py produces JSON output."""
        with tempfile.TemporaryDirectory(prefix="bob-delivery-") as tmpdir:
            output_path = Path(tmpdir) / "test_package.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bob_delivery_package.py"),
                    "--output",
                    str(output_path),
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(output_path.exists())
            
            # Verify JSON is valid
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("generated_by", data)
            self.assertIn("repository_snapshot", data)
            self.assertIn("test_coverage", data)
            self.assertIn("bob_tools", data)
            self.assertGreaterEqual(data["repository_snapshot"]["test_files"], 70)

    def test_delivery_package_markdown_content(self):
        """Test that markdown delivery package has required sections."""
        with tempfile.TemporaryDirectory(prefix="bob-delivery-") as tmpdir:
            output_path = Path(tmpdir) / "test_package.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bob_delivery_package.py"),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0)
            
            content = output_path.read_text(encoding="utf-8")
            
            # Check for required sections
            required_sections = [
                "Repository Snapshot",
                "Bob Findings Summary",
                "Bob-Built Tools",
                "Top Recommended Test Targets",
                "Architecture Decision Records",
                "Verification Commands",
                "PR Summary for Judges",
                "Risks and Limitations",
            ]
            
            for section in required_sections:
                self.assertIn(section, content, f"Missing section: {section}")

    def test_delivery_package_includes_tools(self):
        """Test that delivery package lists Bob-built tools."""
        with tempfile.TemporaryDirectory(prefix="bob-delivery-") as tmpdir:
            output_path = Path(tmpdir) / "test_package.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bob_delivery_package.py"),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0)
            
            content = output_path.read_text(encoding="utf-8")
            
            # Check for Bob tools
            expected_tools = [
                "Bob Accelerator",
                "Coverage Reporter",
                "ADR System",
                "Delivery Package Generator",
                "scripts/bob_delivery_package.py",
            ]
            
            for tool in expected_tools:
                self.assertIn(tool, content, f"Missing tool: {tool}")

    def test_delivery_package_includes_verification_commands(self):
        """Test that delivery package includes verification commands."""
        with tempfile.TemporaryDirectory(prefix="bob-delivery-") as tmpdir:
            output_path = Path(tmpdir) / "test_package.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "bob_delivery_package.py"),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                cwd=ROOT,
            )
            self.assertEqual(result.returncode, 0)
            
            content = output_path.read_text(encoding="utf-8")
            
            # Check for verification commands
            expected_commands = [
                "python scripts/bob_accelerator.py",
                "python scripts/coverage_report.py",
                "python scripts/bob_delivery_package.py",
                "python -m pytest",
            ]
            
            for command in expected_commands:
                self.assertIn(command, content, f"Missing command: {command}")

    def test_submission_doc_is_judge_ready(self):
        """Test that the judge-facing submission doc has concrete repo links and no placeholders."""
        doc = ROOT / "docs" / "IBM_BOB_SUBMISSION.md"
        self.assertTrue(doc.exists())
        content = doc.read_text(encoding="utf-8")

        self.assertIn("git clone https://github.com/fernandogarzaaa/GHOST-Chimera.git", content)
        self.assertIn("docs/bob_delivery_package.md", content)
        self.assertIn("[OK] **Bob built 5 working tools:**", content)
        self.assertNotIn("your-org", content)
        self.assertNotIn("100% test coverage", content)


if __name__ == "__main__":
    unittest.main()

# Made with Bob
