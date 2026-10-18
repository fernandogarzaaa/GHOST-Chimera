"""Turn an OpenAI-style chat message into the answer, minus any reasoning trace.

Reasoning models (NVIDIA Nemotron 3 Nano/Super on Nebius Token Factory,
DeepSeek-R1, Qwen3, ...) spend output tokens on a reasoning trace before the
answer. Depending on the server the trace arrives either inline as
``<think>...</think>`` in ``content`` or in a separate ``reasoning_content``
(or ``reasoning``) field. Callers only ever want the answer, so:

* ``<think>`` blocks are stripped from ``content``;
* ``reasoning_content`` / ``reasoning`` are ignored, never used as a fallback
  answer (they are scratch work, not a reply, and may echo the prompt);
* an answer that is empty after stripping raises :class:`EmptyModelAnswer`
  rather than returning ``""`` so failover chains move on and callers see
  why (usually ``max_tokens`` ran out while the model was still thinking).
"""

from __future__ import annotations

import os
import re
from typing import Any

__all__ = [
    "DEFAULT_MAX_TOKENS",
    "EmptyModelAnswer",
    "extract_answer",
    "resolve_max_tokens",
    "strip_reasoning",
]

#: Default completion budget. Large enough for a reasoning trace plus a JSON
#: answer; small enough to bound cost and latency.
DEFAULT_MAX_TOKENS = 2048

#: Global override for every OpenAI-compatible provider.
MAX_TOKENS_ENV_VAR = "GHOSTCHIMERA_MAX_TOKENS"

_THINK_BLOCK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK = re.compile(r"<(think|thinking|reasoning)>.*\Z", re.IGNORECASE | re.DOTALL)
_ORPHAN_CLOSE = re.compile(r"</(think|thinking|reasoning)>", re.IGNORECASE)


class EmptyModelAnswer(RuntimeError):
    """The model returned no usable answer (only reasoning, or nothing)."""


def strip_reasoning(text: str | None) -> str:
    """Remove reasoning traces from ``text`` and return the stripped answer.

    Handles complete ``<think>...</think>`` blocks, an unclosed ``<think>``
    (the trace was cut off by ``max_tokens``: there is no answer), and an
    orphan ``</think>`` (some chat templates open the tag in the prompt, so
    only the close appears in the output: everything before it is trace).
    """
    if not text:
        return ""
    cleaned = _THINK_BLOCK.sub("", text)
    closes = list(_ORPHAN_CLOSE.finditer(cleaned))
    if closes:
        cleaned = cleaned[closes[-1].end() :]
    cleaned = _UNCLOSED_THINK.sub("", cleaned)
    return cleaned.strip()


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content-parts form: [{"type": "text", "text": ...}]
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type", "text") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def extract_answer(response_json: dict[str, Any], provider_name: str = "provider") -> str:
    """Return the answer text from an OpenAI-style chat completion response.

    Raises ``RuntimeError`` when ``choices`` is missing and
    :class:`EmptyModelAnswer` when nothing is left after stripping reasoning.
    """
    choices = response_json.get("choices")
    if not choices:
        raise RuntimeError(f"{provider_name} response missing choices")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    answer = strip_reasoning(_content_text(message.get("content")))
    if answer:
        return answer
    finish = choice.get("finish_reason")
    had_reasoning = bool(message.get("reasoning_content") or message.get("reasoning"))
    hint = ""
    if finish == "length" or had_reasoning:
        hint = f" (finish_reason={finish!r}; raise max_tokens via {MAX_TOKENS_ENV_VAR} or the provider's *_MAX_TOKENS)"
    raise EmptyModelAnswer(f"{provider_name} returned an empty answer after removing the reasoning trace{hint}")


def resolve_max_tokens(provider_env_var: str = "", default: int = DEFAULT_MAX_TOKENS) -> int:
    """Pick ``max_tokens``: provider env var, then global env var, then default.

    Non-numeric or non-positive values are ignored.
    """
    for var in (provider_env_var, MAX_TOKENS_ENV_VAR):
        if not var:
            continue
        raw = os.environ.get(var, "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return default
