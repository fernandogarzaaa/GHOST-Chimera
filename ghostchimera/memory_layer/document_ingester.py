"""Multi-source document ingestion pipeline for Ghost Chimera memory layer.

Ingests structured or unstructured documents from multiple source types into
the :class:`~ghostchimera.memory_layer.store.MemoryStore` for later RAG
retrieval.  Zero external dependencies — uses stdlib ``csv``, ``json``,
``pathlib``, and ``re``.

Supported source types
----------------------
* ``text``   — plain-text strings
* ``json``   — JSON object (ingested as pretty-printed text + key metadata)
* ``csv``    — CSV data (each row becomes a separate document chunk)
* ``file``   — file path; type inferred from extension (.txt, .json, .csv, .md)
* ``markdown`` — Markdown text (headings become chunk boundaries)

Usage::

    from ghostchimera.memory_layer.document_ingester import DocumentIngester, IngestionSource
    from ghostchimera.memory_layer.store import MemoryStore

    store = MemoryStore("~/.ghostchimera/memory.sqlite3")
    ingester = DocumentIngester(store)

    # Ingest a plain text document
    result = ingester.ingest(IngestionSource(
        source_type="text",
        content="The Ghost Chimera project provides a layered agent runtime...",
        metadata={"title": "Project Overview", "namespace": "docs"},
    ))
    print(result.ingested_count)   # number of chunks ingested

    # Ingest multiple sources at once
    results = ingester.ingest_many([
        IngestionSource(source_type="text", content="...", metadata={}),
        IngestionSource(source_type="json", content=json.dumps({...}), metadata={}),
    ])
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import MemoryStore


@dataclass
class IngestionSource:
    """A single document source to be ingested.

    Parameters
    ----------
    source_type:
        One of ``"text"``, ``"json"``, ``"csv"``, ``"file"``, ``"markdown"``.
    content:
        Document content as a string.  For ``source_type="file"`` this is the
        file path; the file contents will be read automatically.
    metadata:
        Arbitrary key/value metadata stored alongside the document.
    chunk_size:
        Maximum character length of each chunk (``0`` means no chunking).
    source_id:
        Optional stable identifier for deduplication.
    """

    source_type: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_size: int = 2000
    source_id: str = ""


@dataclass
class IngestionResult:
    """Summary of one ingestion run."""

    source_id: str
    source_type: str
    ingested_count: int
    skipped_count: int
    errors: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "ingested_count": self.ingested_count,
            "skipped_count": self.skipped_count,
            "errors": self.errors,
        }


class DocumentIngester:
    """Multi-source document ingestion pipeline.

    Splits documents into chunks, deduplicates via
    :meth:`~ghostchimera.memory_layer.store.MemoryStore.add_document_once`,
    and persists them for RAG retrieval.
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def ingest(self, source: IngestionSource) -> IngestionResult:
        """Ingest a single :class:`IngestionSource` into the memory store."""
        try:
            chunks = self._extract_chunks(source)
        except Exception as exc:  # noqa: BLE001
            return IngestionResult(
                source_id=source.source_id or source.content[:30],
                source_type=source.source_type,
                ingested_count=0,
                skipped_count=0,
                errors=[str(exc)],
            )

        ingested = 0
        skipped = 0
        errors: list[str] = []
        for i, (chunk_text, chunk_meta) in enumerate(chunks):
            chunk_source = source.source_id or f"{source.source_type}:{i}"
            merged_meta = {**source.metadata, **chunk_meta}
            try:
                _, inserted = self.store.add_document_once(chunk_source, chunk_text, metadata=merged_meta)
                if inserted:
                    ingested += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"chunk {i}: {exc}")

        return IngestionResult(
            source_id=source.source_id or source.source_type,
            source_type=source.source_type,
            ingested_count=ingested,
            skipped_count=skipped,
            errors=errors,
            chunks=[c for c, _ in chunks],
        )

    def ingest_many(self, sources: list[IngestionSource]) -> list[IngestionResult]:
        """Ingest multiple sources and return one result per source."""
        return [self.ingest(s) for s in sources]

    # ------------------------------------------------------------------
    # Chunk extraction
    # ------------------------------------------------------------------

    def _extract_chunks(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        """Return a list of (chunk_text, chunk_metadata) pairs."""
        stype = source.source_type.lower().strip()

        if stype == "file":
            return self._extract_file(source)
        if stype == "json":
            return self._extract_json(source)
        if stype == "csv":
            return self._extract_csv(source)
        if stype in ("markdown", "md"):
            return self._extract_markdown(source)
        # default: plain text
        return self._extract_text(source)

    def _extract_text(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        text = source.content.strip()
        if not text:
            return []
        return self._split_text(text, source.chunk_size)

    def _extract_file(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        path = Path(source.content.strip()).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        ext = path.suffix.lower()
        text = path.read_text(encoding="utf-8", errors="replace")
        if ext == ".json":
            fake = IngestionSource("json", text, source.metadata, source.chunk_size, source_id=str(path))
            return self._extract_json(fake)
        if ext == ".csv":
            fake = IngestionSource("csv", text, source.metadata, source.chunk_size, source_id=str(path))
            return self._extract_csv(fake)
        if ext in (".md", ".markdown"):
            fake = IngestionSource("markdown", text, source.metadata, source.chunk_size, source_id=str(path))
            return self._extract_markdown(fake)
        return self._split_text(text, source.chunk_size)

    def _extract_json(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        text = source.content.strip()
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if isinstance(obj, list):
            chunks = []
            for i, item in enumerate(obj):
                item_text = json.dumps(item, indent=2) if isinstance(item, dict) else str(item)
                meta = {"item_index": i}
                if isinstance(item, dict):
                    meta.update(
                        {
                            k: v
                            for k, v in item.items()
                            if isinstance(v, str) and k in ("title", "id", "name", "source", "url")
                        }
                    )
                chunks.extend(self._split_text(item_text, source.chunk_size, extra_meta=meta))
            return chunks

        # single object
        rendered = json.dumps(obj, indent=2)
        return self._split_text(rendered, source.chunk_size)

    def _extract_csv(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        reader = csv.DictReader(io.StringIO(source.content))
        chunks = []
        for i, row in enumerate(reader):
            row_text = "; ".join(f"{k}={v}" for k, v in row.items())
            meta = {"row": i}
            chunks.append((row_text, meta))
        return chunks

    def _extract_markdown(self, source: IngestionSource) -> list[tuple[str, dict[str, Any]]]:
        """Split Markdown at heading boundaries (# / ## / ###)."""
        heading_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        chunks: list[tuple[str, dict[str, Any]]] = []
        positions = [(m.start(), m.group(2).strip()) for m in heading_pattern.finditer(source.content)]

        if not positions:
            return self._split_text(source.content, source.chunk_size)

        for i, (pos, heading) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(source.content)
            section_text = source.content[pos:end].strip()
            if not section_text:
                continue
            meta = {"section": heading}
            chunks.extend(self._split_text(section_text, source.chunk_size, extra_meta=meta))
        return chunks

    @staticmethod
    def _split_text(
        text: str, chunk_size: int, extra_meta: dict[str, Any] | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Split *text* into chunks of at most *chunk_size* characters.

        Prefers splitting at paragraph boundaries (double newline).
        """
        meta = dict(extra_meta or {})
        if chunk_size <= 0 or len(text) <= chunk_size:
            return [(text, meta)] if text.strip() else []

        # Try paragraph splits first
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        chunks: list[tuple[str, dict[str, Any]]] = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 <= chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append((current, {**meta, "chunk": len(chunks)}))
                # If a single paragraph is larger than chunk_size, hard-split it
                while len(para) > chunk_size:
                    chunks.append((para[:chunk_size], {**meta, "chunk": len(chunks)}))
                    para = para[chunk_size:]
                current = para

        if current:
            chunks.append((current, {**meta, "chunk": len(chunks)}))
        return chunks


__all__ = ["DocumentIngester", "IngestionResult", "IngestionSource"]
