"""Append-only audit log for GitHub-connected Ghost actions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class GitHubAuditLog:
    """Append JSONL GitHub task events under the configured state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "github" / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, repo: str, event: str, payload: dict[str, Any]) -> Path:
        entry = {
            "timestamp": time.time(),
            "repo": repo,
            "event": event,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return self.path
