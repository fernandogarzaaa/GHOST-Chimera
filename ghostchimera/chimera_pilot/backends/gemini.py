"""Gemini backend for Chimera Pilot — Track 2: AI Agents with Google AI Studio.

This backend handles ``REASONING`` and ``LONG_CONTEXT_DOC`` tasks using
Google Gemini models.  It is the primary entry point for:

* Multi-agent system workflows (Gemini as orchestrator or sub-agent)
* Long-context document processing (contracts, reports, codebases up to 1M tokens)
* Code generation and developer workflow agents
* Internal AI tools backed by the Gemini API

Configuration
-------------
Set ``GOOGLE_API_KEY`` (from https://ai.google.dev/) and optionally
``GEMINI_MODEL`` in the environment.  When the API key is absent the backend
probes as unavailable and the Chimera Pilot scheduler will fall back to another
backend automatically.

Task inputs recognised by ``LONG_CONTEXT_DOC`` tasks::

    {
        "instruction": "Summarise each section in one sentence.",
        "documents": ["<doc1 text>", ...],   # list of document strings
        "history": [...],                    # optional prior turns
    }

Task inputs recognised by ``REASONING`` tasks::

    {
        "prompt": "Explain the CAP theorem",
        "system": "You are a distributed-systems expert.",
    }
"""

from __future__ import annotations

import os
from typing import Any

from ...logging_config import get_logger
from ..task_ir import TaskKind, TaskSpec
from .base import BackendCapabilities, BackendHealth, ExecutionResult

logger = get_logger("gemini_backend")

_GEMINI_MAX_CONTEXT = 1_000_000


class GeminiBackend:
    """Chimera Pilot backend powered by Google Gemini.

    Handles ``REASONING`` and ``LONG_CONTEXT_DOC`` task kinds.  When a
    ``GOOGLE_API_KEY`` is present the backend is considered available;
    otherwise it probes as unavailable so the scheduler can fall through.
    """

    id = "gemini.cloud"
    name = "Google Gemini (AI Studio)"
    _description = "Google Gemini backend for reasoning and long-context document processing"

    def __init__(self) -> None:
        self._api_key = os.environ.get("GOOGLE_API_KEY", "")
        self._model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
        self.capabilities = BackendCapabilities(
            kinds={TaskKind.REASONING, TaskKind.LONG_CONTEXT_DOC},
            supports_offline=False,
            supports_streaming=True,
            supports_gpu=False,
            supports_network=True,
            max_context_tokens=_GEMINI_MAX_CONTEXT,
            metadata={
                "provider": "gemini",
                "model": self._model,
                "max_context_tokens": _GEMINI_MAX_CONTEXT,
            },
        )
        logger.debug("Backend %s model=%s initialized", self.name, self._model)

    def probe(self) -> BackendHealth:
        available = bool(self._api_key)
        return BackendHealth(
            available=available,
            reliability=0.98 if available else 0.0,
            latency_ms=300,
            estimated_cost_usd=0.0,
            last_error=None if available else "GOOGLE_API_KEY not set",
        )

    def can_run(self, task: TaskSpec) -> bool:
        return self.capabilities.supports(task) and bool(self._api_key)

    def estimate(self, task: TaskSpec) -> BackendHealth:
        if not self._api_key:
            return BackendHealth(available=False, reliability=0.0, latency_ms=0, last_error="GOOGLE_API_KEY not set")
        # For long-context doc tasks, estimate higher latency
        if task.kind == TaskKind.LONG_CONTEXT_DOC:
            doc_count = len(task.inputs.get("documents") or [])
            est_latency = 500 + doc_count * 200
            return BackendHealth(available=True, reliability=0.95, latency_ms=est_latency, estimated_cost_usd=0.0)
        return BackendHealth(available=True, reliability=0.98, latency_ms=300, estimated_cost_usd=0.0)

    def execute(self, task: TaskSpec) -> ExecutionResult:
        try:
            from ...model_layer.gemini_provider import GeminiProvider

            provider = GeminiProvider()
            if not provider.available:
                return ExecutionResult(
                    backend_id=self.id,
                    task_id=task.id,
                    ok=False,
                    output="",
                    error="GeminiProvider unavailable — GOOGLE_API_KEY not set",
                )

            if task.kind == TaskKind.LONG_CONTEXT_DOC:
                return self._execute_long_context(provider, task)
            return self._execute_reasoning(provider, task)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini backend error: %s", exc)
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=False,
                output="",
                error=str(exc),
            )

    def _execute_reasoning(self, provider: Any, task: TaskSpec) -> ExecutionResult:
        system = str(task.inputs.get("system") or "You are a helpful AI assistant.")
        prompt = str(task.inputs.get("prompt") or task.objective)
        history = list(task.inputs.get("history") or [])

        if history:
            reply, updated_history = provider.multi_agent_chat(
                history,
                new_message=prompt,
                system_context=system,
            )
            return ExecutionResult(
                backend_id=self.id,
                task_id=task.id,
                ok=True,
                output=reply,
                metrics={
                    "model": provider.model,
                    "history_turns": len(updated_history),
                    "kind": "reasoning",
                },
            )

        output = provider.chat(system, prompt)
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={"model": provider.model, "kind": "reasoning"},
        )

    def _execute_long_context(self, provider: Any, task: TaskSpec) -> ExecutionResult:
        instruction = str(task.inputs.get("instruction") or task.objective)
        documents = list(task.inputs.get("documents") or [])
        history = list(task.inputs.get("history") or [])

        output = provider.chat_long_context(
            instruction,
            documents=documents,
            history=history,
        )
        return ExecutionResult(
            backend_id=self.id,
            task_id=task.id,
            ok=True,
            output=output,
            metrics={
                "model": provider.model,
                "document_count": len(documents),
                "kind": "long_context_doc",
            },
        )


__all__ = ["GeminiBackend"]
