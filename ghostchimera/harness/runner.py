from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..chimera_pilot.hooks import HookName, HookRegistry
from ..chimera_pilot.kernel import ChimeraPilotKernel
from ..memory_layer.store import MemoryStore
from .case import HarnessCase, HarnessCaseResult


def _safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "task_id": getattr(task, "id", ""),
        "kind": getattr(getattr(task, "kind", None), "value", str(getattr(task, "kind", ""))),
        "objective": getattr(task, "objective", ""),
        "inputs": dict(getattr(task, "inputs", {}) or {}),
        "constraints": dict(getattr(task, "constraints", {}) or {}),
    }


@dataclass
class HarnessArtifacts:
    output_dir: Path
    events_path: Path
    results_path: Path

    @classmethod
    def create(cls, output_dir: str | Path) -> HarnessArtifacts:
        out = Path(output_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        return cls(
            output_dir=out,
            events_path=out / "events.jsonl",
            results_path=out / "results.jsonl",
        )

    def write_event(self, event: dict[str, Any]) -> None:
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(_safe_json(event) + "\n")

    def write_result(self, result: HarnessCaseResult) -> None:
        with self.results_path.open("a", encoding="utf-8") as f:
            f.write(_safe_json(result.to_dict()) + "\n")


class HarnessRunner:
    """Run harness cases through Chimera Pilot and record artifacts."""

    def __init__(self, *, output_dir: str | Path) -> None:
        self.artifacts = HarnessArtifacts.create(output_dir)

    def _hooks_for_case(self, case: HarnessCase) -> HookRegistry:
        hooks = HookRegistry()

        @hooks.on(HookName.TASK_COMPILE)
        def _on_compile(*, objective: str, tasks: list[Any], **_kwargs: Any) -> None:
            self.artifacts.write_event(
                {
                    "type": "task_compile",
                    "case_id": case.id,
                    "at": time.time(),
                    "objective": objective,
                    "tasks": [_task_to_dict(t) for t in tasks],
                }
            )

        @hooks.on(HookName.TASK_EXECUTE_POST)
        def _on_execute_post(*, task: Any, execution: Any, **_kwargs: Any) -> None:
            payload = execution.to_dict() if hasattr(execution, "to_dict") else {"ok": bool(getattr(execution, "ok", False))}
            self.artifacts.write_event(
                {
                    "type": "task_execute_post",
                    "case_id": case.id,
                    "at": time.time(),
                    "task": _task_to_dict(task),
                    "execution": payload,
                }
            )

        @hooks.on(HookName.BACKEND_FALLBACK)
        def _on_fallback(*, task: Any, failed_backend_id: str, fallback_backend_id: str, error: str, **_kwargs: Any) -> None:
            self.artifacts.write_event(
                {
                    "type": "backend_fallback",
                    "case_id": case.id,
                    "at": time.time(),
                    "task": _task_to_dict(task),
                    "failed_backend_id": failed_backend_id,
                    "fallback_backend_id": fallback_backend_id,
                    "error": error,
                }
            )

        return hooks

    def _memory_store_for_case(self, case: HarnessCase) -> MemoryStore | None:
        if not case.memory_documents:
            return None
        mem_dir = self.artifacts.output_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        store = MemoryStore(mem_dir / f"{case.id}.sqlite3")
        for doc in case.memory_documents:
            store.add_document(doc.source, doc.content, metadata=dict(doc.metadata))
        return store

    def run_case(self, case: HarnessCase) -> HarnessCaseResult:
        kernel_args = dict(case.kernel)
        memory_store = self._memory_store_for_case(case)
        hooks = self._hooks_for_case(case)

        include_deterministic_backend = bool(kernel_args.pop("include_deterministic_backend", True))
        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=include_deterministic_backend,
            memory_store=memory_store,
            hooks=hooks,
            **kernel_args,
        )

        executions = [e.to_dict() for e in kernel.run(case.objective)]

        check_details: dict[str, Any] = {}
        ok = True

        if case.expect.ok is not None:
            actual_ok = all(e.get("ok") for e in executions)
            check_details["ok"] = {"expected": case.expect.ok, "actual": actual_ok}
            ok = ok and (actual_ok is bool(case.expect.ok))

        if case.expect.backend_ids:
            actual_backends = tuple(str(e.get("backend_id", "")) for e in executions)
            expected = tuple(case.expect.backend_ids)
            check_details["backend_ids"] = {"expected": expected, "actual": actual_backends}
            ok = ok and all(b in expected for b in actual_backends)

        if case.expect.output_contains:
            outputs = "\n".join(str(e.get("output", "")) for e in executions)
            missing = [s for s in case.expect.output_contains if s not in outputs]
            check_details["output_contains"] = {"expected": tuple(case.expect.output_contains), "missing": missing}
            ok = ok and not missing

        result = HarnessCaseResult(id=case.id, ok=ok, checks=check_details, executions=executions)
        self.artifacts.write_result(result)
        return result

    def run(self, cases: list[HarnessCase]) -> list[HarnessCaseResult]:
        results: list[HarnessCaseResult] = []
        for case in cases:
            results.append(self.run_case(case))
        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r.ok),
            "failed": sum(1 for r in results if not r.ok),
        }
        self.artifacts.write_event({"type": "summary", "at": time.time(), **summary})
        return results

