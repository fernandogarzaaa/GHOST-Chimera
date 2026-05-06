from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ghostchimera.chimera_pilot.policy import PilotPolicy
from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec
from ghostchimera.safety_layer.gating import ExecutionPolicy


class GhostModePolicyTests(unittest.TestCase):
    def test_execution_policy_reads_ghost_mode_from_env(self) -> None:
        with patch.dict(os.environ, {"GHOSTCHIMERA_GHOST_MODE": "possess"}, clear=True):
            policy = ExecutionPolicy.from_env()
        self.assertEqual(policy.ghost_mode, "possess")

    def test_desktop_control_denied_by_default(self) -> None:
        task = TaskSpec.create(kind=TaskKind.DESKTOP_CONTROL, objective="click submit")
        with self.assertRaises(PermissionError):
            PilotPolicy().validate(task)

    def test_desktop_control_allowed_when_enabled(self) -> None:
        task = TaskSpec.create(kind=TaskKind.DESKTOP_CONTROL, objective="click submit")
        PilotPolicy(allow_desktop_control=True, ghost_mode="possess").validate(task)

    def test_invalid_ghost_mode_rejected_in_execution_policy(self) -> None:
        with patch.dict(os.environ, {"GHOSTCHIMERA_GHOST_MODE": "specter"}, clear=True):
            with self.assertRaises(ValueError):
                ExecutionPolicy.from_env()

    def test_invalid_ghost_mode_rejected_in_pilot_policy(self) -> None:
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="think", inputs={"prompt": "think"})
        with self.assertRaises(PermissionError):
            PilotPolicy(ghost_mode="specter").validate(task)


if __name__ == "__main__":
    unittest.main()
