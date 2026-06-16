"""Tests for the public superiority scorecard and Operator Workbench contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.control_plane.console import register_console_routes

ROOT = Path(__file__).resolve().parents[1]


class SuperiorityScorecardTests(unittest.TestCase):
    def test_scorecard_computes_all_three_dimensions_and_next_actions(self) -> None:
        from ghostchimera.superiority import build_superiority_scorecard

        summary = {
            "ok": True,
            "active_path": {"profile_id": "autonomous-engineer"},
            "model": {"provider": "openrouter", "model": "openai/gpt-4o-mini"},
            "counts": {"approved_sources": 1, "pending_candidates": 0},
            "trust": {"ready": True, "pending_approvals": 0},
            "remote": {"counts": {"paired_peers": 1}},
            "conversation": {"active_session": {"mode": "listening"}, "settings": {"full_bypass": False}},
            "production_readiness": {"ready": True, "status": "ready"},
            "warnings": [],
        }
        html = (ROOT / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")
        payload = build_superiority_scorecard(
            operator_summary=summary,
            capabilities={"ok": True, "score_ratio": 1.0, "capability_count": 14, "top_gaps": []},
            routes=[
                "/api/console/operator/summary",
                "/api/console/models/discovery",
                "/api/console/trust/summary",
                "/api/console/evolution/candidates",
                "/api/console/remote/status",
                "/api/console/conversation/status",
                "/api/console/sandbox/journey",
            ],
            static_html=html,
            static_app=app,
        ).to_dict()

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["score_ratio"], 0.85)
        self.assertEqual(
            {dimension["id"] for dimension in payload["dimensions"]},
            {"operator_ux", "platform_breadth", "autonomy_depth"},
        )
        self.assertTrue(payload["next_best_actions"])
        self.assertTrue(payload["claim_boundary"]["no_sentience_claim"])

    def test_scorecard_redacts_secrets_and_private_paths(self) -> None:
        from ghostchimera.superiority import build_superiority_scorecard, contains_secret_like_text

        payload = build_superiority_scorecard(
            operator_summary={
                "model": {
                    "provider": "openai",
                    "api_key": "sk-test-secret",
                    "config_path": r"D:\Users\Private\.ghost\config.json",
                },
                "warnings": ["Add the provider API key in Config before live model runs."],
            },
            capabilities={"ok": True, "score_ratio": 1.0, "capability_count": 12},
            routes=[],
            static_html="operatorWorkbench operatorCommandSearch nextBestActions",
            static_app="/api/console/superiority",
        ).to_dict()
        serialized = json.dumps(payload)

        self.assertNotIn("sk-test-secret", serialized)
        self.assertNotIn(r"D:\Users\Private", serialized)
        self.assertTrue(payload["secret_policy"]["secrets_are_write_only"])
        self.assertFalse(payload["secret_policy"]["raw_secret_values_returned"])
        self.assertFalse(contains_secret_like_text(serialized))
        self.assertTrue(contains_secret_like_text("raw token ghp_abcdefghijklmnopqrstuvwxyz1234567890"))

    def test_local_operator_summary_uses_real_config_and_state_without_secrets(self) -> None:
        from ghostchimera.control_plane.config import save_config
        from ghostchimera.control_plane.evolution import create_learning_source
        from ghostchimera.superiority import build_local_operator_summary

        with tempfile.TemporaryDirectory(prefix="ghostchimera-local-summary-") as tmp:
            state_dir = Path(tmp) / "state"
            config_path = Path(tmp) / "config.json"
            save_config(
                {
                    "model": {
                        "provider": "openrouter",
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-local-secret-1234567890",
                    },
                    "ghost_path": {"profile_id": "manager-operator"},
                },
                config_path,
            )
            create_learning_source(
                state_dir,
                {"source_type": "manual_note", "label": "ops notes", "consent_status": "approved"},
            )

            summary = build_local_operator_summary(state_dir=state_dir, config_path=config_path)

        serialized = json.dumps(summary)
        self.assertEqual(summary["model"]["provider"], "openrouter")
        self.assertTrue(summary["model"]["api_key_configured"])
        self.assertEqual(summary["counts"]["approved_sources"], 1)
        self.assertEqual(summary["active_path"]["profile_id"], "manager-operator")
        self.assertNotIn("sk-local-secret", serialized)

    def test_local_operator_summary_treats_codex_cli_login_as_auth(self) -> None:
        from ghostchimera.control_plane.config import save_config
        from ghostchimera.superiority import build_local_operator_summary

        with tempfile.TemporaryDirectory(prefix="ghostchimera-codex-summary-") as tmp:
            state_dir = Path(tmp) / "state"
            config_path = Path(tmp) / "config.json"
            save_config({"model": {"provider": "codex_cli", "model": "gpt-5.4-mini"}}, config_path)

            with patch(
                "ghostchimera.model_layer.codex_cli_provider.get_codex_cli_status",
                return_value=SimpleNamespace(available=True, logged_in=True, detail="Logged in using ChatGPT"),
            ):
                summary = build_local_operator_summary(state_dir=state_dir, config_path=config_path)

        self.assertEqual(summary["model"]["provider"], "codex_cli")
        self.assertTrue(summary["model"]["api_key_configured"])
        self.assertTrue(summary["model"]["auth_configured"])
        self.assertEqual(summary["model"]["auth_detail"], "Logged in using ChatGPT")

    def test_console_exposes_superiority_route_and_operator_summary_embeds_scorecard(self) -> None:
        server = GatewayServer()
        with tempfile.TemporaryDirectory(prefix="ghostchimera-superiority-") as tmp:
            register_console_routes(server, state_dir=tmp, config_path=Path(tmp) / "config.json")
            route = server.routes.find("GET", "/api/console/superiority")
            summary_route = server.routes.find("GET", "/api/console/operator/summary")

            self.assertIsNotNone(route)
            self.assertIsNotNone(summary_route)
            payload = route.handler(
                {"method": "GET", "path": "/api/console/superiority", "headers": {}, "body": "", "query": {}}
            )
            summary = summary_route.handler(
                {"method": "GET", "path": "/api/console/operator/summary", "headers": {}, "body": "", "query": {}}
            )

        self.assertTrue(payload["ok"])
        self.assertIn("score_ratio", payload)
        self.assertIn("next_best_actions", payload)
        self.assertIn("superiority", summary)
        self.assertIn("next_best_actions", summary)

    def test_cli_and_eval_suite_return_superiority_payloads(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="ghostchimera-superiority-cli-")
        self.addCleanup(tmp.cleanup)
        cli_state = Path(tmp.name) / "state"
        cli_config = Path(tmp.name) / "config.json"
        cli = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera",
                "superiority",
                "score",
                "--format",
                "json",
                "--state-dir",
                str(cli_state),
                "--config",
                str(cli_config),
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr or cli.stdout)
        payload = json.loads(cli.stdout)
        self.assertIn("score_ratio", payload)
        self.assertIn("connect_model", {item["id"] for item in payload["next_best_actions"]})
        self.assertIn("approve_learning_source", {item["id"] for item in payload["next_best_actions"]})
        self.assertEqual(
            {item["id"] for item in payload["dimensions"]}, {"operator_ux", "platform_breadth", "autonomy_depth"}
        )

        eval_run = subprocess.run(
            [sys.executable, "-m", "ghostchimera.evals", "run", "--suite", "superiority"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(eval_run.returncode, 0, eval_run.stderr or eval_run.stdout)
        eval_payload = json.loads(eval_run.stdout)
        self.assertTrue(eval_payload["ok"])
        self.assertIn("superiority_pass_rate", eval_payload["kpis"])

    def test_static_operator_workbench_and_browser_e2e_contract_exist(self) -> None:
        html = (ROOT / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")
        release = (ROOT / "scripts" / "validate_release.py").read_text(encoding="utf-8")

        for token in (
            "operatorWorkbench",
            "operatorCommandSearch",
            "nextBestActions",
            "superiorityScorecards",
            "browserE2EStatus",
        ):
            self.assertIn(token, html)
        self.assertIn("/api/console/superiority", app)
        self.assertIn("renderSuperiorityScorecard", app)
        self.assertTrue((ROOT / "scripts" / "run_operator_workbench_e2e.py").exists())
        self.assertIn("check_public_superiority_artifacts", release)


if __name__ == "__main__":
    unittest.main()
