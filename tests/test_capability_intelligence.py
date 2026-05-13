from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.capability_intelligence import (
    format_capability_report,
    inspect_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]


class CapabilityIntelligenceTests(unittest.TestCase):
    def test_inspect_capabilities_reports_repo_surfaces(self) -> None:
        report = inspect_capabilities(ROOT)

        self.assertTrue(report["ok"], json.dumps(report["top_gaps"], indent=2))
        self.assertGreaterEqual(report["score_ratio"], 0.75)
        self.assertGreaterEqual(report["capability_count"], 10)
        self.assertIn("OpenAI Codex", report["benchmarks"])
        self.assertIn("Claude Code", report["benchmarks"])
        self.assertTrue(any(cap["id"] == "mcp_tool_gateway" for cap in report["capabilities"]))

    def test_missing_required_surface_marks_capability_partial(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-capability-") as tmp:
            root = Path(tmp)
            (root / "ghostchimera" / "chimera_pilot").mkdir(parents=True)
            (root / "ghostchimera" / "chimera_pilot" / "autonomy_queue.py").write_text(
                "class AutonomyJobQueue: pass\n",
                encoding="utf-8",
            )

            report = inspect_capabilities(root)

        background = next(cap for cap in report["capabilities"] if cap["id"] == "background_task_orchestration")
        self.assertEqual(background["status"], "partial")
        self.assertGreater(len(background["missing_surfaces"]), 0)

    def test_markdown_report_is_human_readable(self) -> None:
        report = inspect_capabilities(ROOT)
        rendered = format_capability_report(report)

        self.assertIn("# Ghost Chimera Competitive Capability Report", rendered)
        self.assertIn("Background Task Orchestration", rendered)
        self.assertIn("Score:", rendered)


if __name__ == "__main__":
    unittest.main()
