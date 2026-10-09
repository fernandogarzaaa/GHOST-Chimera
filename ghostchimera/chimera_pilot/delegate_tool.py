"""Model-callable ``delegate`` tool — subagent delegation for the agent run loop.

Closes the v1.0 gap where delegation existed only programmatically
(:class:`~ghostchimera.chimera_pilot.subagent.SubagentPool`,
``agent_pool``, ``mixture_of_agents``) but the model could not spawn a
subagent mid-run. This module exposes:

* a :class:`~ghostchimera.chimera_pilot.toolsets.ToolDefinition` for
  :class:`~ghostchimera.chimera_pilot.toolsets.ToolsetManager` discovery
  (the schema the model sees), and
* a runtime tool dict (``{"name", "description", "schema", "handler",
  "requires_approval"}``) for ``AIAgent._execute_tool_calls``.

Design notes
------------
* Budgets are explicit per delegation: ``max_steps`` (tool rounds, hard),
  ``timeout_seconds`` (wall time, hard — the worker is abandoned on breach),
  ``max_tokens`` (measured post-run; a breach is reported, not silently
  absorbed).
* Depth cap: the handler refuses to spawn at ``depth >= max_depth``, and the
  child is not offered the delegate tool at the cap (defense in depth).
* Approval: the tool declares ``requires_approval=True`` so the agent loop
  routes it through :mod:`ghostchimera.safety_layer.approval` like any
  high-impact tool.
* Audit: spawn, result, and refusal are written to the HMAC-chained audit
  log with the parent session id in the trail.
"""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass
from typing import Any

from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..safety_layer.audit import AuditLog
from .subagent import DELEGATE_BLOCKED_TOOLS, SubagentPool
from .toolsets import ToolDefinition, ToolsetDefinition, ToolsetRegistry

logger = get_logger("delegate_tool")

TOOL_NAME = "delegate"

# Bounds for per-delegation budgets. Generous ceilings keep a single
# delegation from starving the parent; floors keep degenerate values usable.
MIN_STEPS, MAX_STEPS = 1, 100
MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 5, 3600
MIN_TOKENS, MAX_TOKENS = 256, 200000

DEFAULT_MAX_DEPTH = 2


def _clamp(value: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = lo
    return max(lo, min(hi, number))


@dataclass(frozen=True)
class DelegationBudget:
    """Explicit per-delegation budget."""

    max_steps: int = 20
    timeout_seconds: int = 300
    max_tokens: int = 16000

    @classmethod
    def clamped(
        cls,
        max_steps: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        defaults: DelegationBudget | None = None,
    ) -> DelegationBudget:
        """Build a budget from overrides, falling back to ``defaults``."""
        base = defaults or cls()
        return cls(
            max_steps=_clamp(base.max_steps if max_steps is None else max_steps, MIN_STEPS, MAX_STEPS),
            timeout_seconds=_clamp(
                base.timeout_seconds if timeout_seconds is None else timeout_seconds,
                MIN_TIMEOUT_SECONDS,
                MAX_TIMEOUT_SECONDS,
            ),
            max_tokens=_clamp(base.max_tokens if max_tokens is None else max_tokens, MIN_TOKENS, MAX_TOKENS),
        )


def _session_stat(session: Any, name: str) -> int:
    """Read an int stat from a child session, defaulting to 0 on any failure."""
    try:
        value = getattr(session, name)
        value = value() if callable(value) else value
        return int(value or 0)
    except Exception:
        return 0


def _default_agent_factory(
    *,
    objective: str,
    parent_objective: str,
    depth: int,
    max_steps: int,
    tools: list[dict[str, Any]],
    config: GhostChimeraConfig,
) -> Any:
    """Create an isolated child agent, reusing :class:`SubagentPool` machinery."""
    pool = SubagentPool(parent_objective=parent_objective, config=config)
    child_id = f"subagent-d{depth}-{int(time.time() * 1000)}"
    tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
    agent = pool._create_child_agent(child_id, objective, tool_names, depth=depth)
    agent.max_tool_rounds = max_steps
    return agent


class DelegateTool:
    """A model-callable tool that spawns a bounded, audited subagent."""

    TOOL_NAME = TOOL_NAME

    def __init__(
        self,
        *,
        parent_objective: str,
        parent_session_id: str = "",
        depth: int = 0,
        max_depth: int = DEFAULT_MAX_DEPTH,
        default_budget: DelegationBudget | None = None,
        allowed_tools: list[str] | None = None,
        blocked_tools: frozenset[str] | None = None,
        tool_registry: dict[str, dict[str, Any]] | None = None,
        agent_factory: Any | None = None,
        audit_log: AuditLog | None = None,
        config: GhostChimeraConfig | None = None,
    ) -> None:
        self.parent_objective = parent_objective
        self.parent_session_id = parent_session_id
        self.depth = depth
        self.max_depth = max(0, int(max_depth))
        self.default_budget = default_budget or DelegationBudget()
        self.allowed_tools = list(allowed_tools or [])
        self.blocked_tools = blocked_tools or (DELEGATE_BLOCKED_TOOLS | {TOOL_NAME, "delegate_task"})
        self.tool_registry = dict(tool_registry or {})
        self.agent_factory = agent_factory or _default_agent_factory
        self.audit_log = audit_log or AuditLog()
        self.config = config or GhostChimeraConfig.from_env()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Tool surfaces
    # ------------------------------------------------------------------

    @classmethod
    def tool_definition(cls) -> ToolDefinition:
        """Schema the model sees via :class:`ToolsetManager`."""
        return ToolDefinition(
            name=cls.TOOL_NAME,
            description=(
                "Spawn a bounded child subagent with isolated context to complete a "
                "sub-task. Use for work that benefits from a fresh context window. "
                "The child runs with restricted tools and explicit budgets; you receive "
                "a structured receipt (result, turns, tokens, run id)."
            ),
            schema={
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "What the subagent should accomplish (required).",
                    },
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names the child may use. Defaults to the parent's allowance.",
                    },
                    "max_steps": {
                        "type": "integer",
                        "description": "Max tool rounds for the child (1-100).",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Wall-clock timeout for the child (5-3600s).",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Token budget for the child (256-200000).",
                    },
                },
                "required": ["objective"],
            },
            requires_approval=True,
            category="delegation",
        )

    def as_tool_dict(self) -> dict[str, Any]:
        """Runtime tool dict for ``AIAgent._execute_tool_calls``."""
        definition = self.tool_definition()
        return {
            "name": definition.name,
            "description": definition.description,
            "schema": definition.schema,
            "handler": self.delegate,
            "requires_approval": True,
        }

    def child_tool(self, allowed_tools: list[str] | None = None) -> DelegateTool | None:
        """A delegate tool for the child at ``depth + 1``, or ``None`` at the cap.

        ``allowed_tools`` is the child's effective (already narrowed) tool
        list. The nested delegate must not widen it back to the parent's
        full allowance, or a child could grant its own children more tools
        than it received itself.
        """
        if self.depth + 1 >= self.max_depth:
            return None
        return DelegateTool(
            parent_objective=self.parent_objective,
            parent_session_id=self.parent_session_id,
            depth=self.depth + 1,
            max_depth=self.max_depth,
            default_budget=self.default_budget,
            allowed_tools=self.allowed_tools if allowed_tools is None else allowed_tools,
            blocked_tools=self.blocked_tools,
            tool_registry=self.tool_registry,
            agent_factory=self.agent_factory,
            audit_log=self.audit_log,
            config=self.config,
        )

    def build_child_tools(self, allowed_tools: list[str] | None = None) -> list[dict[str, Any]]:
        """Runtime tool dicts for the child agent."""
        requested = list(allowed_tools) if allowed_tools is not None else list(self.allowed_tools)
        effective = [name for name in requested if name not in self.blocked_tools]
        tools = [self.tool_registry[name] for name in effective if name in self.tool_registry]
        nested = self.child_tool(effective)
        if nested is not None:
            tools.append(nested.as_tool_dict())
        return tools

    # ------------------------------------------------------------------
    # Handler (called by the agent loop as ``handler(**args)``)
    # ------------------------------------------------------------------

    def delegate(
        self,
        objective: str = "",
        allowed_tools: list[str] | None = None,
        max_steps: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Spawn a bounded child subagent and return its receipt."""
        objective = (objective or "").strip()
        if not objective:
            return self._failure("", "objective is required", budget=self.default_budget)

        if self.depth >= self.max_depth:
            reason = f"delegation depth cap reached (depth={self.depth}, max_depth={self.max_depth})"
            self._audit(
                "delegate.refused",
                {
                    "parent_session_id": self.parent_session_id,
                    "objective": objective,
                    "depth": self.depth,
                    "reason": reason,
                },
            )
            logger.warning("Delegate refused: %s", reason)
            return self._failure("", reason, budget=self.default_budget)

        budget = DelegationBudget.clamped(
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            defaults=self.default_budget,
        )
        child_tools = self.build_child_tools(allowed_tools)

        child_id = f"subagent-d{self.depth + 1}-{int(time.time() * 1000)}"
        self._audit(
            "delegate.spawn",
            {
                "parent_session_id": self.parent_session_id,
                "child_run_id": child_id,
                "parent_objective": self.parent_objective,
                "objective": objective,
                "depth": self.depth + 1,
                "max_depth": self.max_depth,
                "budget": {
                    "max_steps": budget.max_steps,
                    "timeout_seconds": budget.timeout_seconds,
                    "max_tokens": budget.max_tokens,
                },
                "child_tools": [t.get("name", "") for t in child_tools if isinstance(t, dict)],
            },
        )

        start = time.time()
        try:
            agent = self.agent_factory(
                objective=objective,
                parent_objective=self.parent_objective,
                depth=self.depth + 1,
                max_steps=budget.max_steps,
                tools=child_tools,
                config=self.config,
            )
        except Exception as exc:
            return self._record_result(
                child_id, objective, budget, start, success=False, error=f"child agent creation failed: {exc}"
            )

        result_text = ""
        breach: str | None = None
        error: str | None = None
        outcome: dict[str, Any] = {}
        finished = threading.Event()
        cancelled = threading.Event()

        def _guarded(handler: Any) -> Any:
            """Refuse child tool calls once the delegation is cancelled."""

            @functools.wraps(handler)
            def wrapper(**kwargs: Any) -> Any:
                if cancelled.is_set():
                    raise RuntimeError("delegation cancelled: wall-time budget exceeded")
                return handler(**kwargs)

            return wrapper

        guarded_tools = []
        for tool in child_tools:
            if isinstance(tool, dict) and callable(tool.get("handler")):
                tool = dict(tool)
                tool["handler"] = _guarded(tool["handler"])
            guarded_tools.append(tool)

        def _run_child() -> None:
            try:
                outcome["value"] = agent.run(objective, guarded_tools)
            except Exception as exc:  # noqa: BLE001 — captured into the receipt
                outcome["error"] = exc
            finally:
                # Capture stats here, while the worker is still the only
                # writer; reading them after a timeout would race.
                session = getattr(agent, "session", None)
                if session is not None:
                    outcome["turns_taken"] = _session_stat(session, "turn_count")
                    outcome["tokens_used"] = _session_stat(session, "total_tokens")
                finished.set()

        # Daemon thread: on timeout the worker is abandoned, never joined,
        # so a runaway child cannot hang the parent process at exit.
        # Cooperative cancellation (the `cancelled` event) stops the child
        # from starting new tool calls after the parent has moved on.
        worker = threading.Thread(target=_run_child, daemon=True, name=f"delegate-{child_id}")
        worker.start()
        if not finished.wait(timeout=budget.timeout_seconds):
            breach = "timeout_seconds"
            error = f"delegation wall-time budget exceeded ({budget.timeout_seconds}s); child abandoned"
            cancelled.set()
        elif "error" in outcome:
            error = f"child agent failed: {outcome['error']}"
        else:
            result_text = str(outcome.get("value", ""))

        duration = time.time() - start
        turns_taken = int(outcome.get("turns_taken", 0) or 0)
        tokens_used = int(outcome.get("tokens_used", 0) or 0)

        if breach is None and tokens_used > budget.max_tokens:
            breach = "max_tokens"
            error = f"delegation token budget exceeded (used {tokens_used} > {budget.max_tokens})"

        return self._record_result(
            child_id,
            objective,
            budget,
            start,
            success=breach is None and error is None,
            error=error,
            result=result_text,
            turns_taken=turns_taken,
            tokens_used=tokens_used,
            duration_seconds=duration,
            budget_breach=breach,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _failure(self, child_id: str, error: str, budget: DelegationBudget) -> dict[str, Any]:
        return {
            "subagent_id": child_id,
            "objective": "",
            "result": "",
            "success": False,
            "error": error,
            "turns_taken": 0,
            "tokens_used": 0,
            "duration_seconds": 0.0,
            "depth": self.depth + 1,
            "budget_breach": None,
            "budget": {
                "max_steps": budget.max_steps,
                "timeout_seconds": budget.timeout_seconds,
                "max_tokens": budget.max_tokens,
            },
        }

    def _record_result(
        self,
        child_id: str,
        objective: str,
        budget: DelegationBudget,
        start: float,
        *,
        success: bool,
        error: str | None,
        result: str = "",
        turns_taken: int = 0,
        tokens_used: int = 0,
        duration_seconds: float | None = None,
        budget_breach: str | None = None,
    ) -> dict[str, Any]:
        duration = time.time() - start if duration_seconds is None else duration_seconds
        receipt = {
            "subagent_id": child_id,
            "objective": objective,
            "result": result[:8000],
            "success": success,
            "error": error,
            "turns_taken": turns_taken,
            "tokens_used": tokens_used,
            "duration_seconds": round(duration, 2),
            "depth": self.depth + 1,
            "budget_breach": budget_breach,
            "budget": {
                "max_steps": budget.max_steps,
                "timeout_seconds": budget.timeout_seconds,
                "max_tokens": budget.max_tokens,
            },
        }
        self._audit(
            "delegate.result",
            {
                "parent_session_id": self.parent_session_id,
                "child_run_id": child_id,
                "success": success,
                "error": error,
                "turns_taken": turns_taken,
                "tokens_used": tokens_used,
                "duration_seconds": round(duration, 2),
                "depth": self.depth + 1,
                "budget_breach": budget_breach,
            },
        )
        logger.info(
            "Delegate result child=%s success=%s turns=%d tokens=%d breach=%s",
            child_id,
            success,
            turns_taken,
            tokens_used,
            budget_breach,
        )
        return receipt

    def _audit(self, action: str, details: dict[str, Any]) -> None:
        try:
            with self._lock:
                self.audit_log.record(action, details)
        except Exception as exc:
            logger.warning("Delegate audit write failed (%s): %s", action, exc)


def register_delegate_toolset(registry: ToolsetRegistry) -> None:
    """Register the ``delegation`` toolset (model-callable subagent spawning)."""
    registry.register(
        ToolsetDefinition(
            name="delegation",
            description="Spawn bounded child subagents with isolated context",
            tools=[DelegateTool.tool_definition()],
            permissions={},
        )
    )


__all__ = [
    "TOOL_NAME",
    "DEFAULT_MAX_DEPTH",
    "DelegationBudget",
    "DelegateTool",
    "register_delegate_toolset",
]
