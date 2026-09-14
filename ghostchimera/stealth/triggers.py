"""Trigger Engine: declarative event-condition-action rules.

Hooks map event types to interventions through the evaluator. Triggers are
the lighter, user-facing tier: named rules with payload conditions,
autonomy gates, and cooldowns that fire declarative action descriptors.
Evaluation is pure observation — a hit records *what should happen*, never
acting directly — so registering triggers cannot change loop decisions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .events import Event
from .stealth_policy import AutonomyLevel

CONDITION_OPS = ("eq", "ne", "contains", "in", "gt", "gte", "lt", "lte", "exists")

_MISSING = object()

TOP_LEVEL_FIELDS = ("event_type", "source", "actor", "session_id", "confidence", "timestamp")


def _resolve(event: Event, path: str) -> Any:
    if not path:
        return _MISSING
    head, _, rest = path.partition(".")
    if head in TOP_LEVEL_FIELDS:
        current: Any = getattr(event, head, _MISSING)
    elif head == "payload":
        current = event.payload
    else:
        current = event.payload.get(head, _MISSING)
    if rest and current is not _MISSING and isinstance(current, dict):
        node: Any = current
        for part in rest.split("."):
            if not isinstance(node, dict) or part not in node:
                return _MISSING
            node = node[part]
        return node
    if rest:
        return _MISSING
    return current


@dataclass
class TriggerCondition:
    """One field predicate over an event."""

    field: str = ""
    op: str = "eq"
    value: Any = None

    def matches(self, event: Event) -> bool:
        actual = _resolve(event, self.field)
        op = self.op
        if op == "exists":
            return actual is not _MISSING
        if actual is _MISSING:
            return op == "ne"
        try:
            if op == "eq":
                return bool(actual == self.value)
            if op == "ne":
                return bool(actual != self.value)
            if op == "contains":
                return self.value in actual
            if op == "in":
                return actual in self.value
            if op == "gt":
                return bool(actual > self.value)
            if op == "gte":
                return bool(actual >= self.value)
            if op == "lt":
                return bool(actual < self.value)
            if op == "lte":
                return bool(actual <= self.value)
        except TypeError:
            return False
        return False

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerCondition:
        data = data if isinstance(data, dict) else {}
        op = str(data.get("op", "eq"))
        return cls(field=str(data.get("field", "")), op=op if op in CONDITION_OPS else "eq", value=data.get("value"))


@dataclass
class Trigger:
    """A named event-condition-action rule."""

    name: str
    event_type: str = "*"  # exact type, "prefix.*", or "*"
    conditions: list[TriggerCondition] = field(default_factory=list)
    min_autonomy: AutonomyLevel = AutonomyLevel.OBSERVE
    cooldown_s: float = 0.0
    enabled: bool = True
    action: dict[str, Any] = field(default_factory=dict)
    last_fired: float = 0.0

    def matches_event(self, event: Event) -> bool:
        if self.event_type in ("", "*"):
            return True
        if self.event_type.endswith(".*"):
            return event.event_type.startswith(self.event_type[:-2])
        return event.event_type == self.event_type

    def should_fire(self, event: Event, autonomy: AutonomyLevel = AutonomyLevel.OBSERVE) -> bool:
        """Pure check: enabled, type, autonomy gate, conditions, cooldown."""

        if not self.enabled:
            return False
        if not self.matches_event(event):
            return False
        if autonomy < self.min_autonomy:
            return False
        if not all(condition.matches(event) for condition in self.conditions):
            return False
        return (event.timestamp - self.last_fired) >= max(0.0, self.cooldown_s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event_type": self.event_type,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "min_autonomy": self.min_autonomy.name.lower(),
            "cooldown_s": self.cooldown_s,
            "enabled": self.enabled,
            "action": dict(self.action),
            "last_fired": self.last_fired,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trigger:
        data = data if isinstance(data, dict) else {}
        level = str(data.get("min_autonomy", "observe")).upper()
        return cls(
            name=str(data.get("name", "unnamed")),
            event_type=str(data.get("event_type", "*")),
            conditions=[TriggerCondition.from_dict(item) for item in data.get("conditions", []) or []],
            min_autonomy=AutonomyLevel[level] if level in AutonomyLevel.__members__ else AutonomyLevel.OBSERVE,
            cooldown_s=max(0.0, float(data.get("cooldown_s", 0.0) or 0.0)),
            enabled=bool(data.get("enabled", True)),
            action=dict(data.get("action", {}) or {}),
            last_fired=float(data.get("last_fired", 0.0) or 0.0),
        )


@dataclass
class TriggerHit:
    """Record of one trigger firing."""

    trigger_name: str
    event_id: str
    action: dict[str, Any] = field(default_factory=dict)
    fired_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_name": self.trigger_name,
            "event_id": self.event_id,
            "action": dict(self.action),
            "fired_at": self.fired_at,
        }


def define_trigger(spec: dict[str, Any]) -> Trigger:
    """Declarative API: build a trigger from a YAML/JSON-compatible dict."""

    cfg = spec.get("trigger", spec) if isinstance(spec, dict) else {}
    when = cfg.get("when", {}) if isinstance(cfg.get("when", {}), dict) else {}
    conditions = cfg.get("conditions", when.get("conditions", [])) or []
    return Trigger.from_dict(
        {
            "name": cfg.get("name", "unnamed"),
            "event_type": when.get("event", cfg.get("event_type", "*")),
            "conditions": conditions,
            "min_autonomy": cfg.get("min_autonomy", when.get("autonomy", "observe")),
            "cooldown_s": cfg.get("cooldown_s", when.get("cooldown_s", 0.0)),
            "enabled": cfg.get("enabled", True),
            "action": cfg.get("action", cfg.get("do", {})),
        }
    )


class TriggerEngine:
    """Registry plus pure evaluation for declarative triggers."""

    def __init__(self, *, max_hits: int = 100) -> None:
        self._triggers: dict[str, Trigger] = {}
        self.hits: deque[TriggerHit] = deque(maxlen=max(1, max_hits))

    def register(self, trigger: Trigger) -> None:
        self._triggers[trigger.name] = trigger

    def define(self, spec: dict[str, Any]) -> Trigger:
        trigger = define_trigger(spec)
        self.register(trigger)
        return trigger

    def unregister(self, name: str) -> bool:
        return self._triggers.pop(name, None) is not None

    def enable(self, name: str) -> bool:
        trigger = self._triggers.get(name)
        if trigger is None:
            return False
        trigger.enabled = True
        return True

    def disable(self, name: str) -> bool:
        trigger = self._triggers.get(name)
        if trigger is None:
            return False
        trigger.enabled = False
        return True

    def get(self, name: str) -> Trigger | None:
        return self._triggers.get(name)

    def list(self) -> list[Trigger]:
        return list(self._triggers.values())

    def __len__(self) -> int:
        return len(self._triggers)

    def evaluate(self, event: Event, autonomy: AutonomyLevel = AutonomyLevel.OBSERVE) -> list[TriggerHit]:
        """Fire matching triggers; records hits, never acts."""

        fired: list[TriggerHit] = []
        for trigger in self._triggers.values():
            if not trigger.should_fire(event, autonomy):
                continue
            trigger.last_fired = event.timestamp
            hit = TriggerHit(
                trigger_name=trigger.name,
                event_id=event.event_id,
                action=dict(trigger.action),
                fired_at=event.timestamp,
            )
            self.hits.append(hit)
            fired.append(hit)
        return fired

    def recent_hits(self, limit: int = 10) -> list[TriggerHit]:
        return list(self.hits)[-max(0, limit) :]

    def to_dict(self) -> dict[str, Any]:
        return {"triggers": [trigger.to_dict() for trigger in self._triggers.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerEngine:
        engine = cls()
        for item in (data or {}).get("triggers", []) or []:
            engine.register(Trigger.from_dict(item))
        return engine


__all__ = [
    "CONDITION_OPS",
    "Trigger",
    "TriggerCondition",
    "TriggerEngine",
    "TriggerHit",
    "define_trigger",
]
