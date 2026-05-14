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

    def test_eval_cli_outputs_user_journey_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.evals", "run", "--suite", "user-journey"],
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["suite"], "user-journey")

    def test_unknown_suite_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown eval suite"):
            run_suite("missing")

    def test_autonomy_suite_reports_profile_contracts(self) -> None:
        report = run_suite("autonomy")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 4)
        self.assertIn("autonomy_contract_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["autonomy_contract_gate"])

    def test_user_journey_suite_reports_operator_contracts(self) -> None:
        report = run_suite("user-journey")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 4)
        self.assertIn("operator_journey_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["operator_journey_gate"])

    def test_github_connected_suite_reports_contracts(self) -> None:
        report = run_suite("github-connected")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 3)
        self.assertIn("github_connected_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["github_connected_gate"])

    def test_path_synthesis_suite_reports_contracts(self) -> None:
        report = run_suite("path-synthesis")

        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["passed"], 3)
        self.assertIn("path_synthesis_pass_rate", report["kpis"])
        self.assertTrue(report["gates"]["path_synthesis_gate"])


if __name__ == "__main__":
    unittest.main()
