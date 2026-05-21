"""MiniMind lifecycle helpers for local-first Ghost Chimera deployments."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory_layer.store import MemoryStore
from ..personalization.document_ingester import DocumentIngester
from ..personalization.email_ingester import EmailIngester
from .local_profiles import get_local_model_profile, list_local_model_profiles
from .minimind_runtime import (
    infer_from_dataset_adapter,
    inspect_minimind_runtime,
    minimind_source_metadata,
    train_dataset_adapter,
)


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
        self.root = (
            Path(root or os.environ.get("MINIMIND_ROOT", "")).expanduser()
            if (root or os.environ.get("MINIMIND_ROOT"))
            else None
        )

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

    def dataset_path(self) -> Path:
        return self.state_dir / "minimind" / "datasets" / "dataset.jsonl"

    def adapter_path(self) -> Path:
        return self.state_dir / "minimind" / "adapters" / "local_adapter.json"

    def train_local_adapter(self, *, dataset_path: str | Path | None = None) -> dict[str, Any]:
        """Train Ghost's lightweight local MiniMind adapter from JSONL data.

        This creates an on-disk retrieval adapter that can answer from the
        user's approved MiniMind dataset without external services. It is not
        neural weight fine-tuning; that remains an optional heavier path when
        MiniMind weights and training dependencies are installed.
        """

        return train_dataset_adapter(
            dataset_path or self.dataset_path(),
            state_dir=self.state_dir,
            profile_name=self.profile.name,
        )

    def infer(self, query: str) -> dict[str, Any]:
        """Answer a query from the trained local MiniMind adapter."""

        return infer_from_dataset_adapter(self.adapter_path(), query)

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

    def bootstrap_personal_dataset(
        self,
        *,
        memory_db: str | Path,
        allow_files: bool,
        allow_email: bool,
        file_paths: list[str] | None = None,
        email_paths: list[str] | None = None,
        max_files: int = 500,
        max_emails: int = 1000,
        generate_training: bool = True,
    ) -> dict[str, Any]:
        """Explicitly ingest user-approved files/emails and seed MiniMind dataset.

        This is an opt-in orchestration helper: callers must pass explicit
        allow flags and concrete paths. No implicit machine-wide crawling occurs.
        """
        file_paths = [p for p in (file_paths or []) if str(p).strip()]
        email_paths = [p for p in (email_paths or []) if str(p).strip()]

        store = MemoryStore(memory_db)
        doc_ingester = DocumentIngester(store)
        mail_ingester = EmailIngester(store)

        summary: dict[str, Any] = {
            "ok": True,
            "memory_db": str(Path(memory_db).expanduser()),
            "allow_files": bool(allow_files),
            "allow_email": bool(allow_email),
            "files": [],
            "emails": [],
            "dataset_path": "",
            "dataset_records": 0,
        }

        dataset_records: list[dict[str, str]] = []

        if allow_files:
            for raw in file_paths:
                p = Path(raw).expanduser()
                if p.is_dir():
                    result = doc_ingester.ingest_directory(p, max_files=max_files)
                else:
                    result = doc_ingester.ingest_file(p)
                summary["files"].append({"path": str(p), **result.to_dict()})
                if result.errors:
                    summary["ok"] = False
                if result.ingested > 0 and result.chunks > 0:
                    dataset_records.append(
                        {
                            "prompt": f"Summarize and remember key points from: {p}",
                            "response": f"Ingested {result.chunks} chunks from {p.name}.",
                        }
                    )

        if allow_email:
            for raw in email_paths:
                p = Path(raw).expanduser()
                if p.is_dir():
                    result = mail_ingester.ingest_directory(p, max_files=max_emails)
                elif p.suffix.lower() == ".mbox":
                    result = mail_ingester.ingest_mbox_file(p, max_messages=max_emails)
                else:
                    result = mail_ingester.ingest_eml_file(p)
                summary["emails"].append({"path": str(p), **result.to_dict()})
                if result.errors:
                    summary["ok"] = False
                if result.ingested > 0:
                    dataset_records.append(
                        {
                            "prompt": f"Extract actionable tasks from mailbox source: {p}",
                            "response": f"Ingested {result.ingested} email records from {p.name}.",
                        }
                    )

        if dataset_records and generate_training:
            dataset_path = self.generate_dataset(dataset_records)
            summary["dataset_path"] = str(dataset_path)
            summary["dataset_records"] = len(dataset_records)

        summary["memory_documents"] = store.count()
        return summary


__all__ = ["MiniMindLifecycle", "MiniMindRuntimeStatus"]
