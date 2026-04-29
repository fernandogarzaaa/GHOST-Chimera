"""
Executor
========

The executor walks through a list of tasks produced by the planner and
delegates each to the appropriate skill.  It aggregates the results and
returns a combined response.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any

from .memory import MemoryManager
from .skill_manager import SkillManager
from ..safety_layer.audit import record as record_audit
from ..safety_layer.gating import ExecutionPolicy, PolicyViolation


class Executor:
    """Executes planned tasks using available skills."""

    def __init__(
        self,
        skills: SkillManager,
        memory: MemoryManager,
        logger: logging.Logger = None,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self.skills = skills
        self.memory = memory
        self.logger = logger or logging.getLogger(__name__)
        self.policy = policy or ExecutionPolicy.from_env()

    def execute(self, tasks: List[Dict[str, Any]]) -> str:
        """Execute a sequence of tasks and return the aggregate result."""
        results: List[str] = []
        for task in tasks:
            action = task.get("action")
            self.logger.debug("Executing task: %s", task)
            try:
                authorized_task = self.policy.authorize_task(task)
            except PolicyViolation as exc:
                result = {"ok": False, "error": str(exc)}
                record_audit(task, result)
                results.append(f"Policy denied {action}: {exc}")
                continue
            # Look up a skill that can handle this action
            skill = self.skills.get_skill_for_action(action)
            if skill is None:
                self.logger.warning("No skill found for action '%s'", action)
                results.append(f"No skill for action '{action}'")
                continue
            try:
                result = skill.run(authorized_task)
                results.append(str(result))
                if action in {"shell", "write_file", "read_file", "http_get"}:
                    record_audit(task, {"ok": True, "result": str(result)[:500]})
            except Exception as exc:
                self.logger.exception("Skill '%s' raised an exception", skill.name)
                record_audit(task, {"ok": False, "error": str(exc)})
                results.append(f"Error executing {action}: {exc}")
        # Combine results into a single string
        return "\n".join(results)
