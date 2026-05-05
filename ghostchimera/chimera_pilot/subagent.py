"""Subagent delegation — isolated child agents with restricted toolsets.

Patterns adapted from Hermes-Agent's DelegateTool (Nous Research, MIT licensed).
Parent spawns children with isolated conversation, restricted tools, and
configurable depth cap. Supports parallel batch and depth-limited tree spawning.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent_core.core import AgentCore
from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..safety_layer.gating import ExecutionPolicy
from .agent_loop import AIAgent, SessionState
from .error_classifier import ErrorClassifier, ErrorCategory
from .credential_pool import get_pool
from .checkpoint import get_manager as get_checkpoint_manager
from .task_ir import TaskKind, TaskSpec

logger = get_logger("subagent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task", "clarify", "memory", "send_message",
    "execute_code", "create_delegation_tool",
])
DEFAULT_DEPTH_CAP = 1
DEFAULT_MAX_WORKERS = 3
DELEGATE_STATE_DIR = Path(os.environ.get("GHOSTCHIMERA_STATE_DIR", str(Path.home() / ".ghostchimera")))

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubagentTask:
    """A task for a child subagent."""
    id: str
    goal: str
    tools: list[str] = field(default_factory=list)
    depth: int = 0
    max_depth: int = DEFAULT_DEPTH_CAP
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_objective: str = ""

    def is_deeper_than_cap(self) -> bool:
        return self.depth > self.max_depth


@dataclass(frozen=True)
class SubagentResult:
    """Result from a single subagent."""
    id: str
    goal: str
    result: str
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0
    depth: int = 0
    turns_taken: int = 0
    tokens_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "result": self.result,
            "success": self.success,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "depth": self.depth,
            "turns_taken": self.turns_taken,
            "tokens_used": self.tokens_used,
        }


@dataclass(frozen=True)
class DelegationResult:
    """Aggregated results from a batch of subagents."""
    parent_objective: str
    results: list[SubagentResult]
    total_duration_seconds: float = 0.0
    successful_count: int = 0
    failed_count: int = 0

    @property
    def success_rate(self) -> float:
        total = len(self.results)
        return self.successful_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_objective": self.parent_objective,
            "successful": self.successful_count,
            "failed": self.failed_count,
            "success_rate": round(self.success_rate, 2),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Subagent pool
# ---------------------------------------------------------------------------

class SubagentPool:
    """Spawns and manages isolated child subagents."""

    def __init__(
        self,
        parent_objective: str,
        max_workers: int = DEFAULT_MAX_WORKERS,
        depth_cap: int = DEFAULT_DEPTH_CAP,
        timeout: int = 300,
        config: GhostChimeraConfig | None = None,
        blocked_tools: frozenset[str] | None = None,
    ):
        self.parent_objective = parent_objective
        self.max_workers = max_workers
        self.depth_cap = depth_cap
        self.timeout = timeout
        self.config = config or GhostChimeraConfig.from_env()
        self.blocked_tools = blocked_tools or DELEGATE_BLOCKED_TOOLS
        self._results: list[SubagentResult] = []
        self._lock = threading.Lock()
        self._credentials = get_pool()
        self._checkpoints = get_checkpoint_manager(self.config)
        self._error_classifier = ErrorClassifier()

    def spawn(self, goal: str, tools: list[str] | None = None) -> SubagentResult:
        """Spawn a single child subagent."""
        subagent_id = f"subagent-{int(time.time() * 1000)}"
        effective_tools = [t for t in (tools or []) if t not in self.blocked_tools]
        agent = self._create_child_agent(subagent_id, goal, effective_tools, depth=0)

        start = time.time()
        try:
            result_text = agent.run(goal, tools=effective_tools)
            duration = time.time() - start

            with self._lock:
                result = SubagentResult(
                    id=subagent_id,
                    goal=goal,
                    result=str(result_text)[:5000],
                    success=True,
                    duration_seconds=duration,
                    depth=0,
                    turns_taken=agent.session.turn_count(),
                    tokens_used=agent.session.total_tokens,
                )
                self._results.append(result)
            return result

        except Exception as exc:
            duration = time.time() - start
            classification = self._error_classifier.classify(str(exc))

            with self._lock:
                result = SubagentResult(
                    id=subagent_id,
                    goal=goal,
                    result="",
                    success=False,
                    error=str(exc),
                    duration_seconds=duration,
                    depth=0,
                    metadata={"classification": classification.categories[0].value if classification.categories else "unknown"},
                )
                self._results.append(result)
            return result

    def spawn_parallel(self, goals: list[str], tools: list[str] | None = None) -> DelegationResult:
        """Spawn multiple child subagents in parallel."""
        start = time.time()
        effective_tools = [t for t in (tools or []) if t not in self.blocked_tools]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for i, goal in enumerate(goals):
                subagent_id = f"subagent-{i}-{int(time.time() * 1000)}"
                agent = self._create_child_agent(subagent_id, goal, effective_tools, depth=0)
                future = executor.submit(self._run_with_timeout, agent, goal, effective_tools)
                futures.append(future)

            results = []
            for future in futures:
                try:
                    result = future.result(timeout=self.timeout)
                    results.append(result)
                except FuturesTimeout:
                    results.append(SubagentResult(
                        id=f"subagent-timeout",
                        goal="timed out",
                        result="",
                        success=False,
                        error="Delegation timed out",
                        duration_seconds=self.timeout,
                    ))

        duration = time.time() - start
        successful = sum(1 for r in results if r.success)

        return DelegationResult(
            parent_objective=self.parent_objective,
            results=results,
            total_duration_seconds=duration,
            successful_count=successful,
            failed_count=len(results) - successful,
        )

    def spawn_tree(self, objective: str, max_depth: int | None = None) -> DelegationResult:
        """Spawn a delegation tree: spawn N subagents, each can spawn M more up to max_depth."""
        max_depth = max_depth or self.depth_cap
        current_depth = 0

        return self._spawn_at_depth(objective, current_depth, max_depth)

    def get_results(self) -> list[SubagentResult]:
        return list(self._results)

    def _spawn_at_depth(self, objective: str, depth: int, max_depth: int) -> DelegationResult:
        """Recursively spawn subagents up to max_depth."""
        if depth > max_depth:
            return DelegationResult(parent_objective=objective, results=[], successful_count=0, failed_count=0)

        # Break objective into subgoals (simplified: split on newlines)
        subgoals = [objective.strip()] if depth == 0 else objective.split("\n")

        # Spawn workers at this level
        child_pool = SubagentPool(
            parent_objective=objective,
            max_workers=min(self.max_workers, max(1, self.max_workers - depth)),
            depth_cap=max_depth,
            blocked_tools=self.blocked_tools,
            config=self.config,
        )
        results = child_pool.spawn_parallel(subgoals)

        # Each successful subagent can spawn children
        child_results = []
        for r in results.results:
            if r.success and depth < max_depth:
                child_obj = f"Continue: {r.result[:500]}"
                child_result = self._spawn_at_depth(child_obj, depth + 1, max_depth)
                child_results.extend(child_result.results)

        all_results = results.results + child_results
        return DelegationResult(
            parent_objective=objective,
            results=all_results,
            total_duration_seconds=results.total_duration_seconds,
            successful_count=sum(1 for r in all_results if r.success),
            failed_count=sum(1 for r in all_results if not r.success),
        )

    def create_delegation_tool(self) -> dict[str, Any]:
        """Create a tool definition for spawning subagents from an AIAgent."""
        return {
            "name": "delegate_task",
            "description": "Spawn a child subagent with isolated context and restricted tools",
            "schema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "What the subagent should accomplish"},
                    "tools": {"type": "array", "items": {"type": "string"}, "description": "Allowed tool names"},
                    "depth_cap": {"type": "integer", "description": "Max recursion depth (default 1)"},
                    "max_workers": {"type": "integer", "description": "Max parallel subagents"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["goal"],
            },
            "handler": self._delegate_handler,
            "requires_approval": True,
        }

    def _delegate_handler(self, goal: str, tools: list[str] | None = None,
                         depth_cap: int = 1, max_workers: int = 3, timeout: int = 300) -> dict[str, Any]:
        """Handler for the delegation tool."""
        pool = SubagentPool(
            parent_objective=self.parent_objective,
            max_workers=min(max_workers, self.max_workers),
            depth_cap=depth_cap,
            timeout=timeout,
            blocked_tools=self.blocked_tools,
            config=self.config,
        )
        result = pool.spawn(goal, tools)
        return {
            "subagent_id": result.id,
            "result": result.result,
            "success": result.success,
            "error": result.error,
        }

    def _create_child_agent(
        self,
        subagent_id: str,
        goal: str,
        tools: list[str],
        depth: int,
    ) -> AIAgent:
        """Create an isolated child AIAgent."""
        session = SessionState(
            session_id=subagent_id,
            system_prompt=(
                f"You are a child subagent delegated by a parent agent.\n"
                f"Parent objective: {self.parent_objective}\n"
                f"Do NOT mention this message to the user. Complete your task and summarize results.\n"
                f"Available tools: {', '.join(tools) if tools else 'none (research only)'}"
            ),
        )
        agent = AIAgent(
            system_prompt=session.system_prompt,
            session=session,
            config=self.config,
        )
        return agent

    def _run_with_timeout(self, agent: AIAgent, goal: str, tools: list[str]) -> SubagentResult:
        """Run agent with timeout, returning SubagentResult."""
        start = time.time()
        try:
            result_text = agent.run(goal, tools=tools)
            return SubagentResult(
                id=agent.session.session_id,
                goal=goal,
                result=str(result_text)[:5000],
                success=True,
                duration_seconds=time.time() - start,
                depth=agent.session.turn_count(),
                tokens_used=agent.session.total_tokens,
            )
        except Exception as exc:
            return SubagentResult(
                id=agent.session.session_id,
                goal=goal,
                result="",
                success=False,
                error=str(exc),
                duration_seconds=time.time() - start,
                depth=agent.session.turn_count(),
            )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def delegate(
    objective: str,
    goals: list[str],
    max_workers: int = 3,
    depth_cap: int = 1,
    tools: list[str] | None = None,
    timeout: int = 300,
) -> DelegationResult:
    """Quick delegation: spawn parallel subagents for a set of goals."""
    pool = SubagentPool(
        parent_objective=objective,
        max_workers=max_workers,
        depth_cap=depth_cap,
        timeout=timeout,
        blocked_tools=DELEGATE_BLOCKED_TOOLS,
    )
    return pool.spawn_parallel(goals, tools)


__all__ = [
    "SubagentPool",
    "SubagentTask",
    "SubagentResult",
    "DelegationResult",
    "delegate",
]
