"""Persistent operator-facing workspace state.

The store makes the existing workspace primitives inspectable through CLI and
console surfaces. It tracks explicit evidence, reflections, goals, and
uncertainty; it does not imply subjective consciousness.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from ..config import GhostChimeraConfig
from .workspace import AttentionController, ReflectionEngine, SelfModel, WorkingMemory

WORKSPACE_STATE_FILENAME = "operator_workspace.json"

DEFAULT_CAPABILITIES: dict[str, str] = {
    "chimera_pilot": "Compiles local objectives into policy-gated task specs and backend executions.",
    "local_memory": "Retrieves local SQLite-backed evidence with source citations.",
    "autonomy_profiles": "Runs adjustable autonomy jobs under explicit profile and execution gates.",
    "minimind_architecture": "Inspects embedded MiniMind-compatible architecture contracts without bundled weights.",
    "release_validation": "Reports the beta release gate commands and built-in eval suites.",
}

DEFAULT_LIMITS: dict[str, str] = {
    "no_subjective_consciousness": "Workspace state is an inspectable runtime model, not proof of subjective experience.",
    "no_untrusted_host_execution": "Untrusted prompts, repositories, and code still require external isolation and review.",
    "optional_model_weights": "Local model inference requires operator-provided weights and optional dependencies.",
    "beta_security_review": "Commercial or high-impact deployment requires additional hardening and review.",
}

DEFAULT_GOALS: dict[str, str] = {
    "ship_safe_beta": "Keep Ghost Chimera useful for local operators while preserving conservative policy gates.",
    "truthful_positioning": "Expose capability state without AGI, SGI, or consciousness claims.",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_confidence(value: Any, *, default: float = 0.5) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


class OperatorWorkspaceStore:
    """Durable state wrapper around the consciousness-inspired primitives."""

    def __init__(self, *, state_dir: str | Path | None = None, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = Path(path).expanduser()
            self.state_dir = self.path.parent
        else:
            self.state_dir = Path(state_dir).expanduser() if state_dir else GhostChimeraConfig.from_env().state_dir
            self.path = self.state_dir / WORKSPACE_STATE_FILENAME
        self.load_error = ""
        self.self_model, self.memory = self._load_or_seed()

    def snapshot(self) -> dict[str, Any]:
        """Return the inspectable workspace state used by CLI and console."""

        memory_snapshot = self.memory.snapshot()
        attention = self._rank_attention(memory_snapshot)
        return {
            "ok": True,
            "state_file": str(self.path),
            "updated_at": _now(),
            "load_error": self.load_error,
            "self_model": self.self_model.snapshot(),
            "working_memory": memory_snapshot,
            "attention": attention,
            "uncertainty": self._uncertainty(memory_snapshot),
            "positioning": (
                "Inspectable workspace state for local beta operation; "
                "not subjective consciousness or fully autonomous production operation."
            ),
        }

    def add_evidence(self, source: str, content: str, *, confidence: float = 0.5) -> dict[str, Any]:
        source = source.strip()
        content = content.strip()
        if not source:
            raise ValueError("Missing evidence source")
        if not content:
            raise ValueError("Missing evidence content")
        self.memory.add_evidence(source, content, confidence=confidence)
        self.save()
        return self.snapshot()

    def add_reflection(self, *, action: str, outcome: str, confidence: float = 0.5) -> dict[str, Any]:
        action = action.strip()
        outcome = outcome.strip()
        if not action:
            raise ValueError("Missing reflection action")
        if not outcome:
            raise ValueError("Missing reflection outcome")
        ReflectionEngine().record(self.memory, action=action, outcome=outcome, confidence=confidence)
        self.save()
        return self.snapshot()

    def set_goal(self, name: str, description: str) -> dict[str, Any]:
        name = name.strip()
        description = description.strip()
        if not name:
            raise ValueError("Missing goal name")
        if not description:
            raise ValueError("Missing goal description")
        self.self_model.set_goal(name, description)
        self.save()
        return self.snapshot()

    def clear(self) -> dict[str, Any]:
        self.self_model, self.memory = self._seed()
        self.save()
        return self.snapshot()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now(),
            "self_model": self.self_model.snapshot(),
            "working_memory": self.memory.snapshot(),
        }
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _load_or_seed(self) -> tuple[SelfModel, WorkingMemory]:
        if not self.path.exists():
            return self._seed()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            return self._seed()
        if not isinstance(data, dict):
            self.load_error = "Workspace state file did not contain a JSON object."
            return self._seed()
        return self._self_model_from(data.get("self_model")), self._memory_from(data.get("working_memory"))

    def _seed(self) -> tuple[SelfModel, WorkingMemory]:
        model = SelfModel(identity="ghost-chimera")
        for name, description in DEFAULT_CAPABILITIES.items():
            model.add_capability(name, description)
        for name, description in DEFAULT_LIMITS.items():
            model.add_limit(name, description)
        for name, description in DEFAULT_GOALS.items():
            model.set_goal(name, description)
        return model, WorkingMemory(task="local operator workspace")

    def _self_model_from(self, payload: object) -> SelfModel:
        if not isinstance(payload, dict):
            return self._seed()[0]
        model = SelfModel(identity=str(payload.get("identity") or "ghost-chimera"))
        for name, description in DEFAULT_CAPABILITIES.items():
            model.add_capability(name, description)
        for name, description in DEFAULT_LIMITS.items():
            model.add_limit(name, description)
        for name, description in DEFAULT_GOALS.items():
            model.set_goal(name, description)
        for name, description in dict(payload.get("capabilities") or {}).items():
            model.add_capability(str(name), str(description))
        for name, description in dict(payload.get("limits") or {}).items():
            model.add_limit(str(name), str(description))
        for name, description in dict(payload.get("goals") or {}).items():
            model.set_goal(str(name), str(description))
        return model

    def _memory_from(self, payload: object) -> WorkingMemory:
        if not isinstance(payload, dict):
            return self._seed()[1]
        memory = WorkingMemory(task=str(payload.get("task") or "local operator workspace"))
        for item in payload.get("evidence") or []:
            if isinstance(item, dict):
                memory.evidence.append(
                    {
                        "source": str(item.get("source") or "unknown"),
                        "content": str(item.get("content") or ""),
                        "confidence": _bounded_confidence(item.get("confidence")),
                        "timestamp": str(item.get("timestamp") or _now()),
                    }
                )
        for item in payload.get("reflections") or []:
            if isinstance(item, dict):
                memory.reflections.append(
                    {
                        "action": str(item.get("action") or ""),
                        "outcome": str(item.get("outcome") or ""),
                        "confidence": _bounded_confidence(item.get("confidence")),
                        "timestamp": str(item.get("timestamp") or _now()),
                    }
                )
        return memory

    def _rank_attention(self, memory_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for evidence in memory_snapshot["evidence"]:
            items.append(
                {
                    "type": "evidence",
                    "source": evidence.get("source"),
                    "content": evidence.get("content"),
                    "relevance": 0.82,
                    "trust": evidence.get("confidence", 0.5),
                    "recency": 1.0,
                    "novelty": 0.25,
                }
            )
        for reflection in memory_snapshot["reflections"]:
            items.append(
                {
                    "type": "reflection",
                    "action": reflection.get("action"),
                    "content": reflection.get("outcome"),
                    "relevance": 0.76,
                    "trust": reflection.get("confidence", 0.5),
                    "recency": 1.0,
                    "novelty": 0.35,
                }
            )
        return AttentionController().rank(items)[:12]

    def _uncertainty(self, memory_snapshot: dict[str, Any]) -> dict[str, Any]:
        confidences = [
            _bounded_confidence(item.get("confidence"))
            for item in [*memory_snapshot["evidence"], *memory_snapshot["reflections"]]
        ]
        mean_confidence = fmean(confidences) if confidences else 0.0
        score = round(1.0 - mean_confidence, 6) if confidences else 1.0
        return {
            "score": score,
            "mean_confidence": round(mean_confidence, 6),
            "evidence_count": len(memory_snapshot["evidence"]),
            "reflection_count": len(memory_snapshot["reflections"]),
            "note": "Lower uncertainty means more local evidence/reflection confidence is available; it is not a truth guarantee.",
        }


__all__ = [
    "DEFAULT_CAPABILITIES",
    "DEFAULT_GOALS",
    "DEFAULT_LIMITS",
    "OperatorWorkspaceStore",
    "WORKSPACE_STATE_FILENAME",
]
