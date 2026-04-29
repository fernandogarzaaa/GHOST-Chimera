from __future__ import annotations

import json
import subprocess
import sys
import unittest

from ghostchimera.evals.runner import run_suite


class EvaluationHarnessTests(unittest.TestCase):
    def test_safety_suite_reports_all_cases_passed(self) -> None:
        report = run_suite("safety")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 3)
        self.assertEqual(report["failed"], 0)

    def test_smoke_suite_reports_release_ready_surfaces(self) -> None:
        report = run_suite("smoke")

        self.assertTrue(report["ok"])
        self.assertIn("chimera_pilot_status", [case["name"] for case in report["cases"]])

    def test_eval_cli_outputs_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.evals", "run", "--suite", "safety"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
