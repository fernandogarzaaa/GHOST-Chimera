"""Stealth Loop: the event loop everything else exists to make intelligent.

EVENT -> NORMALIZE -> UPDATE STATE -> RECALL EXPERIENCE -> MATCH
WORKFLOW -> PREDICT -> DECIDE -> PREPARE / INJECT / ACT -> OBSERVE
OUTCOME -> LEARN. Tiered: cheap deterministic stages run inline; only
high-value inference leaves the hot path (via BackgroundRuntime).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger
from .approvals import ApprovalQueue, ApprovalRequest
from .attention import AttentionEngine, AttentionSignal
from .budgets import ATTENTION_BUDGET, PROPOSAL_BUDGET, BudgetTracker
from .cloud_worker import CloudEnricher
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
from .graduation import ProposalQueue
from .intent import FrictionDetector, FrictionState, IntentEngine
from .intervention import Intervention, InterventionOutcome, InterventionState
from .perception import PerceptionManager
from .prediction import PredictionEngine
from .runtime import BackgroundRuntime
from .standing_context import StandingContext
from .stealth_policy import AutonomyLevel, Decision, EvaluationSignals, GhostPolicy, StealthEvaluator
from .temporal import TemporalContext
from .triggers import TriggerEngine, TriggerHit
from .user_model import UserModel
from .workflow_learner import WorkflowLearner
from .world_state import WorldState

logger = get_logger("stealth_loop")

# PREDICT-phase Nemotron 3 Super gating (see StealthLoop._consult_nemotron_predict).
NEMOTRON_PREDICT_CONFIDENCE_THRESHOLD = 0.6
NEMOTRON_PREDICT_MIN_INTERVAL_S = 30.0


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "") or default))
    except ValueError:
        return default


def _payload_unit(payload: Any, key: str, default: Any) -> float:
    """Producer-supplied score coerced to [0, 1].

    ``"high"``, ``None`` or garbage must not abort the event (it used to raise
    after the paid cloud call and leave ``last_result`` on the previous event).
    """
    from .nemotron_reasoning import coerce_unit

    fallback = coerce_unit(default, default=0.0)
    if not isinstance(payload, dict) or payload.get(key) is None:
        return fallback
    return coerce_unit(payload.get(key), default=fallback)


@dataclass
class _CloudSlot:
    """Where an event's cloud results land, whenever they arrive.

    Results that arrive before the event's trace exists (sync mode, cache
    hits) wait in ``values``; later ones are written straight into ``trace``,
    which is the same dict the LoopResult and the intervention provenance hold.
    """

    values: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] | None = None
    intervention_id: str = ""


def _cloud_key(*parts: Any) -> str:
    try:
        text = json.dumps(parts, sort_keys=True, default=str)
    except Exception:
        text = repr(parts)
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


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
        reasoner: Any | None = None,
        grounding: Any | None = None,
        cloud_mode: str | None = None,
    ) -> None:
        self.policy = policy or GhostPolicy.conservative_default()
        # Serialises event processing and cloud-result attachment.
        self._lock = threading.RLock()
        # last_result is per emitting thread (the bus delivers synchronously
        # on the emitter's thread), so concurrent callers each read their own
        # event's result; _results maps recent event ids to their results.
        self._tls = threading.local()
        self._results: OrderedDict[str, LoopResult] = OrderedDict()
        self._results_max = 256
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
        self.user_model = UserModel()
        self.standing_context = StandingContext()
        self.triggers = TriggerEngine()
        self.trigger_hits: list[TriggerHit] = []
        self.proposals = ProposalQueue()
        self.approvals = ApprovalQueue()
        self.budgets = BudgetTracker()
        self.temporal = TemporalContext()
        self.maturity = WorkflowMaturityTracker()
        self.governor = WorkflowAutonomyGovernor(self.maturity)
        self.computer = ComputerUseManager()
        self.computer.register(DelegatingComputerProvider(name="browser-structured", modality=ComputerModality.BROWSER))
        self.computer.register(
            DelegatingComputerProvider(name="desktop-accessibility", modality=ComputerModality.DESKTOP)
        )
        self.computer.register(DelegatingComputerProvider(name="vision-last-resort", modality=ComputerModality.VISION))
        self.computer_capability = computer_capability or ComputerCapability()

        # Optional cloud enhancements: Nemotron reasoning (Nebius Token
        # Factory) and Tavily web grounding in the UNDERSTAND phase. Both
        # default to None — the loop runs fully local unless the caller
        # attaches them (see stealth.nemotron_reasoning.build_cloud_enhancements).
        self._reasoner = reasoner
        self._grounding = grounding
        # PREDICT-phase Nemotron 3 Super consultation is gated: only when the
        # local Prediction Engine is unsure, and at most once per interval per
        # stream (Super is the heavy 120B model, so never per event).
        self.nemotron_predict_threshold = NEMOTRON_PREDICT_CONFIDENCE_THRESHOLD
        self.nemotron_predict_interval_s = _env_float(
            "GHOSTCHIMERA_NEMOTRON_PREDICT_INTERVAL_S", NEMOTRON_PREDICT_MIN_INTERVAL_S
        )
        self._nemotron_predict_last: OrderedDict[str, float] = OrderedDict()
        # Cloud calls run off the hot path by default ("async"): emit() returns
        # after the local stages and Nemotron results are attached to the
        # event's trace/intervention when they land. "sync" (ghost demo,
        # deterministic tests) runs them inline. GHOSTCHIMERA_NEMOTRON_MODE
        # overrides the default.
        mode = (cloud_mode or os.environ.get("GHOSTCHIMERA_NEMOTRON_MODE", "") or "async").strip().lower()
        self._cloud = CloudEnricher(mode="sync" if mode == "sync" else "async")

        self._experience: ExperienceState | None = None
        self._experience_stream: Any = None
        self._session_id = ""
        self._eve_interventions: dict[str, EveIntervention] = {}

        self.interventions: dict[str, Intervention] = {}
        # Per-session state is LRU-bounded (it used to gain one entry per
        # session id forever); GHOSTCHIMERA_STEALTH_MAX_SESSIONS overrides.
        self.max_sessions = max(1, int(_env_float("GHOSTCHIMERA_STEALTH_MAX_SESSIONS", 1000)))
        self._recent: OrderedDict[str, deque[str]] = OrderedDict()
        self._interventions_1h: deque[float] = deque()
        self.bus.subscribe("*", self._on_event)
        if self._own_runtime:
            self.runtime.start()
            self.runtime.register("prepare_context", self._handle_prepare_job)

    def close(self) -> None:
        self._cloud.close()
        if self._own_runtime:
            self.runtime.stop()

    @property
    def cloud(self) -> CloudEnricher:
        return self._cloud

    def wait_for_cloud(self, timeout: float | None = 30.0) -> bool:
        """Block until pending Nemotron calls have landed (tests, recording, shutdown)."""
        return self._cloud.wait_idle(timeout)

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

    def _session_history(self, stream: str) -> deque[str]:
        history = self._recent.get(stream)
        if history is None:
            history = deque(maxlen=20)
            self._recent[stream] = history
        self._recent.move_to_end(stream)
        while len(self._recent) > self.max_sessions:
            evicted, _ = self._recent.popitem(last=False)
            self._nemotron_predict_last.pop(evicted, None)
            self.learner.forget_stream(evicted)
        return history

    def emit_and_get(self, event: Event) -> LoopResult | None:
        """Emit ``event`` and return the LoopResult for *that* event.

        Safe under concurrency: unlike reading the shared ``last_result``
        after ``emit()``, another thread's event can never be returned.
        Returns None when the bus dropped the event as a duplicate.
        """
        with self._lock:
            delivered = self.bus.emit(event)
            return self._results.get(event.event_id) if delivered else None

    def result_for(self, event_id: str) -> LoopResult | None:
        with self._lock:
            return self._results.get(event_id)

    def _set_last(self, result: LoopResult | None) -> None:
        self._last = result
        self._tls.last = result

    def _set_last_result(self, event_id: str, result: LoopResult) -> None:
        with self._lock:
            self._set_last(result)
            self._results[event_id] = result
            while len(self._results) > self._results_max:
                self._results.popitem(last=False)

    def _on_event(self, event: Event) -> None:
        # One event at a time: the learners, engines and per-session dicts
        # below are not thread-safe, and the console calls emit() from
        # concurrent HTTP threads. Cloud calls run outside this lock (async).
        with self._lock:
            self._process_event(event)

    def _process_event(self, event: Event) -> None:
        # Never leave last_result pointing at a previous event: if anything
        # below raises, readers see None rather than the wrong decision.
        self._set_last(None)
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
        history = self._session_history(stream)
        history.append(event.event_type)
        self.learner.observe(stream, event.event_type)
        self.predictions.observe(event.event_type)
        self.user_model.observe_event(event)
        self.temporal.observe_event(event)
        fired = self.triggers.evaluate(event, self.policy.autonomy)
        self.trigger_hits.extend(fired)
        del self.trigger_hits[: max(0, len(self.trigger_hits) - 100)]
        for hit in fired:
            if self.budgets.spend(PROPOSAL_BUDGET, 1.0, now=event.timestamp):
                self.proposals.propose_from_hit(hit, now=event.timestamp)

        intent_hypotheses = self.intent_engine.update(event, self.graph, self.learner)
        hypothesis = self.learner.match(list(history))
        preds = self.predictions.predict(list(history), hypothesis)
        cloud_slot = _CloudSlot()
        # UNDERSTAND-phase cloud enrichment (best-effort; off the hot path).
        self._consult_nemotron_reasoner(event, hypothesis, preds, slot=cloud_slot)
        # PREDICT-phase cloud enrichment via Nemotron 3 Super (best-effort, gated).
        self._consult_nemotron_predict(event, stream, list(history), hypothesis, preds, slot=cloud_slot)
        web_context = self._consult_web_grounding(event)
        friction = self.friction_detector.observe(event, predicted_actions=[pred.action for pred in preds])
        self.attention.update_friction(friction.score)
        self._update_experience(event, perception_result, intent_hypotheses, friction)

        now = time.time()
        while self._interventions_1h and now - self._interventions_1h[0] > 3600:
            self._interventions_1h.popleft()

        primary_intent = self.intent_engine.get_primary()
        base_confidence = _payload_unit(
            event.payload,
            "confidence",
            hypothesis.confidence if hypothesis else event.confidence,
        )
        if base_confidence >= 0.31 and primary_intent and primary_intent.confidence > 0.7:
            base_confidence = max(base_confidence, primary_intent.confidence * 0.9)

        signals = EvaluationSignals(
            relevance=_payload_unit(event.payload, "relevance", 0.5 if hypothesis else 0.2),
            confidence=base_confidence,
            user_benefit=_payload_unit(event.payload, "benefit", 0.5),
            cost=_payload_unit(event.payload, "cost", 0.2),
            risk=_payload_unit(event.payload, "risk", 0.1),
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
        with self._lock:
            # Results already in (sync mode / cache hit) go in now; later
            # async results are written into this same dict when they land.
            trace.update(cloud_slot.values)
            cloud_slot.trace = trace
        if web_context:
            trace["web_grounding"] = web_context
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
            cloud_slot.intervention_id = intervention_id
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
        self._set_last_result(
            event.event_id,
            LoopResult(
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
            ),
        )

    def _minimal_update(self, event: Event, attention_signal: AttentionSignal) -> None:
        self.world.observe_event(event.event_type, {"actor": event.actor, **event.payload})
        self.graph.record_event(event)
        if self.store is not None:
            with suppress(Exception):
                self.store.record_event(event)

        stream = event.session_id or event.correlation_id or "global"
        history = self._session_history(stream)
        history.append(event.event_type)
        self.learner.observe(stream, event.event_type)
        self.predictions.observe(event.event_type)
        self.user_model.observe_event(event)
        self.temporal.observe_event(event)
        fired = self.triggers.evaluate(event, self.policy.autonomy)
        self.trigger_hits.extend(fired)
        del self.trigger_hits[: max(0, len(self.trigger_hits) - 100)]
        for hit in fired:
            if self.budgets.spend(PROPOSAL_BUDGET, 1.0, now=event.timestamp):
                self.proposals.propose_from_hit(hit, now=event.timestamp)

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
        self._set_last_result(
            event.event_id,
            LoopResult(
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
            ),
        )

    def _attach_cloud(self, slot: _CloudSlot, key: str, value: Any) -> None:
        """Attach a cloud result to its event's trace (and intervention) when it lands."""
        if not value:
            return
        with self._lock:
            slot.values[key] = value
            if slot.trace is None:
                return
            slot.trace[key] = value
            intervention = self.interventions.get(slot.intervention_id) if slot.intervention_id else None
        if intervention is not None and self.store is not None:
            with suppress(Exception):
                self.store.record_intervention(intervention)

    def _consult_nemotron_reasoner(
        self, event: Event, hypothesis: Any, preds: Any, *, slot: _CloudSlot | None = None
    ) -> dict[str, Any] | None:
        """UNDERSTAND via Nemotron 3 on Nebius Token Factory (best-effort).

        Identical events share one call (cache + in-flight de-dup), calls are
        budgeted per minute, and in async mode the call runs on the cloud
        worker so ``emit()`` never waits on the network. Returns the insight
        when it is available immediately (sync mode or cache hit).
        """
        reasoner = self._reasoner
        if reasoner is None or not getattr(reasoner, "available", False):
            return None
        if event.privacy_classification == "secret":
            return None
        slot = slot if slot is not None else _CloudSlot()
        # Keyed on the event itself: the same event re-emitted (bursts,
        # retries, polling producers) reuses one interpretation even while
        # the local hypothesis drifts.
        key = _cloud_key("understand", event.event_type, event.source, event.privacy_classification, event.payload)

        def call() -> dict[str, Any] | None:
            insight = reasoner.understand(event, hypothesis=hypothesis, predictions=preds)
            return insight if isinstance(insight, dict) else None

        def done(insight: Any) -> None:
            self._attach_cloud(slot, "nemotron", dict(insight) if isinstance(insight, dict) else None)

        status = self._cloud.request(key, call, done)
        if status == "budget":
            logger.debug("Nemotron UNDERSTAND skipped: per-minute call budget spent")
        value = slot.values.get("nemotron")
        return value if isinstance(value, dict) else None

    def _consult_nemotron_predict(
        self,
        event: Event,
        stream: str,
        history: list[str],
        hypothesis: Any,
        preds: Any,
        *,
        slot: _CloudSlot | None = None,
    ) -> list[dict[str, Any]] | None:
        """PREDICT via Nemotron 3 Super on Nebius Token Factory (best-effort).

        Consulted only when a reasoner is attached and available, the event is
        not ``secret``, the local Prediction Engine is unsure (no workflow- or
        experience-based prediction at ``nemotron_predict_threshold`` or above;
        base-rate guesses do not count), and the stream has not been consulted
        within ``nemotron_predict_interval_s``. Results are advisory: they land
        in the trace and never change the decision. Like UNDERSTAND, the call
        runs on the cloud worker in async mode.
        """
        reasoner = self._reasoner
        if reasoner is None or not getattr(reasoner, "available", False):
            return None
        predict_next = getattr(reasoner, "predict_next", None)
        if not callable(predict_next):
            return None
        if event.privacy_classification == "secret":
            return None
        # Base-rate guesses are a weak prior (the engine normalizes them, so a
        # single observed event type looks "confident"); only learned evidence
        # from a matched workflow or the experience graph counts as confident.
        learned_top = max(
            (
                float(getattr(p, "probability", 0.0) or 0.0)
                for p in (preds or [])
                if getattr(p, "basis", "") in ("workflow", "experience")
            ),
            default=0.0,
        )
        if learned_top >= self.nemotron_predict_threshold:
            return None
        now = float(event.timestamp or time.time())
        with self._lock:
            last = self._nemotron_predict_last.get(stream)
            if last is not None and now - last < self.nemotron_predict_interval_s:
                return None
            self._nemotron_predict_last[stream] = now
            self._nemotron_predict_last.move_to_end(stream)
            while len(self._nemotron_predict_last) > self.max_sessions:
                self._nemotron_predict_last.popitem(last=False)
        workflow = getattr(hypothesis, "name", "") if hypothesis is not None else ""
        history_text = "\n".join(history[-20:])
        slot = slot if slot is not None else _CloudSlot()

        def call() -> list[dict[str, Any]] | None:
            result = predict_next(history_text, hypothesis=str(workflow or ""))
            if not isinstance(result, list) or not result:
                return None
            return [dict(item) for item in result if isinstance(item, dict)] or None

        def done(result: Any) -> None:
            self._attach_cloud(slot, "nemotron_predictions", [dict(item) for item in result] if result else None)

        self._cloud.request(_cloud_key("predict", stream, history_text, workflow), call, done)
        value = slot.values.get("nemotron_predictions")
        return value if isinstance(value, list) else None

    def _consult_web_grounding(self, event: Event) -> dict[str, Any] | None:
        """UNDERSTAND-phase Tavily web grounding (best-effort).

        Skipped when a Nemotron reasoner is attached and available — the
        reasoner already grounds internally, so this avoids double web calls.
        """
        grounding = self._grounding
        if grounding is None or not getattr(grounding, "available", False):
            return None
        reasoner = self._reasoner
        if reasoner is not None and getattr(reasoner, "available", False):
            return None
        try:
            grounded = grounding.ground_event(event)
        except Exception as exc:
            logger.warning("Tavily web grounding failed: %s", exc)
            return None
        return grounded if isinstance(grounded, dict) else None

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
                action_digest=str(approval.get("action_digest") or ""),
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
        """Result of the last event emitted on the calling thread (else the last overall)."""
        tls = getattr(self, "_tls", None)
        if tls is not None and hasattr(tls, "last"):
            return tls.last
        return getattr(self, "_last", None)

    def get_standing_context(self, *, host: str = "", task: str = "", max_chars: int = 2000) -> str:
        """Render the current standing context for a host or task."""

        self.standing_context.refresh(self.user_model)
        return self.standing_context.render(host=host, task=task, max_chars=max_chars)

    def get_temporal_context(self, *, now: float | None = None, max_chars: int = 500) -> str:
        """Render the current temporal context (framing plus upcoming items)."""

        return self.temporal.render(now=now, max_chars=max_chars)

    def recent_trigger_hits(self, limit: int = 10) -> list[TriggerHit]:
        """Latest declarative trigger hits, newest last."""

        return self.trigger_hits[-max(0, limit) :]

    def submit_proposal(
        self,
        proposal_id: str,
        autonomy: AutonomyLevel = AutonomyLevel.OBSERVE,
        *,
        requested_by: str = "",
        now: float | None = None,
    ) -> ApprovalRequest | None:
        """Submit handoff: submit the proposal, then file its approval ask."""

        if not self.proposals.submit(proposal_id, autonomy, now=now):
            return None
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return None
        ask = self.approvals.request_for_proposal(proposal, requested_by=requested_by, now=now)
        if ask is not None:
            self.budgets.record(ATTENTION_BUDGET, 1.0)
        return ask

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
            approval = self.approvals.request_for_intervention(intervention)
            if approval is not None:
                self.budgets.record(ATTENTION_BUDGET, 1.0)
            return {
                "ok": True,
                "decision": "ask",
                "intervention_id": intervention.id,
                "approval_id": approval.id if approval is not None else "",
            }
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
