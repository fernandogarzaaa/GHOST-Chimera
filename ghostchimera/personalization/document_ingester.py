"""Bulk document ingestion for Ghost Chimera personal memory.

Reads plain-text files (Markdown, Python, JSON, CSV, etc.) and loads
them into a :class:`~ghostchimera.memory_layer.store.MemoryStore`.  Large
files are chunked at natural paragraph/sentence boundaries so that FTS
search returns focused, relevant snippets rather than entire files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory_layer.store import MemoryStore

_MAX_CHUNK_CHARS: int = 1_500

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".go", ".rs",
    ".json", ".yaml", ".yml", ".toml", ".csv", ".html", ".xml",
    ".sh", ".bash", ".zsh", ".fish",
})


@dataclass
class DocumentIngestResult:
    """Summary of a document ingestion operation."""

    ingested: int = 0
    skipped: int = 0
    chunks: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingested": self.ingested,
            "skipped": self.skipped,
            "chunks": self.chunks,
            "errors": self.errors,
        }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Splits are made at paragraph boundaries first, then at sentence
    boundaries, to keep semantically related content together.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current = (current + " " + sent).strip() if current else sent
                    else:
                        if current:
                            chunks.append(current)
                        current = sent[:max_chars]

    if current:
        chunks.append(current)
    return chunks


# ── Public class ─────────────────────────────────────────────────────────────

class DocumentIngester:
    """Ingest text documents into a MemoryStore.

    Supports individual text strings, single files, and entire directory
    trees.  Documents are chunked automatically so search results are
    focused.  Duplicate chunks are skipped via
    :meth:`~ghostchimera.memory_layer.store.MemoryStore.add_document_once`.

    Supported file extensions: ``.txt``, ``.md``, ``.py``, ``.js``, ``.ts``,
    ``.go``, ``.rs``, ``.json``, ``.yaml``, ``.yml``, ``.toml``, ``.csv``,
    ``.html``, ``.xml``, and common shell scripts.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self.memory_store = memory_store

    # ── Ingestion methods ────────────────────────────────────────────────

    def ingest_text(
        self,
        source: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentIngestResult:
        """Ingest a text string under the given *source* label."""
        result = DocumentIngestResult()
        if not text.strip():
            result.skipped += 1
            return result

        chunks = _chunk_text(text)
        if not chunks:
            result.skipped += 1
            return result

        for i, chunk in enumerate(chunks):
            chunk_meta = dict(metadata or {})
            if len(chunks) > 1:
                chunk_meta["chunk"] = i
                chunk_meta["total_chunks"] = len(chunks)
            _, is_new = self.memory_store.add_document_once(source, chunk, metadata=chunk_meta)
            if is_new:
                result.chunks += 1
            else:
                result.skipped += 1

        result.ingested += 1
        return result

    def ingest_file(self, path: str | Path, *, source_prefix: str = "") -> DocumentIngestResult:
        """Read a file and ingest its text content."""
        p = Path(path).expanduser()
        result = DocumentIngestResult()

        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            result.skipped += 1
            return result

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            source = f"{source_prefix}/{p.name}".lstrip("/") if source_prefix else p.name
            sub = self.ingest_text(
                source,
                text,
                metadata={"path": str(p), "extension": p.suffix},
            )
            result.ingested += sub.ingested
            result.skipped += sub.skipped
            result.chunks += sub.chunks
            result.errors.extend(sub.errors)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{p}: {exc}")

        return result

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        max_files: int = 500,
        glob_pattern: str = "**/*",
    ) -> DocumentIngestResult:
        """Recursively ingest all supported files under *directory*."""
        d = Path(directory).expanduser()
        combined = DocumentIngestResult()
        count = 0

        for p in sorted(d.glob(glob_pattern)):
            if count >= max_files:
                break
            if not p.is_file():
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            sub = self.ingest_file(p, source_prefix=d.name)
            combined.ingested += sub.ingested
            combined.skipped += sub.skipped
            combined.chunks += sub.chunks
            combined.errors.extend(sub.errors)
            count += 1

        return combined
