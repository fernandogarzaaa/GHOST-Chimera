from __future__ import annotations

import json
import subprocess
import sys
import unittest

from ghostchimera.chimera_pilot import ChimeraPilotKernel, ChimeraScheduler, TaskKind, TaskSpec, get_autonomy_profile
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.chimera_pilot.backends import DeterministicBackend


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


if __name__ == "__main__":
    unittest.main()
