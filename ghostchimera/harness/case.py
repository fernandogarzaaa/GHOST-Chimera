from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HarnessExpectation:
    """Expected properties of a harness run.

    This is intentionally minimal; it is meant for deterministic regression
    checks (e.g., expected backend selection) rather than open-ended LLM grading.
    """

    ok: bool | None = True
    backend_ids: tuple[str, ...] = field(default_factory=tuple)
    output_contains: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> HarnessExpectation:
        payload = dict(payload or {})
        ok = payload.get("ok", True)
        backend_ids = tuple(str(x) for x in (payload.get("backend_ids") or ()))
        output_contains = tuple(str(x) for x in (payload.get("output_contains") or ()))
        return cls(ok=ok, backend_ids=backend_ids, output_contains=output_contains)


@dataclass(frozen=True)
class MemoryDocument:
    source: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MemoryDocument:
        return cls(
            source=str(payload.get("source", "")).strip(),
            content=str(payload.get("content", "")).strip(),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class HarnessCase:
    id: str
    objective: str
    kernel: dict[str, Any] = field(default_factory=dict)
    memory_documents: tuple[MemoryDocument, ...] = field(default_factory=tuple)
    expect: HarnessExpectation = field(default_factory=HarnessExpectation)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> HarnessCase:
        payload = dict(payload or {})
        case_id = str(payload.get("id", "")).strip()
        objective = str(payload.get("objective", "")).strip()
        if not case_id:
            raise ValueError("HarnessCase is missing required field 'id'")
        if not objective:
            raise ValueError(f"HarnessCase '{case_id}' is missing required field 'objective'")
        kernel = dict(payload.get("kernel") or {})
        memory_documents = tuple(
            MemoryDocument.from_dict(d)
            for d in (payload.get("memory_documents") or ())
        )
        expect = HarnessExpectation.from_dict(payload.get("expect"))
        return cls(
            id=case_id,
            objective=objective,
            kernel=kernel,
            memory_documents=memory_documents,
            expect=expect,
        )


@dataclass(frozen=True)
class HarnessCaseResult:
    id: str
    ok: bool
    checks: dict[str, Any]
    executions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ok": self.ok,
            "checks": dict(self.checks),
            "executions": list(self.executions),
        }

