"""Stealth Kernel for Ghost Chimera vNext.

Background Event-Driven AI: EVENT -> UNDERSTAND -> UPDATE STATE ->
RECALL EXPERIENCE -> MATCH WORKFLOW -> PREDICT -> DECIDE ->
PREPARE / INJECT / ACT -> OBSERVE OUTCOME -> LEARN.

This package is the new center of gravity. The legacy agent runtime
(AgentCore / Chimera Pilot planner+executor) is demoted to an optional
execution capability underneath it. All modules are stdlib-only so the
core test suite never requires an external service.
"""

from __future__ import annotations

from .agent_prompt import (
    AgentAction,
    AgentActionType,
    gate_agent_action,
    parse_agent_output,
    render_system_prompt,
)
from .eval import EvalReport, StealthEval
from .event_bus import EventBus, read_only_consumer
from .events import Event, new_event
from .experience import ExperienceGraph
from .hooks import StealthHook, StealthHookRegistry, define_hook, ghost_on
from .hosts import (
    AdapterRegistry,
    ClaudeCodeAdapter,
    CodexAdapter,
    GeminiAdapter,
    HermesAdapter,
    HostAdapter,
    OpenClawAdapter,
    OpenCodeAdapter,
)
from .intervention import Intervention, InterventionOutcome, InterventionState
from .loop import LoopResult, StealthLoop
from .prediction import Prediction, PredictionEngine
from .ste import SimplifyResult, simplify, simplify_sentence
from .stealth_policy import AutonomyLevel, Decision, GhostPolicy, StealthEvaluator
from .store import StealthStore
from .workflow_learner import WorkflowHypothesis, WorkflowLearner
from .world_state import WorldState

__all__ = [
    "AutonomyLevel",
    "AgentAction",
    "AgentActionType",
    "AdapterRegistry",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "Decision",
    "Event",
    "EventBus",
    "EvalReport",
    "StealthEval",
    "ExperienceGraph",
    "GeminiAdapter",
    "GhostPolicy",
    "HermesAdapter",
    "HostAdapter",
    "Intervention",
    "InterventionOutcome",
    "InterventionState",
    "LoopResult",
    "OpenClawAdapter",
    "OpenCodeAdapter",
    "Prediction",
    "PredictionEngine",
    "SimplifyResult",
    "StealthEvaluator",
    "StealthHook",
    "StealthHookRegistry",
    "StealthLoop",
    "StealthStore",
    "WorkflowHypothesis",
    "WorkflowLearner",
    "WorldState",
    "define_hook",
    "gate_agent_action",
    "ghost_on",
    "new_event",
    "parse_agent_output",
    "read_only_consumer",
    "render_system_prompt",
    "simplify",
    "simplify_sentence",
]
