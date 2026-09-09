"""Stealth Hooks: event trigger + contextual inference + policy +
asynchronous intervention + outcome feedback.

Two definition surfaces (programmatic ``ghost_on`` and declarative
``define_hook`` dicts, e.g. loaded from YAML) compile to the same
``StealthHook`` engine object; the engine never depends on either syntax.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .events import Event
from .intervention import Intervention, InterventionState
from .stealth_policy import Decision, EvaluationSignals, StealthEvaluator

Action = Callable[[Event, dict[str, Any]], dict[str, Any] | None]


@dataclass
class StealthHook:
    name: str
    event_type: str  # exact type or "prefix.*"
    workflow: str = ""
    min_confidence: float = 0.8
    actions: list[Action] = field(default_factory=list)
    inject_into: str = "next_agent_session"
    autonomy_mode: str = "prepare_only"
    outcome_feedback: dict[str, float] = field(default_factory=dict)

    def matches(self, event: Event) -> bool:
        if self.event_type.endswith(".*"):
            return event.event_type.startswith(self.event_type[:-2])
        return event.event_type == self.event_type

    def run(self, event: Event, evaluator: StealthEvaluator) -> Intervention | None:
        signals = EvaluationSignals(
            relevance=float(event.payload.get("relevance", 0.5)),
            confidence=float(event.payload.get("confidence", event.confidence)),
            user_benefit=float(event.payload.get("benefit", 0.5)),
            cost=float(event.payload.get("cost", 0.2)),
            risk=float(event.payload.get("risk", 0.1)),
            external_side_effect=self.autonomy_mode not in ("prepare_only", "observe_only"),
            privacy_ok=event.privacy_classification != "secret",
        )
        decision, trace = evaluator.evaluate(signals)
        if decision in (Decision.NONE, Decision.STORE):
            return None
        if decision == Decision.ASK:
            return None  # approval surface arrives with Host Adapters (Phase 5)
        intervention = Intervention(
            trigger_event_id=event.event_id,
            workflow=self.workflow or "unknown",
            confidence=signals.confidence,
            reason=f"hook={self.name} decision={decision} score={trace.get('score')}",
            provenance={"hook": self.name, "trace": trace, "inject_into": self.inject_into},
        )
        intervention.transition(InterventionState.QUEUED, note="hook matched")
        context: dict[str, Any] = {}
        for action in self.actions:
            try:
                result = action(event, context)
            except Exception:
                continue
            if result:
                context.update(result)
        intervention.context = context
        return intervention

    def observe_outcome(self, outcome: str, *, useful: bool) -> None:
        adj = 0.02 if useful else -0.05
        key = self.workflow or self.name
        self.outcome_feedback[key] = round(self.outcome_feedback.get(key, 0.0) + adj, 4)


class StealthHookRegistry:
    def __init__(self, evaluator: StealthEvaluator | None = None) -> None:
        self.evaluator = evaluator or StealthEvaluator()
        self._hooks: dict[str, StealthHook] = {}

    def register(self, hook: StealthHook) -> None:
        self._hooks[hook.name] = hook

    def on(self, event_type: str, name: str = "", **kwargs: Any) -> Callable[[Action], Action]:
        hook = StealthHook(name=name or event_type, event_type=event_type, **kwargs)

        def decorator(fn: Action) -> Action:
            hook.actions.append(fn)
            self._hooks[hook.name] = hook
            return fn

        self._hooks.setdefault(hook.name, hook)
        return decorator

    def handle(self, event: Event) -> list[Intervention]:
        out = []
        for hook in self._hooks.values():
            if hook.matches(event) and event.confidence >= hook.min_confidence:
                intervention = hook.run(event, self.evaluator)
                if intervention is not None:
                    out.append(intervention)
        return out

    def __len__(self) -> int:
        return len(self._hooks)


def ghost_on(registry: StealthHookRegistry, event_type: str, **kwargs: Any) -> Callable[[Action], Action]:
    """Programmatic API: ``ghost_on(registry, "email.received")(my_action)``."""
    return registry.on(event_type, **kwargs)


def define_hook(spec: dict[str, Any]) -> StealthHook:
    """Declarative API: build a hook from a YAML/JSON-compatible dict."""
    hook_cfg = spec.get("hook", spec)
    when = hook_cfg.get("when", {})
    detect = hook_cfg.get("detect", {})
    threshold = str(detect.get("confidence", ">0.8")).lstrip(">").strip()
    return StealthHook(
        name=str(hook_cfg.get("name", "unnamed")),
        event_type=str(when.get("event", "*")),
        workflow=str(detect.get("workflow", "")),
        min_confidence=float(threshold or 0.8),
        inject_into=str(hook_cfg.get("inject", {}).get("into", "next_agent_session")),
        autonomy_mode=str(hook_cfg.get("autonomy", {}).get("mode", "prepare_only")),
    )


__all__ = ["Action", "StealthHook", "StealthHookRegistry", "define_hook", "ghost_on"]
