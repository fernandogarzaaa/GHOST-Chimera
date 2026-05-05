"""
Memory Manager
==============

GhostChimera uses a simple persistent memory to record previous interactions.
The memory is stored as a JSON list on disk.  Each event is appended to the
list with a timestamp.  This implementation is intentionally simple; in a
real system you would use a more sophisticated vector store for semantic
search and retrieval.

The location of the memory file defaults to ``~/.ghostchimera/memory.json``
but can be overridden by setting the ``GHOSTCHIMERA_MEMORY_FILE``
environment variable.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_FILE = os.environ.get(
    "GHOSTCHIMERA_MEMORY_FILE",
    os.path.expanduser("~/.ghostchimera/memory.json"),
)


class MemoryManager:
    """Thread‑safe persistent memory store."""

    def __init__(self, file_path: str | None = None) -> None:
        self.file_path = file_path or DEFAULT_FILE
        self._lock = threading.Lock()
        # ensure directory exists
        Path(os.path.dirname(self.file_path)).mkdir(parents=True, exist_ok=True)
        # ensure file exists
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def _read_events(self) -> list[dict[str, Any]]:
        with open(self.file_path, encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []

    def _write_events(self, events: list[dict[str, Any]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)

    def add_event(self, event: dict[str, Any]) -> None:
        """Append an event to the memory."""
        entry = dict(event)
        entry["timestamp"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with self._lock:
            events = self._read_events()
            events.append(entry)
            self._write_events(events)

    def get_events(self) -> list[dict[str, Any]]:
        """Return all events from memory."""
        with self._lock:
            return self._read_events()

    def search(self, query: str) -> list[dict[str, Any]]:
        """Naive keyword search over stored events."""
        results = []
        for event in self.get_events():
            if any(query.lower() in str(value).lower() for value in event.values()):
                results.append(event)
        return results
