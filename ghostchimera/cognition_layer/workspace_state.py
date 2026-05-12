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
from ..memory_layer.store import MemoryStore
from .workspace import AttentionController, ReflectionEngine, SelfModel, WorkingMemory

WORKSPACE_STATE_FILENAME = "operator_workspace.json"
DEFAULT_STALE_AFTER_DAYS = 30.0

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


def _bounded_days(value: Any, *, default: float = DEFAULT_STALE_AFTER_DAYS) -> float:
    try:
        days = float(value)
    except (TypeError, ValueError):
        days = default
    return max(0.0, days)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_days(value: Any) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds() / 86400.0)


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


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
            "quality": self.quality_report(),
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

    def sync_to_memory(
        self,
        *,
        memory_db: str | Path | None = None,
        min_confidence: float = 0.0,
        stale_after_days: float = DEFAULT_STALE_AFTER_DAYS,
    ) -> dict[str, Any]:
        """Promote workspace evidence/reflections into CWR memory with provenance."""

        threshold = _bounded_confidence(min_confidence, default=0.0)
        stale_days = _bounded_days(stale_after_days)
        target_db = Path(memory_db).expanduser() if memory_db else GhostChimeraConfig.from_env().memory_db
        store = MemoryStore(target_db)
        synced: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        filtered: list[dict[str, Any]] = []
        documents = self._memory_documents(threshold, stale_days)

        for item in documents:
            record = {
                "source": item["source"],
                "workspace_type": item["metadata"]["workspace_type"],
                "quality_flags": item["metadata"]["workspace_quality_flags"],
                "sync_recommendation": item["metadata"]["sync_recommendation"],
                "content": item["content"],
            }
            if "low_confidence" in item["metadata"]["workspace_quality_flags"]:
                filtered.append(record)
                continue
            row_id, inserted = store.add_document_once(
                str(item["source"]),
                str(item["content"]),
                metadata=dict(item["metadata"]),
            )
            persisted = {
                "id": row_id,
                "inserted": inserted,
                **record,
            }
            if inserted:
                synced.append(persisted)
            else:
                skipped.append(persisted)

        return {
            "ok": True,
            "memory_db": str(target_db),
            "state_file": str(self.path),
            "min_confidence": threshold,
            "stale_after_days": stale_days,
            "synced": len(synced),
            "skipped": len(skipped),
            "filtered": len(filtered),
            "synced_documents": synced,
            "skipped_documents": skipped,
            "filtered_documents": filtered,
            "quality": self._quality_summary(documents),
            "note": "Workspace records were promoted into CWR memory with explicit provenance.",
        }

    def quality_report(
        self,
        *,
        min_confidence: float = 0.0,
        stale_after_days: float = DEFAULT_STALE_AFTER_DAYS,
    ) -> dict[str, Any]:
        """Summarize evidence freshness, conflicts, and confidence before sync."""

        threshold = _bounded_confidence(min_confidence, default=0.0)
        stale_days = _bounded_days(stale_after_days)
        documents = self._memory_documents(threshold, stale_days)
        return {
            **self._quality_summary(documents),
            "min_confidence": threshold,
            "stale_after_days": stale_days,
            "note": "Quality flags are retrieval provenance, not a truth guarantee.",
        }

    def workspace_context_for_objective(
        self,
        objective: str,
        *,
        min_confidence: float = 0.5,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return workspace evidence/reflections relevant to *objective*.

        This provides a lightweight, in-memory retrieval path that does not
        require workspace to be synced to the CWR SQLite store first.  It
        matches on simple substring overlap between the objective words and
        the evidence/reflection content.

        Parameters
        ----------
        objective:
            The task objective text to match against.
        min_confidence:
            Only return items with confidence >= this threshold.
        limit:
            Maximum number of context items to return.

        Returns
        -------
        list of dicts with keys ``type``, ``source``, ``content``,
        ``confidence``, and ``relevance_hint``.
        """
        tokens = {t.casefold() for t in objective.split() if len(t) > 2}
        items: list[tuple[float, dict[str, Any]]] = []

        for evidence in self.memory.evidence:
            confidence = _bounded_confidence(evidence.get("confidence"))
            if confidence < min_confidence:
                continue
            content = str(evidence.get("content") or "")
            hits = sum(1 for tok in tokens if tok in content.casefold())
            if hits == 0:
                continue
            relevance = round(min(1.0, hits / max(1, len(tokens))), 6)
            items.append(
                (
                    relevance,
                    {
                        "type": "evidence",
                        "source": str(evidence.get("source") or "workspace"),
                        "content": content,
                        "confidence": confidence,
                        "relevance_hint": relevance,
                    },
                )
            )

        for reflection in self.memory.reflections:
            confidence = _bounded_confidence(reflection.get("confidence"))
            if confidence < min_confidence:
                continue
            content = str(reflection.get("outcome") or "")
            hits = sum(1 for tok in tokens if tok in content.casefold())
            if hits == 0:
                continue
            relevance = round(min(1.0, hits / max(1, len(tokens))), 6)
            items.append(
                (
                    relevance,
                    {
                        "type": "reflection",
                        "source": str(reflection.get("action") or "workspace"),
                        "content": content,
                        "confidence": confidence,
                        "relevance_hint": relevance,
                    },
                )
            )

        items.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in items[:limit]]

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

    def _memory_documents(self, min_confidence: float, stale_after_days: float) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for index, evidence in enumerate(self.memory.evidence):
            confidence = _bounded_confidence(evidence.get("confidence"))
            source = str(evidence.get("source") or "unknown")
            timestamp = str(evidence.get("timestamp") or "")
            age = _age_days(timestamp)
            flags = self._quality_flags(confidence, min_confidence, age, stale_after_days)
            documents.append(
                {
                    "source": f"workspace:evidence:{source}",
                    "content": f"Workspace evidence from {source}: {evidence.get('content')}",
                    "conflict_key": ("evidence", _normalized_text(source)),
                    "conflict_value": _normalized_text(evidence.get("content")),
                    "metadata": {
                        "workspace_type": "evidence",
                        "workspace_index": index,
                        "workspace_source": source,
                        "workspace_timestamp": timestamp,
                        "workspace_age_days": round(age, 6) if age is not None else None,
                        "workspace_stale_after_days": stale_after_days,
                        "workspace_quality_flags": flags,
                        "sync_recommendation": "review" if flags else "use",
                        "confidence": confidence,
                        "state_file": str(self.path),
                    },
                }
            )
        for index, reflection in enumerate(self.memory.reflections):
            confidence = _bounded_confidence(reflection.get("confidence"))
            action = str(reflection.get("action") or "unknown")
            timestamp = str(reflection.get("timestamp") or "")
            age = _age_days(timestamp)
            flags = self._quality_flags(confidence, min_confidence, age, stale_after_days)
            documents.append(
                {
                    "source": f"workspace:reflection:{action}",
                    "content": f"Workspace reflection after {action}: {reflection.get('outcome')}",
                    "conflict_key": ("reflection", _normalized_text(action)),
                    "conflict_value": _normalized_text(reflection.get("outcome")),
                    "metadata": {
                        "workspace_type": "reflection",
                        "workspace_index": index,
                        "workspace_action": action,
                        "workspace_timestamp": timestamp,
                        "workspace_age_days": round(age, 6) if age is not None else None,
                        "workspace_stale_after_days": stale_after_days,
                        "workspace_quality_flags": flags,
                        "sync_recommendation": "review" if flags else "use",
                        "confidence": confidence,
                        "state_file": str(self.path),
                    },
                }
            )
        self._mark_conflicts(documents)
        return documents

    def _quality_flags(
        self,
        confidence: float,
        min_confidence: float,
        age: float | None,
        stale_after_days: float,
    ) -> list[str]:
        flags: list[str] = []
        if confidence < min_confidence:
            flags.append("low_confidence")
        if age is not None and stale_after_days > 0 and age > stale_after_days:
            flags.append("stale")
        return flags

    def _mark_conflicts(self, documents: list[dict[str, Any]]) -> None:
        grouped: dict[tuple[str, str], set[str]] = {}
        for item in documents:
            key = item["conflict_key"]
            if isinstance(key, tuple):
                grouped.setdefault(key, set()).add(str(item["conflict_value"]))
        conflicting_keys = {key for key, values in grouped.items() if len(values) > 1}
        for item in documents:
            if item["conflict_key"] in conflicting_keys:
                flags = item["metadata"]["workspace_quality_flags"]
                if "conflicting" not in flags:
                    flags.append("conflicting")
                item["metadata"]["sync_recommendation"] = "review"

    def _quality_summary(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(documents)
        filtered_low_confidence = 0
        stale = 0
        conflicting = 0
        needs_review = 0
        for item in documents:
            flags = set(item["metadata"]["workspace_quality_flags"])
            if "low_confidence" in flags:
                filtered_low_confidence += 1
            if "stale" in flags:
                stale += 1
            if "conflicting" in flags:
                conflicting += 1
            if flags:
                needs_review += 1
        return {
            "total": total,
            "eligible": total - filtered_low_confidence,
            "filtered_low_confidence": filtered_low_confidence,
            "stale": stale,
            "conflicting": conflicting,
            "needs_review": needs_review,
        }

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
