"""Personalization utilities for Ghost Chimera.

This package focuses on *local-first* personalization: capturing user-provided
context into local memory and using it to condition subsequent runs.

It does not implement model fine-tuning by itself; training pipelines are
expected to be external/optional, with Ghost Chimera providing dataset export
and safe ingestion surfaces.

Modules
-------
context_provider
    Retrieves relevant memory snippets (optionally compressed via MiniMind)
    and injects them as personal context into AI calls.
email_ingester
    Parses ``.eml`` / ``.mbox`` files and raw email text into MemoryStore.
document_ingester
    Bulk-ingests text files and directory trees into MemoryStore.
"""

from .context_provider import PersonalContextProvider, PersonalContextResult
from .document_ingester import DocumentIngester, DocumentIngestResult
from .email_ingester import EmailIngester, EmailIngestResult

__all__ = [
    "PersonalContextProvider",
    "PersonalContextResult",
    "EmailIngester",
    "EmailIngestResult",
    "DocumentIngester",
    "DocumentIngestResult",
]

