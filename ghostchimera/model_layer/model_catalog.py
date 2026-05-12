"""Model catalog — statically known model metadata.

Mirrors OpenClaw's ``ModelCatalogEntry`` pattern.  The catalog lets the
Chimera Pilot scheduler compute *real* cost estimates for registered
providers/models instead of always returning ``0.0``.

Usage::

    from ghostchimera.model_layer.model_catalog import get_catalog_entry, list_catalog

    entry = get_catalog_entry("openai", "gpt-4o-mini")
    if entry:
        cost = (tokens / 1000) * entry.input_cost_usd_per_1k

Adding a new model is a single-line dict entry in ``_CATALOG``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCatalogEntry:
    """Static metadata for a known provider/model combination.

    Attributes
    ----------
    provider:
        Provider name, e.g. ``"openai"`` or ``"anthropic"``.
    model_id:
        Model identifier as used in API requests.
    display_name:
        Human-readable name.
    context_window_tokens:
        Maximum context window size in tokens.
    input_cost_usd_per_1k:
        Cost in USD per 1 000 input tokens (``0.0`` if unknown/free).
    output_cost_usd_per_1k:
        Cost in USD per 1 000 output tokens (``0.0`` if unknown/free).
    supports_streaming:
        Whether the model supports streaming completions.
    supports_vision:
        Whether the model accepts image inputs.
    """

    provider: str
    model_id: str
    display_name: str
    context_window_tokens: int
    input_cost_usd_per_1k: float = 0.0
    output_cost_usd_per_1k: float = 0.0
    supports_streaming: bool = False
    supports_vision: bool = False

    def estimate_cost_usd(self, input_tokens: int, output_tokens: int = 0) -> float:
        """Estimate total request cost in USD for the given token counts."""
        return (
            (input_tokens / 1000.0) * self.input_cost_usd_per_1k
            + (output_tokens / 1000.0) * self.output_cost_usd_per_1k
        )


# ---------------------------------------------------------------------------
# Catalog data
# Pricing reflects public list prices as of 2025-05. Update as needed.
# ---------------------------------------------------------------------------

_CATALOG: list[ModelCatalogEntry] = [
    # ── OpenAI ──────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-3.5-turbo",
        display_name="GPT-3.5 Turbo",
        context_window_tokens=16_385,
        input_cost_usd_per_1k=0.0005,
        output_cost_usd_per_1k=0.0015,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o",
        display_name="GPT-4o",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.005,
        output_cost_usd_per_1k=0.015,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4o-mini",
        display_name="GPT-4o mini",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.00015,
        output_cost_usd_per_1k=0.0006,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="openai",
        model_id="gpt-4-turbo",
        display_name="GPT-4 Turbo",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.01,
        output_cost_usd_per_1k=0.03,
        supports_streaming=True,
        supports_vision=True,
    ),
    # ── Anthropic ────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        context_window_tokens=200_000,
        input_cost_usd_per_1k=0.0008,
        output_cost_usd_per_1k=0.004,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        context_window_tokens=200_000,
        input_cost_usd_per_1k=0.003,
        output_cost_usd_per_1k=0.015,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model_id="claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        context_window_tokens=200_000,
        input_cost_usd_per_1k=0.015,
        output_cost_usd_per_1k=0.075,
        supports_streaming=True,
        supports_vision=True,
    ),
    # ── Local / free ────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="llamacpp",
        model_id="local",
        display_name="Local GGUF (llama.cpp)",
        context_window_tokens=4_096,
        input_cost_usd_per_1k=0.0,
        output_cost_usd_per_1k=0.0,
    ),
    ModelCatalogEntry(
        provider="minimind",
        model_id="local",
        display_name="Local MiniMind",
        context_window_tokens=2_048,
        input_cost_usd_per_1k=0.0,
        output_cost_usd_per_1k=0.0,
    ),
    # ── Google Gemini (AI Studio) ────────────────────────────────────────────
    ModelCatalogEntry(
        provider="gemini",
        model_id="gemini-2.0-flash-exp",
        display_name="Gemini 2.0 Flash (Experimental)",
        context_window_tokens=1_000_000,
        input_cost_usd_per_1k=0.0,
        output_cost_usd_per_1k=0.0,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="gemini",
        model_id="gemini-1.5-pro",
        display_name="Gemini 1.5 Pro",
        context_window_tokens=1_000_000,
        input_cost_usd_per_1k=0.00125,
        output_cost_usd_per_1k=0.005,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="gemini",
        model_id="gemini-1.5-flash",
        display_name="Gemini 1.5 Flash",
        context_window_tokens=1_000_000,
        input_cost_usd_per_1k=0.000075,
        output_cost_usd_per_1k=0.0003,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="gemini",
        model_id="gemini-1.0-pro",
        display_name="Gemini 1.0 Pro",
        context_window_tokens=32_760,
        input_cost_usd_per_1k=0.0005,
        output_cost_usd_per_1k=0.0015,
        supports_streaming=True,
    ),
]

# Build a quick lookup index: (provider, model_id) -> entry
_INDEX: dict[tuple[str, str], ModelCatalogEntry] = {
    (e.provider, e.model_id): e for e in _CATALOG
}


def get_catalog_entry(provider: str, model_id: str) -> ModelCatalogEntry | None:
    """Return the catalog entry for *provider*/*model_id*, or ``None``."""
    return _INDEX.get((provider, model_id))


def list_catalog(provider: str | None = None) -> list[ModelCatalogEntry]:
    """Return all catalog entries, optionally filtered to *provider*."""
    if provider is None:
        return list(_CATALOG)
    return [e for e in _CATALOG if e.provider == provider]


__all__ = ["ModelCatalogEntry", "get_catalog_entry", "list_catalog"]
