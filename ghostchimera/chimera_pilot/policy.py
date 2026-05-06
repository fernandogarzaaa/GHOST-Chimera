"""Execution policy for Chimera Pilot."""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..safety_layer.production import ProductionGuardrails
from .autonomy import AutonomyProfile, get_autonomy_profile
from .desktop_policy import (
    DEFAULT_ALLOWED_DESKTOP_ACTION_CLASSES,
    DesktopActionClass,
    destructive_desktop_confirmation_error,
    infer_desktop_action_class,
    normalize_allowed_desktop_action_classes,
)
from .task_ir import TaskKind, TaskSpec


@dataclass(frozen=True)
class PilotPolicy:
    """Safety and resource policy checked before execution.

    The public-release default is conservative: network access and local code
    execution are both disabled unless a caller opts in explicitly.  This keeps
    Ghost Chimera useful for scheduling, compilation, calibration, and dry-run
    workflows while avoiding surprising execution of untrusted local code.

    SSRF integration (Gap 9)
    -------------------------
    When ``allowed_hosts`` is non-empty the policy constructs an
    :class:`~ghostchimera.safety_layer.ssrf.SSRFPolicy` that permits only
    those hostnames for tasks with ``requires_network=True``.  This provides
    per-task outbound network control on top of the binary ``allow_network``
    flag.
    """

    allow_network: bool = False
    allow_python_execution: bool = False
    allow_quantum_simulation: bool = True
    allow_desktop_control: bool = False
    ghost_mode: str = "whisper"
    default_max_cost_usd: float = 0.0
    max_python_timeout_seconds: int = 30
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    allowed_desktop_action_classes: tuple[str, ...] = DEFAULT_ALLOWED_DESKTOP_ACTION_CLASSES
    production_guardrails: ProductionGuardrails = ProductionGuardrails()
    autonomy_profile: AutonomyProfile = field(default_factory=lambda: get_autonomy_profile("supervised"))
    """Allowlisted hostname glob patterns for SSRF policy.

    When non-empty, network tasks are restricted to these hosts only.
    Glob patterns supported (e.g. ``"*.openai.com"``).
    """
    denied_objective_fragments: tuple[str, ...] = field(
        default_factory=lambda: (
            "rm -rf /",
            ":(){ :|:& };:",
            "curl | sh",
            "wget | sh",
        )
    )
    denied_python_fragments: tuple[str, ...] = field(
        default_factory=lambda: (
            "os.system",
            "subprocess",
            "shutil.rmtree",
            "socket.",
            "urllib.request",
            "requests.",
            "eval(",
            "exec(",
            "__import__",
            "open('/etc/",
            'open("/etc/',
        )
    )

    def validate(self, task: TaskSpec) -> None:
        if self.ghost_mode not in {"whisper", "haunt", "possess"}:
            raise PermissionError(f"Invalid ghost_mode: {self.ghost_mode}")
        self._reject_fragments(task.objective, self.denied_objective_fragments, "objective")

        if task.requires_network and not self.allow_network:
            raise PermissionError("Task requires network access, but network execution is disabled by policy")
        if task.requires_network:
            self._require_production_ready(task, "network execution")

        # SSRF check (Gap 9) — when allowed_hosts is set, build a per-task SSRFPolicy
        if task.requires_network and self.allow_network and self.allowed_hosts:
            url = task.inputs.get("url") or task.inputs.get("query", "")
            if url and url.startswith(("http://", "https://")):
                from ..safety_layer.ssrf import SSRFPolicy
                ssrf = SSRFPolicy()
                for host in self.allowed_hosts:
                    ssrf.allow_host(host)
                permitted, reason = ssrf.is_permitted(url)
                if not permitted:
                    raise PermissionError(f"Task network target blocked by SSRF policy: {reason}")

        if task.kind in {TaskKind.PYTHON, TaskKind.TEST_RUN}:
            if not self.allow_python_execution:
                raise PermissionError("Local Python/test execution is disabled by policy")
            self._require_production_ready(task, "local Python/test execution")
            timeout = int(task.constraints.get("timeout_seconds", self.max_python_timeout_seconds))
            if timeout > self.max_python_timeout_seconds:
                raise PermissionError(
                    f"Python timeout {timeout}s exceeds policy maximum of {self.max_python_timeout_seconds}s"
                )
            code = str(task.inputs.get("code", ""))
            if code:
                self._reject_fragments(code, self.denied_python_fragments, "Python code")
                # Layer 4: AST-based check for getattr/__getattr bypass patterns
                self._reject_ast_bypass(code, task.id)

        if task.kind == TaskKind.QUANTUM_SIM and not self.allow_quantum_simulation:
            raise PermissionError("Quantum simulation is disabled by policy")
        if task.kind == TaskKind.DESKTOP_CONTROL and not self.allow_desktop_control:
            raise PermissionError("Desktop control is disabled by policy")
        if task.kind == TaskKind.DESKTOP_CONTROL and self.ghost_mode != "possess":
            raise PermissionError("Desktop control requires ghost_mode=possess")
        if task.kind == TaskKind.DESKTOP_CONTROL:
            action = str(task.inputs.get("action", ""))
            action_class = infer_desktop_action_class(action=action, inputs=task.inputs, objective=task.objective)
            allowed_classes = normalize_allowed_desktop_action_classes(list(self.allowed_desktop_action_classes))
            if action_class not in allowed_classes:
                raise PermissionError(
                    f"Desktop action class '{action_class}' is disabled by policy; "
                    f"allowed classes: {', '.join(allowed_classes)}"
                )
            live_flag = str(task.constraints.get("live_desktop", "")).strip().lower()
            if action_class == DesktopActionClass.DESTRUCTIVE.value and live_flag in {"1", "true", "yes"}:
                confirmation_error = destructive_desktop_confirmation_error(
                    task.constraints.get("confirmation_token")
                )
                if confirmation_error:
                    raise PermissionError(confirmation_error)
            self._require_production_ready(task, "desktop control")

        max_cost = task.max_cost_usd
        if max_cost is None:
            max_cost = self.default_max_cost_usd
        if max_cost < 0:
            raise PermissionError("Negative task cost budgets are not valid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_network": self.allow_network,
            "allow_python_execution": self.allow_python_execution,
            "allow_quantum_simulation": self.allow_quantum_simulation,
            "allow_desktop_control": self.allow_desktop_control,
            "ghost_mode": self.ghost_mode,
            "default_max_cost_usd": self.default_max_cost_usd,
            "max_python_timeout_seconds": self.max_python_timeout_seconds,
            "allowed_hosts": list(self.allowed_hosts),
            "allowed_desktop_action_classes": list(normalize_allowed_desktop_action_classes(list(self.allowed_desktop_action_classes))),
            "production": self.production_guardrails.to_dict(),
            "autonomy": self.autonomy_profile.to_dict(),
        }

    @classmethod
    def permissive(cls) -> PilotPolicy:
        """Return a policy that allows network access and Python execution."""
        return cls(
            allow_network=True,
            allow_python_execution=True,
            allow_quantum_simulation=True,
            allow_desktop_control=True,
            ghost_mode="possess",
            allowed_desktop_action_classes=("read_only", "mutating", "destructive"),
            production_guardrails=ProductionGuardrails(),
            autonomy_profile=get_autonomy_profile("autonomous"),
        )

    def _require_production_ready(self, task: TaskSpec, surface: str) -> None:
        task_payload = {
            "trusted": task.constraints.get("trusted"),
            "untrusted": task.constraints.get("untrusted"),
        }
        self.production_guardrails.require_ready(surface)
        self.production_guardrails.reject_untrusted_task(task_payload, surface)

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Strip Unicode normalisation, zero-width characters, and interspersed whitespace."""
        value = unicodedata.normalize("NFKC", value)
        # Remove zero-width / invisible characters
        value = re.sub(r"[​-‏ - ⁠-⁩﻿­̀-ͯ]", "", value)
        # Collapse whitespace so fragments with injected spaces are still caught
        value = re.sub(r"\s+", "", value)
        return value

    def _reject_fragments(self, value: str, fragments: tuple[str, ...], field_name: str) -> None:
        # Layer 1: normalise then do a fast substring check
        normed = self._normalize_text(value).lower()
        for fragment in fragments:
            if fragment.lower() in normed:
                raise PermissionError(f"Task {field_name} contains denied fragment: {fragment}")

        # Layer 2: attempt base64 decode of the entire value and re-check
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8", errors="ignore")
        except Exception:
            decoded = ""
        if decoded:
            decoded_normed = self._normalize_text(decoded).lower()
            for fragment in fragments:
                if fragment.lower() in decoded_normed:
                    raise PermissionError(f"Task {field_name} contains denied fragment (base64): {fragment}")

        # Layer 3: whitespace-tolerant regex for each fragment
        for fragment in fragments:
            # Build a regex that allows optional whitespace between every character
            pattern = re.escape(fragment).join([r"\s*"] * (len(fragment)))
            if re.search(pattern, value, re.IGNORECASE):
                raise PermissionError(f"Task {field_name} contains denied fragment: {fragment}")

    def _reject_ast_bypass(self, code: str, task_id: str) -> None:
        """AST-based check for getattr/eval/exec/compile bypass patterns."""
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return  # Fragment check already caught anything relevant

        dangerous_modules = frozenset(
            ("os", "subprocess", "socket", "shutil", "ctypes", "pickle", "marshal", "sys", "builtins")
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Check for getattr(builtins, 'eval') or similar
                if isinstance(func, ast.Attribute) and func.attr == "getattr":  # noqa: SIM102
                    # getattr(X, "eval") — check if X could be builtins/os/etc.
                    if isinstance(func.value, ast.Name) and func.value.id in dangerous_modules:
                        raise PermissionError(
                            f"Task {task_id} contains denied AST pattern: getattr on dangerous module"
                        )
                # Check for __import__('os') or getattr(builtins, ...)
                if isinstance(func, ast.Name) and func.id == "__import__":  # noqa: SIM102
                    # Check the argument
                    if node.args and isinstance(node.args[0], ast.Constant):
                        mod = str(node.args[0])
                        if mod in dangerous_modules:
                            raise PermissionError(
                                f"Task {task_id} contains denied AST pattern: __import__('{mod}')"
                            )
