"""Local small-model profiles for constrained Ghost Chimera deployments."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LocalModelProfile:
    """Resource and runtime contract for a local model."""

    name: str
    model_id: str
    quantization: str
    max_context_tokens: int
    estimated_system_ram_gb: float
    estimated_gpu_vram_gb: float
    prompt_template: str
    provider_hint: str = "minimind"
    # Reasoning / serving hints (consumed by LlamaCppRuntime tuning).
    supports_thinking: bool = False
    recommended_kv_cache_type: str | None = None
    recommended_temperature: float = 0.0

    def fits_budget(self, *, system_ram_gb: float, gpu_vram_gb: float = 0.0) -> bool:
        return system_ram_gb >= self.estimated_system_ram_gb and gpu_vram_gb >= self.estimated_gpu_vram_gb

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


_PROFILES: dict[str, LocalModelProfile] = {
    "tiny": LocalModelProfile(
        name="tiny",
        model_id="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        quantization="q4",
        max_context_tokens=8192,
        estimated_system_ram_gb=2.0,
        estimated_gpu_vram_gb=0.0,
        prompt_template="qwen2.5-instruct",
    ),
    "balanced": LocalModelProfile(
        name="balanced",
        model_id="HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF",
        quantization="q4",
        max_context_tokens=8192,
        estimated_system_ram_gb=4.0,
        estimated_gpu_vram_gb=0.0,
        prompt_template="chatml",
    ),
    "stronger": LocalModelProfile(
        name="stronger",
        model_id="microsoft/Phi-3.5-mini-instruct",
        quantization="q4",
        max_context_tokens=8192,
        estimated_system_ram_gb=6.0,
        estimated_gpu_vram_gb=4.0,
        prompt_template="phi3",
    ),
    # Small reasoning model: a 1.7B that "thinks longer" can beat a single-pass
    # 8B on the 4GB/8GB target. Pairs with test-time compute + q8_0 KV cache.
    "reasoning": LocalModelProfile(
        name="reasoning",
        model_id="Qwen/Qwen3-1.7B-GGUF",
        quantization="q4_k_m",
        max_context_tokens=32768,
        estimated_system_ram_gb=4.0,
        estimated_gpu_vram_gb=0.0,
        prompt_template="qwen3-thinking",
        provider_hint="llamacpp",
        supports_thinking=True,
        recommended_kv_cache_type="q8_0",
        recommended_temperature=0.6,
    ),
}


def get_local_model_profile(name: str) -> LocalModelProfile:
    key = name.strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        available = ", ".join(sorted(_PROFILES))
        raise ValueError(f"Unknown local model profile '{name}'. Available profiles: {available}") from exc


def list_local_model_profiles() -> list[LocalModelProfile]:
    return [_PROFILES[name] for name in sorted(_PROFILES)]
