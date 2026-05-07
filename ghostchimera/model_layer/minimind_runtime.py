"""Ghost-native MiniMind architecture and optional runtime adapter.

The base Ghost Chimera install keeps this module dependency-light. It embeds
MiniMind architecture metadata and adapter contracts, then loads heavy
Transformers/PyTorch code only when a local model path is configured.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MINIMIND_SOURCE_URL = "https://github.com/jingyaogong/minimind"
MINIMIND_SOURCE_COMMIT = "dddedc688121028dd8adab55b95d139ecd87205c"
MINIMIND_LICENSE = "Apache-2.0"


@dataclass(frozen=True)
class MiniMindArchitectureSpec:
    """Dependency-free MiniMind architecture contract used by Ghost Chimera."""

    name: str
    parameter_count: str
    active_parameter_count: str
    release_date: str
    vocab_size: int
    max_position_embeddings: int
    rope_theta: float
    num_hidden_layers: int
    hidden_size: int
    num_key_value_heads: int
    num_attention_heads: int
    architecture: str
    num_experts: int = 0
    experts_per_token: int = 0
    status: str = "embedded"

    @property
    def head_dim(self) -> int:
        return self.hidden_size // self.num_attention_heads

    @property
    def intermediate_size(self) -> int:
        return math.ceil(self.hidden_size * math.pi / 64) * 64

    @property
    def uses_moe(self) -> bool:
        return self.num_experts > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "head_dim": self.head_dim,
                "intermediate_size": self.intermediate_size,
                "uses_moe": self.uses_moe,
                "source_url": MINIMIND_SOURCE_URL,
                "source_commit": MINIMIND_SOURCE_COMMIT,
                "license": MINIMIND_LICENSE,
            }
        )
        return payload


_ARCHITECTURE_ORDER = [
    "minimind-3",
    "minimind-3-moe",
    "minimind2-small",
    "minimind2-moe",
    "minimind2",
]

_ARCHITECTURES: dict[str, MiniMindArchitectureSpec] = {
    "minimind-3": MiniMindArchitectureSpec(
        name="minimind-3",
        parameter_count="64M",
        active_parameter_count="64M",
        release_date="2026-04-01",
        vocab_size=6400,
        max_position_embeddings=32768,
        rope_theta=1_000_000.0,
        num_hidden_layers=8,
        hidden_size=768,
        num_key_value_heads=4,
        num_attention_heads=8,
        architecture="dense",
    ),
    "minimind-3-moe": MiniMindArchitectureSpec(
        name="minimind-3-moe",
        parameter_count="198M",
        active_parameter_count="64M",
        release_date="2026-04-01",
        vocab_size=6400,
        max_position_embeddings=32768,
        rope_theta=1_000_000.0,
        num_hidden_layers=8,
        hidden_size=768,
        num_key_value_heads=4,
        num_attention_heads=8,
        architecture="moe",
        num_experts=4,
        experts_per_token=1,
    ),
    "minimind2-small": MiniMindArchitectureSpec(
        name="minimind2-small",
        parameter_count="26M",
        active_parameter_count="26M",
        release_date="2025-04-26",
        vocab_size=6400,
        max_position_embeddings=32768,
        rope_theta=1_000_000.0,
        num_hidden_layers=8,
        hidden_size=512,
        num_key_value_heads=2,
        num_attention_heads=8,
        architecture="dense-historical",
    ),
    "minimind2-moe": MiniMindArchitectureSpec(
        name="minimind2-moe",
        parameter_count="145M",
        active_parameter_count="145M",
        release_date="2025-04-26",
        vocab_size=6400,
        max_position_embeddings=32768,
        rope_theta=1_000_000.0,
        num_hidden_layers=8,
        hidden_size=640,
        num_key_value_heads=2,
        num_attention_heads=8,
        architecture="moe-historical",
        num_experts=4,
        experts_per_token=1,
    ),
    "minimind2": MiniMindArchitectureSpec(
        name="minimind2",
        parameter_count="104M",
        active_parameter_count="104M",
        release_date="2025-04-26",
        vocab_size=6400,
        max_position_embeddings=32768,
        rope_theta=1_000_000.0,
        num_hidden_layers=16,
        hidden_size=768,
        num_key_value_heads=2,
        num_attention_heads=8,
        architecture="dense-historical",
    ),
}

_PROFILE_ARCHITECTURE = {
    "tiny": "minimind2-small",
    "balanced": "minimind-3",
    "stronger": "minimind2",
}

_PACKAGE_RUNTIME_FACTORIES = ("load_model", "create_chat_model")
_MODEL_FILE_SUFFIXES = {".safetensors", ".bin", ".pth", ".gguf"}


@dataclass(frozen=True)
class MiniMindRuntimeInspection:
    """Resolved MiniMind runtime state without importing heavy model code."""

    architecture_embedded: bool
    architecture: dict[str, Any]
    package_found: bool
    package_importable: bool
    package_compatible: bool
    package_error: str
    workspace_found: bool
    workspace_compatible: bool
    workspace_root: str
    model_path: str
    model_files_found: bool
    optional_dependencies: dict[str, bool]
    inference_available: bool
    runtime_hint: str
    errors: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture_embedded": self.architecture_embedded,
            "architecture": dict(self.architecture),
            "package_found": self.package_found,
            "package_importable": self.package_importable,
            "package_compatible": self.package_compatible,
            "package_error": self.package_error,
            "workspace_found": self.workspace_found,
            "workspace_compatible": self.workspace_compatible,
            "workspace_root": self.workspace_root,
            "model_path": self.model_path,
            "model_files_found": self.model_files_found,
            "optional_dependencies": dict(self.optional_dependencies),
            "inference_available": self.inference_available,
            "runtime_hint": self.runtime_hint,
            "errors": list(self.errors),
            "notes": list(self.notes),
            "source": minimind_source_metadata(),
        }


class MiniMindTransformersRuntime:
    """Chat adapter for a local Transformers-format MiniMind model directory."""

    def __init__(self, model_path: str | Path) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.model_path = str(Path(model_path).expanduser())
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_path, trust_remote_code=True)
        self.model.eval().to(self.device)

    def chat(self, messages: list[dict[str, str]], *, max_context_tokens: int = 8192) -> str:
        max_new_tokens = int(os.environ.get("MINIMIND_MAX_NEW_TOKENS", "512"))
        if hasattr(self.tokenizer, "apply_chat_template"):
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            prompt = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in messages)
            prompt += "\nassistant:"

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_context_tokens,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            generated_ids = self.model.generate(
                inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=getattr(self.tokenizer, "pad_token_id", None)
                or getattr(self.tokenizer, "eos_token_id", None),
                eos_token_id=getattr(self.tokenizer, "eos_token_id", None),
            )
        new_tokens = generated_ids[0][len(inputs["input_ids"][0]) :]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def minimind_source_metadata() -> dict[str, str]:
    return {
        "url": MINIMIND_SOURCE_URL,
        "commit": MINIMIND_SOURCE_COMMIT,
        "license": MINIMIND_LICENSE,
        "integration": "Ghost-native architecture metadata and optional runtime adapter",
    }


def list_minimind_architectures() -> list[MiniMindArchitectureSpec]:
    return [_ARCHITECTURES[name] for name in _ARCHITECTURE_ORDER]


def get_minimind_architecture(name: str) -> MiniMindArchitectureSpec:
    key = _PROFILE_ARCHITECTURE.get(name.strip().lower(), name.strip().lower())
    try:
        return _ARCHITECTURES[key]
    except KeyError as exc:
        available = ", ".join(_ARCHITECTURE_ORDER)
        raise ValueError(f"Unknown MiniMind architecture '{name}'. Available architectures: {available}") from exc


def inspect_minimind_runtime(
    profile_name: str | None = None,
    *,
    state_dir: str | Path | None = None,
    root: str | Path | None = None,
    model_path: str | Path | None = None,
) -> MiniMindRuntimeInspection:
    del state_dir
    architecture = get_minimind_architecture(profile_name or os.environ.get("MINIMIND_ARCHITECTURE", "minimind-3"))
    errors: list[str] = []
    notes: list[str] = []

    package_spec = _safe_find_spec("minimind")
    package_found = package_spec is not None
    package_importable = False
    package_compatible = False
    package_error = ""
    if package_found:
        try:
            module = importlib.import_module("minimind")
            package_importable = True
            package_compatible = _is_package_runtime_compatible(module)
            if not package_compatible:
                notes.append("minimind package is importable but does not expose a Ghost-compatible chat runtime")
        except Exception as exc:
            package_error = f"{type(exc).__name__}: {exc}"
            errors.append(f"minimind package import failed: {package_error}")
    else:
        notes.append("minimind package is not installed; embedded architecture metadata remains available")

    root_path = _resolve_path(root or os.environ.get("MINIMIND_ROOT", ""))
    workspace_found = bool(root_path and root_path.exists())
    workspace_compatible = bool(
        workspace_found
        and (root_path / "model" / "model_minimind.py").exists()
        and (root_path / "eval_llm.py").exists()
    )
    if root_path and not root_path.exists():
        errors.append(f"MINIMIND_ROOT does not exist: {root_path}")
    elif workspace_found and not workspace_compatible:
        notes.append("MINIMIND_ROOT exists but does not look like an upstream MiniMind workspace")

    explicit_model_path = _resolve_path(model_path or os.environ.get("MINIMIND_MODEL_PATH", ""))
    discovered_model_path = explicit_model_path or _discover_model_path(root_path)
    model_files_found = bool(discovered_model_path and _has_model_files(discovered_model_path))
    if explicit_model_path and not explicit_model_path.exists():
        errors.append(f"MINIMIND_MODEL_PATH does not exist: {explicit_model_path}")
    if not model_files_found:
        notes.append("No MiniMind model weights were found; set MINIMIND_MODEL_PATH for local inference")

    optional_dependencies = {
        "torch": _module_available("torch"),
        "transformers": _module_available("transformers"),
        "tokenizers": _module_available("tokenizers"),
    }
    missing_runtime_deps = [name for name, ok in optional_dependencies.items() if not ok]
    if missing_runtime_deps:
        notes.append("Missing optional MiniMind inference dependencies: " + ", ".join(missing_runtime_deps))

    transformers_ready = model_files_found and all(optional_dependencies.values())
    inference_available = package_compatible or transformers_ready
    runtime_hint = _runtime_hint(
        package_compatible=package_compatible,
        transformers_ready=transformers_ready,
        workspace_compatible=workspace_compatible,
    )

    return MiniMindRuntimeInspection(
        architecture_embedded=True,
        architecture=architecture.to_dict(),
        package_found=package_found,
        package_importable=package_importable,
        package_compatible=package_compatible,
        package_error=package_error,
        workspace_found=workspace_found,
        workspace_compatible=workspace_compatible,
        workspace_root=str(root_path) if root_path else "",
        model_path=str(discovered_model_path) if discovered_model_path else "",
        model_files_found=model_files_found,
        optional_dependencies=optional_dependencies,
        inference_available=inference_available,
        runtime_hint=runtime_hint,
        errors=errors,
        notes=notes,
    )


def load_minimind_chat_runtime(
    profile_name: str | None = None,
    *,
    state_dir: str | Path | None = None,
    root: str | Path | None = None,
    model_path: str | Path | None = None,
    local_profile: dict[str, Any] | None = None,
) -> tuple[Any | None, MiniMindRuntimeInspection]:
    inspection = inspect_minimind_runtime(
        profile_name=profile_name,
        state_dir=state_dir,
        root=root,
        model_path=model_path,
    )
    architecture = get_minimind_architecture(profile_name or os.environ.get("MINIMIND_ARCHITECTURE", "minimind-3"))
    if inspection.package_compatible:
        module = importlib.import_module("minimind")
        return _load_package_runtime(module, profile_name=profile_name, architecture=architecture, local_profile=local_profile), inspection
    if inspection.model_files_found and all(inspection.optional_dependencies.values()):
        try:
            return MiniMindTransformersRuntime(inspection.model_path), inspection
        except Exception as exc:
            failed = MiniMindRuntimeInspection(
                architecture_embedded=inspection.architecture_embedded,
                architecture=inspection.architecture,
                package_found=inspection.package_found,
                package_importable=inspection.package_importable,
                package_compatible=inspection.package_compatible,
                package_error=inspection.package_error,
                workspace_found=inspection.workspace_found,
                workspace_compatible=inspection.workspace_compatible,
                workspace_root=inspection.workspace_root,
                model_path=inspection.model_path,
                model_files_found=inspection.model_files_found,
                optional_dependencies=inspection.optional_dependencies,
                inference_available=False,
                runtime_hint="embedded-architecture",
                errors=[*inspection.errors, f"MiniMind Transformers runtime failed to load: {exc}"],
                notes=inspection.notes,
            )
            return None, failed
    return None, inspection


def _load_package_runtime(
    minimind_module: Any,
    *,
    profile_name: str | None,
    architecture: MiniMindArchitectureSpec,
    local_profile: dict[str, Any] | None,
) -> Any:
    profile = dict(local_profile or {})
    profile.setdefault("name", profile_name or architecture.name)
    profile["minimind_architecture"] = architecture.to_dict()
    profile["minimind_source"] = minimind_source_metadata()
    for factory in _PACKAGE_RUNTIME_FACTORIES:
        if hasattr(minimind_module, factory):
            return getattr(minimind_module, factory)(profile)
    if hasattr(minimind_module, "llm_chat"):
        return minimind_module
    return None


def _runtime_hint(*, package_compatible: bool, transformers_ready: bool, workspace_compatible: bool) -> str:
    if package_compatible:
        return "package"
    if transformers_ready:
        return "transformers"
    if workspace_compatible:
        return "workspace"
    return "embedded-architecture"


def _is_package_runtime_compatible(module: Any) -> bool:
    return any(hasattr(module, name) for name in (*_PACKAGE_RUNTIME_FACTORIES, "llm_chat"))


def _module_available(module_name: str) -> bool:
    return _safe_find_spec(module_name) is not None


def _safe_find_spec(module_name: str) -> Any | None:
    if module_name in sys.modules:
        return getattr(sys.modules[module_name], "__spec__", object()) or object()
    try:
        return importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None


def _resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text).expanduser()


def _discover_model_path(root_path: Path | None) -> Path | None:
    if root_path is None or not root_path.exists():
        return None
    for candidate in (
        root_path / "minimind-3",
        root_path / "scripts" / "minimind-3",
        root_path / "minimind2-small",
        root_path / "out",
    ):
        if _has_model_files(candidate):
            return candidate
    return None


def _has_model_files(path: Path) -> bool:
    if path.is_file():
        return path.suffix.lower() in _MODEL_FILE_SUFFIXES
    if not path.is_dir():
        return False
    weight_files = [
        child
        for child in path.iterdir()
        if child.is_file() and child.suffix.lower() in _MODEL_FILE_SUFFIXES
    ]
    if not weight_files:
        return False
    return (path / "config.json").exists() or any(child.suffix.lower() in {".pth", ".gguf"} for child in weight_files)


__all__ = [
    "MINIMIND_LICENSE",
    "MINIMIND_SOURCE_COMMIT",
    "MINIMIND_SOURCE_URL",
    "MiniMindArchitectureSpec",
    "MiniMindRuntimeInspection",
    "MiniMindTransformersRuntime",
    "get_minimind_architecture",
    "inspect_minimind_runtime",
    "list_minimind_architectures",
    "load_minimind_chat_runtime",
    "minimind_source_metadata",
]
