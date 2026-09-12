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
from .attention import AttentionContext, AttentionEngine, AttentionSignal
from .bpo_store import BpoStore
from .cdp import CdpBrowser, CdpClient, CdpError
from .computer import (
    ComputerAction,
    ComputerApproval,
    ComputerCapability,
    ComputerModality,
    ComputerRisk,
    ComputerUseManager,
    ComputerUsePlan,
    ComputerUseProvider,
    DelegatingComputerProvider,
    classify_risk,
)
from .computer_live import (
    LIVE_OPERATIONS,
    CdpBrowserExecutor,
    OpenCodeVisionExecutor,
    PyAutoGuiDesktopExecutor,
    attach_live_backends,
    attach_managed_browser,
    live_capability,
)
from .eval import EvalReport, StealthEval
from .eve_model import (
    EnvironmentState,
    Evidence,
    ExperienceEvent,
    ExperienceEventType,
    ExperienceState,
    ExperienceStream,
    FrictionState,
    IntentHypothesis,
    InterventionMode,
    OutcomeState,
    PerceptionLevel,
    TrajectoryState,
    WorkflowMaturity,
)
from .eve_model import (
    Intervention as EveIntervention,
)
from .eve_model import (
    Prediction as EvePrediction,
)
from .event_bus import EventBus, read_only_consumer
from .events import Event, new_event
from .experience import ExperienceGraph
from .governance import (
    GovernedDecision,
    MaturityThresholds,
    WorkflowAutonomyGovernor,
    WorkflowMaturityState,
    WorkflowMaturityTracker,
)
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
from .intent import FrictionDetector, IntentEngine
from .intervention import Intervention, InterventionOutcome, InterventionState
from .loop import LoopResult, StealthLoop
from .perception import (
    AccessibilityPerceptionProvider,
    BackendFn,
    BrowserPerceptionProvider,
    EventPerceptionProvider,
    PerceptionManager,
    PerceptionProvider,
    PerceptionResult,
    StructuredPerceptionProvider,
    VisionPerceptionProvider,
)
from .prediction import Prediction, PredictionEngine
from .project_scan import ProjectFinding, ProjectScanReport, scan_project
from .ste import SimplifyResult, simplify, simplify_sentence
from .stealth_policy import AutonomyLevel, Decision, GhostPolicy, StealthEvaluator
from .store import StealthStore
from .untrusted import FENCE_CLOSE, FENCE_OPEN, fence_content, fence_mapping, is_fenced
from .workflow_learner import WorkflowHypothesis, WorkflowLearner
from .world_state import WorldState

__all__ = [
    "AutonomyLevel",
    "AgentAction",
    "AgentActionType",
    "AdapterRegistry",
    "AttentionEngine",
    "AttentionSignal",
    "AttentionContext",
    "BpoStore",
    "BackendFn",
    "CdpBrowser",
    "CdpBrowserExecutor",
    "CdpClient",
    "CdpError",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "ComputerAction",
    "ComputerApproval",
    "ComputerCapability",
    "ComputerModality",
    "ComputerRisk",
    "ComputerUseManager",
    "ComputerUsePlan",
    "ComputerUseProvider",
    "Decision",
    "DelegatingComputerProvider",
    "Event",
    "EventBus",
    "EvalReport",
    "StealthEval",
    "ExperienceGraph",
    "ExperienceEventType",
    "ExperienceEvent",
    "ExperienceState",
    "ExperienceStream",
    "Evidence",
    "EnvironmentState",
    "EvePrediction",
    "EveIntervention",
    "FENCE_CLOSE",
    "FENCE_OPEN",
    "FrictionDetector",
    "FrictionState",
    "GovernedDecision",
    "GeminiAdapter",
    "GhostPolicy",
    "HermesAdapter",
    "HostAdapter",
    "IntentEngine",
    "IntentHypothesis",
    "Intervention",
    "InterventionMode",
    "InterventionOutcome",
    "InterventionState",
    "LoopResult",
    "MaturityThresholds",
    "OpenCodeVisionExecutor",
    "OpenClawAdapter",
    "OpenCodeAdapter",
    "OutcomeState",
    "AccessibilityPerceptionProvider",
    "BrowserPerceptionProvider",
    "EventPerceptionProvider",
    "PerceptionLevel",
    "PerceptionManager",
    "PerceptionProvider",
    "PerceptionResult",
    "StructuredPerceptionProvider",
    "VisionPerceptionProvider",
    "Prediction",
    "PredictionEngine",
    "ProjectFinding",
    "ProjectScanReport",
    "SimplifyResult",
    "StealthEvaluator",
    "StealthHook",
    "StealthHookRegistry",
    "StealthLoop",
    "StealthStore",
    "TrajectoryState",
    "WorkflowAutonomyGovernor",
    "WorkflowHypothesis",
    "WorkflowLearner",
    "WorkflowMaturity",
    "WorkflowMaturityState",
    "WorkflowMaturityTracker",
    "WorldState",
    "LIVE_OPERATIONS",
    "PyAutoGuiDesktopExecutor",
    "attach_live_backends",
    "attach_managed_browser",
    "classify_risk",
    "define_hook",
    "fence_content",
    "fence_mapping",
    "gate_agent_action",
    "ghost_on",
    "is_fenced",
    "live_capability",
    "new_event",
    "parse_agent_output",
    "read_only_consumer",
    "render_system_prompt",
    "scan_project",
    "simplify",
    "simplify_sentence",
]
