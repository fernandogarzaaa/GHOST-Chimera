"""
Agent Core
==========

The agent core orchestrates planning, execution, memory and skills.  It
exposes a single high level entry point :class:`AgentCore` that accepts
natural language requests and performs the required actions.

At a high level the core performs three steps:

1. **Planning** – convert a request into one or more structured tasks.
2. **Execution** – select appropriate skills/tools to handle each task and
   execute them in order.
3. **Memory** – record requests, plans and results for future context.

The implementation here is intentionally conservative.  It does not attempt
to implement AGI or self‑improvement but instead lays a clean and extensible
foundation.  More advanced planners and reasoners can be plugged in via the
``cognition_layer`` and additional skills added under ``skill_layer``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..chimera_pilot import ChimeraPilotKernel
from ..model_layer.llm import LLM
from ..safety_layer.gating import ExecutionPolicy
from .executor import Executor
from .memory import MemoryManager
from .planner import Planner
from .skill_manager import SkillManager


class AgentCore:
    """Entry point for performing natural language requests.

    Parameters
    ----------
    llm : :class:`ghostchimera.model_layer.llm.LLM`
        The language model used for planning.  If ``None`` a default LLM
        instance is created using environment variables.
    memory_manager : :class:`ghostchimera.agent_core.memory.MemoryManager`
        Persistent memory store.  If ``None`` a default manager writing to
        ``~/.ghostchimera/memory.json`` is used.
    skill_manager : :class:`ghostchimera.agent_core.skill_manager.SkillManager`
        Registry of available skills.  A default manager loads all skills
        defined under ``ghostchimera.skill_layer``.
    logger : :class:`logging.Logger`
        Optional logger for debug output.
    """

    def __init__(
        self,
        llm: LLM | None = None,
        memory_manager: MemoryManager | None = None,
        skill_manager: SkillManager | None = None,
        pilot_kernel: ChimeraPilotKernel | None = None,
        execution_policy: ExecutionPolicy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.llm = llm or LLM()
        self.memory = memory_manager or MemoryManager()
        self.skills = skill_manager or SkillManager(logger=self.logger)
        self.planner = Planner(self.llm)
        self.pilot_kernel = pilot_kernel or ChimeraPilotKernel.default()
        self.executor = Executor(self.skills, self.memory, logger=self.logger, policy=execution_policy)

    def handle_request(self, request: str) -> str:
        """Handle a natural language request and return the result.

        This method will plan, execute and record the request.  Exceptions
        raised during planning or execution propagate to the caller.

        Parameters
        ----------
        request: str
            The user's natural language instruction.

        Returns
        -------
        str
            The textual result of performing the request.
        """
        self.logger.info("Received request: %s", request)
        pilot_result, pilot_confidence = self._try_chimera_pilot(request)
        if pilot_result is not None:
            memory_record: dict[str, Any] = {
                "type": "interaction",
                "request": request,
                "runtime": "chimera_pilot",
                "result": pilot_result,
            }
            if pilot_confidence is not None:
                memory_record["confidence"] = pilot_confidence
            self.memory.add_event(memory_record)
            return pilot_result
        # Plan the request into structured tasks
        tasks = self.planner.plan(request)
        self.logger.debug("Planner produced tasks: %s", tasks)
        # Execute the tasks sequentially
        result = self.executor.execute(tasks)
        # Record the full interaction into memory
        memory_record: dict[str, Any] = {
            "type": "interaction",
            "request": request,
            "tasks": tasks,
            "result": result,
        }
        if pilot_confidence is not None:
            memory_record["confidence"] = pilot_confidence
        self.memory.add_event(memory_record)
        return result

    def _try_chimera_pilot(self, request: str) -> tuple[str | None, float | None]:
        """Use Chimera Pilot for task kinds with an available runtime backend.

        Returns a tuple of (result_string, confidence) where both may be None.
        """

        try:
            executions = self.pilot_kernel.run(request)
        except PermissionError as exc:
            return (f"Policy denied by Chimera Pilot: {exc}", None)
        except RuntimeError:
            return (None, None)

        if not executions:
            return (None, None)

        # Extract confidence from envelopes if available
        confidence_values: list[float] = []
        for execution in executions:
            if execution.envelope is not None:
                confidence_values.append(execution.envelope.confidence)

        avg_confidence = (sum(confidence_values) / len(confidence_values)) if confidence_values else None
        payload = [execution.to_dict() for execution in executions]
        return (json.dumps(payload, indent=2, sort_keys=True), avg_confidence)
