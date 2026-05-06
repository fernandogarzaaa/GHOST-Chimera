"""MiniMind lifecycle helpers for local-first Ghost Chimera deployments."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .local_profiles import get_local_model_profile, list_local_model_profiles


@dataclass(frozen=True)
class MiniMindRuntimeStatus:
    """Resolved MiniMind runtime status without importing heavy model code."""

    available: bool
    profile: str
    package_found: bool
    root: str
    runtime_hint: str
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "profile": self.profile,
            "package_found": self.package_found,
            "root": self.root,
            "runtime_hint": self.runtime_hint,
            "errors": list(self.errors),
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
        errors: list[str] = []
        package_found = importlib.util.find_spec("minimind") is not None
        root_text = str(self.root) if self.root is not None else ""
        if self.root is not None and not self.root.exists():
            errors.append(f"MINIMIND_ROOT does not exist: {self.root}")
        if not package_found:
            errors.append("minimind package is not installed")
        runtime_hint = "package" if package_found else "unavailable"
        if self.root is not None and self.root.exists():
            runtime_hint = "workspace"
        return MiniMindRuntimeStatus(
            available=package_found or (self.root is not None and self.root.exists()),
            profile=self.profile.name,
            package_found=package_found,
            root=root_text,
            runtime_hint=runtime_hint,
            errors=errors,
        )

    def generate_dataset(
        self,
        records: list[dict[str, Any]],
        *,
        output_path: str | Path | None = None,
    ) -> Path:
        """Write prompt/response records as JSONL for local MiniMind workflows."""

        destination = Path(output_path) if output_path else self.state_dir / "minimind" / "datasets" / "dataset.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
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
