"""Runtime specialization planning for local model execution.

This module adapts the CuTeDSL/ROSE idea to Ghost Chimera's current local
runtime surface: classify the workload, derive launch/load hints, and make the
chosen specialization visible to the scheduler and operator. It does not claim
to execute custom CuTeDSL kernels unless that runtime is explicitly installed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .local_profiles import LocalModelProfile, get_local_model_profile, list_local_model_profiles


class WorkloadPhase(StrEnum):
    """Inference phase selected from prompt and generation shape."""

    PREFILL = "prefill"
    DECODE = "decode"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Local accelerator/runtime facts used for specialization."""

    n_gpu_layers: int = 0
    architecture: str = ""
    sm_count: int | None = None
    cute_dsl_available: bool = False
    cute_dsl_reason: str = ""

    @property
    def has_gpu_offload(self) -> bool:
        return self.n_gpu_layers > 0

    @property
    def is_blackwell(self) -> bool:
        text = self.architecture.lower()
        return any(token in text for token in ("blackwell", "sm100", "sm120", "b100", "b200", "rtx 50"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkloadShape:
    """Approximate model workload shape for a single request."""

    input_tokens: int
    output_tokens: int
    batch_size: int = 1
    dtype: str = "bf16"
    hidden_dim: int | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def phase(self) -> WorkloadPhase:
        if self.output_tokens <= 4 and self.input_tokens <= 384:
            return WorkloadPhase.DECODE
        if self.output_tokens <= 16 and self.input_tokens > 384:
            return WorkloadPhase.HYBRID
        return WorkloadPhase.PREFILL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"phase": self.phase().value, "total_tokens": self.total_tokens}


@dataclass(frozen=True)
class RuntimeSpecializationPlan:
    """Concrete runtime plan selected for one local model request."""

    profile_name: str
    execution_path: str
    phase: WorkloadPhase
    kernel_family: str
    vector_width_elements: int
    load_width_bits: int
    recommended_warps: int
    use_grid_barrier: bool
    llama_cpp_n_batch: int
    cache_key: str
    cache_dir: str | None
    workload: WorkloadShape
    environment: RuntimeEnvironment
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "execution_path": self.execution_path,
            "phase": self.phase.value,
            "kernel_family": self.kernel_family,
            "vector_width_elements": self.vector_width_elements,
            "load_width_bits": self.load_width_bits,
            "recommended_warps": self.recommended_warps,
            "use_grid_barrier": self.use_grid_barrier,
            "llama_cpp_n_batch": self.llama_cpp_n_batch,
            "cache_key": self.cache_key,
            "cache_dir": self.cache_dir,
            "workload": self.workload.to_dict(),
            "environment": self.environment.to_dict(),
            "warnings": list(self.warnings),
        }


DEFAULT_WARMUP_WORKLOADS: tuple[tuple[str, WorkloadShape], ...] = (
    ("decode_short", WorkloadShape(input_tokens=128, output_tokens=2, dtype="q4")),
    ("hybrid_context", WorkloadShape(input_tokens=1024, output_tokens=8, dtype="q4")),
    ("prefill_long", WorkloadShape(input_tokens=2048, output_tokens=256, dtype="q4")),
)


def estimate_tokens(text: str) -> int:
    """Return a deterministic rough token estimate without external tokenizers."""

    stripped = text.strip()
    if not stripped:
        return 1
    return max(1, math.ceil(len(stripped) / 4))


def workload_from_messages(
    *,
    system_message: str = "",
    user_message: str = "",
    estimated_output_tokens: int = 128,
    batch_size: int = 1,
    dtype: str = "bf16",
    hidden_dim: int | None = None,
) -> WorkloadShape:
    return WorkloadShape(
        input_tokens=estimate_tokens(f"{system_message}\n{user_message}"),
        output_tokens=max(1, int(estimated_output_tokens)),
        batch_size=max(1, int(batch_size)),
        dtype=dtype,
        hidden_dim=hidden_dim,
    )


def detect_runtime_environment(
    *,
    n_gpu_layers: int = 0,
    architecture: str | None = None,
    sm_count: int | None = None,
) -> RuntimeEnvironment:
    arch = architecture or os.environ.get("GHOSTCHIMERA_GPU_ARCH", "")
    sm = sm_count if sm_count is not None else _int_from_env("GHOSTCHIMERA_GPU_SM_COUNT")
    cute_available = importlib.util.find_spec("cutlass") is not None
    reason = "cutlass module available" if cute_available else "nvidia-cutlass-dsl is not installed"
    return RuntimeEnvironment(
        n_gpu_layers=max(0, int(n_gpu_layers)),
        architecture=arch,
        sm_count=sm,
        cute_dsl_available=cute_available,
        cute_dsl_reason=reason,
    )


def plan_runtime_specialization(
    *,
    profile: LocalModelProfile,
    workload: WorkloadShape,
    environment: RuntimeEnvironment,
    cache_dir: str | None = None,
) -> RuntimeSpecializationPlan:
    """Select the best available local-runtime specialization."""

    phase = workload.phase()
    load_width_bits = 256 if environment.is_blackwell else 128
    vector_width = _vector_width_elements(workload.dtype or profile.quantization, load_width_bits)
    recommended_warps = _recommended_warps(phase=phase, workload=workload, sm_count=environment.sm_count)
    use_grid_barrier = (
        phase == WorkloadPhase.DECODE and bool(environment.sm_count) and workload.batch_size <= environment.sm_count
    )

    if not environment.has_gpu_offload:
        execution_path = "llama_cpp.cpu"
        kernel_family = "cpu_reference"
    elif environment.cute_dsl_available:
        execution_path = "llama_cpp.gpu_with_cute_dsl_hints"
        kernel_family = f"cute_dsl_{phase.value}"
    else:
        execution_path = "llama_cpp.gpu"
        kernel_family = f"llama_cpp_{phase.value}"

    warnings: list[str] = []
    if environment.has_gpu_offload and not environment.cute_dsl_available:
        warnings.append(environment.cute_dsl_reason)
    if workload.hidden_dim is None:
        warnings.append("hidden_dim not configured; using token-shape heuristics")

    n_batch = _llama_cpp_n_batch(phase=phase, workload=workload)
    cache_key = _cache_key(
        {
            "profile": profile.to_dict(),
            "workload": workload.to_dict(),
            "environment": environment.to_dict(),
            "load_width_bits": load_width_bits,
            "vector_width": vector_width,
            "warps": recommended_warps,
            "n_batch": n_batch,
        }
    )
    resolved_cache_dir = str(Path(cache_dir).expanduser()) if cache_dir else None
    plan = RuntimeSpecializationPlan(
        profile_name=profile.name,
        execution_path=execution_path,
        phase=phase,
        kernel_family=kernel_family,
        vector_width_elements=vector_width,
        load_width_bits=load_width_bits,
        recommended_warps=recommended_warps,
        use_grid_barrier=use_grid_barrier,
        llama_cpp_n_batch=n_batch,
        cache_key=cache_key,
        cache_dir=resolved_cache_dir,
        workload=workload,
        environment=environment,
        warnings=tuple(warnings),
    )
    if resolved_cache_dir:
        write_specialization_manifest(plan)
    return plan


def write_specialization_manifest(plan: RuntimeSpecializationPlan) -> Path:
    """Persist a specialization manifest for warmup/replay diagnostics."""

    if not plan.cache_dir:
        raise ValueError("Cannot write specialization manifest without cache_dir")
    path = Path(plan.cache_dir).expanduser() / f"{plan.cache_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def warm_runtime_specialization_cache(
    *,
    cache_dir: str,
    profile_names: Iterable[str] | None = None,
    environment: RuntimeEnvironment | None = None,
    workloads: Iterable[tuple[str, WorkloadShape]] | None = None,
) -> dict[str, Any]:
    """Precompute specialization manifests for representative local workloads."""

    resolved_cache = Path(cache_dir).expanduser()
    profiles = _resolve_profiles(profile_names)
    env = environment or detect_runtime_environment()
    selected_workloads = tuple(workloads or DEFAULT_WARMUP_WORKLOADS)
    plans: list[dict[str, Any]] = []
    manifest_paths: list[str] = []
    for profile in profiles:
        for workload_name, workload in selected_workloads:
            workload_for_profile = WorkloadShape(
                input_tokens=workload.input_tokens,
                output_tokens=workload.output_tokens,
                batch_size=workload.batch_size,
                dtype=workload.dtype or profile.quantization,
                hidden_dim=workload.hidden_dim,
            )
            plan = plan_runtime_specialization(
                profile=profile,
                workload=workload_for_profile,
                environment=env,
                cache_dir=str(resolved_cache),
            )
            manifest_path = resolved_cache / f"{plan.cache_key}.json"
            manifest_paths.append(str(manifest_path))
            plans.append(
                {
                    "workload_name": workload_name,
                    "manifest_path": str(manifest_path),
                    "plan": plan.to_dict(),
                }
            )

    index = {
        "ok": True,
        "created_at": time.time(),
        "cache_dir": str(resolved_cache),
        "environment": env.to_dict(),
        "profiles": [profile.name for profile in profiles],
        "workload_count": len(selected_workloads),
        "manifest_count": len(manifest_paths),
        "manifest_paths": manifest_paths,
        "plans": plans,
    }
    resolved_cache.mkdir(parents=True, exist_ok=True)
    index_path = resolved_cache / "index.json"
    index["index_path"] = str(index_path)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    return index


def _resolve_profiles(profile_names: Iterable[str] | None) -> list[LocalModelProfile]:
    names = [name for name in (profile_names or []) if name]
    if not names:
        return list_local_model_profiles()
    return [get_local_model_profile(name) for name in names]


def _int_from_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _vector_width_elements(dtype: str, load_width_bits: int) -> int:
    bits = {
        "float32": 32,
        "fp32": 32,
        "f32": 32,
        "bfloat16": 16,
        "bf16": 16,
        "float16": 16,
        "fp16": 16,
        "f16": 16,
        "fp8": 8,
        "mxfp8": 8,
        "int8": 8,
        "q8": 8,
        "q4": 4,
        "mxfp4": 4,
        "nvfp4": 4,
    }.get(dtype.strip().lower(), 16)
    return max(1, load_width_bits // bits)


def _recommended_warps(*, phase: WorkloadPhase, workload: WorkloadShape, sm_count: int | None) -> int:
    if phase == WorkloadPhase.DECODE:
        return 1
    token_work = workload.total_tokens * workload.batch_size
    if sm_count and token_work < sm_count * 8:
        return 1
    if token_work >= 4096:
        return 16
    if token_work >= 1024:
        return 8
    return 4 if phase == WorkloadPhase.PREFILL else 2


def _llama_cpp_n_batch(*, phase: WorkloadPhase, workload: WorkloadShape) -> int:
    if phase == WorkloadPhase.DECODE:
        return 128
    if phase == WorkloadPhase.HYBRID:
        return min(1024, max(256, _round_up_power_of_two(workload.input_tokens)))
    return min(2048, max(512, _round_up_power_of_two(workload.input_tokens)))


def _round_up_power_of_two(value: int) -> int:
    value = max(1, int(value))
    return 1 << (value - 1).bit_length()


def _cache_key(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


__all__ = [
    "RuntimeEnvironment",
    "RuntimeSpecializationPlan",
    "WorkloadPhase",
    "WorkloadShape",
    "DEFAULT_WARMUP_WORKLOADS",
    "detect_runtime_environment",
    "estimate_tokens",
    "plan_runtime_specialization",
    "warm_runtime_specialization_cache",
    "workload_from_messages",
    "write_specialization_manifest",
]
