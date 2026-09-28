"""Nemotron cloud reasoning for the Stealth Loop.

Optional UNDERSTAND / PREDICT enrichment: when ``NEBIUS_API_KEY`` is set,
the loop can consult NVIDIA Nemotron 3 models served by Nebius Token
Factory to interpret an observation and sharpen next-action predictions.
Nemotron 3 Nano handles the fast understanding calls; Nemotron 3 Super
handles the heavier reasoning.

Everything here is best-effort: failures return ``None`` and the
deterministic loop carries on unchanged. Events classified ``"secret"``
are never sent to the cloud.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..logging_config import get_logger
from .tavily_grounding import TavilyGrounding

logger = get_logger("nemotron_reasoning")

NEBIUS_PROVIDER_ID = "nebius"
NANO_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"

_UNDERSTAND_SYSTEM = (
    "You are the cloud reasoning backend for Ghost Chimera, a local-first "
    "ambient intelligence runtime. Given a compact event summary (and optional "
    "fresh web context), interpret what is happening. Respond with STRICT JSON "
    "only, no markdown fences, with keys: intent (short label), confidence "
    "(0-1), suggested_workflow (short label or empty string), risk_flags "
    "(list of short strings), rationale (one sentence)."
)

_PREDICT_SYSTEM = (
    "You are the cloud reasoning backend for Ghost Chimera. Given a short "
    "history summary, predict the user's most likely next actions. Respond "
    "with STRICT JSON only, no markdown fences: a list of objects with keys "
    "action (short label), probability (0-1), rationale (one sentence). "
    "At most 3 items."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


class NemotronReasoner:
    """Consult Nemotron 3 on Nebius Token Factory from the Stealth Loop."""

    def __init__(
        self,
        provider: Any | None = None,
        grounding: TavilyGrounding | None = None,
        reasoning_model: str = SUPER_MODEL,
    ) -> None:
        self._provider = provider if provider is not None else self._default_provider()
        self._grounding = grounding
        self._reasoning_model = reasoning_model
        self._reasoning_provider: Any | None = None

    @staticmethod
    def _default_provider() -> Any | None:
        try:
            from ..model_layer.providers import get_provider

            return get_provider(NEBIUS_PROVIDER_ID)
        except Exception as exc:
            logger.warning("Could not create Nebius provider: %s", exc)
            return None

    @property
    def available(self) -> bool:
        return self._provider is not None and bool(getattr(self._provider, "available", False))

    @property
    def provider(self) -> Any | None:
        return self._provider

    @property
    def grounding(self) -> TavilyGrounding | None:
        return self._grounding

    # -- UNDERSTAND --------------------------------------------------------

    def understand(
        self,
        event: Any,
        hypothesis: Any | None = None,
        predictions: Any | None = None,
    ) -> dict[str, Any] | None:
        """Interpret an event via Nemotron 3 Nano (or None on any failure)."""
        if not self.available:
            return None
        if str(getattr(event, "privacy_classification", "internal")) == "secret":
            logger.debug("Skipping cloud reasoning for secret-classified event")
            return None

        summary = self._event_summary(event, hypothesis, predictions)
        web_block = self._grounding_block(event)
        user_message = summary + web_block + "\n\nRespond with strict JSON only."

        try:
            raw = self._provider.chat(_UNDERSTAND_SYSTEM, user_message)
            data = json.loads(_strip_fences(raw))
        except Exception as exc:
            logger.warning("Nemotron understand call failed: %s", exc)
            return None
        if not isinstance(data, dict) or "intent" not in data:
            logger.warning("Nemotron understand returned unusable payload")
            return None
        data["provider"] = NEBIUS_PROVIDER_ID
        data["model"] = getattr(self._provider, "model", NANO_MODEL)
        if web_block:
            data["grounded_with_web"] = True
        return data

    # -- PREDICT -----------------------------------------------------------

    def predict_next(self, history_summary: str, hypothesis: str = "") -> list[dict[str, Any]] | None:
        """Sharpen next-action predictions via Nemotron 3 Super (or None)."""
        provider = self._reasoning_provider_instance()
        if provider is None:
            return None
        user_message = (
            f"Workflow hypothesis: {hypothesis}\nRecent history:\n{history_summary[:2000]}"
            "\n\nRespond with strict JSON only."
        )
        try:
            raw = provider.chat(_PREDICT_SYSTEM, user_message)
            data = json.loads(_strip_fences(raw))
        except Exception as exc:
            logger.warning("Nemotron predict call failed: %s", exc)
            return None
        if not isinstance(data, list):
            return None
        cleaned = []
        for item in data[:3]:
            if isinstance(item, dict) and "action" in item:
                cleaned.append(
                    {
                        "action": str(item.get("action", "")),
                        "probability": float(item.get("probability", 0.0) or 0.0),
                        "rationale": str(item.get("rationale", "")),
                        "provider": NEBIUS_PROVIDER_ID,
                        "model": self._reasoning_model,
                    }
                )
        return cleaned or None

    def _reasoning_provider_instance(self) -> Any | None:
        if self._reasoning_provider is not None:
            return self._reasoning_provider if getattr(self._reasoning_provider, "available", False) else None
        if not self.available:
            return None
        try:
            from ..model_layer.auth_profiles import AuthProfile
            from ..model_layer.providers import get_provider

            profile = AuthProfile(
                provider=NEBIUS_PROVIDER_ID,
                api_key=getattr(self._provider, "api_key", "") or os.environ.get("NEBIUS_API_KEY", ""),
                model=self._reasoning_model,
            )
            candidate = get_provider(NEBIUS_PROVIDER_ID, profile)
            if candidate is not None and getattr(candidate, "available", False):
                self._reasoning_provider = candidate
                return candidate
        except Exception as exc:
            logger.warning("Could not create Nemotron reasoning provider: %s", exc)
        return None

    # -- helpers -----------------------------------------------------------

    def _event_summary(self, event: Any, hypothesis: Any, predictions: Any) -> str:
        payload = getattr(event, "payload", None) or {}
        try:
            payload_text = json.dumps(payload, default=str)[:1500]
        except Exception:
            payload_text = str(payload)[:1500]
        lines = [
            f"event_type: {getattr(event, 'event_type', '')}",
            f"source: {getattr(event, 'source', '')}",
            f"payload: {payload_text}",
        ]
        if hypothesis is not None:
            lines.append(f"local_hypothesis: {getattr(hypothesis, 'name', hypothesis)}")
        if predictions:
            try:
                top = [getattr(p, "action", p) for p in list(predictions)[:3]]
                lines.append(f"local_predictions: {top}")
            except Exception:
                pass
        return "\n".join(lines)

    def _grounding_block(self, event: Any) -> str:
        if self._grounding is None or not self._grounding.available:
            return ""
        try:
            grounded = self._grounding.ground_event(event)
        except Exception as exc:
            logger.warning("Tavily grounding inside reasoner failed: %s", exc)
            return ""
        if not grounded:
            return ""
        snippets = []
        for hit in (grounded.get("results") or [])[:3]:
            snippets.append(f"- {hit.get('title', '')} ({hit.get('url', '')}): {hit.get('snippet', '')[:300]}")
        if not snippets:
            return ""
        joined = "\n".join(snippets)
        transport = grounded.get("transport", "?")
        return f"\n\nFresh web context (via Tavily, transport={transport}):\n{joined}"


# ---------------------------------------------------------------------------
# Environment-driven factory
# ---------------------------------------------------------------------------


def build_cloud_enhancements(
    *,
    enable_reasoning: bool | None = None,
    enable_grounding: bool | None = None,
) -> tuple[NemotronReasoner | None, TavilyGrounding | None]:
    """Build ``(reasoner, grounding)`` from the environment.

    Returns ``(None, None)`` when no keys are configured — the Stealth Loop
    then runs fully local, exactly as before. Set ``GHOSTCHIMERA_NEBIUS_REASONING=0``
    to force reasoning off even with a key present.
    """
    grounding: TavilyGrounding | None = None
    if enable_grounding is None:
        enable_grounding = bool(os.environ.get("TAVILY_API_KEY", ""))
    if enable_grounding:
        candidate = TavilyGrounding()
        if candidate.available:
            grounding = candidate

    reasoner: NemotronReasoner | None = None
    reasoning_flag = os.environ.get("GHOSTCHIMERA_NEBIUS_REASONING", "1")
    if enable_reasoning is None:
        enable_reasoning = reasoning_flag != "0" and bool(os.environ.get("NEBIUS_API_KEY", ""))
    if enable_reasoning:
        candidate = NemotronReasoner(grounding=grounding)
        if candidate.available:
            reasoner = candidate
        else:
            logger.warning("NEBIUS_API_KEY present but Nebius provider unavailable")
    return reasoner, grounding


__all__ = [
    "NemotronReasoner",
    "build_cloud_enhancements",
    "NANO_MODEL",
    "SUPER_MODEL",
    "NEBIUS_PROVIDER_ID",
]
