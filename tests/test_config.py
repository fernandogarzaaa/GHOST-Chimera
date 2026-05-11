from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.config import GhostChimeraConfig


class GhostChimeraConfigTests(unittest.TestCase):
    def test_defaults_resolve_under_user_state_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = GhostChimeraConfig.from_env()

        self.assertFalse(config.policy.allow_shell)
        self.assertFalse(config.policy.allow_network)
        self.assertEqual(config.local_model_profile, "tiny")
        self.assertTrue(str(config.memory_db).endswith("memory.sqlite3"))
        self.assertTrue(str(config.audit_file).endswith("audit.json"))

    def test_env_overrides_paths_policy_and_local_model(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-config-test-") as tmp:
            root = Path(tmp)
            with patch.dict(
                os.environ,
                {
                    "GHOSTCHIMERA_STATE_DIR": str(root / "state"),
                    "GHOSTCHIMERA_ALLOWED_ROOTS": str(root),
                    "GHOSTCHIMERA_ALLOW_FILE_READ": "true",
                    "GHOSTCHIMERA_ALLOW_FILE_WRITE": "true",
                    "GHOSTCHIMERA_ALLOW_SHELL": "true",
                    "GHOSTCHIMERA_SHELL_TIMEOUT_SECONDS": "7",
                    "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
                    "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
                    "GHOSTCHIMERA_SECURITY_REVIEWED": "true",
                    "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "true",
                    "GHOSTCHIMERA_LOCAL_MODEL_PATH": str(root / "tiny.gguf"),
                    "GHOSTCHIMERA_LOCAL_MODEL_PROFILE": "balanced",
                    "GHOSTCHIMERA_LOCAL_MODEL_GPU_LAYERS": "4",
                    "GHOSTCHIMERA_AUTONOMY_LEVEL": "autonomous",
                },
                clear=True,
            ):
                config = GhostChimeraConfig.from_env()

        self.assertEqual(config.state_dir, root / "state")
        self.assertEqual(config.policy.allowed_roots, (str(root),))
        self.assertTrue(config.policy.allow_shell)
        self.assertTrue(config.policy.allow_file_read)
        self.assertTrue(config.policy.allow_file_write)
        self.assertEqual(config.policy.shell_timeout_seconds, 7)
        self.assertTrue(config.policy.production_guardrails.ready)
        self.assertEqual(config.local_model_profile, "balanced")
        self.assertEqual(config.local_model_gpu_layers, 4)
        self.assertEqual(config.autonomy_level, "autonomous")

    def test_to_dict_is_json_ready(self) -> None:
        config = GhostChimeraConfig.from_env()

        payload = config.to_dict()

        self.assertIn("state_dir", payload)
        self.assertIn("policy", payload)
        self.assertIn("local_model", payload)
        self.assertIn("ghost_mode", payload["policy"])
        self.assertIn("production", payload["policy"])
        self.assertIn("autonomy_level", payload)

    def test_control_plane_can_show_resolved_config(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "--config-show"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("state_dir", payload)
        self.assertIn("policy", payload)

    def test_control_plane_doctor_production_reports_missing_guardrails(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "doctor", "--production"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("Production mode", completed.stdout)

    def test_control_plane_doctor_production_passes_with_guardrails(self) -> None:
        env = {
            **os.environ,
            "GHOSTCHIMERA_DEPLOYMENT_MODE": "production",
            "GHOSTCHIMERA_EXTERNAL_ISOLATION": "container",
            "GHOSTCHIMERA_SECURITY_REVIEWED": "1",
            "GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED": "1",
        }
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "doctor", "--production"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
            env=env,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_control_plane_pilot_status_accepts_desktop_flags(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera.control_plane.cli",
                "--pilot-status",
                "--enable-desktop-backend",
                "--allow-desktop-control",
                "--desktop-allow-app",
                "chrome",
                "--desktop-deny-window",
                "Admin",
                "--ghost-mode",
                "possess",
                "--desktop-max-actions",
                "4",
                "--desktop-max-duration-seconds",
                "45",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        backend_ids = [item["id"] for item in payload["backends"]]
        self.assertIn("desktop.runtime", backend_ids)
        desktop = next(item for item in payload["backends"] if item["id"] == "desktop.runtime")
        self.assertEqual(desktop["metadata"]["max_live_actions"], 4)
        self.assertEqual(desktop["metadata"]["max_session_seconds"], 45.0)
        self.assertEqual(payload["policy"]["ghost_mode"], "possess")
        self.assertEqual(payload["policy"]["allowed_desktop_apps"], ["chrome"])
        self.assertEqual(payload["policy"]["denied_desktop_windows"], ["Admin"])


if __name__ == "__main__":
    unittest.main()
