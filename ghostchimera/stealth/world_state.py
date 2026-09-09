"""WorldState: temporal representation of what is currently happening.

People, projects, orgs, documents, repos, meetings, tasks, commitments,
relationships, current activities. Every assertion carries bi-temporal
metadata (valid_from/valid_to/recorded_at) + confidence + provenance,
mirroring the existing ``TemporalGraphStore`` semantics so the graph
can later back this projection without replacement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityAssertion:
    subject: str
    predicate: str
    object: str
    valid_from: float = field(default_factory=time.time)
    valid_to: float | None = None
    recorded_at: float = field(default_factory=time.time)
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)
    expired: bool = False


class WorldState:
    """In-memory temporal projection. Durable backing comes in Phase 2."""

    def __init__(self) -> None:
        self._assertions: list[EntityAssertion] = []
        self._current_activity: dict[str, Any] = {}

    def assert_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        *,
        confidence: float = 1.0,
        provenance: dict[str, Any] | None = None,
        valid_from: float | None = None,
        valid_to: float | None = None,
    ) -> EntityAssertion:
        assertion = EntityAssertion(
            subject=subject,
            predicate=predicate,
            object=obj,
            valid_from=valid_from if valid_from is not None else time.time(),
            valid_to=valid_to,
            confidence=max(0.0, min(1.0, confidence)),
            provenance=dict(provenance or {}),
        )
        self._assertions.append(assertion)
        return assertion

    def retract(self, subject: str, predicate: str, obj: str) -> int:
        """Expire matching assertions (belief revision, never delete)."""
        now = time.time()
        count = 0
        for assertion in self._assertions:
            if assertion.subject == subject and assertion.predicate == predicate and assertion.object == obj:
                if not assertion.expired:
                    assertion.expired = True
                    assertion.valid_to = now
                    count += 1
        return count

    def active_facts(
        self, subject: str | None = None, predicate: str | None = None, *, at: float | None = None
    ) -> list[EntityAssertion]:
        now = at if at is not None else time.time()
        out = []
        for assertion in self._assertions:
            if assertion.expired:
                continue
            if assertion.valid_from > now:
                continue
            if assertion.valid_to is not None and assertion.valid_to <= now:
                continue
            if subject is not None and assertion.subject != subject:
                continue
            if predicate is not None and assertion.predicate != predicate:
                continue
            out.append(assertion)
        return out

    def neighbors(self, subject: str) -> list[EntityAssertion]:
        return self.active_facts(subject=subject)

    def set_activity(self, key: str, value: Any) -> None:
        self._current_activity[key] = value

    def activity(self) -> dict[str, Any]:
        return dict(self._current_activity)

    def observe_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Minimal world-state updater fed by the Event Fabric.

        Heuristic only: records actor/entity mentions so workflow
        matching has state to work with before the Experience Graph lands.
        """
        actor = str(payload.get("actor") or payload.get("sender") or "")
        if actor:
            self.assert_fact(
                actor, "observed_in", event_type, confidence=0.6, provenance={"via": "world_state.observe_event"}
            )
        project = str(payload.get("project") or payload.get("repository") or "")
        if project and actor:
            self.assert_fact(
                actor, "works_on", project, confidence=0.6, provenance={"via": "world_state.observe_event"}
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "facts": [
                {
                    "subject": a.subject,
                    "predicate": a.predicate,
                    "object": a.object,
                    "confidence": a.confidence,
                    "valid_from": a.valid_from,
                    "valid_to": a.valid_to,
                }
                for a in self.active_facts()
            ],
            "activity": self.activity(),
        }


__all__ = ["EntityAssertion", "WorldState"]
