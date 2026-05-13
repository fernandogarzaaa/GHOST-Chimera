"""MiniMind lifecycle helpers for local-first Ghost Chimera deployments."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_profiles import get_local_model_profile, list_local_model_profiles
from .minimind_runtime import inspect_minimind_runtime, minimind_source_metadata


@dataclass(frozen=True)
class MiniMindRuntimeStatus:
    """Resolved MiniMind runtime status without importing heavy model code."""

    available: bool
    profile: str
    package_found: bool
    root: str
    runtime_hint: str
    errors: list[str]
    architecture_embedded: bool
    architecture: dict[str, Any]
    inference_available: bool
    package_importable: bool
    package_compatible: bool
    package_error: str
    workspace_found: bool
    workspace_compatible: bool
    model_path: str
    model_files_found: bool
    optional_dependencies: dict[str, bool]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "profile": self.profile,
            "package_found": self.package_found,
            "root": self.root,
            "runtime_hint": self.runtime_hint,
            "errors": list(self.errors),
            "architecture_embedded": self.architecture_embedded,
            "architecture": dict(self.architecture),
            "inference_available": self.inference_available,
            "package_importable": self.package_importable,
            "package_compatible": self.package_compatible,
            "package_error": self.package_error,
            "workspace_found": self.workspace_found,
            "workspace_compatible": self.workspace_compatible,
            "model_path": self.model_path,
            "model_files_found": self.model_files_found,
            "optional_dependencies": dict(self.optional_dependencies),
            "notes": list(self.notes),
            "source": minimind_source_metadata(),
            "profiles": [profile.to_dict() for profile in list_local_model_profiles()],
        }


class MiniMindLifecycle:
    """Small operational wrapper around minimind-compatible local runtimes."""

    def __init__(
        self,
        *,
        profile_name: str | None = None,
        state_dir: str | Path | None = None,
        root: str | Path | None = None,
    ) -> None:
        self.profile = get_local_model_profile(profile_name or os.environ.get("MINIMIND_MODEL_PROFILE", "tiny"))
        self.state_dir = Path(state_dir or os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera")).expanduser()
        self.root = Path(root or os.environ.get("MINIMIND_ROOT", "")).expanduser() if (root or os.environ.get("MINIMIND_ROOT")) else None

    def status(self) -> MiniMindRuntimeStatus:
        inspection = inspect_minimind_runtime(profile_name=self.profile.name, state_dir=self.state_dir, root=self.root)
        return MiniMindRuntimeStatus(
            available=inspection.architecture_embedded or inspection.inference_available or inspection.workspace_found,
            profile=self.profile.name,
            package_found=inspection.package_found,
            root=inspection.workspace_root,
            runtime_hint=inspection.runtime_hint,
            errors=inspection.errors,
            architecture_embedded=inspection.architecture_embedded,
            architecture=inspection.architecture,
            inference_available=inspection.inference_available,
            package_importable=inspection.package_importable,
            package_compatible=inspection.package_compatible,
            package_error=inspection.package_error,
            workspace_found=inspection.workspace_found,
            workspace_compatible=inspection.workspace_compatible,
            model_path=inspection.model_path,
            model_files_found=inspection.model_files_found,
            optional_dependencies=inspection.optional_dependencies,
            notes=inspection.notes,
        )

    def generate_dataset(
        self,
        records: list[dict[str, Any]],
        *,
        output_path: str | Path | None = None,
    ) -> Path:
        """Append prompt/response records as JSONL for local MiniMind workflows.

        Records are *appended* to the dataset file so that repeated calls
        accumulate training examples rather than overwriting previous ones.
        """

        destination = Path(output_path) if output_path else self.state_dir / "minimind" / "datasets" / "dataset.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("a", encoding="utf-8") as handle:
            for record in records:
                prompt = str(record.get("prompt") or record.get("instruction") or "").strip()
                response = str(record.get("response") or record.get("output") or "").strip()
                if not prompt and not response:
                    continue
                handle.write(json.dumps({"instruction": prompt, "input": "", "output": response}) + "\n")
        return destination

    def log_low_confidence(
        self,
        *,
        prompt: str,
        response: str,
        confidence: float,
        threshold: float = 0.5,
        output_path: str | Path | None = None,
    ) -> bool:
        """Append a low-confidence record when confidence is below threshold."""

        if confidence >= threshold:
            return False
        destination = Path(output_path) if output_path else self.state_dir / "minimind" / "low_confidence.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "prompt": prompt,
            "response": response,
            "confidence": confidence,
            "threshold": threshold,
            "profile": self.profile.name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return True


__all__ = ["MiniMindLifecycle", "MiniMindRuntimeStatus"]
