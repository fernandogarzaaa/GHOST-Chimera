"""Stealth Loop: the event loop everything else exists to make intelligent.

EVENT -> NORMALIZE -> UPDATE STATE -> RECALL EXPERIENCE -> MATCH
WORKFLOW -> PREDICT -> DECIDE -> PREPARE / INJECT / ACT -> OBSERVE
OUTCOME -> LEARN. Tiered: cheap deterministic stages run inline; only
high-value inference leaves the hot path (via BackgroundRuntime).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .context import ContextFabric, InMemoryRetriever, InjectionEnvelope
from .events import Event
from .event_bus import EventBus
from .experience import ExperienceGraph
from .intervention import Intervention, InterventionOutcome, InterventionState
from .prediction import PredictionEngine
from .runtime import BackgroundRuntime
from .stealth_policy import Decision, EvaluationSignals, GhostPolicy, StealthEvaluator
from .world_state import WorldState
from .workflow_learner import WorkflowLearner


@dataclass
class LoopResult:
    event_id: str
    decision: Decision
    intervention_id: str = ""
    predictions: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


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
        self.store = store  # optional StealthStore journal; best-effort, never blocking
        self._own_runtime = own_runtime and runtime is None
        self.interventions: dict[str, Intervention] = {}
        self._recent: dict[str, deque[str]] = {}
        self._interventions_1h: deque[float] = deque()
        self.bus.subscribe("*", self._on_event)
        if self._own_runtime:
            self.runtime.start()
            self.runtime.register("prepare_context", self._handle_prepare_job)

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        if self._own_runtime:
            self.runtime.stop()

    # -- hot path ----------------------------------------------------------
    def emit(self, event: Event) -> bool:
        return self.bus.emit(event)

    def _on_event(self, event: Event) -> None:
        # 1-3. state + experience + workflow observation (all cheap).
        self.world.observe_event(event.event_type, {"actor": event.actor, **event.payload})
        self.graph.record_event(event)
        if self.store is not None:
            try:
                self.store.record_event(event)
            except Exception:
                pass  # durability is best-effort; memory stays authoritative
        stream = event.session_id or event.correlation_id or "global"
        history = self._recent.setdefault(stream, deque(maxlen=20))
        history.append(event.event_type)
        self.learner.observe(stream, event.event_type)
        self.predictions.observe(event.event_type)

        # 4-5. match + predict.
        hypothesis = self.learner.match(list(history))
        preds = self.predictions.predict(list(history), hypothesis)
        recent_pred = next((p.probability for p in preds if not p.action.endswith(":none")), 0.0)

        # 6. decide (conservative; silence is success).
        now = time.time()
        while self._interventions_1h and now - self._interventions_1h[0] > 3600:
            self._interventions_1h.popleft()
        signals = EvaluationSignals(
            relevance=float(event.payload.get("relevance", 0.5 if hypothesis else 0.2)),
            confidence=float(event.payload.get("confidence", hypothesis.confidence if hypothesis else event.confidence)),
            user_benefit=float(event.payload.get("benefit", 0.5)),
            cost=float(event.payload.get("cost", 0.2)),
            risk=float(event.payload.get("risk", 0.1)),
            external_side_effect=False,  # the loop only ever prepares/injects
            privacy_ok=event.privacy_classification != "secret",
            intervention_count_1h=len(self._interventions_1h),
        )
        decision, trace = self.evaluator.evaluate(signals)

        # 7. prepare / inject (async where possible).
        intervention_id = ""
        if decision in (Decision.PREPARE, Decision.INJECT):
            intervention = Intervention(
                trigger_event_id=event.event_id,
                workflow=hypothesis.name if hypothesis else "unknown",
                confidence=signals.confidence,
                reason=f"loop decision={decision} score={trace.get('score')}",
                provenance={"trace": trace, "predictions": [p.action for p in preds[:3]]},
            )
            intervention.transition(InterventionState.QUEUED)
            self.interventions[intervention.id] = intervention
            self.graph.record_intervention(intervention.workflow, intervention.id)
            if self.store is not None:
                try:
                    self.store.record_intervention(intervention)
                except Exception:
                    pass
            self._interventions_1h.append(now)
            intervention_id = intervention.id
            if decision == Decision.PREPARE and self._own_runtime:
                self.runtime.submit("prepare_context", {"intervention_id": intervention.id,
                                                        "event": event.to_dict()})
            else:
                self._prepare(intervention, event)
        self._last = LoopResult(event_id=event.event_id, decision=decision,
                                intervention_id=intervention_id,
                                predictions=[{"action": p.action, "p": p.probability} for p in preds[:3]],
                                trace=trace)

    # -- background job ------------------------------------------------------
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
        package = self.fabric.assemble(event, workflow=intervention.workflow,
                                       confidence=intervention.confidence)
        intervention.context = package.to_dict()
        intervention.transition(InterventionState.READY)
        return package

    # -- host surface ----------------------------------------------------------
    def inject(self, intervention_id: str, host: str) -> str:
        """Render the prepared package for a host adapter. Returns markdown."""
        intervention = self.interventions[intervention_id]
        package_dict = intervention.context
        from .context import ContextItem, ContextPackage

        package = ContextPackage(
            reason=str(package_dict.get("reason", "")),
            confidence=float(package_dict.get("confidence", 0.0)),
            workflow=str(package_dict.get("workflow", "")),
            items=[ContextItem(source=i["source"], kind=i["kind"], text=i["text"],
                               score=i.get("score", 0.0), confidence=i.get("confidence", 0.0),
                               provenance=i.get("provenance", {}),
                               privacy_class=i.get("privacy_class", "internal"))
                   for i in package_dict.get("items", [])],
            warnings=list(package_dict.get("warnings", [])),
            provenance=dict(package_dict.get("provenance", {})),
        )
        package.tokens = int(package_dict.get("tokens", 0))
        intervention.transition(InterventionState.INJECTED)
        return InjectionEnvelope(package=package, host=host).render_markdown()

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
        useful = outcome in (InterventionOutcome.USEFUL, InterventionOutcome.SUCCESSFUL)
        self.graph.record_outcome(intervention.workflow, useful=useful)
        self.learner.observe_outcome(intervention.workflow, useful=useful)
        if self.store is not None:
            try:
                self.store.record_intervention(intervention)
                self.store.record_outcome(intervention.id, intervention.workflow, str(outcome))
            except Exception:
                pass

    def sync_workflows(self) -> int:
        """Persist learned hypotheses (consolidation pass; call periodically)."""
        if self.store is None:
            return 0
        count = 0
        for hypothesis in self.learner.hypotheses():
            try:
                self.store.upsert_workflow(hypothesis.name, list(hypothesis.pattern),
                                           hypothesis.support, hypothesis.confidence,
                                           explicit=hypothesis.explicit)
                count += 1
            except Exception:
                continue
        return count

    @property
    def last_result(self) -> LoopResult | None:
        return getattr(self, "_last", None)

    # -- stealth agent output (BPO/VA contract) -------------------------------
    def handle_agent_output(
        self,
        text: str,
        *,
        connection_map: dict[str, str] | None = None,
        executor: Any = None,
    ) -> dict[str, Any]:
        """Parse a stealth agent's JSON output, gate it through policy, and
        draft / queue / execute accordingly.

        - NONE/STORE  -> silence (returns ok with no intervention).
        - PREPARE     -> draft intervention READY for human review.
        - ASK         -> intervention left QUEUED with needs_approval flag.
        - ACT         -> executes via *executor* (Nango-backed); without an
          executor the action safely downgrades to ASK.
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
            provenance={"event_summary": action.event_summary,
                        "actions": action.actions},
        )
        intervention.transition(InterventionState.QUEUED)
        self.interventions[intervention.id] = intervention
        self.graph.record_intervention(intervention.workflow, intervention.id)
        if self.store is not None:
            try:
                self.store.record_intervention(intervention)
            except Exception:
                pass
        if decision == Decision.ASK and executor is None:
            intervention.provenance["needs_approval"] = True
            return {"ok": True, "decision": "ask", "intervention_id": intervention.id}
        if decision in (Decision.PREPARE, Decision.ASK):
            intervention.transition(InterventionState.PREPARING)
            intervention.context = {"draft": action.actions, "summary": action.event_summary}
            intervention.transition(InterventionState.READY)
            return {"ok": True, "decision": str(decision).lower()
                    if decision == Decision.PREPARE else "ask",
                    "intervention_id": intervention.id}
        # ACT with an executor: external side effects, one action at a time.
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
                executed.append({"action": item, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        intervention.context = {"executed": executed}
        intervention.transition(InterventionState.CONSUMED)
        intervention.record_outcome(InterventionOutcome.SUCCESSFUL if not failed else InterventionOutcome.FAILED)
        useful = not failed
        self.graph.record_outcome(intervention.workflow, useful=useful)
        self.learner.observe_outcome(intervention.workflow, useful=useful)
        if self.store is not None:
            try:
                self.store.record_intervention(intervention)
                self.store.record_outcome(intervention.id, intervention.workflow,
                                          str(intervention.outcome))
            except Exception:
                pass
        return {"ok": True, "decision": "act", "intervention_id": intervention.id,
                "executed": executed}


__all__ = ["LoopResult", "StealthLoop"]
