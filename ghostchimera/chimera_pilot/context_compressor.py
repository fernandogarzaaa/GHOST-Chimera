"""Automatic context window compression for long conversations.

Patterns adapted from Hermes-Agent's ContextCompressor (Nous Research, MIT licensed).
Ghost Chimera implements a deterministic compression path (no LLM dependency)
with optional LLM-guided summarization when available.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

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
_PRUNED_TOOL_MARKER = "[Old tool output cleared to save context space]"
_FAILURE_COOLDOWN_SECONDS = 600
_COMPRESSION_THRESHOLD = 0.75  # 75% of model context length

# Minimum protected messages at head/tail
_PROTECT_FIRST_N = 3
_PROTECT_LAST_N = 6
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
    "your",
}
_FILLER_RE = re.compile(
    r"\b(?:please note that|it is worth noting that|in order to|basically|actually|very|just|simply|clearly)\b",
    flags=re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")


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


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", str(text or ""))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@dataclass(frozen=True)
class QueryAwareCompressionResult:
    """Result for deterministic query-aware text compression."""

    ok: bool
    text: str
    original_tokens: int
    compressed_tokens: int
    original_chars: int
    compressed_chars: int
    focus_terms: list[str] = field(default_factory=list)
    code_blocks_preserved: int = 0
    passes_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "original_tokens": self.original_tokens,
            "compressed_tokens": self.compressed_tokens,
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "focus_terms": self.focus_terms,
            "code_blocks_preserved": self.code_blocks_preserved,
            "passes_applied": self.passes_applied,
        }


def compress_text_query_aware(text: str, *, budget_tokens: int = 800, focus: str = "") -> QueryAwareCompressionResult:
    """Compress text deterministically while preserving code and focus terms."""

    raw = str(text or "")
    original_tokens = _estimate_tokens(raw)
    if not raw.strip():
        return QueryAwareCompressionResult(True, "", 0, 0, 0, 0)

    stashed, blocks = _stash_code_blocks(raw)
    focus_terms = _extract_focus_terms(focus or raw)
    passes = ["code_block_stash"] if blocks else []
    normalized = _normalize_whitespace(_FILLER_RE.sub("", stashed))
    passes.append("filler_strip")
    units = _rank_compression_units(normalized, focus_terms)
    budget = max(8, int(budget_tokens))
    kept: list[str] = []
    used = 0
    for unit in units:
        cost = _estimate_tokens(unit["text"])
        if used + cost > budget and kept:
            continue
        kept.append(unit["text"])
        used += cost
        if used >= budget:
            break
    compressed = "\n".join(dict.fromkeys(kept)) if kept else normalized[: budget * _CHARS_PER_TOKEN]
    compressed = _restore_code_blocks(compressed, blocks)
    compressed = _normalize_whitespace(compressed)
    if _estimate_tokens(compressed) >= original_tokens and original_tokens > budget:
        compressed = compressed[: max(1, budget * _CHARS_PER_TOKEN)]
        compressed = _normalize_whitespace(compressed)
    passes.extend(["focus_rank", "dedupe"])
    return QueryAwareCompressionResult(
        ok=True,
        text=compressed,
        original_tokens=original_tokens,
        compressed_tokens=_estimate_tokens(compressed),
        original_chars=len(raw),
        compressed_chars=len(compressed),
        focus_terms=focus_terms,
        code_blocks_preserved=len(blocks),
        passes_applied=passes,
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(str(text or "")) // _CHARS_PER_TOKEN)


def _stash_code_blocks(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def stash(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return f"__GHOST_CODE_BLOCK_{len(blocks) - 1}__"

    return _CODE_BLOCK_RE.sub(stash, text), blocks


def _restore_code_blocks(text: str, blocks: list[str]) -> str:
    for index, block in enumerate(blocks):
        text = text.replace(f"__GHOST_CODE_BLOCK_{index}__", block)
    return text


def _token_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_./:-]+", text.lower()):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        terms.append(token[:80])
    return terms


def _extract_focus_terms(text: str, limit: int = 12) -> list[str]:
    counts = Counter(_token_terms(text))
    return [term for term, _count in counts.most_common(limit)]


def _rank_compression_units(text: str, focus_terms: list[str]) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"(?:\n\s*\n|(?<=[.!?])\s+)", text) if chunk.strip()]
    if not chunks:
        chunks = [text]
    focus = set(focus_terms)
    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        key = re.sub(r"\s+", " ", chunk.lower())
        if key in seen:
            continue
        seen.add(key)
        terms = set(_token_terms(chunk))
        score = len(terms & focus) * 4 + min(len(terms), 20) / 20
        if "__GHOST_CODE_BLOCK_" in chunk:
            score += 100
        ranked.append({"index": index, "text": chunk, "score": score})
    return sorted(ranked, key=lambda item: (-item["score"], item["index"]))


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
    def update_from_response(self, usage: dict[str, Any]) -> None:
        """Update tracked token usage from an API response."""

    @abstractmethod
    def should_compress(self, prompt_tokens: int = None) -> bool:
        """Return True if compaction should fire this turn."""

    @abstractmethod
    def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> list[dict[str, Any]]:
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
        self._compressed_messages: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def update_from_response(self, usage: dict[str, Any]) -> None:
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        threshold = prompt_tokens * self.threshold_percent if prompt_tokens is not None else self.threshold_tokens
        return threshold > 0 and (prompt_tokens or self.last_prompt_tokens) > threshold

    def should_compress_preflight(self, messages: list[dict[str, Any]]) -> bool:
        """Quick rough check before the API call."""
        total = sum(_content_length(m.get("content")) for m in messages)
        return total > self.threshold_tokens

    def has_content_to_compress(self, messages: list[dict[str, Any]]) -> bool:
        """Is there anything compressible?"""
        protected = self.protect_first_n + self.protect_last_n
        return len(messages) > protected + 2

    def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> list[dict[str, Any]]:
        """Compact the message list."""
        if not messages:
            return messages

        # Check cooldown
        if self._last_failure_time and (now() - self._last_failure_time) < _FAILURE_COOLDOWN_SECONDS:
            logger.info("Compression is in failure cooldown; attempting deterministic compression anyway")

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
        messages: list[dict[str, Any]],
        current_tokens: int | None,
        focus_topic: str | None,
    ) -> list[dict[str, Any]]:
        # Split into head / middle / tail
        protected = self.protect_first_n + self.protect_last_n
        if len(messages) <= protected:
            return messages  # nothing to compress

        head = messages[: self.protect_first_n]
        middle = messages[self.protect_first_n : -self.protect_last_n]
        tail = messages[-self.protect_last_n :]

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
        logger.info(
            "Compressed: %d messages -> %d (compression #%d)",
            len(messages),
            len(self._compressed_messages),
            self.compression_count,
        )
        return self._compressed_messages

    def _prune_tool_outputs(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Clear tool result content to save context space."""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                new_msg = dict(msg)
                new_msg["content"] = _PRUNED_TOOL_MARKER
                result.append(new_msg)
            else:
                result.append(msg)
        return result

    def _deterministic_summarize(
        self,
        messages: list[dict[str, Any]],
        budget: int,
    ) -> str:
        """Deterministic summarization: extract key information per turn."""
        sections = {"Resolved": [], "Pending": [], "Files": [], "Key Decisions": []}
        for msg in messages:
            role = msg.get("role", "")
            content = _content_text(msg.get("content"))
            if not content or content == _PRUNED_TOOL_MARKER:
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
            summary = summary[: budget - 50] + "\n\n[Summary truncated to budget]"
        return summary or "[No compressible content found in middle section]"

    def _llm_summarize(
        self,
        messages: list[dict[str, Any]],
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
            if content and content != _PRUNED_TOOL_MARKER:
                summarize_prompt += f"[{role}]: {content[:500]}\n\n"

        if focus_topic:
            summarize_prompt += f"\nSpecial focus topic: {focus_topic}"

        # In practice, this would call the auxiliary LLM client
        logger.info(
            "LLM summarization requested — %d messages, budget: %d tokens", len(messages), self.summary_budget_tokens
        )
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
