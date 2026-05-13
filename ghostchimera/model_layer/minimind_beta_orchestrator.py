"""Beta orchestrator for Personal MiniMind + autonomous handoff workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..chimera_pilot.autonomy_queue import AutonomyJobQueue
from ..memory_layer.store import MemoryStore
from ..personalization.email_ingester import EmailIngester
from .minimind_lifecycle import MiniMindLifecycle


@dataclass(frozen=True)
class BetaVisionConfig:
    memory_db: str
    file_paths: list[str]
    email_paths: list[str]
    run_autonomy_jobs: bool
    autonomy_profile: str
    autonomy_jobs: list[str]


def load_beta_config(path: str | Path) -> BetaVisionConfig:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return BetaVisionConfig(
        memory_db=str(payload.get("memory_db") or ".ghostchimera-memory.sqlite3"),
        file_paths=[str(p) for p in payload.get("file_paths", [])],
        email_paths=[str(p) for p in payload.get("email_paths", [])],
        run_autonomy_jobs=bool(payload.get("run_autonomy_jobs", False)),
        autonomy_profile=str(payload.get("autonomy_profile") or "supervised"),
        autonomy_jobs=[str(p) for p in payload.get("autonomy_jobs", ["self-audit", "memory-refresh"])],
    )


def _extract_email_tasks(memory_db: str | Path, *, limit: int = 20) -> list[dict[str, Any]]:
    store = MemoryStore(memory_db)
    items = store.search("todo OR action OR follow-up OR deadline", limit=limit)
    out: list[dict[str, Any]] = []
    for item in items:
        content = str(item.get("content") or "")
        m = re.search(r"(?i)(todo|action|follow[- ]up|deadline)[:\\-\\s](.{0,160})", content)
        snippet = (m.group(2).strip() if m else content[:160]).strip()
        if snippet:
            out.append({"source": item.get("source", "memory"), "task_hint": snippet})
    return out


def run_beta_vision(
    *,
    config: BetaVisionConfig,
    state_dir: str | Path | None = None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    lifecycle = MiniMindLifecycle(profile_name=profile_name, state_dir=state_dir)
    bootstrap = lifecycle.bootstrap_personal_dataset(
        memory_db=config.memory_db,
        allow_files=True,
        allow_email=True,
        file_paths=config.file_paths,
        email_paths=config.email_paths,
    )
    task_hints = _extract_email_tasks(config.memory_db)

    queued: list[dict[str, Any]] = []
    if config.run_autonomy_jobs:
        queue = AutonomyJobQueue(state_dir=state_dir)
        for name in config.autonomy_jobs:
            queued.append(
                queue.enqueue(name, profile=config.autonomy_profile, execute=False, run_now=False, source="minimind-beta")
            )

    return {
        "ok": True,
        "bootstrap": bootstrap,
        "task_hints": task_hints,
        "queued_jobs": queued,
        "next_step": "Use task_hints as RAG context for your configured primary model execution loop.",
    }
