from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.agent_core.executor import Executor
from ghostchimera.agent_core.memory import MemoryManager
from ghostchimera.agent_core.skill_manager import SkillManager
from ghostchimera.safety_layer.gating import ExecutionPolicy
from ghostchimera.safety_layer.production import ProductionGuardrails
from ghostchimera.tool_layer.shell import run_command


class AgentCoreSafetyPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="ghostchimera-safety-test-")
        self.root = Path(self.tmp.name)
        self.memory = MemoryManager(str(self.root / "memory.json"))
        self.audit_file = self.root / "audit.json"

        import ghostchimera.safety_layer.audit as audit

        audit.AUDIT_FILE = str(self.audit_file)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _executor(self, policy: ExecutionPolicy) -> Executor:
        return Executor(SkillManager(), self.memory, policy=policy)

    def test_shell_task_is_denied_by_default_and_audited(self) -> None:
        executor = self._executor(ExecutionPolicy())

        result = executor.execute([{"action": "shell", "command": [sys.executable, "-c", "print('unsafe')"]}])

        self.assertIn("Policy denied shell", result)
        records = json.loads(self.audit_file.read_text(encoding="utf-8"))
        self.assertEqual(records[0]["task"]["action"], "shell")
        self.assertFalse(records[0]["result"]["ok"])

    def test_shell_task_runs_only_with_policy_opt_in_and_timeout(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_shell=True,
                allowed_roots=(str(self.root),),
                shell_timeout_seconds=5,
            )
        )

        result = executor.execute([{"action": "shell", "command": [sys.executable, "-c", "print('safe')"]}])

        self.assertEqual(result.strip(), "safe")

    def test_file_write_is_denied_outside_allowed_roots(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_file_write=True,
                allowed_roots=(str(self.root),),
            )
        )
        outside = self.root.parent / "outside-policy.txt"

        result = executor.execute([{"action": "write_file", "path": str(outside), "content": "blocked"}])

        self.assertIn("Policy denied write_file", result)
        self.assertFalse(outside.exists())

    def test_file_write_and_read_within_allowed_roots(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_file_read=True,
                allow_file_write=True,
                allowed_roots=(str(self.root),),
            )
        )
        target = self.root / "allowed.txt"

        write_result = executor.execute([{"action": "write_file", "path": str(target), "content": "hello"}])
        read_result = executor.execute([{"action": "read_file", "path": str(target)}])

        self.assertIn("Wrote 5 bytes", write_result)
        self.assertEqual(read_result, "hello")

    def test_direct_shell_tool_requires_policy_authorization(self) -> None:
        with self.assertRaises(PermissionError):
            run_command([sys.executable, "-c", "print('blocked')"])

    def test_production_mode_blocks_shell_without_guardrails(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_shell=True,
                allowed_roots=(str(self.root),),
                production_guardrails=ProductionGuardrails(deployment_mode="production"),
            )
        )

        result = executor.execute([{"action": "shell", "command": [sys.executable, "-c", "print('blocked')"]}])

        self.assertIn("Production mode blocks shell execution", result)

    def test_production_mode_allows_shell_with_isolation_review_and_approval(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_shell=True,
                allowed_roots=(str(self.root),),
                production_guardrails=ProductionGuardrails(
                    deployment_mode="production",
                    external_isolation="container",
                    security_reviewed=True,
                    human_approval_required=True,
                    trusted_inputs_only=True,
                ),
            )
        )

        result = executor.execute([{"action": "shell", "command": [sys.executable, "-c", "print('safe')"]}])

        self.assertEqual(result.strip(), "safe")

    def test_production_mode_blocks_untrusted_shell_on_host(self) -> None:
        executor = self._executor(
            ExecutionPolicy(
                allow_shell=True,
                allowed_roots=(str(self.root),),
                production_guardrails=ProductionGuardrails(
                    deployment_mode="production",
                    external_isolation="container",
                    security_reviewed=True,
                    human_approval_required=True,
                    trusted_inputs_only=True,
                ),
            )
        )

        result = executor.execute(
            [{"action": "shell", "command": [sys.executable, "-c", "print('blocked')"], "trusted": False}]
        )

        self.assertIn("blocks untrusted shell execution", result)


if __name__ == "__main__":
    unittest.main()
