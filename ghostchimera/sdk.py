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

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chimera_pilot.executor import PilotExecution
from .chimera_pilot.kernel import ChimeraPilotKernel
from .memory_layer.store import MemoryStore
from .model_layer.minimind_lifecycle import MiniMindLifecycle
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
        ok = all(e.ok for e in execs)
        output = "\n".join(str(e.result.output or "") for e in execs if e.result.output).strip()
        backend_id = execs[-1].result.backend_id if execs else ""
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
        autonomy_level: str = "supervised",
        enable_personal_context: bool = True,
        enable_minimind_summary: bool = True,
        include_deterministic_backend: bool = True,
    ) -> None:
        _state = Path(
            state_dir or os.environ.get("GHOSTCHIMERA_STATE_DIR", "~/.ghostchimera")
        ).expanduser()
        _db = Path(
            memory_db or os.environ.get("GHOSTCHIMERA_MEMORY_DB", str(_state / "memory.sqlite3"))
        ).expanduser()

        self._state_dir = _state
        self._autonomy_level = autonomy_level
        self._enable_personal_context = enable_personal_context
        self._enable_minimind_summary = enable_minimind_summary
        self._include_deterministic_backend = include_deterministic_backend

        self._memory = MemoryStore(_db)
        self._email_ingester = EmailIngester(self._memory)
        self._doc_ingester = DocumentIngester(self._memory)

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

    def ingest_directory(
        self, path: str | Path, *, max_files: int = 500
    ) -> DocumentIngestResult:
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
            with contextlib.suppress(Exception):
                dataset_count = sum(
                    1 for line in dataset_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
        status["dataset_path"] = str(dataset_path)
        status["dataset_count"] = dataset_count
        return status

    # ── Context preview (debugging) ───────────────────────────────────────

    def preview_context(
        self, objective: str, *, limit: int = 5
    ) -> dict[str, Any]:
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
