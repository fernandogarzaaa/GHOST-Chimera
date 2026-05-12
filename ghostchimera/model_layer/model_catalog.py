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
    # ── Groq ─────────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="groq",
        model_id="llama-3.3-70b-versatile",
        display_name="Llama 3.3 70B (Groq)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.00059,
        output_cost_usd_per_1k=0.00079,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="groq",
        model_id="llama-3.1-8b-instant",
        display_name="Llama 3.1 8B Instant (Groq)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.00005,
        output_cost_usd_per_1k=0.00008,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="groq",
        model_id="mixtral-8x7b-32768",
        display_name="Mixtral 8x7B (Groq)",
        context_window_tokens=32_768,
        input_cost_usd_per_1k=0.00024,
        output_cost_usd_per_1k=0.00024,
        supports_streaming=True,
    ),
    # ── xAI (Grok) ───────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="xai",
        model_id="grok-3-mini",
        display_name="Grok 3 Mini (xAI)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.0003,
        output_cost_usd_per_1k=0.0005,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="xai",
        model_id="grok-3",
        display_name="Grok 3 (xAI)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.003,
        output_cost_usd_per_1k=0.015,
        supports_streaming=True,
        supports_vision=True,
    ),
    # ── Mistral AI ────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="mistral",
        model_id="mistral-small-latest",
        display_name="Mistral Small (latest)",
        context_window_tokens=32_768,
        input_cost_usd_per_1k=0.0002,
        output_cost_usd_per_1k=0.0006,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="mistral",
        model_id="mistral-large-latest",
        display_name="Mistral Large (latest)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.002,
        output_cost_usd_per_1k=0.006,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="mistral",
        model_id="codestral-latest",
        display_name="Codestral (latest)",
        context_window_tokens=32_768,
        input_cost_usd_per_1k=0.001,
        output_cost_usd_per_1k=0.003,
        supports_streaming=True,
    ),
    # ── DeepSeek ─────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="deepseek",
        model_id="deepseek-chat",
        display_name="DeepSeek Chat (V3)",
        context_window_tokens=64_000,
        input_cost_usd_per_1k=0.00027,
        output_cost_usd_per_1k=0.00110,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="deepseek",
        model_id="deepseek-reasoner",
        display_name="DeepSeek Reasoner (R1)",
        context_window_tokens=64_000,
        input_cost_usd_per_1k=0.00055,
        output_cost_usd_per_1k=0.00219,
        supports_streaming=True,
    ),
    # ── Together AI ───────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="together",
        model_id="meta-llama/Llama-3-70b-chat-hf",
        display_name="Llama 3 70B Chat (Together)",
        context_window_tokens=8_192,
        input_cost_usd_per_1k=0.0009,
        output_cost_usd_per_1k=0.0009,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="together",
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        display_name="Llama 3.1 8B Turbo (Together)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.00018,
        output_cost_usd_per_1k=0.00018,
        supports_streaming=True,
    ),
    # ── OpenRouter ────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="openrouter",
        model_id="openai/gpt-4o-mini",
        display_name="GPT-4o mini via OpenRouter",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.00015,
        output_cost_usd_per_1k=0.0006,
        supports_streaming=True,
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="openrouter",
        model_id="meta-llama/llama-3.3-70b-instruct",
        display_name="Llama 3.3 70B Instruct via OpenRouter",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.00059,
        output_cost_usd_per_1k=0.00079,
        supports_streaming=True,
    ),
    # ── Ollama (local) ────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="ollama",
        model_id="llama3.2",
        display_name="Llama 3.2 (Ollama local)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.0,
        output_cost_usd_per_1k=0.0,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="ollama",
        model_id="mistral",
        display_name="Mistral 7B (Ollama local)",
        context_window_tokens=8_192,
        input_cost_usd_per_1k=0.0,
        output_cost_usd_per_1k=0.0,
        supports_streaming=True,
    ),
    # ── Cohere ────────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="cohere",
        model_id="command-r-plus",
        display_name="Command R+ (Cohere)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.0025,
        output_cost_usd_per_1k=0.010,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="cohere",
        model_id="command-r",
        display_name="Command R (Cohere)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.00015,
        output_cost_usd_per_1k=0.0006,
        supports_streaming=True,
    ),
    # ── Perplexity ────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="perplexity",
        model_id="llama-3.1-sonar-small-128k-online",
        display_name="Sonar Small Online (Perplexity)",
        context_window_tokens=127_072,
        input_cost_usd_per_1k=0.0002,
        output_cost_usd_per_1k=0.0002,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="perplexity",
        model_id="llama-3.1-sonar-large-128k-online",
        display_name="Sonar Large Online (Perplexity)",
        context_window_tokens=127_072,
        input_cost_usd_per_1k=0.001,
        output_cost_usd_per_1k=0.001,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="perplexity",
        model_id="llama-3.1-sonar-huge-128k-online",
        display_name="Sonar Huge Online (Perplexity)",
        context_window_tokens=127_072,
        input_cost_usd_per_1k=0.005,
        output_cost_usd_per_1k=0.005,
        supports_streaming=True,
    ),
    # ── Fireworks AI ──────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="fireworks",
        model_id="accounts/fireworks/models/llama-v3p1-70b-instruct",
        display_name="Llama 3.1 70B Instruct (Fireworks)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.0009,
        output_cost_usd_per_1k=0.0009,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="fireworks",
        model_id="accounts/fireworks/models/deepseek-r1",
        display_name="DeepSeek R1 (Fireworks)",
        context_window_tokens=163_840,
        input_cost_usd_per_1k=0.003,
        output_cost_usd_per_1k=0.008,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="fireworks",
        model_id="accounts/fireworks/models/qwen2p5-72b-instruct",
        display_name="Qwen 2.5 72B Instruct (Fireworks)",
        context_window_tokens=131_072,
        input_cost_usd_per_1k=0.0009,
        output_cost_usd_per_1k=0.0009,
        supports_streaming=True,
    ),
    # ── Cerebras ──────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="cerebras",
        model_id="llama3.1-70b",
        display_name="Llama 3.1 70B (Cerebras)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.0006,
        output_cost_usd_per_1k=0.0006,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="cerebras",
        model_id="llama3.1-8b",
        display_name="Llama 3.1 8B (Cerebras)",
        context_window_tokens=128_000,
        input_cost_usd_per_1k=0.0001,
        output_cost_usd_per_1k=0.0001,
        supports_streaming=True,
    ),
    # ── AI21 Labs ─────────────────────────────────────────────────────────────
    ModelCatalogEntry(
        provider="ai21",
        model_id="jamba-1.5-mini",
        display_name="Jamba 1.5 Mini (AI21)",
        context_window_tokens=256_000,
        input_cost_usd_per_1k=0.0002,
        output_cost_usd_per_1k=0.0004,
        supports_streaming=True,
    ),
    ModelCatalogEntry(
        provider="ai21",
        model_id="jamba-1.5-large",
        display_name="Jamba 1.5 Large (AI21)",
        context_window_tokens=256_000,
        input_cost_usd_per_1k=0.002,
        output_cost_usd_per_1k=0.008,
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
