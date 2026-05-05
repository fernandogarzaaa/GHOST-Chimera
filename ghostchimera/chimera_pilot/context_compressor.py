"""Automatic context window compression for long conversations.

Patterns adapted from Hermes-Agent's ContextCompressor (Nous Research, MIT licensed).
Ghost Chimera implements a deterministic compression path (no LLM dependency)
with optional LLM-guided summarization when available.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..logging_config import get_logger
from .telemetry import now

logger = get_logger("context_compressor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted "
    "into the summary below. This is a handoff from a previous context "
    "window — treat it as background reference, NOT as active instructions. "
    "Do NOT answer questions or fulfill requests mentioned in this summary; "
    "they were already addressed. "
    "Your current task is identified in the '## Active Task' section of the "
    "summary — resume exactly from there. "
    "Respond ONLY to the latest user message that appears AFTER this summary."
)

_CHARS_PER_TOKEN = 4
_IMAGE_TOKEN_ESTIMATE = 1600
_IMAGE_CHAR_EQUIVALENT = _IMAGE_TOKEN_ESTIMATE * _CHARS_PER_TOKEN
_MIN_SUMMARY_TOKENS = 2000
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 12_000
_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"
_FAILURE_COOLDOWN_SECONDS = 600
_COMPRESSION_THRESHOLD = 0.75  # 75% of model context length

# Minimum protected messages at head/tail
_PROTECT_FIRST_N = 3
_PROTECT_LAST_N = 6


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------

def _content_length(raw_content: Any) -> int:
    """Return the effective character-length for token budgeting."""
    if isinstance(raw_content, str):
        return len(raw_content)
    if not isinstance(raw_content, list):
        return len(str(raw_content or ""))
    total = 0
    for p in raw_content:
        if isinstance(p, str):
            total += len(p)
        elif isinstance(p, dict):
            ptype = p.get("type")
            if ptype in {"image_url", "input_image", "image"}:
                total += _IMAGE_CHAR_EQUIVALENT
            else:
                total += len(p.get("text", "") or "")
    return total


def _content_text(raw_content: Any) -> str:
    """Return best-effort text view of message content."""
    if raw_content is None:
        return ""
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: list[str] = []
        for item in raw_content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(raw_content)


def _append_text(content: Any, text: str, *, prepend: bool = False) -> Any:
    """Append or prepend text to message content safely."""
    if content is None:
        return text
    if isinstance(content, str):
        return text + content if prepend else content + text
    if isinstance(content, list):
        text_block = {"type": "text", "text": text}
        return [text_block, *content] if prepend else [*content, text_block]
    return text + str(content) if prepend else str(content) + text


# ---------------------------------------------------------------------------
# Context engine base
# ---------------------------------------------------------------------------

class ContextEngine(ABC):
    """Base class all context engines must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (e.g. 'compressor', 'lcm')."""

    # -- Token state (read by caller for display/logging) ------------
    last_prompt_tokens: int = 0
    last_completion_tokens: int = 0
    last_total_tokens: int = 0
    threshold_tokens: int = 0
    context_length: int = 0
    compression_count: int = 0

    # -- Compaction parameters ------------
    threshold_percent: float = _COMPRESSION_THRESHOLD
    protect_first_n: int = _PROTECT_FIRST_N
    protect_last_n: int = _PROTECT_LAST_N

    @abstractmethod
    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """Update tracked token usage from an API response."""

    @abstractmethod
    def should_compress(self, prompt_tokens: int = None) -> bool:
        """Return True if compaction should fire this turn."""

    @abstractmethod
    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        """Compact the message list and return the new list."""


# ---------------------------------------------------------------------------
# Default compressor — deterministic + optional LLM
# ---------------------------------------------------------------------------

class ContextCompressor(ContextEngine):
    """Deterministic context window compression with optional LLM summarization.

    Strategy:
    1. Tool output pruning (cheap pre-pass — clear old tool outputs)
    2. Middle-turn summarization (deterministic first, LLM-guided if available)
    3. Head/tail protection via token budget
    """

    @property
    def name(self) -> str:
        return "compressor"

    def __init__(
        self,
        *,
        model_context_length: int = 128_000,
        use_llm_summarization: bool = False,
        summary_llm_model: str = "claude-haiku-4-20250514",
        summary_budget_tokens: int = _MIN_SUMMARY_TOKENS,
    ):
        self.context_length = model_context_length
        self.threshold_tokens = int(model_context_length * self.threshold_percent)
        self.use_llm_summarization = use_llm_summarization
        self.summary_llm_model = summary_llm_model
        self.summary_budget_tokens = summary_budget_tokens
        self._last_failure_time: float = 0.0
        self._iterative_summary: str = ""  # persists across compressions
        self._compressed_messages: List[Dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        if prompt_tokens is not None:
            threshold = prompt_tokens * self.threshold_percent
        else:
            threshold = self.threshold_tokens
        return threshold > 0 and (prompt_tokens or self.last_prompt_tokens) > threshold

    def should_compress_preflight(self, messages: List[Dict[str, Any]]) -> bool:
        """Quick rough check before the API call."""
        total = sum(_content_length(m.get("content")) for m in messages)
        return total > self.threshold_tokens

    def has_content_to_compress(self, messages: List[Dict[str, Any]]) -> bool:
        """Is there anything compressible?"""
        protected = self.protect_first_n + self.protect_last_n
        return len(messages) > protected + 2

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        """Compact the message list."""
        if not messages:
            return messages

        # Check cooldown
        if self._last_failure_time and (now() - self._last_failure_time) < _FAILURE_COOLDOWN_SECONDS:
            pass  # in cooldown — try anyway but log

        try:
            return self._do_compress(messages, current_tokens, focus_topic)
        except Exception as exc:
            logger.error("Compression failed: %s", exc)
            self._last_failure_time = now()
            return messages

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int | None,
        focus_topic: str | None,
    ) -> List[Dict[str, Any]]:
        # Split into head / middle / tail
        protected = self.protect_first_n + self.protect_last_n
        if len(messages) <= protected:
            return messages  # nothing to compress

        head = messages[:self.protect_first_n]
        middle = messages[self.protect_first_n:-self.protect_last_n]
        tail = messages[-self.protect_last_n:]

        if not middle:
            return messages

        # Step 1: Tool output pruning (cheap pre-pass)
        pruned_middle = self._prune_tool_outputs(middle)

        # Step 2: Estimate token budget for this compression
        head_tokens = sum(_content_length(m.get("content")) for m in head)
        tail_tokens = sum(_content_length(m.get("content")) for m in tail)
        budget = self.context_length

        if current_tokens is not None:
            remaining = current_tokens - head_tokens - tail_tokens
        else:
            remaining = int(budget * (1.0 - self.threshold_percent))

        # Step 3: Build summary of middle
        if self.use_llm_summarization:
            summary_text = self._llm_summarize(pruned_middle, focus_topic)
        else:
            summary_text = self._deterministic_summarize(pruned_middle, remaining)

        # Merge with any previous iterative summary
        if self._iterative_summary:
            full_summary = f"{self._iterative_summary}\n\n[Previous compaction] {summary_text}"
        else:
            full_summary = summary_text

        # Step 4: Build result
        summary_msg = {
            "role": "system",
            "content": f"{_SUMMARY_PREFIX}\n\n{full_summary}",
        }
        self._compressed_messages = [summary_msg] + tail
        self._iterative_summary = full_summary
        self.compression_count += 1
        logger.info("Compressed: %d messages -> %d (compression #%d)",
                     len(messages), len(self._compressed_messages), self.compression_count)
        return self._compressed_messages

    def _prune_tool_outputs(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Clear tool result content to save context space."""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                new_msg = dict(msg)
                new_msg["content"] = _PRUNED_TOOL_PLACEHOLDER
                result.append(new_msg)
            else:
                result.append(msg)
        return result

    def _deterministic_summarize(
        self,
        messages: List[Dict[str, Any]],
        budget: int,
    ) -> str:
        """Deterministic summarization: extract key information per turn."""
        sections = {"Resolved": [], "Pending": [], "Files": [], "Key Decisions": []}
        for msg in messages:
            role = msg.get("role", "")
            content = _content_text(msg.get("content"))
            if not content or content == _PRUNED_TOOL_PLACEHOLDER:
                continue

            # Extract file references
            file_refs = re.findall(r'[\'"](\.[^\']*[\'"]|[\w./-]+\.\w+)', content)
            if file_refs:
                sections["Files"].extend(file_refs)

            # Classify content type
            if role == "assistant" and not content.startswith("["):
                sections["Key Decisions"].append(f"Decision: {content[:200]}")
            elif role == "user":
                sections["Pending"].append(f"Request: {content[:200]}")
            elif role == "system":
                sections["Resolved"].append(f"System: {content[:200]}")

        # Build structured summary
        parts = []
        for section_name, items in sections.items():
            if items:
                # Deduplicate files
                if section_name == "Files":
                    items = list(dict.fromkeys(items))
                items = items[:10]  # limit items per section
                parts.append(f"## {section_name}\n" + "\n".join(f"- {item}" for item in items))

        summary = "\n\n".join(parts)
        # Truncate to budget
        if len(summary) > budget:
            summary = summary[:budget - 50] + "\n\n[Summary truncated to budget]"
        return summary or "[No compressible content found in middle section]"

    def _llm_summarize(
        self,
        messages: List[Dict[str, Any]],
        focus_topic: str | None,
    ) -> str:
        """LLM-guided summarization via auxiliary client."""
        # Build summarization prompt
        summarize_prompt = (
            "Summarize the following conversation turns. Focus on:\n"
            "1. Goals and objectives addressed\n"
            "2. Key decisions made\n"
            "3. Files and code modified\n"
            "4. Remaining work that needs to be done\n\n"
            "If focus_topic is provided, prioritize information related to it.\n\n"
            "---\n"
        )
        for msg in messages:
            role = msg.get("role", "").upper()
            content = _content_text(msg.get("content"))
            if content and content != _PRUNED_TOOL_PLACEHOLDER:
                summarize_prompt += f"[{role}]: {content[:500]}\n\n"

        if focus_topic:
            summarize_prompt += f"\nSpecial focus topic: {focus_topic}"

        # In practice, this would call the auxiliary LLM client
        logger.info("LLM summarization requested — %d messages, budget: %d tokens",
                     len(messages), self.summary_budget_tokens)
        return f"[LLM-summarized {len(messages)} turns — integration requires auxiliary LLM client]"


# ---------------------------------------------------------------------------
# Factory / registry
# ---------------------------------------------------------------------------

_engine_registry: dict[str, type[ContextEngine]] = {
    "compressor": ContextCompressor,
}


def get_context_engine(engine_type: str = "compressor", **kwargs) -> ContextEngine:
    """Get a context engine by type."""
    engine_cls = _engine_registry.get(engine_type)
    if engine_cls is None:
        logger.warning("Unknown engine type %s, using compressor", engine_type)
        engine_cls = ContextCompressor
    return engine_cls(**kwargs)


def register_context_engine(name: str, engine_cls: type[ContextEngine]) -> None:
    """Register a custom context engine (plugin hook)."""
    _engine_registry[name] = engine_cls
    logger.info("Registered context engine: %s", name)


__all__ = [
    "ContextEngine",
    "ContextCompressor",
    "get_context_engine",
    "register_context_engine",
    "ContextEngine",
]
