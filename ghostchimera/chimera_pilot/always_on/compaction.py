"""Automatic context compaction for always-on sessions.

:class:`AutoCompactor` wraps :class:`ContextCompressor` and fires compaction
automatically once a session crosses its token budget threshold. Continuity
is preserved through the compressor's iterative summary, which the daemon
persists into the durable session after every wake cycle so a restart never
loses what earlier context windows established.
"""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ..context_compressor import ContextCompressor

logger = get_logger("always_on.compaction")

DEFAULT_THRESHOLD_PERCENT = 0.75


class AutoCompactor:
    """Budget-driven automatic compaction around a ContextCompressor."""

    def __init__(
        self,
        *,
        model_context_length: int = 128_000,
        threshold_percent: float = DEFAULT_THRESHOLD_PERCENT,
        use_llm_summarization: bool = False,
        compressor: ContextCompressor | None = None,
    ) -> None:
        if not 0.0 < threshold_percent < 1.0:
            raise ValueError("threshold_percent must be between 0 and 1")
        self.model_context_length = model_context_length
        self.threshold_percent = threshold_percent
        self.compressor = compressor or ContextCompressor(
            model_context_length=model_context_length,
            use_llm_summarization=use_llm_summarization,
        )
        # Keep the wrapped compressor's own threshold in sync.
        self.compressor.threshold_percent = threshold_percent
        self.compressor.threshold_tokens = int(model_context_length * threshold_percent)
        self._auto_compactions = 0

    @property
    def threshold_tokens(self) -> int:
        return int(self.model_context_length * self.threshold_percent)

    @property
    def auto_compactions(self) -> int:
        return self._auto_compactions

    def over_budget(self, messages: list[dict[str, Any]]) -> bool:
        """True when the message list crosses the compaction threshold."""
        return self.compressor.should_compress_preflight(messages)

    def maybe_compact(
        self,
        messages: list[dict[str, Any]],
        *,
        focus_topic: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Compact when over budget; otherwise return messages untouched.

        Returns ``(messages, did_compact)``. The iterative summary inside the
        compressor carries continuity forward across repeated compactions.
        """
        if not messages:
            return messages, False
        if not self.over_budget(messages):
            return messages, False
        if not self.compressor.has_content_to_compress(messages):
            return messages, False
        compacted = self.compressor.compress(messages, focus_topic=focus_topic)
        self._auto_compactions += 1
        logger.info(
            "Auto-compaction #%d: %d -> %d messages (threshold %d tokens)",
            self._auto_compactions,
            len(messages),
            len(compacted),
            self.threshold_tokens,
        )
        return compacted, True

    def get_compaction_state(self) -> dict[str, Any]:
        """Export the continuity record for durable storage."""
        return self.compressor.get_compaction_state()

    def set_compaction_state(self, state: dict[str, Any] | None) -> None:
        """Restore the continuity record (e.g. after a daemon restart)."""
        self.compressor.set_compaction_state(state)

    def stats(self) -> dict[str, Any]:
        return {
            "model_context_length": self.model_context_length,
            "threshold_percent": self.threshold_percent,
            "threshold_tokens": self.threshold_tokens,
            "auto_compactions": self._auto_compactions,
            "compressor_compactions": self.compressor.compression_count,
            "has_iterative_summary": bool(self.compressor.get_compaction_state().get("iterative_summary")),
        }


__all__ = ["AutoCompactor", "DEFAULT_THRESHOLD_PERCENT"]
