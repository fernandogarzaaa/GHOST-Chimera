from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot import ChimeraPilotKernel, ChimeraScheduler, TaskKind, TaskSpec, get_autonomy_profile
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.chimera_pilot.autonomy_jobs import AutonomyJobRunner
from ghostchimera.chimera_pilot.backends import DeterministicBackend
from ghostchimera.control_plane.config import get_autonomy_config, save_config
from ghostchimera.model_layer.minimind_lifecycle import MiniMindLifecycle


class AutonomyProfileTests(unittest.TestCase):
    def test_aliases_map_to_generalist_without_changing_positioning(self) -> None:
        profile = get_autonomy_profile("sgi")

        self.assertEqual(profile.name, "generalist")
        self.assertIn("not AGI", profile.positioning)
        self.assertFalse(profile.allow_self_training)

    def test_scheduler_strategy_is_capped_by_profile(self) -> None:
        backends = [
            DeterministicBackend("a", reliability=0.8),
            DeterministicBackend("b", reliability=0.7),
            DeterministicBackend("c", reliability=0.9),
        ]
        scheduler = ChimeraScheduler(backends, autonomy_profile=get_autonomy_profile("assist"))
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="reason", constraints={"uncertainty": 0.9})

        self.assertEqual(scheduler.select_strategy(task, uncertainty=0.9), "single")

    def test_generalist_profile_allows_moa_strategy(self) -> None:
        backends = [
            DeterministicBackend("a", reliability=0.8),
            DeterministicBackend("b", reliability=0.7),
            DeterministicBackend("c", reliability=0.9),
        ]
        scheduler = ChimeraScheduler(backends, autonomy_profile=get_autonomy_profile("generalist"))
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="reason")

        self.assertEqual(scheduler.select_strategy(task, uncertainty=0.9), "moa")

    def test_kernel_status_exposes_active_autonomy_profile(self) -> None:
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True, autonomy_level="autonomous")
        status = kernel.status()

        self.assertEqual(status["autonomy"]["name"], "autonomous")
        self.assertEqual(status["policy"]["autonomy"]["name"], "autonomous")

    def test_agent_loop_uses_autonomy_tool_round_budget(self) -> None:
        agent = AIAgent(autonomy_profile=get_autonomy_profile("assist"))

        self.assertEqual(agent.max_tool_rounds, 6)

    def test_chimera_pilot_cli_lists_autonomy_profiles(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.chimera_pilot.cli", "autonomy-profiles"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        names = {profile["name"] for profile in payload["profiles"]}
        self.assertIn("assist", names)
        self.assertIn("generalist", names)

    def test_autonomy_runner_returns_repair_preview_without_execution(self) -> None:
        runner = AutonomyJobRunner(profile="generalist")

        result = runner.run("repair-preview")

        self.assertEqual(result.status, "preview")
        self.assertIn("plan", result.artifacts)

    def test_autonomy_runner_previews_regression_for_supervised_profile(self) -> None:
        runner = AutonomyJobRunner(profile="supervised")

        result = runner.run("test-regression", execute=True)

        self.assertEqual(result.status, "preview")
        self.assertTrue(result.artifacts["requires_execute"])

    def test_persistent_autonomy_config_round_trips(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-autonomy-config-") as tmp:
            path = Path(tmp) / "config.json"
            save_config({"autonomy": {"level": "autonomous", "local_model_profile": "stronger"}}, path=path)
            config = json.loads(path.read_text(encoding="utf-8"))

        autonomy = get_autonomy_config(config)
        self.assertEqual(autonomy["level"], "autonomous")
        self.assertEqual(autonomy["local_model_profile"], "stronger")

    def test_minimind_lifecycle_dataset_and_low_confidence_logging(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-minimind-") as tmp:
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            dataset = lifecycle.generate_dataset([{"prompt": "p", "response": "r"}])
            logged = lifecycle.log_low_confidence(prompt="p", response="r", confidence=0.2)

            self.assertTrue(dataset.exists())
            self.assertTrue(logged)
            self.assertTrue((Path(tmp) / "minimind" / "low_confidence.jsonl").exists())

    def test_control_plane_cli_exposes_autonomy_jobs_and_minimind_status(self) -> None:
        jobs = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "autonomy", "jobs"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(jobs.returncode, 0, jobs.stderr)
        self.assertIn("repair-preview", jobs.stdout)

        status = subprocess.run(
            [sys.executable, "-m", "ghostchimera.control_plane.cli", "minimind", "status"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("available", json.loads(status.stdout))


if __name__ == "__main__":
    unittest.main()
