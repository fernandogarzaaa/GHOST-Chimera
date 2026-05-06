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
        self.assertIn("policy_guardrail_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["policy_guardrail_gate"])

    def test_smoke_suite_reports_release_ready_surfaces(self) -> None:
        report = run_suite("smoke")

        self.assertTrue(report["ok"])
        self.assertIn("chimera_pilot_status", [case["name"] for case in report["cases"]])
        self.assertIn("first_choice_success_rate_proxy", report["kpis"])
        self.assertTrue(report["gates"]["smoke_reliability_gate"])

    def test_eval_cli_outputs_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.evals", "run", "--suite", "safety"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["ok"])

    def test_autonomy_suite_reports_profile_contracts(self) -> None:
        report = run_suite("autonomy")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 4)
        self.assertIn("autonomy_contract_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["autonomy_contract_gate"])


if __name__ == "__main__":
    unittest.main()
