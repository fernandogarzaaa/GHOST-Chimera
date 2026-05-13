"""Personalization utilities for Ghost Chimera.

This package focuses on *local-first* personalization: capturing user-provided
context into local memory and using it to condition subsequent runs.

It does not implement model fine-tuning by itself; training pipelines are
expected to be external/optional, with Ghost Chimera providing dataset export
and safe ingestion surfaces.
"""

from .context_provider import PersonalContextProvider, PersonalContextResult

__all__ = ["PersonalContextProvider", "PersonalContextResult"]

