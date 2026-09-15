"""First-class User Model: layered, conservative identity for the user proxy.

The model answers "what would this user likely know, prefer, say, do, or
need?" without ever impersonating them. Four layers:

- ``identity`` — explicit facts only (name, email, role, organization).
- ``communication`` — tone, formality, verbosity, language, style hints.
- ``personality`` — inferred behavioral traits, always provisional.
- ``work`` — people, organizations, projects, repositories, documents.

Every inferred trait carries confidence, evidence, and timestamps; nothing
is treated as fact without confirmation. Explicit facts never decay.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .events import Event

LAYERS = ("identity", "communication", "personality", "work")

CONFIRMED_CONFIDENCE = 0.7
PROPOSAL_CONFIDENCE_CAP = 0.4
CONFIRM_STEP = 0.15
MAX_CONFIDENCE = 0.95
PRUNE_BELOW = 0.15
DECAY_HALF_LIFE_DAYS = 90.0

EXPLICIT_FACT_KEYS = ("name", "email", "role", "organization", "language", "timezone")


@dataclass
class TraitEvidence:
    """One observation backing a trait value."""

    source_event_id: str = ""
    observed_at: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"source_event_id": self.source_event_id, "observed_at": self.observed_at, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraitEvidence:
        data = data if isinstance(data, dict) else {}
        return cls(
            source_event_id=str(data.get("source_event_id", "")),
            observed_at=float(data.get("observed_at", 0.0)),
            note=str(data.get("note", "")),
        )


@dataclass
class UserTrait:
    """A single layered belief about the user with provenance."""

    key: str
    value: str
    layer: str = "personality"
    confidence: float = 0.0
    explicit: bool = False
    confirmations: int = 0
    contradictions: int = 0
    evidence: list[TraitEvidence] = field(default_factory=list)
    first_observed: float = field(default_factory=time.time)
    last_observed: float = field(default_factory=time.time)

    def confirmed(self) -> bool:
        return self.confidence >= CONFIRMED_CONFIDENCE

    def touch(self, confidence: float, evidence: TraitEvidence, *, now: float | None = None) -> None:
        moment = now if now is not None else time.time()
        self.last_observed = moment
        if self.explicit:
            self.evidence.append(evidence)
            return
        if confidence >= self.confidence or not self.evidence:
            self.evidence.append(evidence)
        self.confirmations += 1
        self.confidence = min(MAX_CONFIDENCE, PROPOSAL_CONFIDENCE_CAP + CONFIRM_STEP * self.confirmations)

    def contradict(self, evidence: TraitEvidence, *, now: float | None = None) -> None:
        moment = now if now is not None else time.time()
        self.last_observed = moment
        if self.explicit:
            return
        self.contradictions += 1
        self.confidence *= 0.7
        self.evidence.append(evidence)

    def decay(self, now: float, *, half_life_days: float = DECAY_HALF_LIFE_DAYS) -> bool:
        """Age an inferred trait; return True when it should be pruned."""

        if self.explicit:
            self.last_observed = now
            return False
        age_days = max(0.0, (now - self.last_observed) / 86400.0)
        if age_days > 0:
            self.confidence *= 0.5 ** (age_days / max(1.0, half_life_days))
            self.last_observed = now
        return self.confidence < PRUNE_BELOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "layer": self.layer,
            "confidence": round(self.confidence, 3),
            "explicit": self.explicit,
            "confirmations": self.confirmations,
            "contradictions": self.contradictions,
            "evidence": [item.to_dict() for item in self.evidence[-10:]],
            "first_observed": self.first_observed,
            "last_observed": self.last_observed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserTrait:
        data = data if isinstance(data, dict) else {}
        evidence = [TraitEvidence.from_dict(item) for item in data.get("evidence", []) if isinstance(item, dict)]
        return cls(
            key=str(data.get("key", "")),
            value=str(data.get("value", "")),
            layer=str(data.get("layer", "personality")),
            confidence=float(data.get("confidence", 0.0)),
            explicit=bool(data.get("explicit", False)),
            confirmations=int(data.get("confirmations", 0)),
            contradictions=int(data.get("contradictions", 0)),
            evidence=evidence,
            first_observed=float(data.get("first_observed", time.time())),
            last_observed=float(data.get("last_observed", time.time())),
        )


class UserModel:
    """Layered user model learned conservatively from normalized events."""

    def __init__(self) -> None:
        self._traits: dict[tuple[str, str], UserTrait] = {}
        self._relations: dict[str, dict[str, float]] = {}

    def get(self, layer: str, key: str) -> UserTrait | None:
        """Return the trait for a layer/key pair, if any."""

        return self._traits.get((layer, key))

    def confirmed_traits(self, layer: str = "") -> list[UserTrait]:
        """Traits at or above confirmation confidence, optionally filtered."""

        traits = [trait for trait in self._traits.values() if trait.confirmed()]
        if layer:
            traits = [trait for trait in traits if trait.layer == layer]
        return sorted(traits, key=lambda trait: trait.confidence, reverse=True)

    def set_fact(
        self,
        layer: str,
        key: str,
        value: str,
        *,
        source_event_id: str = "",
        now: float | None = None,
    ) -> UserTrait:
        """Record an explicit fact at full confidence; never decays."""

        moment = now if now is not None else time.time()
        trait = self._traits.get((layer, key))
        if trait is None:
            trait = UserTrait(key=key, value=value, layer=layer, first_observed=moment)
            self._traits[(layer, key)] = trait
        trait.value = value
        trait.explicit = True
        trait.confidence = 1.0
        trait.last_observed = moment
        trait.evidence.append(TraitEvidence(source_event_id=source_event_id, observed_at=moment, note="explicit"))
        return trait

    def propose_trait(
        self,
        layer: str,
        key: str,
        value: str,
        *,
        confidence: float = 0.4,
        source_event_id: str = "",
        note: str = "",
        now: float | None = None,
    ) -> UserTrait:
        """Propose or confirm an inferred trait from one observation."""

        if layer not in LAYERS:
            raise ValueError(f"Unknown user-model layer: {layer}")
        moment = now if now is not None else time.time()
        evidence = TraitEvidence(source_event_id=source_event_id, observed_at=moment, note=note)
        trait = self._traits.get((layer, key))
        if trait is None:
            trait = UserTrait(
                key=key,
                value=value,
                layer=layer,
                confidence=min(max(0.0, confidence), PROPOSAL_CONFIDENCE_CAP),
                first_observed=moment,
                last_observed=moment,
                evidence=[evidence],
            )
            self._traits[(layer, key)] = trait
            return trait
        if trait.explicit or trait.value == value:
            trait.touch(confidence, evidence, now=moment)
            return trait
        if not evidence.note:
            evidence.note = f"challenger:{value}"
        trait.contradict(evidence, now=moment)
        challenger_hits = sum(1 for item in trait.evidence if item.note == f"challenger:{value}")
        if trait.contradictions >= 3 and challenger_hits >= 3:
            trait.value = value
            trait.contradictions = 0
            trait.confirmations = 1
            trait.confidence = min(MAX_CONFIDENCE, PROPOSAL_CONFIDENCE_CAP + CONFIRM_STEP)
        return trait

    def note_relation(self, source: str, relation: str, target: str, *, weight: float = 1.0) -> None:
        """Record a weighted work-graph edge such as person works-on project."""

        if not source or not relation or not target:
            return
        key = f"{source}\x00{relation}"
        bucket = self._relations.setdefault(key, {})
        bucket[target] = min(99.0, bucket.get(target, 0.0) + max(0.0, weight))

    def relations(self, source: str = "", relation: str = "") -> dict[str, dict[str, float]]:
        """Work-graph edges, optionally filtered by source and relation."""

        out: dict[str, dict[str, float]] = {}
        for key, bucket in self._relations.items():
            node, _, edge = key.partition("\x00")
            if source and node != source:
                continue
            if relation and edge != relation:
                continue
            out[f"{node}\x00{edge}"] = dict(bucket)
        return out

    def observe_event(self, event: Event) -> None:
        """Fold one normalized event into identity facts and the work graph."""

        moment = event.timestamp or time.time()
        profile = event.payload.get("profile") if isinstance(event.payload.get("profile"), dict) else {}
        user_block = event.payload.get("user") if isinstance(event.payload.get("user"), dict) else {}
        for key in EXPLICIT_FACT_KEYS:
            value = profile.get(key, user_block.get(key, ""))
            if isinstance(value, str) and value.strip():
                self.set_fact("identity", key, value.strip(), source_event_id=event.event_id, now=moment)
        actor = event.actor.strip()
        project = str(event.payload.get("project") or event.payload.get("repository") or "").strip()
        if actor:
            self.note_relation(f"person:{actor}", "participated_in", f"event:{event.event_type}")
            if project:
                self.note_relation(f"person:{actor}", "works_on", f"project:{project}")
        if project:
            self.note_relation(f"event:{event.event_type}", "concerns", f"project:{project}")

    def decay(self, now: float | None = None, *, half_life_days: float = DECAY_HALF_LIFE_DAYS) -> int:
        """Age inferred traits and prune the exhausted; return pruned count."""

        moment = now if now is not None else time.time()
        pruned = [key for key, trait in self._traits.items() if trait.decay(moment, half_life_days=half_life_days)]
        for key in pruned:
            del self._traits[key]
        return len(pruned)

    def snapshot(self) -> dict[str, Any]:
        """Full serializable model state."""

        layers: dict[str, list[dict[str, Any]]] = {layer: [] for layer in LAYERS}
        for trait in self._traits.values():
            layers.setdefault(trait.layer, []).append(trait.to_dict())
        for entries in layers.values():
            entries.sort(key=lambda item: item["confidence"], reverse=True)
        return {"layers": layers, "relations": {key: dict(bucket) for key, bucket in self._relations.items()}}

    def save(self, path: str | Path) -> None:
        """Persist the model to a JSON file (best effort)."""

        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self.snapshot()), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def load(cls, path: str | Path) -> UserModel:
        """Load a persisted model; return an empty model when unavailable."""

        model = cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return model
        if not isinstance(data, dict):
            return model
        for layer, entries in (data.get("layers") or {}).items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                try:
                    trait = UserTrait.from_dict(entry)
                except (TypeError, ValueError):
                    continue
                if trait.key:
                    model._traits[(trait.layer or layer, trait.key)] = trait
        relations = data.get("relations", {})
        if isinstance(relations, dict):
            for key, bucket in relations.items():
                if isinstance(bucket, dict):
                    model._relations[str(key)] = {str(k): float(v) for k, v in bucket.items()}
        return model

    def standing_block(self, *, host: str = "", task: str = "", max_chars: int = 2000) -> str:
        """Render a compact standing-context block for a host or task."""

        lines = ["# Standing context"]
        if host or task:
            lines.append(f"host={host or '-'} task={task or '-'}")
        identity = self.confirmed_traits("identity") + [
            trait for trait in self._traits.values() if trait.layer == "identity" and trait.explicit
        ]
        seen: set[str] = set()
        for trait in identity:
            if trait.key in seen:
                continue
            seen.add(trait.key)
            lines.append(f"identity.{trait.key}: {trait.value}")
        for trait in self.confirmed_traits("communication"):
            lines.append(f"communication.{trait.key}: {trait.value}")
        for trait in self.confirmed_traits("personality"):
            lines.append(f"personality.{trait.key}: {trait.value} (confidence {trait.confidence:.2f})")
        block = "\n".join(lines).strip()
        marker = "\n[...truncated...]"
        budget = max(0, max_chars)
        if len(block) > budget:
            if budget <= len(marker):
                return block[:budget]
            block = block[: budget - len(marker)].rstrip() + marker
        return block


__all__ = [
    "LAYERS",
    "UserModel",
    "UserTrait",
    "TraitEvidence",
    "CONFIRMED_CONFIDENCE",
]
