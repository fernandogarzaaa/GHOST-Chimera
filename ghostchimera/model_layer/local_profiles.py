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

    def fits_budget(self, *, system_ram_gb: float, gpu_vram_gb: float = 0.0) -> bool:
        return (
            system_ram_gb >= self.estimated_system_ram_gb
            and gpu_vram_gb >= self.estimated_gpu_vram_gb
        )

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
