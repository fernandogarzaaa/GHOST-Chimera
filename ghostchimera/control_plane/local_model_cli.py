"""Local model bootstrap CLI handler for ``ghostchimera local-model``."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

from ..model_layer.local_profiles import list_local_model_profiles

_INSTALL_GUIDANCE: dict[str, list[str]] = {
    "tiny": [
        "Install Ghost Chimera with local inference support:",
        "  pip install 'ghostchimera[local]'",
        "",
        "Download Qwen2.5-0.5B-Instruct-GGUF (Q4) weights (~350 MB) from Hugging Face:",
        "  huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF Qwen2.5-0.5B-Instruct-Q4_K_M.gguf --local-dir ./models",
        "",
        "Export the model path:",
        "  export MINIMIND_MODEL_PATH=./models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
        "",
        "Verify with:",
        "  ghostchimera minimind status",
    ],
    "balanced": [
        "Install Ghost Chimera with local inference support:",
        "  pip install 'ghostchimera[local]'",
        "",
        "Download SmolLM2-1.7B-Instruct-GGUF (Q4) weights (~1 GB) from Hugging Face:",
        "  huggingface-cli download HuggingFaceTB/SmolLM2-1.7B-Instruct-GGUF smollm2-1.7b-instruct-q4_k_m.gguf --local-dir ./models",
        "",
        "Export the model path:",
        "  export MINIMIND_MODEL_PATH=./models/smollm2-1.7b-instruct-q4_k_m.gguf",
        "",
        "Verify with:",
        "  ghostchimera minimind status",
    ],
    "stronger": [
        "Install Ghost Chimera with local inference support and GPU support:",
        "  pip install 'ghostchimera[local]'",
        "",
        "Download Phi-3.5-mini-instruct GGUF (Q4) weights (~2.2 GB) from Hugging Face:",
        "  huggingface-cli download microsoft/Phi-3.5-mini-instruct-gguf Phi-3.5-mini-instruct-Q4_K_M.gguf --local-dir ./models",
        "",
        "Export the model path (and GPU layers if a compatible GPU is present):",
        "  export MINIMIND_MODEL_PATH=./models/Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "  # Optional: export GHOSTCHIMERA_GPU_LAYERS=32  # offload layers to GPU",
        "",
        "Verify with:",
        "  ghostchimera minimind status",
    ],
}


def _detect_resources() -> dict[str, Any]:
    """Return an approximate system resource snapshot without external deps."""
    cpu_count = os.cpu_count() or 1

    # Approximate RAM from /proc/meminfo on Linux; fall back to None elsewhere
    ram_gb: float | None = None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    ram_gb = round(kb / (1024 * 1024), 1)
                    break
    except (OSError, ValueError):
        pass

    # Detect GPU by checking for nvidia-smi or rocm-smi
    gpu_detected = shutil.which("nvidia-smi") is not None or shutil.which("rocm-smi") is not None
    llama_cpp_available = False
    try:
        import llama_cpp  # noqa: F401

        llama_cpp_available = True
    except ImportError:
        pass

    return {
        "cpu_count": cpu_count,
        "ram_gb": ram_gb,
        "gpu_detected": gpu_detected,
        "llama_cpp_available": llama_cpp_available,
    }


def _profile_fit(profile_name: str, resources: dict[str, Any]) -> dict[str, Any]:
    from ..model_layer.local_profiles import get_local_model_profile

    profile = get_local_model_profile(profile_name)
    ram_gb = resources.get("ram_gb")
    gpu_vram_gb = resources.get("gpu_vram_gb", 0.0) or 0.0

    if ram_gb is None:
        fits = None
        fit_detail = "RAM unknown — cannot determine fit; install psutil for accurate detection"
    else:
        fits = ram_gb >= profile.estimated_system_ram_gb and gpu_vram_gb >= profile.estimated_gpu_vram_gb
        if fits:
            fit_detail = f"System RAM {ram_gb} GB >= required {profile.estimated_system_ram_gb} GB"
        else:
            reason_parts = []
            if ram_gb < profile.estimated_system_ram_gb:
                reason_parts.append(f"RAM {ram_gb} GB < required {profile.estimated_system_ram_gb} GB")
            if gpu_vram_gb < profile.estimated_gpu_vram_gb:
                reason_parts.append(f"VRAM {gpu_vram_gb} GB < required {profile.estimated_gpu_vram_gb} GB")
            fit_detail = "; ".join(reason_parts)

    return {
        "profile": profile_name,
        "model_id": profile.model_id,
        "quantization": profile.quantization,
        "max_context_tokens": profile.max_context_tokens,
        "estimated_system_ram_gb": profile.estimated_system_ram_gb,
        "estimated_gpu_vram_gb": profile.estimated_gpu_vram_gb,
        "prompt_template": profile.prompt_template,
        "fits_resources": fits,
        "fit_detail": fit_detail,
    }


def run_local_model_cli(action: str, profile: str = "") -> int:
    """Dispatch ``ghostchimera local-model <action>``."""
    resources = _detect_resources()

    if action == "profiles":
        profiles = list_local_model_profiles()
        results = []
        for p in profiles:
            results.append(_profile_fit(p.name, resources))
        print(json.dumps({"ok": True, "profiles": results, "resources": resources}, indent=2, sort_keys=True))
        return 0

    if action == "check":
        profile_name = profile.strip() or "balanced"
        fit = _profile_fit(profile_name, resources)
        model_path = os.environ.get("MINIMIND_MODEL_PATH", "")
        model_found = bool(model_path) and __import__("pathlib").Path(model_path).expanduser().exists()

        status: dict[str, Any] = {
            "ok": True,
            "profile": fit,
            "resources": resources,
            "model_path_env": model_path or None,
            "model_file_found": model_found,
            "llama_cpp_installed": resources["llama_cpp_available"],
            "recommendations": [],
        }
        recs: list[str] = []
        if not resources["llama_cpp_available"]:
            recs.append("Install llama-cpp-python: pip install 'ghostchimera[local]'")
        if not model_path:
            recs.append(f"Set MINIMIND_MODEL_PATH to a .gguf file for the '{profile_name}' profile")
        elif not model_found:
            recs.append(f"Model file not found at MINIMIND_MODEL_PATH={model_path!r}; download it first")
        if fit["fits_resources"] is False:
            recs.append(f"Resource constraint: {fit['fit_detail']} — consider the 'tiny' profile")
        if not recs:
            recs.append("System looks ready for local inference.")
        status["recommendations"] = recs
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0

    if action == "guide":
        profile_name = profile.strip() or "balanced"
        guidance = _INSTALL_GUIDANCE.get(profile_name)
        if guidance is None:
            available = ", ".join(sorted(_INSTALL_GUIDANCE))
            print(
                json.dumps(
                    {"ok": False, "error": f"No guide for profile '{profile_name}'. Available: {available}"}, indent=2
                )
            )
            return 1
        print(json.dumps({"ok": True, "profile": profile_name, "steps": guidance}, indent=2, sort_keys=True))
        return 0

    print(json.dumps({"ok": False, "error": f"Unknown action '{action}'. Use: check, guide, profiles"}, indent=2))
    return 1
