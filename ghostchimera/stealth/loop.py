"""Stealth Loop: the event loop everything else exists to make intelligent.

EVENT -> NORMALIZE -> UPDATE STATE -> RECALL EXPERIENCE -> MATCH
WORKFLOW -> PREDICT -> DECIDE -> PREPARE / INJECT / ACT -> OBSERVE
OUTCOME -> LEARN. Tiered: cheap deterministic stages run inline; only
high-value inference leaves the hot path (via BackgroundRuntime).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from .attention import AttentionEngine, AttentionSignal
from .computer import (
    ComputerAction,
    ComputerApproval,
    ComputerCapability,
    ComputerModality,
    ComputerUseManager,
    DelegatingComputerProvider,
)
from .context import ContextFabric, InjectionEnvelope, InMemoryRetriever
from .eve_model import (
    ExperienceEvent,
    ExperienceEventType,
    ExperienceState,
    InterventionMode,
    PerceptionLevel,
)
from .eve_model import (
    Intervention as EveIntervention,
)
from .eve_model import (
    Prediction as EvePrediction,
)
from .event_bus import EventBus
from .events import Event
from .experience import ExperienceGraph
from .governance import WorkflowAutonomyGovernor, WorkflowMaturityTracker
from .intent import FrictionDetector, FrictionState, IntentEngine
from .intervention import Intervention, InterventionOutcome, InterventionState
from .perception import PerceptionManager
from .prediction import PredictionEngine
from .runtime import BackgroundRuntime
from .stealth_policy import Decision, EvaluationSignals, GhostPolicy, StealthEvaluator
from .workflow_learner import WorkflowLearner
from .world_state import WorldState


@dataclass
class LoopResult:
    event_id: str
    decision: Decision
    intervention_id: str = ""
    predictions: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    experience_id: str = ""
    attention: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    friction: dict[str, Any] | None = None


class StealthLoop:
    """Owns events, memory projection, experience, workflow, context,
    intervention, and background execution. The legacy agent runtime is
    an optional execution capability underneath — not the identity."""

    def __init__(
        self,
        *,
        policy: GhostPolicy | None = None,
        fabric: ContextFabric | None = None,
        runtime: BackgroundRuntime | None = None,
        own_runtime: bool = True,
        store: Any = None,
        computer_capability: ComputerCapability | None = None,
    ) -> None:
        self.policy = policy or GhostPolicy.conservative_default()
        self.evaluator = StealthEvaluator(self.policy)
        self.bus = EventBus()
        self.world = WorldState()
        self.graph = ExperienceGraph()
        self.learner = WorkflowLearner()
        self.predictions = PredictionEngine(graph=self.graph)
        self.fabric = fabric or ContextFabric(retrievers=[InMemoryRetriever()])
        self.runtime = runtime or BackgroundRuntime()
        self.store = store
        self._own_runtime = own_runtime and runtime is None

        self.attention = AttentionEngine()
        self.perception = PerceptionManager()
        self.intent_engine = IntentEngine()
        self.friction_detector = FrictionDetector()
        self.maturity = WorkflowMaturityTracker()
        self.governor = WorkflowAutonomyGovernor(self.maturity)
        self.computer = ComputerUseManager()
        self.computer.register(DelegatingComputerProvider(name="browser-structured", modality=ComputerModality.BROWSER))
        self.computer.register(
            DelegatingComputerProvider(name="desktop-accessibility", modality=ComputerModality.DESKTOP)
        )
        self.computer.register(DelegatingComputerProvider(name="vision-last-resort", modality=ComputerModality.VISION))
        self.computer_capability = computer_capability or ComputerCapability()

        self._experience: ExperienceState | None = None
        self._experience_stream: Any = None
        self._session_id = ""
        self._eve_interventions: dict[str, EveIntervention] = {}

        self.interventions: dict[str, Intervention] = {}
        self._recent: dict[str, deque[str]] = {}
        self._interventions_1h: deque[float] = deque()
        self.bus.subscribe("*", self._on_event)
        if self._own_runtime:
            self.runtime.start()
            self.runtime.register("prepare_context", self._handle_prepare_job)

    def close(self) -> None:
        if self._own_runtime:
            self.runtime.stop()

    def set_session(self, session_id: str) -> None:
        """Set the active session for experience tracking."""
        from .eve_model import ExperienceStream

        self._session_id = session_id
        self._experience = ExperienceState(session_id=session_id)
        self._experience_stream = ExperienceStream(
            session_id=session_id,
            experience_id=self._experience.experience_id,
        )

    def emit(self, event: Event) -> bool:
        return self.bus.emit(event)

    def _on_event(self, event: Event) -> None:
        attention_signal = self.attention.evaluate(event)
        self.attention.update_perception(attention_signal.level)

        if not attention_signal.should_attend:
            self._minimal_update(event, attention_signal)
            return

        perception_result = self._perceive(event, attention_signal.level)

        self.world.observe_event(event.event_type, {"actor": event.actor, **event.payload})
        self.graph.record_event(event)
        if self.store is not None:
            with suppress(Exception):
                self.store.record_event(event)

        stream = event.session_id or event.correlation_id or "global"
        history = self._recent.setdefault(stream, deque(maxlen=20))
        history.append(event.event_type)
        self.learner.observe(stream, event.event_type)
        self.predictions.observe(event.event_type)

        intent_hypotheses = self.intent_engine.update(event, self.graph, self.learner)
        hypothesis = self.learner.match(list(history))
        preds = self.predictions.predict(list(history), hypothesis)
        friction = self.friction_detector.observe(event, predicted_actions=[pred.action for pred in preds])
        self.attention.update_friction(friction.score)
        self._update_experience(event, perception_result, intent_hypotheses, friction)

        now = time.time()
        while self._interventions_1h and now - self._interventions_1h[0] > 3600:
            self._interventions_1h.popleft()

        primary_intent = self.intent_engine.get_primary()
        base_confidence = float(
            event.payload.get(
                "confidence",
                hypothesis.confidence if hypothesis else event.confidence,
            )
        )
        if base_confidence >= 0.31 and primary_intent and primary_intent.confidence > 0.7:
            base_confidence = max(base_confidence, primary_intent.confidence * 0.9)

        signals = EvaluationSignals(
            relevance=float(event.payload.get("relevance", 0.5 if hypothesis else 0.2)),
            confidence=base_confidence,
            user_benefit=float(event.payload.get("benefit", 0.5)),
            cost=float(event.payload.get("cost", 0.2)),
            risk=float(event.payload.get("risk", 0.1)),
            external_side_effect=False,
            privacy_ok=event.privacy_classification != "secret",
            intervention_count_1h=len(self._interventions_1h),
        )
        decision, trace = self.evaluator.evaluate(signals)
        workflow = hypothesis.name if hypothesis else "unknown"
        if hypothesis:
            self.maturity.observe(workflow, support=hypothesis.support, confidence=hypothesis.confidence)
        governed = self.governor.govern(decision, workflow)
        decision = governed.decision
        trace = {**trace, "governance": governed.to_dict()}
        requested_action = event.payload.get("computer_action")
        if isinstance(requested_action, dict) and decision == Decision.ACT:
            computer_use = self.request_computer_use(requested_action, workflow=workflow, dry_run=True)
            trace = {**trace, "computer_use": computer_use["plan"]}

        intervention_id = ""
        if decision in (Decision.PREPARE, Decision.INJECT, Decision.ACT):
            mode = self._decision_to_mode(decision)
            intervention = self._create_intervention(
                event,
                hypothesis,
                mode,
                signals,
                trace,
                intent_hypotheses,
                preds,
                friction,
                decision,
            )
            intervention_id = intervention.id
            if decision == Decision.PREPARE and self._own_runtime:
                self.runtime.submit(
                    "prepare_context",
                    {"intervention_id": intervention.id, "event": event.to_dict()},
                )
            else:
                self._prepare(intervention, event)

        self._record_experience_event(
            event,
            decision,
            intervention_id,
            intent_hypotheses,
            friction,
            perception_result,
        )
        self._last = LoopResult(
            event_id=event.event_id,
            decision=decision,
            intervention_id=intervention_id,
            predictions=[{"action": p.action, "p": p.probability} for p in preds[:3]],
            trace=trace,
            experience_id=self._experience.experience_id if self._experience else "",
            attention={
                "should_attend": attention_signal.should_attend,
                "level": attention_signal.level.value,
                "reason": attention_signal.reason,
            },
            intent=self.intent_engine.to_dict(),
            friction=friction.to_dict(),
        )

    def _minimal_update(self, event: Event, attention_signal: AttentionSignal) -> None:
        self.world.observe_event(event.event_type, {"actor": event.actor, **event.payload})
        self.graph.record_event(event)
        if self.store is not None:
            with suppress(Exception):
                self.store.record_event(event)

        stream = event.session_id or event.correlation_id or "global"
        history = self._recent.setdefault(stream, deque(maxlen=20))
        history.append(event.event_type)
        self.learner.observe(stream, event.event_type)
        self.predictions.observe(event.event_type)

        friction = self.friction_detector.observe(event)
        self.attention.update_friction(friction.score)
        self._record_experience_event(
            event,
            Decision.NONE,
            "",
            [],
            friction,
            None,
        )
        self._last = LoopResult(
            event_id=event.event_id,
            decision=Decision.NONE,
            intervention_id="",
            predictions=[],
            trace={},
            experience_id=self._experience.experience_id if self._experience else "",
            attention={
                "should_attend": attention_signal.should_attend,
                "level": attention_signal.level.value,
                "reason": attention_signal.reason,
            },
            intent=self.intent_engine.to_dict(),
            friction=friction.to_dict(),
        )

    def _perceive(self, event: Event, level: PerceptionLevel):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.perception.perceive(event, level, self._get_perception_context()))

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.perception.perceive(event, level, self._get_perception_context()))
        finally:
            loop.close()

    def _get_perception_context(self) -> dict[str, Any]:
        return {
            "session_id": self._session_id,
            "experience_id": self._experience.experience_id if self._experience else "",
            "world_state": self.world.snapshot(),
            "experience_graph": self.graph.snapshot(),
        }

    def _update_experience(
        self,
        event: Event,
        perception_result: Any,
        intent_hypotheses: list,
        friction_state: FrictionState,
    ) -> None:
        if not self._experience:
            return

        self._experience.timestamp_last_updated = time.time()
        if perception_result and perception_result.success and perception_result.environment:
            self._experience.environment = perception_result.environment
        primary = self.intent_engine.get_primary()
        if primary:
            self._experience.intent = primary
            self._experience.task = primary.goal
        self._experience.friction = friction_state
        self._experience.trajectory.actions.append(
            {
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "payload_summary": str(event.payload)[:200],
            }
        )

    def _decision_to_mode(self, decision: Decision) -> InterventionMode:
        mapping = {
            Decision.NONE: InterventionMode.WITNESS,
            Decision.STORE: InterventionMode.WITNESS,
            Decision.PREPARE: InterventionMode.PREPARE,
            Decision.INJECT: InterventionMode.COPILOT,
            Decision.ACT: InterventionMode.GHOST,
            Decision.ASK: InterventionMode.COPILOT,
        }
        return mapping.get(decision, InterventionMode.WITNESS)

    def _create_intervention(
        self,
        event: Event,
        hypothesis: Any,
        mode: InterventionMode,
        signals: EvaluationSignals,
        trace: dict,
        intent_hypotheses: list,
        preds: list,
        friction: FrictionState,
        decision: Decision,
    ) -> Intervention:
        primary_intent = self.intent_engine.get_primary()
        workflow = hypothesis.name if hypothesis else "unknown"
        reason = f"loop decision={decision} score={trace.get('score')}"
        expected_benefit = primary_intent.goal if primary_intent else "Assist user"
        evidence = []
        if primary_intent:
            evidence.append(f"intent:{primary_intent.goal}")
        if hypothesis:
            evidence.append(f"workflow:{hypothesis.name}")
        evidence.append(f"predictions:{[p.action for p in preds[:3]]}")

        intervention = Intervention(
            trigger_event_id=event.event_id,
            workflow=workflow,
            confidence=signals.confidence,
            reason=reason,
            provenance={
                "trace": trace,
                "predictions": [p.action for p in preds[:3]],
                "eve_mode": mode.value,
                "expected_benefit": expected_benefit,
                "intent": primary_intent.__dict__ if primary_intent else None,
                "friction": friction.to_dict(),
            },
        )
        intervention.transition(InterventionState.QUEUED)
        self.interventions[intervention.id] = intervention
        self.maturity.note_proposal(
            workflow,
            support=hypothesis.support if hypothesis else 0,
            confidence=hypothesis.confidence if hypothesis else signals.confidence,
        )

        eve_intervention = EveIntervention(
            trigger_event_id=event.event_id,
            mode=mode,
            reason=reason,
            expected_benefit=expected_benefit,
            evidence=evidence,
            predicted_outcome=(
                EvePrediction(
                    predicted_action=preds[0].action,
                    probability=preds[0].probability,
                    expected_friction=friction.score,
                    basis="workflow" if hypothesis else "base_rate",
                )
                if preds
                else None
            ),
            confidence=signals.confidence,
            requires_approval=mode in (InterventionMode.COPILOT, InterventionMode.GHOST),
        )
        self._eve_interventions[intervention.id] = eve_intervention
        if self._experience:
            self._experience.intervention = eve_intervention

        self.graph.record_intervention(workflow, intervention.id)
        if self.store is not None:
            with suppress(Exception):
                self.store.record_intervention(intervention)
        self._interventions_1h.append(time.time())
        return intervention

    def _record_experience_event(
        self,
        event: Event,
        decision: Decision,
        intervention_id: str,
        intent_hypotheses: list,
        friction_state: FrictionState,
        perception_result: Any,
    ) -> None:
        if not self._experience_stream:
            return

        if intervention_id:
            event_type = ExperienceEventType.INTERVENTION_PROPOSED
        elif friction_state.score > 0.5:
            event_type = ExperienceEventType.FRICTION_DETECTED
        elif self.intent_engine.get_primary() and not self._experience.intent:
            event_type = ExperienceEventType.TASK_STARTED
        elif self.intent_engine.get_primary() and self._experience.intent:
            event_type = ExperienceEventType.INTENT_CHANGED
        else:
            event_type = ExperienceEventType.ENVIRONMENT_CHANGED

        self._experience_stream.append(
            ExperienceEvent(
                event_type=event_type,
                session_id=self._session_id,
                experience_id=self._experience.experience_id if self._experience else "",
                payload={
                    "ghost_event_type": event.event_type,
                    "decision": str(decision),
                    "intervention_id": intervention_id,
                    "intent": [h.goal for h in intent_hypotheses[:3]],
                    "friction_score": friction_state.score,
                    "perception_level": (perception_result.level.value if perception_result else "none"),
                },
                provenance={
                    "event_id": event.event_id,
                    "source": event.source,
                },
            )
        )
        if self.store is not None:
            with suppress(Exception):
                self.store.record_event(event)

    def _handle_prepare_job(self, job: Any) -> dict[str, Any]:
        intervention_id = job.payload["intervention_id"]
        event = Event.from_dict(job.payload["event"])
        intervention = self.interventions.get(intervention_id)
        if intervention is None:
            return {"ok": False, "error": "unknown intervention"}
        package = self._prepare(intervention, event)
        return {"ok": True, "tokens": package.tokens, "items": len(package.items)}

    def _prepare(self, intervention: Intervention, event: Event):
        intervention.transition(InterventionState.PREPARING)
        package = self.fabric.assemble(
            event,
            workflow=intervention.workflow,
            confidence=intervention.confidence,
        )
        intervention.context = package.to_dict()
        intervention.transition(InterventionState.READY)
        self.maturity.note_assistance(intervention.workflow)
        return package

    def inject(self, intervention_id: str, host: str) -> str:
        """Render the prepared package for a host adapter. Returns markdown."""
        intervention = self.interventions[intervention_id]
        package_dict = intervention.context
        from .context import ContextItem, ContextPackage

        package = ContextPackage(
            reason=str(package_dict.get("reason", "")),
            confidence=float(package_dict.get("confidence", 0.0)),
            workflow=str(package_dict.get("workflow", "")),
            items=[
                ContextItem(
                    source=i["source"],
                    kind=i["kind"],
                    text=i["text"],
                    score=i.get("score", 0.0),
                    confidence=i.get("confidence", 0.0),
                    provenance=i.get("provenance", {}),
                    privacy_class=i.get("privacy_class", "internal"),
                )
                for i in package_dict.get("items", [])
            ],
            warnings=list(package_dict.get("warnings", [])),
            provenance=dict(package_dict.get("provenance", {})),
        )
        package.tokens = int(package_dict.get("tokens", 0))
        intervention.transition(InterventionState.INJECTED)
        self.maturity.note_assistance(intervention.workflow)
        return InjectionEnvelope(package=package, host=host).render_markdown()

    def request_computer_use(
        self,
        action: dict[str, Any],
        *,
        workflow: str = "unknown",
        approval: ComputerApproval | dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        action_id = str(action.get("action_id") or f"computer-{uuid.uuid4().hex[:12]}")
        computer_action = ComputerAction(
            operation=str(action.get("operation", "")),
            target=str(action.get("target", "")),
            parameters=dict(action.get("parameters") or {}),
            context=dict(action.get("context") or {}),
            modality=action.get("modality"),
            risk=action.get("risk"),
            action_id=action_id,
            idempotency_key=str(action.get("idempotency_key") or action_id),
        )
        maturity = self.maturity.state(workflow).maturity
        plan = self.computer.plan(computer_action, self.computer_capability, maturity)
        if dry_run:
            return {"ok": plan.executable, "plan": plan.to_dict(), "receipt": None}
        approval_obj: ComputerApproval | None = None
        if isinstance(approval, ComputerApproval):
            approval_obj = approval
        elif isinstance(approval, dict):
            approval_obj = ComputerApproval(
                approved_by=str(approval.get("approved_by", "")),
                action_id=str(approval.get("action_id", computer_action.action_id)),
                granted_at=float(approval.get("granted_at", time.time())),
                expires_at=approval.get("expires_at"),
            )
        receipt = self.computer.execute(plan, self.computer_capability, approval_obj)
        return {"ok": bool(receipt.get("ok", False)), "plan": plan.to_dict(), "receipt": receipt}

    def observe_outcome(self, intervention_id: str, outcome: InterventionOutcome) -> None:
        intervention = self.interventions[intervention_id]
        if intervention.state == InterventionState.READY:
            intervention.transition(InterventionState.EXECUTED)
        elif intervention.state in (InterventionState.INJECTED, InterventionState.EXECUTED):
            pass
        else:
            raise ValueError(f"Cannot record outcome while intervention is {intervention.state}")
        if intervention.state != InterventionState.CONSUMED:
            intervention.transition(InterventionState.CONSUMED)
        intervention.record_outcome(outcome)
        if outcome in (
            InterventionOutcome.USEFUL,
            InterventionOutcome.SUCCESSFUL,
            InterventionOutcome.MODIFIED,
        ):
            self.maturity.note_success(intervention.workflow)
        elif outcome == InterventionOutcome.REJECTED:
            self.maturity.note_rejection(intervention.workflow)
        elif outcome != InterventionOutcome.PENDING:
            self.maturity.note_failure(intervention.workflow)
        useful = outcome in (InterventionOutcome.USEFUL, InterventionOutcome.SUCCESSFUL)
        self.graph.record_outcome(intervention.workflow, useful=useful)
        self.learner.observe_outcome(intervention.workflow, useful=useful)
        if self.store is not None:
            try:
                self.store.record_intervention(intervention)
                self.store.record_outcome(
                    intervention.id,
                    intervention.workflow,
                    str(outcome),
                )
            except Exception:
                pass

    def sync_workflows(self) -> int:
        """Persist learned hypotheses (consolidation pass; call periodically)."""
        if self.store is None:
            return 0
        count = 0
        for hypothesis in self.learner.hypotheses():
            try:
                self.store.upsert_workflow(
                    hypothesis.name,
                    list(hypothesis.pattern),
                    hypothesis.support,
                    hypothesis.confidence,
                    explicit=hypothesis.explicit,
                )
                count += 1
            except Exception:
                continue
        return count

    @property
    def last_result(self) -> LoopResult | None:
        return getattr(self, "_last", None)

    def handle_agent_output(
        self,
        text: str,
        *,
        connection_map: dict[str, str] | None = None,
        executor: Any = None,
    ) -> dict[str, Any]:
        """Parse a stealth agent's JSON output, gate it through policy, and
        draft / queue / execute accordingly.
        """
        from .agent_prompt import gate_agent_action, parse_agent_output

        try:
            action = parse_agent_output(text)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        decision = gate_agent_action(action, self.policy)
        if decision in (Decision.NONE, Decision.STORE):
            return {"ok": True, "decision": str(decision), "intervention_id": ""}

        intervention = Intervention(
            trigger_event_id="",
            workflow="agent:stealth-bpo",
            confidence=action.confidence_score,
            reason=f"agent action_type={action.action_type}",
            provenance={
                "event_summary": action.event_summary,
                "actions": action.actions,
            },
        )
        intervention.transition(InterventionState.QUEUED)
        self.interventions[intervention.id] = intervention
        self.graph.record_intervention(intervention.workflow, intervention.id)
        if self.store is not None:
            with suppress(Exception):
                self.store.record_intervention(intervention)

        if decision == Decision.ASK and executor is None:
            intervention.provenance["needs_approval"] = True
            return {"ok": True, "decision": "ask", "intervention_id": intervention.id}
        if decision in (Decision.PREPARE, Decision.ASK):
            intervention.transition(InterventionState.PREPARING)
            intervention.context = {
                "draft": action.actions,
                "summary": action.event_summary,
            }
            intervention.transition(InterventionState.READY)
            return {
                "ok": True,
                "decision": (str(decision).lower() if decision == Decision.PREPARE else "ask"),
                "intervention_id": intervention.id,
            }

        connections = connection_map or {}
        executed: list[dict[str, Any]] = []
        failed = False
        intervention.transition(InterventionState.PREPARING)
        intervention.transition(InterventionState.READY)
        intervention.transition(InterventionState.EXECUTED)
        for item in action.actions:
            connection_id = connections.get(str(item.get("provider", "")), "")
            try:
                result = executor(item, connection_id) if executor else None
                executed.append({"action": item, "ok": True, "result": result})
            except Exception as exc:
                failed = True
                executed.append(
                    {
                        "action": item,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        intervention.context = {"executed": executed}
        intervention.transition(InterventionState.CONSUMED)
        intervention.record_outcome(InterventionOutcome.SUCCESSFUL if not failed else InterventionOutcome.FAILED)
        useful = not failed
        self.graph.record_outcome(intervention.workflow, useful=useful)
        self.learner.observe_outcome(intervention.workflow, useful=useful)
        if self.store is not None:
            try:
                self.store.record_intervention(intervention)
                self.store.record_outcome(
                    intervention.id,
                    intervention.workflow,
                    str(intervention.outcome),
                )
            except Exception:
                pass
        return {
            "ok": True,
            "decision": "act",
            "intervention_id": intervention.id,
            "executed": executed,
        }


__all__ = ["LoopResult", "StealthLoop"]
