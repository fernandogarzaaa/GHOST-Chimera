"""Tool result middleware pipeline for Ghost Chimera.

Mirrors OpenClaw's ``registerAgentToolResultMiddleware`` surface.
Middleware transforms tool results *before* they are appended to the
agent conversation context.

Usage::

    from ghostchimera.chimera_pilot.tool_middleware import (
        ToolResultMiddleware,
        ToolMiddlewareChain,
        get_default_chain,
    )

    class TruncateMiddleware(ToolResultMiddleware):
        name = "truncate"
        def transform(self, tool_name, result, context):
            if isinstance(result, str) and len(result) > 4000:
                return result[:4000] + "... [truncated]"
            return result

    chain = get_default_chain()
    chain.add(TruncateMiddleware())

    # Inside AIAgent._execute_tool_calls, call:
    result = chain.run(tool_name, raw_result, context)
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

from ..logging_config import get_logger

logger = get_logger("tool_middleware")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ToolResultMiddleware(ABC):
    """Base class for tool-result middleware.

    Implement :meth:`transform` to mutate or replace a tool result before
    it enters the agent conversation context.

    Attributes
    ----------
    name:
        Unique middleware identifier.
    runtimes:
        Optional list of runtime identifiers this middleware applies to
        (e.g. ``["pi", "codex", "cli"]``).  An empty list means *all* runtimes.
    """

    name: str = "base"
    runtimes: list[str] = []

    @abstractmethod
    def transform(
        self,
        tool_name: str,
        result: Any,
        context: dict[str, Any],
    ) -> Any:
        """Transform *result* and return the new value.

        Parameters
        ----------
        tool_name:
            The name of the tool that produced *result*.
        result:
            The raw tool output (string, dict, list, etc.).
        context:
            Session/task context (session_id, task_id, agent_id, etc.).

        Returns
        -------
        Any
            The transformed result.
        """


# ---------------------------------------------------------------------------
# Middleware chain
# ---------------------------------------------------------------------------


class ToolMiddlewareChain:
    """Ordered chain of :class:`ToolResultMiddleware` instances.

    Middleware is applied in registration order.  Exceptions inside a
    middleware are caught and logged; the un-transformed result from the
    previous step is passed to the next middleware.
    """

    def __init__(self, runtime: str = "") -> None:
        self._middleware: list[ToolResultMiddleware] = []
        self._lock = threading.Lock()
        self.runtime = runtime

    def add(self, middleware: ToolResultMiddleware) -> None:
        """Append *middleware* to the chain."""
        with self._lock:
            self._middleware.append(middleware)
        logger.debug("Added middleware '%s' to chain", middleware.name)

    def remove(self, name: str) -> bool:
        """Remove middleware by *name*. Returns True if found."""
        with self._lock:
            before = len(self._middleware)
            self._middleware = [m for m in self._middleware if m.name != name]
            return len(self._middleware) < before

    def run(
        self,
        tool_name: str,
        result: Any,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Apply all middleware to *result* and return the final value."""
        ctx = context or {}
        with self._lock:
            chain = list(self._middleware)

        current = result
        for mw in chain:
            if mw.runtimes and self.runtime and self.runtime not in mw.runtimes:
                continue
            try:
                current = mw.transform(tool_name, current, ctx)
            except Exception as exc:
                logger.warning(
                    "Middleware '%s' failed on tool '%s': %s",
                    mw.name, tool_name, exc,
                )
        return current

    @property
    def middleware_names(self) -> list[str]:
        with self._lock:
            return [m.name for m in self._middleware]

    def __len__(self) -> int:
        with self._lock:
            return len(self._middleware)


# ---------------------------------------------------------------------------
# Built-in middleware
# ---------------------------------------------------------------------------


class TruncateMiddleware(ToolResultMiddleware):
    """Truncate excessively long string results.

    The default limit (32 KB) matches the typical context-window budget
    for a single tool result.  Override ``max_chars`` to adjust.
    """

    name = "truncate"

    def __init__(self, max_chars: int = 32_768) -> None:
        self.max_chars = max_chars

    def transform(self, tool_name: str, result: Any, context: dict[str, Any]) -> Any:
        if isinstance(result, str) and len(result) > self.max_chars:
            logger.debug(
                "Truncating tool '%s' result from %d to %d chars",
                tool_name, len(result), self.max_chars,
            )
            return result[: self.max_chars] + f"\n... [truncated at {self.max_chars} chars]"
        return result


class JsonNormalizerMiddleware(ToolResultMiddleware):
    """Serialize dict/list results to JSON strings.

    Keeps the conversation context to plain strings, which is what most
    LLM providers expect.
    """

    name = "json_normalizer"

    def transform(self, tool_name: str, result: Any, context: dict[str, Any]) -> Any:
        if isinstance(result, (dict, list)):
            import json
            try:
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                return str(result)
        return result


class ErrorWrapperMiddleware(ToolResultMiddleware):
    """Wrap exception objects in a human-readable error string."""

    name = "error_wrapper"

    def transform(self, tool_name: str, result: Any, context: dict[str, Any]) -> Any:
        if isinstance(result, Exception):
            return f"[Tool error in '{tool_name}': {type(result).__name__}: {result}]"
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_chain: ToolMiddlewareChain | None = None
_chain_lock = threading.Lock()


def get_default_chain() -> ToolMiddlewareChain:
    """Return the process-wide default :class:`ToolMiddlewareChain`.

    The chain is pre-populated with :class:`ErrorWrapperMiddleware`,
    :class:`JsonNormalizerMiddleware`, and :class:`TruncateMiddleware`
    (in that order).
    """
    global _default_chain
    if _default_chain is None:
        with _chain_lock:
            if _default_chain is None:
                _default_chain = ToolMiddlewareChain()
                _default_chain.add(ErrorWrapperMiddleware())
                _default_chain.add(JsonNormalizerMiddleware())
                _default_chain.add(TruncateMiddleware())
    return _default_chain


def reset_default_chain() -> None:
    """Reset the singleton chain (useful in tests)."""
    global _default_chain
    with _chain_lock:
        _default_chain = None


__all__ = [
    "ToolResultMiddleware",
    "ToolMiddlewareChain",
    "TruncateMiddleware",
    "JsonNormalizerMiddleware",
    "ErrorWrapperMiddleware",
    "get_default_chain",
    "reset_default_chain",
]
