"""Rule-based compiler from high-level objectives into Chimera Pilot tasks."""

from __future__ import annotations

import re

from .desktop_policy import infer_desktop_action_class
from .desktop_targeting import resolve_target_descriptor
from .schema import validate_task
from .task_ir import TaskKind, TaskSpec

_DESKTOP_SEQUENCE_PATTERN = re.compile(r"\s+(?:and then|then)\b\s*|\s*->\s*")


class RuleBasedTaskCompiler:
    """Small deterministic compiler for common Ghost Chimera objectives."""

    def compile(self, objective: str) -> list[TaskSpec]:
        text = objective.strip()
        if not text:
            raise ValueError("Objective cannot be empty")

        lower = text.lower()

        python_code = self._extract_prefixed_payload(text, prefixes=("python:", "run python:", "execute python:"))
        if python_code is not None:
            spec = TaskSpec.create(
                kind=TaskKind.PYTHON,
                objective=text,
                inputs={"code": python_code},
                privacy_level="private",
                max_cost_usd=0.0,
                max_latency_ms=10_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("run tests") or lower.startswith("test ") or "run unittest" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.TEST_RUN,
                objective=text,
                inputs=self._compile_test_inputs(text),
                privacy_level="private",
                max_cost_usd=0.0,
                max_latency_ms=60_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if any(token in lower for token in ("quantum", "qasm", "qubit", "ghz")):
            spec = TaskSpec.create(
                kind=TaskKind.QUANTUM_SIM,
                objective=text,
                inputs={"circuit": "ghz" if "ghz" in lower else "default", "qubits": self._extract_qubit_count(lower)},
                privacy_level="normal",
                max_cost_usd=0.0,
                max_latency_ms=10_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("research ") or lower.startswith("search web ") or "latest" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.WEB_RESEARCH,
                objective=text,
                inputs={"query": text},
                requires_network=True,
                privacy_level="normal",
                max_latency_ms=30_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if lower.startswith("analyze file") or lower.startswith("inspect file"):
            spec = TaskSpec.create(
                kind=TaskKind.FILE_ANALYSIS,
                objective=text,
                inputs={"path": text.split(maxsplit=2)[-1] if len(text.split(maxsplit=2)) == 3 else ""},
                privacy_level="private",
                max_cost_usd=0.0,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        desktop_action, desktop_constraints = self._parse_desktop_action(text, lower)
        if desktop_action is not None:
            spec = TaskSpec.create(
                kind=TaskKind.DESKTOP_CONTROL,
                objective=text,
                inputs=desktop_action,
                constraints=desktop_constraints,
                privacy_level="private",
                max_cost_usd=0.0,
                max_latency_ms=5_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        if "rag" in lower or "retrieve" in lower:
            spec = TaskSpec.create(
                kind=TaskKind.RAG_QUERY,
                objective=text,
                inputs={"query": text},
                privacy_level="normal",
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        # ── Track 2: Gemini long-context document processing ────────────────
        if any(
            tok in lower
            for tok in (
                "summarise document",
                "summarize document",
                "analyze contract",
                "analyse contract",
                "process report",
                "long context",
            )
        ):
            spec = TaskSpec.create(
                kind=TaskKind.LONG_CONTEXT_DOC,
                objective=text,
                inputs={"instruction": text, "documents": []},
                requires_network=True,
                privacy_level="normal",
                max_latency_ms=30_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        # ── Track 3: Simulation ──────────────────────────────────────────────
        if any(
            tok in lower
            for tok in ("simulate", "simulation", "digital twin", "robot", "waypoint", "kinematics", "policy test")
        ):
            sim_mode = "kinematics"
            if "digital twin" in lower:
                sim_mode = "digital_twin"
            elif "policy" in lower:
                sim_mode = "policy_test"
            spec = TaskSpec.create(
                kind=TaskKind.SIMULATION,
                objective=text,
                inputs={"sim_mode": sim_mode},
                privacy_level="normal",
                max_cost_usd=0.0,
                max_latency_ms=10_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        # ── Track 4: Analytics / Data Pipeline ──────────────────────────────
        if any(
            tok in lower
            for tok in ("analytics", "data pipeline", "validate data", "detect anomal", "forecast", "knowledge graph")
        ):
            if any(tok in lower for tok in ("pipeline", "validate data", "ingest", "knowledge graph")):
                spec = TaskSpec.create(
                    kind=TaskKind.DATA_PIPELINE,
                    objective=text,
                    inputs={"data": [], "pipeline": ["validate_schema", "profile", "detect_anomalies"]},
                    privacy_level="private",
                    max_cost_usd=0.0,
                    max_latency_ms=60_000,
                )
                validate_task(spec.kind, spec.inputs)
                return [spec]
            spec = TaskSpec.create(
                kind=TaskKind.ANALYTICS_QUERY,
                objective=text,
                inputs={"query": text},
                privacy_level="normal",
                max_cost_usd=0.0,
                max_latency_ms=30_000,
            )
            validate_task(spec.kind, spec.inputs)
            return [spec]

        spec = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective=text,
            inputs={"prompt": text},
            privacy_level="normal",
        )
        validate_task(spec.kind, spec.inputs)
        return [spec]

    def _extract_prefixed_payload(self, text: str, prefixes: tuple[str, ...]) -> str | None:
        stripped = text.strip()
        lower = stripped.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                return stripped[len(prefix) :].strip()
        return None

    def _extract_qubit_count(self, lower: str) -> int:
        match = re.search(r"(\d+)\s*-?\s*qubit", lower)
        if not match:
            return 3
        return max(2, int(match.group(1)))

    def _compile_test_inputs(self, text: str) -> dict[str, str]:
        match = re.search(r"pattern\s*=\s*([^\s]+)", text)
        if match:
            return {"pattern": match.group(1)}
        return {"pattern": "test_*.py"}

    def _parse_desktop_action(self, text: str, lower: str) -> tuple[dict[str, object] | None, dict[str, object]]:
        constraints: dict[str, object] = {}
        if lower.startswith("live desktop:"):
            constraints["live_desktop"] = True
            text = text[len("live desktop:") :].strip()
            lower = text.lower()
        elif lower.startswith("dryrun desktop:"):
            constraints["live_desktop"] = False
            text = text[len("dryrun desktop:") :].strip()
            lower = text.lower()

        plan_segments = self._split_desktop_sequence(text)
        if len(plan_segments) > 1:
            steps: list[dict[str, object]] = []
            for idx, segment in enumerate(plan_segments):
                parsed = self._parse_single_desktop_action(segment)
                if parsed is None:
                    return None, {}
                step = {**parsed, "step_id": f"step-{idx + 1}", "stop_on_failure": True}
                steps.append(step)
            overall_class = "read_only"
            if any(step.get("action_class") == "destructive" for step in steps):
                overall_class = "destructive"
            elif any(step.get("action_class") == "mutating" for step in steps):
                overall_class = "mutating"
            return {"action": "plan", "plan": steps, "action_class": overall_class}, constraints

        single = self._parse_single_desktop_action(text)
        if single is None:
            return None, {}
        return single, constraints

    def _parse_single_desktop_action(self, text: str) -> dict[str, object] | None:
        lower = text.lower()
        if lower.startswith("move ") or lower == "move":
            return self._desktop_inputs("move", text, target=text[5:].strip())
        if lower.startswith("click ") or lower == "click":
            return self._desktop_inputs("click", text, target=text[6:].strip())
        if lower.startswith("double click "):
            return self._desktop_inputs("double_click", text, target=text[13:].strip())
        if lower.startswith("right click "):
            return self._desktop_inputs("right_click", text, target=text[12:].strip())
        if lower.startswith("type "):
            return self._desktop_inputs("type", text, text=text[5:].strip(), target="")
        if lower.startswith("press ") or lower.startswith("hotkey "):
            payload = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) == 2 else ""
            keys = [k.strip() for k in payload.split("+") if k.strip()]
            return self._desktop_inputs("hotkey", text, keys=keys)
        return None

    def _split_desktop_sequence(self, text: str) -> list[str]:
        """Split desktop objectives by supported chain separators: 'then', 'and then', and '->'."""
        parts = [segment.strip() for segment in _DESKTOP_SEQUENCE_PATTERN.split(text) if segment.strip()]
        return parts or [text]

    def _desktop_inputs(
        self,
        action: str,
        objective: str,
        *,
        target: str = "",
        text: str = "",
        keys: list[str] | None = None,
    ) -> dict[str, object]:
        inputs: dict[str, object] = {"action": action}
        if target:
            inputs["target"] = target
        if text:
            inputs["text"] = text
        if keys is not None:
            inputs["keys"] = keys
        descriptor = resolve_target_descriptor(inputs)
        if descriptor:
            inputs["target_descriptor"] = descriptor
        inputs["action_class"] = infer_desktop_action_class(action=action, inputs=inputs, objective=objective)
        return inputs
