from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..logging_config import get_logger
from ..memory_layer.store import MemoryStore
from ..model_layer.minimind_runtime import load_minimind_chat_runtime

logger = get_logger("personal_context")


@dataclass(frozen=True)
class PersonalContextResult:
    ok: bool
    context: str
    sources: tuple[str, ...]
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "context": self.context,
            "sources": list(self.sources),
            "detail": self.detail,
        }


class PersonalContextProvider:
    """Build objective-scoped personal context from local memory.

    Default behavior is deterministic and offline: fetch top FTS matches from
    :class:`~ghostchimera.memory_layer.store.MemoryStore` and format them as
    excerpts. When MiniMind inference is available, it can optionally compress
    excerpts into a short brief for downstream models.
    """

    def __init__(
        self,
        *,
        memory_store: MemoryStore,
        enable_minimind: bool = True,
        minimind_profile: str | None = None,
        minimind_state_dir: str | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.enable_minimind = enable_minimind
        self.minimind_profile = minimind_profile
        self.minimind_state_dir = minimind_state_dir

    def context_for_objective(
        self,
        objective: str,
        *,
        limit: int = 5,
        max_excerpt_chars: int = 600,
        max_context_chars: int = 4000,
        summarize: bool = True,
    ) -> PersonalContextResult:
        query = (objective or "").strip()
        if not query:
            return PersonalContextResult(ok=True, context="", sources=(), detail="empty objective")

        results = self.memory_store.search(query, limit=limit)
        if not results:
            return PersonalContextResult(ok=True, context="", sources=(), detail="no memory hits")

        sources: list[str] = []
        excerpts: list[str] = []
        for item in results:
            source = str(item.get("source") or "").strip() or "memory"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            sources.append(source)
            snippet = content[: max(0, int(max_excerpt_chars))].strip()
            excerpts.append(f"- [{source}] {snippet}")

        excerpt_block = "\n".join(excerpts).strip()
        if not excerpt_block:
            return PersonalContextResult(ok=True, context="", sources=tuple(sources), detail="empty excerpts")

        if not self.enable_minimind or not summarize:
            return PersonalContextResult(
                ok=True,
                context=excerpt_block[:max_context_chars],
                sources=tuple(sources),
                detail="excerpts",
            )

        runtime, inspection = load_minimind_chat_runtime(self.minimind_profile, state_dir=self.minimind_state_dir)
        if runtime is None:
            return PersonalContextResult(
                ok=True,
                context=excerpt_block[:max_context_chars],
                sources=tuple(sources),
                detail=f"minimind unavailable ({inspection.runtime_hint})",
            )
        if inspection.runtime_hint == "dataset-adapter":
            return PersonalContextResult(
                ok=True,
                context=excerpt_block[:max_context_chars],
                sources=tuple(sources),
                detail="excerpts (dataset adapter reserved for direct MiniMind inference)",
            )

        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are Ghost Chimera's personal memory model. "
                        "Given the user's objective and memory excerpts, produce a concise, factual brief "
                        "containing only relevant details. Do not invent. Use bullet points."
                    ),
                },
                {"role": "user", "content": f"Objective:\n{query}\n\nMemory excerpts:\n{excerpt_block}"},
            ]
            summary = str(runtime.chat(messages, max_context_tokens=4096)).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MiniMind context summarization failed: %s", exc)
            return PersonalContextResult(
                ok=True,
                context=excerpt_block[:max_context_chars],
                sources=tuple(sources),
                detail=f"minimind error: {exc}",
            )

        if not summary:
            return PersonalContextResult(
                ok=True,
                context=excerpt_block[:max_context_chars],
                sources=tuple(sources),
                detail="minimind empty summary",
            )
        return PersonalContextResult(
            ok=True,
            context=summary[:max_context_chars],
            sources=tuple(sources),
            detail="minimind summary",
        )
