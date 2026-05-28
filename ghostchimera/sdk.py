"""Ghost Chimera SDK — high-level Python API for agent orchestration.

This module exposes :class:`GhostClient`, the recommended entry point for
Python applications that want to drive Ghost Chimera programmatically.

Ghost Chimera's value proposition is **bridging the gap** between powerful
AI models and *your specific context*.  The SDK makes that pipeline
accessible in a few lines:

Example::

    from ghostchimera.sdk import GhostClient

    # Create a client (uses ~/.ghostchimera by default)
    ghost = GhostClient()

    # Teach Ghost about your work
    ghost.ingest_document("project-notes", "We build with FastAPI and PostgreSQL.")
    ghost.ingest_email_file("/path/to/export.mbox")

    # Run an objective — personal memory is automatically injected
    result = ghost.run("What database does our project use?")
    print(result.output)

    # Keep teaching from real interactions
    ghost.teach("What is our DB?", "PostgreSQL, as noted in project-notes.")

The ``teach()`` / ``ingest_*`` methods build a personal knowledge base stored
in a local SQLite file.  When ``enable_personal_context=True`` (the default),
the most relevant snippets from that knowledge base are automatically injected
into every AI call, acting as a built-in RAG layer that grows smarter as you
use it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chimera_pilot.executor import PilotExecution
from .chimera_pilot.kernel import ChimeraPilotKernel
from .config import GhostChimeraConfig
from .memory_layer.store import MemoryStore
from .model_layer.minimind_lifecycle import MiniMindLifecycle
from .model_layer.minimind_personal_agent import MiniMindPersonalAgent
from .personalization.context_provider import PersonalContextProvider
from .personalization.document_ingester import DocumentIngester, DocumentIngestResult
from .personalization.email_ingester import EmailIngester, EmailIngestResult


@dataclass(frozen=True)
class RunResult:
    """Result of a single Ghost Chimera objective run."""

    ok: bool
    output: str
    backend_id: str
    executions: list[dict[str, Any]]

    @classmethod
    def from_executions(cls, execs: list[PilotExecution]) -> RunResult:
        if not execs:
            return cls(ok=False, output="", backend_id="", executions=[])
        ok = all(e.ok for e in execs)
        output = "\n".join(str(e.result.output or "") for e in execs if e.result.output).strip()
        backend_id = execs[-1].result.backend_id
        return cls(ok=ok, output=output, backend_id=backend_id, executions=[e.to_dict() for e in execs])

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "backend_id": self.backend_id,
            "executions": self.executions,
        }


class GhostClient:
    """High-level Ghost Chimera client.

    :class:`GhostClient` wraps the full Chimera Pilot pipeline behind a
    simple, consistent API.  It manages a local MemoryStore for personal
    context, provides ingestion helpers for emails and documents, and
    exposes a :meth:`teach` method for building MiniMind training datasets.

    Args:
        state_dir: Override state directory.  Defaults to the
            ``GHOSTCHIMERA_STATE_DIR`` environment variable or
            ``~/.ghostchimera``.
        memory_db: Override memory database path.  Defaults to
            ``<state_dir>/memory.sqlite3``.
        autonomy_level: One of ``assist``, ``supervised``, ``autonomous``,
            ``generalist``.  Default is ``supervised``.
        enable_personal_context: When ``True``, relevant memory snippets
            are injected into every AI call.  Default is ``True``.
        enable_minimind_summary: When ``True`` and MiniMind is available
            locally, uses the tiny model to compress memory excerpts before
            injection.  Default is ``True``.
        include_deterministic_backend: Include the offline
            ``DeterministicBackend`` so keyword-only objectives can be
            answered without an API key.  Default is ``True``.
    """

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        memory_db: str | Path | None = None,
        config_path: str | Path | None = None,
        autonomy_level: str = "supervised",
        enable_personal_context: bool = True,
        enable_minimind_summary: bool = True,
        include_deterministic_backend: bool = True,
    ) -> None:
        _state = Path(state_dir or os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera")).expanduser()
        _db = Path(memory_db or os.environ.get("GHOSTCHIMERA_MEMORY_DB", str(_state / "memory.sqlite3"))).expanduser()

        self._state_dir = _state
        self._autonomy_level = autonomy_level
        self._enable_personal_context = enable_personal_context
        self._enable_minimind_summary = enable_minimind_summary
        self._include_deterministic_backend = include_deterministic_backend
        self._config_path = Path(config_path).expanduser() if config_path is not None else None

        self._memory = MemoryStore(_db)
        self._email_ingester = EmailIngester(self._memory)
        self._doc_ingester = DocumentIngester(self._memory)
        self._personal_minimind = MiniMindPersonalAgent(
            state_dir=self._state_dir,
            memory_db=self._memory.db_path,
        )

    # ── Running objectives ────────────────────────────────────────────────

    def run(self, objective: str) -> RunResult:
        """Run *objective* through the Chimera Pilot pipeline.

        Personal context from memory is automatically injected when
        ``enable_personal_context=True`` (the default).

        Returns a :class:`RunResult` with ``.ok``, ``.output``, and the
        full raw ``.executions`` list.
        """
        kernel = ChimeraPilotKernel.default(
            include_deterministic_backend=self._include_deterministic_backend,
            memory_store=self._memory,
            autonomy_level=self._autonomy_level,
            enable_personal_context=self._enable_personal_context,
            enable_minimind_personal_context=self._enable_minimind_summary,
        )
        execs = kernel.run(objective)
        return RunResult.from_executions(execs)

    # ── Memory / personal context ─────────────────────────────────────────

    def ingest_document(
        self,
        source: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentIngestResult:
        """Add a text document to Ghost's personal memory.

        Args:
            source: A short label describing the origin
                (e.g. ``"project-notes"`` or ``"slack-export"``).
            text: The full text to ingest.
            metadata: Optional key/value metadata stored alongside the
                document for reference.

        Returns:
            :class:`~ghostchimera.personalization.document_ingester.DocumentIngestResult`
        """
        return self._doc_ingester.ingest_text(source, text, metadata=metadata)

    def ingest_file(self, path: str | Path) -> DocumentIngestResult:
        """Ingest a local file into Ghost's personal memory.

        Supported formats: ``.txt``, ``.md``, ``.py``, ``.js``, ``.ts``,
        ``.go``, ``.rs``, ``.json``, ``.yaml``, ``.yml``, ``.toml``,
        ``.csv``, ``.html``, and more.
        """
        return self._doc_ingester.ingest_file(path)

    def ingest_directory(self, path: str | Path, *, max_files: int = 500) -> DocumentIngestResult:
        """Recursively ingest all supported files in *path*."""
        return self._doc_ingester.ingest_directory(path, max_files=max_files)

    def ingest_email_file(self, path: str | Path) -> EmailIngestResult:
        """Ingest a ``.eml`` or ``.mbox`` email file into personal memory.

        ``.mbox`` files (e.g. Gmail Takeout exports) can contain thousands
        of messages; up to 500 are ingested by default per file.
        """
        p = Path(path).expanduser()
        if p.suffix.lower() == ".mbox":
            return self._email_ingester.ingest_mbox_file(p)
        return self._email_ingester.ingest_eml_file(p)

    def ingest_raw_email(self, raw_text: str) -> EmailIngestResult:
        """Parse and ingest a raw RFC 2822 email string.

        Useful for piping email text directly from a mail client or script.
        """
        return self._email_ingester.ingest_raw_email(raw_text)

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Full-text search across Ghost's personal memory.

        Returns up to *limit* ranked results, each a dict with
        ``source``, ``content``, ``freshness_score``, and
        ``citation_quality`` fields.
        """
        return self._memory.search(query, limit=limit)

    def memory_count(self) -> int:
        """Return the total number of documents stored in personal memory."""
        return self._memory.count()

    # ── Teaching Ghost (MiniMind training data) ───────────────────────────

    def teach(
        self,
        prompt: str,
        response: str,
        *,
        output_path: str | Path | None = None,
    ) -> Path:
        """Record a prompt/response pair as MiniMind training data.

        Calling this repeatedly builds a personal JSONL dataset that can
        be used to fine-tune a local MiniMind model on your specific domain.
        The dataset is appended (not overwritten) on every call.

        Args:
            prompt: The user instruction or question.
            response: The ideal answer or completion.
            output_path: Override the destination JSONL file path.

        Returns:
            Path to the dataset file.
        """
        lifecycle = MiniMindLifecycle(state_dir=self._state_dir)
        return lifecycle.generate_dataset(
            [{"prompt": prompt, "response": response}],
            output_path=output_path,
        )

    def teach_many(
        self,
        records: list[dict[str, Any]],
        *,
        output_path: str | Path | None = None,
    ) -> Path:
        """Append multiple prompt/response pairs to the MiniMind dataset."""

        lifecycle = MiniMindLifecycle(state_dir=self._state_dir)
        return lifecycle.generate_dataset(records, output_path=output_path)

    def training_status(self) -> dict[str, Any]:
        """Return status of the local MiniMind training setup.

        Includes whether MiniMind weights are present, the training dataset
        path, and training record count (if available).
        """
        lifecycle = MiniMindLifecycle(state_dir=self._state_dir)
        status = lifecycle.status().to_dict()

        dataset_path = self._state_dir / "minimind" / "datasets" / "dataset.jsonl"
        dataset_count = 0
        if dataset_path.exists():
            try:
                dataset_count = sum(1 for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip())
            except (OSError, UnicodeDecodeError):
                dataset_count = -1
        status["dataset_path"] = str(dataset_path)
        status["dataset_count"] = dataset_count
        return status

    def enable_personal_minimind(
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
        operator: str = "sdk",
    ) -> dict[str, Any]:
        """Grant explicit consent for Personal MiniMind source ingestion."""

        return self._personal_minimind.grant_consent(
            admin_controls=admin_controls,
            allow_system_specs=allow_system_specs,
            allow_files=allow_files,
            allow_email=allow_email,
            allow_machine_crawl=allow_machine_crawl,
            allow_email_crawl=allow_email_crawl,
            allow_autonomy=allow_autonomy,
            allow_training=allow_training,
            file_paths=file_paths,
            email_paths=email_paths,
            crawl_roots=crawl_roots,
            exclude_paths=exclude_paths,
            operator=operator,
        )

    def revoke_personal_minimind(self) -> dict[str, Any]:
        """Revoke Personal MiniMind consent."""

        return self._personal_minimind.revoke_consent()

    def personal_minimind_status(self) -> dict[str, Any]:
        """Return Personal MiniMind consent, memory, dataset, and RAG readiness."""

        return self._personal_minimind.status()

    def bootstrap_personal_minimind(
        self,
        *,
        file_paths: list[str | Path] | None = None,
        email_paths: list[str | Path] | None = None,
        include_system_specs: bool = False,
        max_files: int = 500,
        max_emails: int = 1000,
    ) -> dict[str, Any]:
        """Ingest consented local sources and build the Personal MiniMind dataset."""

        return self._personal_minimind.bootstrap(
            file_paths=file_paths,
            email_paths=email_paths,
            include_system_specs=include_system_specs,
            max_files=max_files,
            max_emails=max_emails,
        )

    def minimind_handoff(self, objective: str, *, limit: int = 8) -> dict[str, Any]:
        """Build a Personal MiniMind RAG prompt for the configured primary model."""

        return self._personal_minimind.build_handoff(objective, limit=limit)

    # ── Context preview (debugging) ───────────────────────────────────────

    def preview_context(self, objective: str, *, limit: int = 5) -> dict[str, Any]:
        """Preview the personal context Ghost would inject for *objective*.

        Useful for debugging: see exactly which memory snippets will be
        included before running a real objective.

        Returns a dict with ``ok``, ``context``, ``sources``, and
        ``detail`` fields (no summarization is applied).
        """
        provider = PersonalContextProvider(
            memory_store=self._memory,
            enable_minimind=False,
        )
        result = provider.context_for_objective(objective, limit=limit, summarize=False)
        return result.to_dict()

    def recent_memory_documents(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent memory documents with metadata."""

        return self._memory.recent_documents(limit=limit)

    def providers(self) -> dict[str, Any]:
        """Return provider configuration and readiness summary."""

        from .control_plane.config import config_to_env_vars, load_config
        from .model_layer.provider_auth import provider_auth_summary
        from .model_layer.providers import get_provider

        config = load_config(self._config_path)
        env_overlay = {**os.environ, **config_to_env_vars(config)}
        active_provider = str(env_overlay.get("GHOSTCHIMERA_MODEL_PROVIDER") or "").strip().lower()
        payload = provider_auth_summary(config)
        status: dict[str, Any] = {
            "ok": False,
            "provider": active_provider,
            "available": False,
            "errors": [],
        }
        if active_provider:
            provider = get_provider(active_provider)
            if provider is None:
                status["errors"] = [f"Unknown provider: {active_provider}"]
            else:
                errors = provider.validate_config()
                status = {
                    "ok": provider.available and not errors,
                    "provider": provider.name,
                    "available": provider.available,
                    "errors": errors,
                }
        else:
            status["errors"] = ["No provider configured."]
        payload["status"] = status
        return payload

    def trust_status(self) -> dict[str, Any]:
        """Return trust-runtime readiness and approval posture."""

        from .trust_runtime import TrustRuntimeStore

        return TrustRuntimeStore(self._state_dir).trust_status()

    def workspace(self, objective: str = "", *, limit: int = 5) -> dict[str, Any]:
        """Return workspace state and optional relevant objective evidence."""

        from .cognition_layer.workspace_state import OperatorWorkspaceStore

        store = OperatorWorkspaceStore(state_dir=self._state_dir)
        snapshot = store.snapshot()
        if objective.strip():
            snapshot["objective"] = objective
            snapshot["objective_context"] = store.workspace_context_for_objective(objective, limit=limit)
        return snapshot

    def train_personal_minimind(
        self,
        *,
        mode: str = "local",
        epochs: int = 12,
        learning_rate: float = 0.25,
        max_vocab: int = 512,
    ) -> dict[str, Any]:
        """Train local or neural MiniMind adapters."""

        normalized = mode.strip().lower() or "local"
        if normalized == "local":
            lifecycle = MiniMindLifecycle(state_dir=self._state_dir)
            training = lifecycle.train_local_adapter()
            return {"ok": bool(training.get("ok")), "mode": normalized, "training": training, "status": self.training_status()}
        if normalized == "neural":
            training = self._personal_minimind.train_neural_adapter(
                epochs=epochs,
                learning_rate=learning_rate,
                max_vocab=max_vocab,
            )
            return {"ok": bool(training.get("ok")), "mode": normalized, "training": training, "status": self.training_status()}
        raise ValueError(f"Unsupported MiniMind training mode: {mode}")

    def runtime_status(self) -> dict[str, Any]:
        """Return an aggregated Ghost runtime status payload."""

        from .personalization.path_state import get_active_ghost_path

        config = GhostChimeraConfig.from_env().to_dict()
        config["state_dir"] = str(self._state_dir)
        config["memory_db"] = str(self._memory.db_path)
        config["autonomy_level"] = self._autonomy_level
        providers = self.providers()
        training = self.training_status()
        personal = self.personal_minimind_status()
        trust = self.trust_status()
        workspace = self.workspace()
        path = get_active_ghost_path(config_path=self._config_path)
        return {
            "ok": True,
            "summary": {
                "memory_count": self.memory_count(),
                "provider_ready": bool(providers.get("status", {}).get("ok")),
                "trust_ready": bool(trust.get("ready")),
                "training_ready": bool(personal.get("readiness", {}).get("training_ready")),
            },
            "config": config,
            "providers": providers,
            "training": training,
            "personal_minimind": personal,
            "trust": trust,
            "workspace": {
                "state_file": workspace.get("state_file"),
                "quality": workspace.get("quality"),
                "attention": workspace.get("attention"),
                "uncertainty": workspace.get("uncertainty"),
            },
            "path": path,
        }

    # ── Convenience ───────────────────────────────────────────────────────

    @property
    def memory(self) -> MemoryStore:
        """Direct access to the underlying :class:`MemoryStore`."""
        return self._memory

    def __repr__(self) -> str:
        return (
            f"GhostClient(state_dir={self._state_dir!r}, "
            f"autonomy_level={self._autonomy_level!r}, "
            f"personal_context={self._enable_personal_context})"
        )
