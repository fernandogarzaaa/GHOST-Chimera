"""Consent-gated Personal MiniMind orchestration.

This module turns the lower-level memory, email, document, and MiniMind dataset
helpers into a single operator-facing workflow. It is intentionally local-first:
the personal agent only reads paths that were explicitly consented to, stores
state under the Ghost Chimera state directory, and prepares a handoff prompt for
the configured primary model rather than sending data anywhere itself.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..memory_layer.store import MemoryStore
from ..personalization.context_provider import PersonalContextProvider
from ..personalization.document_ingester import SUPPORTED_EXTENSIONS
from .minimind_beta_orchestrator import _extract_email_tasks
from .minimind_lifecycle import MiniMindLifecycle

PERSONAL_MINIMIND_VERSION = "0.4.0-beta"
_CONSENT_FILE = "personal_consent.json"
_DEFAULT_DATASET_LIMIT = 200
_EMAIL_EXTENSIONS = {".eml", ".mbox"}
_DEFAULT_EXCLUDED_NAMES = {
    "$recycle.bin",
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "appdata",
    "application data",
    "cache",
    "caches",
    "library",
    "node_modules",
    "program files",
    "program files (x86)",
    "programdata",
    "site-packages",
    "system volume information",
    "temp",
    "tmp",
    "venv",
    "windows",
}


@dataclass(frozen=True)
class PersonalMiniMindConsent:
    """Persisted operator consent for Personal MiniMind."""

    admin_controls: bool = False
    allow_system_specs: bool = False
    allow_files: bool = False
    allow_email: bool = False
    allow_machine_crawl: bool = False
    allow_email_crawl: bool = False
    allow_autonomy: bool = False
    allow_training: bool = False
    file_paths: list[str] = field(default_factory=list)
    email_paths: list[str] = field(default_factory=list)
    crawl_roots: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    operator: str = "operator"
    granted_at: str = ""
    updated_at: str = ""
    version: str = PERSONAL_MINIMIND_VERSION

    @property
    def enabled(self) -> bool:
        return bool(self.admin_controls)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean_paths(paths: list[str | Path] | None) -> list[str]:
    cleaned: list[str] = []
    for raw in paths or []:
        value = str(raw).strip()
        if value:
            cleaned.append(str(Path(value).expanduser()))
    return cleaned


class MiniMindPersonalAgent:
    """High-level Personal MiniMind service.

    The service has three jobs:
    1. Store explicit admin consent and source scopes.
    2. Bootstrap local memory and an optional MiniMind training dataset.
    3. Build a personal RAG handoff prompt for the primary Ghost model.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        memory_db: str | Path | None = None,
        profile_name: str | None = None,
    ) -> None:
        self.state_dir = Path(state_dir or os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera")).expanduser()
        self.memory_db = Path(
            memory_db or os.environ.get("GHOSTCHIMERA_MEMORY_DB", str(self.state_dir / "memory.sqlite3"))
        ).expanduser()
        self.profile_name = profile_name or os.environ.get("MINIMIND_MODEL_PROFILE", "tiny")
        self.minimind_dir = self.state_dir / "minimind"
        self.consent_path = self.minimind_dir / _CONSENT_FILE
        self.lifecycle = MiniMindLifecycle(profile_name=self.profile_name, state_dir=self.state_dir)

    def status(self) -> dict[str, Any]:
        consent = self.load_consent()
        dataset_path = self._dataset_path()
        dataset_count = self._dataset_count(dataset_path)
        runtime = self.lifecycle.status().to_dict()
        return {
            "ok": True,
            "version": PERSONAL_MINIMIND_VERSION,
            "enabled": consent.enabled,
            "consent": consent.to_dict(),
            "memory_db": str(self.memory_db),
            "memory_count": MemoryStore(self.memory_db).count(),
            "dataset_path": str(dataset_path),
            "dataset_count": dataset_count,
            "runtime": runtime,
            "readiness": self._readiness(consent, dataset_count, runtime),
        }

    def load_consent(self) -> PersonalMiniMindConsent:
        if not self.consent_path.exists():
            return PersonalMiniMindConsent()
        try:
            payload = json.loads(self.consent_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PersonalMiniMindConsent()
        return PersonalMiniMindConsent(
            admin_controls=bool(payload.get("admin_controls", False)),
            allow_system_specs=bool(payload.get("allow_system_specs", False)),
            allow_files=bool(payload.get("allow_files", False)),
            allow_email=bool(payload.get("allow_email", False)),
            allow_machine_crawl=bool(payload.get("allow_machine_crawl", False)),
            allow_email_crawl=bool(payload.get("allow_email_crawl", False)),
            allow_autonomy=bool(payload.get("allow_autonomy", False)),
            allow_training=bool(payload.get("allow_training", False)),
            file_paths=_clean_paths(payload.get("file_paths") or []),
            email_paths=_clean_paths(payload.get("email_paths") or []),
            crawl_roots=_clean_paths(payload.get("crawl_roots") or []),
            exclude_paths=_clean_paths(payload.get("exclude_paths") or []),
            operator=str(payload.get("operator") or "operator"),
            granted_at=str(payload.get("granted_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            version=str(payload.get("version") or PERSONAL_MINIMIND_VERSION),
        )

    def grant_consent(
        self,
        *,
        admin_controls: bool,
        allow_system_specs: bool = False,
        allow_files: bool = False,
        allow_email: bool = False,
        allow_machine_crawl: bool = False,
        allow_email_crawl: bool = False,
        allow_autonomy: bool = False,
        allow_training: bool = False,
        file_paths: list[str | Path] | None = None,
        email_paths: list[str | Path] | None = None,
        crawl_roots: list[str | Path] | None = None,
        exclude_paths: list[str | Path] | None = None,
        operator: str = "operator",
    ) -> dict[str, Any]:
        if not admin_controls:
            return {
                "ok": False,
                "type": "consent_required",
                "error": "Personal MiniMind requires explicit admin_controls consent before reading local sources.",
            }
        existing = self.load_consent()
        timestamp = _now()
        consent = PersonalMiniMindConsent(
            admin_controls=True,
            allow_system_specs=bool(allow_system_specs),
            allow_files=bool(allow_files),
            allow_email=bool(allow_email),
            allow_machine_crawl=bool(allow_machine_crawl),
            allow_email_crawl=bool(allow_email_crawl),
            allow_autonomy=bool(allow_autonomy),
            allow_training=bool(allow_training),
            file_paths=_clean_paths(file_paths),
            email_paths=_clean_paths(email_paths),
            crawl_roots=_clean_paths(crawl_roots),
            exclude_paths=_clean_paths(exclude_paths),
            operator=operator or "operator",
            granted_at=existing.granted_at or timestamp,
            updated_at=timestamp,
        )
        self.consent_path.parent.mkdir(parents=True, exist_ok=True)
        self.consent_path.write_text(json.dumps(consent.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        return {"ok": True, "consent": consent.to_dict(), "path": str(self.consent_path)}

    def revoke_consent(self) -> dict[str, Any]:
        if self.consent_path.exists():
            self.consent_path.unlink()
        return {"ok": True, "enabled": False, "path": str(self.consent_path)}

    def bootstrap(
        self,
        *,
        file_paths: list[str | Path] | None = None,
        email_paths: list[str | Path] | None = None,
        include_system_specs: bool = False,
        max_files: int = 500,
        max_emails: int = 1000,
        dataset_limit: int = _DEFAULT_DATASET_LIMIT,
    ) -> dict[str, Any]:
        consent = self.load_consent()
        if not consent.enabled:
            return {
                "ok": False,
                "type": "consent_required",
                "error": "Enable Personal MiniMind admin controls before bootstrapping local or email data.",
                "status": self.status(),
            }

        approved_file_paths = _clean_paths(file_paths) or consent.file_paths
        approved_email_paths = _clean_paths(email_paths) or consent.email_paths
        crawl_summary = self.discover_machine_sources(
            consent=consent,
            max_files=max_files,
            max_emails=max_emails,
        )
        if crawl_summary["enabled"]:
            approved_file_paths = [*approved_file_paths, *crawl_summary["documents"]]
            approved_email_paths = [*approved_email_paths, *crawl_summary["emails"]]
        system_profile: dict[str, Any] = {"ok": False, "skipped": True}

        store = MemoryStore(self.memory_db)
        dataset_records: list[dict[str, str]] = []

        if include_system_specs and consent.allow_system_specs:
            system_profile = self.collect_system_profile()
            store.add_document_once(
                "system_specs",
                json.dumps(system_profile["profile"], indent=2, sort_keys=True),
                metadata={"personal_minimind": True, "scope": "system_specs"},
            )
            dataset_records.append(
                {
                    "prompt": "Use this machine profile to tailor local execution plans.",
                    "response": json.dumps(system_profile["profile"], sort_keys=True),
                }
            )

        bootstrap = self.lifecycle.bootstrap_personal_dataset(
            memory_db=self.memory_db,
            allow_files=(consent.allow_files or consent.allow_machine_crawl) and bool(approved_file_paths),
            allow_email=(consent.allow_email or consent.allow_email_crawl) and bool(approved_email_paths),
            file_paths=approved_file_paths,
            email_paths=approved_email_paths,
            max_files=max_files,
            max_emails=max_emails,
            generate_training=consent.allow_training,
        )

        if consent.allow_training:
            dataset_records.extend(self._records_from_memory(limit=dataset_limit))
            if dataset_records:
                dataset_path = self.lifecycle.generate_dataset(dataset_records)
                bootstrap["dataset_path"] = str(dataset_path)
                bootstrap["dataset_records"] = int(bootstrap.get("dataset_records", 0)) + len(dataset_records)

        task_hints = _extract_email_tasks(self.memory_db)
        return {
            "ok": bool(bootstrap.get("ok", True)),
            "version": PERSONAL_MINIMIND_VERSION,
            "consent": consent.to_dict(),
            "system_profile": system_profile,
            "crawl": crawl_summary,
            "bootstrap": bootstrap,
            "task_hints": task_hints,
            "handoff": self.build_handoff("Summarize the user's pending work and execution context."),
        }

    def discover_machine_sources(
        self,
        *,
        consent: PersonalMiniMindConsent | None = None,
        max_files: int = 500,
        max_emails: int = 1000,
    ) -> dict[str, Any]:
        consent = consent or self.load_consent()
        roots = [Path(p).expanduser() for p in (consent.crawl_roots or self._default_crawl_roots())]
        excluded = {Path(p).expanduser().resolve(strict=False) for p in consent.exclude_paths}
        excluded.add(self.state_dir.resolve(strict=False))
        documents: list[str] = []
        emails: list[str] = []
        skipped_dirs: list[str] = []
        errors: list[str] = []

        enabled = consent.enabled and (consent.allow_machine_crawl or consent.allow_email_crawl)
        if not enabled:
            return {
                "enabled": False,
                "roots": [str(root) for root in roots],
                "documents": [],
                "emails": [],
                "documents_discovered": 0,
                "emails_discovered": 0,
                "skipped_dirs": [],
                "errors": [],
            }

        for root in roots:
            if len(documents) >= max_files and len(emails) >= max_emails:
                break
            if not root.exists():
                errors.append(f"root not found: {root}")
                continue
            root_resolved = root.resolve(strict=False)
            effective_excluded = {
                excluded_path
                for excluded_path in excluded
                if excluded_path != root_resolved and excluded_path not in root_resolved.parents
            }
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
                current = Path(dirpath)
                try:
                    current_resolved = current.resolve(strict=False)
                except OSError as exc:
                    errors.append(f"{current}: {exc}")
                    dirnames[:] = []
                    continue
                if self._is_excluded(current_resolved, effective_excluded):
                    skipped_dirs.append(str(current))
                    dirnames[:] = []
                    continue
                dirnames[:] = [
                    name for name in dirnames
                    if name.lower() not in _DEFAULT_EXCLUDED_NAMES
                    and not self._is_excluded((current / name).resolve(strict=False), effective_excluded)
                ]
                for filename in filenames:
                    if len(documents) >= max_files and len(emails) >= max_emails:
                        break
                    path = current / filename
                    suffix = path.suffix.lower()
                    if consent.allow_email_crawl and suffix in _EMAIL_EXTENSIONS and len(emails) < max_emails:
                        emails.append(str(path))
                    elif consent.allow_machine_crawl and suffix in SUPPORTED_EXTENSIONS and len(documents) < max_files:
                        documents.append(str(path))

        return {
            "enabled": True,
            "roots": [str(root) for root in roots],
            "documents": documents,
            "emails": emails,
            "documents_discovered": len(documents),
            "emails_discovered": len(emails),
            "skipped_dirs": skipped_dirs[:100],
            "errors": errors[:100],
        }

    def build_handoff(self, objective: str, *, limit: int = 8, role_path: dict[str, Any] | None = None) -> dict[str, Any]:
        consent = self.load_consent()
        if not consent.enabled:
            return {
                "ok": False,
                "type": "consent_required",
                "error": "Personal MiniMind handoff requires admin_controls consent.",
            }
        provider = PersonalContextProvider(memory_store=MemoryStore(self.memory_db), enable_minimind=True)
        context = provider.context_for_objective(objective, limit=limit)
        task_hints = _extract_email_tasks(self.memory_db, limit=limit)
        if role_path is None:
            from ..personalization.path_state import get_active_ghost_path

            role_path = get_active_ghost_path()["synthesis"]
        role = role_path.get("role", {}) if isinstance(role_path, dict) else {}
        proxy_policy = role_path.get("proxy_policy", {}) if isinstance(role_path, dict) else {}
        prompt_parts = [
            "Personal MiniMind context for the primary Ghost Chimera model:",
            f"Active Ghost path: {role.get('name', 'Autonomous Engineer')} ({role.get('id', 'autonomous-engineer')}).",
            f"Proxy posture: {proxy_policy.get('allowed_claim', 'authorized Ghost Chimera operator proxy')}.",
            context.context or "No matching personal memory was found.",
        ]
        if task_hints:
            prompt_parts.append("Autonomous task hints:")
            prompt_parts.extend(f"- {item.get('task_hint', '')}" for item in task_hints if item.get("task_hint"))
        prompt_parts.append(f"Primary objective: {objective}")
        return {
            "ok": True,
            "objective": objective,
            "personal_context": context.context,
            "ghost_path": role_path,
            "sources": list(context.sources),
            "detail": context.detail,
            "task_hints": task_hints,
            "primary_model_prompt": "\n".join(part for part in prompt_parts if str(part).strip()),
        }

    def collect_system_profile(self) -> dict[str, Any]:
        home = Path.home()
        cwd = Path.cwd()
        profile: dict[str, Any] = {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "home": str(home),
            "cwd": str(cwd),
            "disks": {},
        }
        for label, path in (("home", home), ("cwd", cwd)):
            try:
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            profile["disks"][label] = {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
            }
        return {"ok": True, "profile": profile}

    def _default_crawl_roots(self) -> list[str]:
        if platform.system().lower() == "windows":
            roots: list[str] = []
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                root = Path(f"{letter}:\\")
                if root.exists():
                    roots.append(str(root))
            return roots or [str(Path.home())]
        return [str(Path.home())]

    def _is_excluded(self, path: Path, excluded: set[Path]) -> bool:
        name = path.name.lower()
        if name in _DEFAULT_EXCLUDED_NAMES:
            return True
        return any(path == excluded_path or excluded_path in path.parents for excluded_path in excluded)

    def _records_from_memory(self, *, limit: int) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        store = MemoryStore(self.memory_db)
        for item in reversed(store.recent_documents(limit=limit)):
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            source = str(item.get("source") or "memory")
            records.append(
                {
                    "prompt": f"Remember and use this personal context from {source}.",
                    "response": content[:4000],
                }
            )
        return records

    def _dataset_path(self) -> Path:
        return self.state_dir / "minimind" / "datasets" / "dataset.jsonl"

    def _dataset_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        except (OSError, UnicodeDecodeError):
            return -1

    def _readiness(self, consent: PersonalMiniMindConsent, dataset_count: int, runtime: dict[str, Any]) -> dict[str, Any]:
        return {
            "consent_ready": consent.enabled,
            "memory_ready": MemoryStore(self.memory_db).count() > 0,
            "dataset_ready": dataset_count > 0,
            "rag_ready": consent.enabled and MemoryStore(self.memory_db).count() > 0,
            "training_ready": consent.allow_training and dataset_count > 0,
            "inference_ready": bool(runtime.get("inference_available")),
            "primary_model_handoff_ready": consent.enabled and MemoryStore(self.memory_db).count() > 0,
            "whole_machine_crawl_ready": consent.enabled and consent.allow_machine_crawl,
            "email_crawl_ready": consent.enabled and consent.allow_email_crawl,
        }


__all__ = ["MiniMindPersonalAgent", "PersonalMiniMindConsent", "PERSONAL_MINIMIND_VERSION"]
