"""Durable autonomy job queue for local operator surfaces."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import GhostChimeraConfig
from .autonomy import get_autonomy_profile
from .autonomy_jobs import JOB_SPECS, AutonomyJobRunner

RunnerFactory = Callable[..., AutonomyJobRunner]


class AutonomyJobQueue:
    """Persist and run bounded autonomy jobs through the existing runner."""

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        runner_factory: RunnerFactory | None = None,
    ) -> None:
        base = Path(state_dir or GhostChimeraConfig.from_env().state_dir).expanduser()
        self.state_dir = base
        self._state_file = base / "autonomy" / "jobs.json"
        self._runner_factory = runner_factory or AutonomyJobRunner
        self._lock = threading.RLock()
        self._jobs: list[dict[str, Any]] = []
        self._load()

    @staticmethod
    def available_jobs() -> list[dict[str, Any]]:
        return AutonomyJobRunner.list_jobs()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(job) for job in self._jobs]

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            for job in self._jobs:
                if job["id"] == job_id:
                    return dict(job)
        raise KeyError(f"Unknown autonomy job record '{job_id}'")

    def validate_request(self, job_name: str, *, profile: str = "supervised", execute: bool = False) -> str:
        key = self._normalize_job_name(job_name)
        resolved_profile = get_autonomy_profile(profile)
        self._validate_execution(key, resolved_profile.name, execute=execute)
        return key

    def enqueue(
        self,
        job_name: str,
        *,
        profile: str = "supervised",
        execute: bool = False,
        run_now: bool = True,
        source: str = "console",
        schedule_id: str = "",
    ) -> dict[str, Any]:
        key = self.validate_request(job_name, profile=profile, execute=execute)
        resolved_profile = get_autonomy_profile(profile)
        now = time.time()
        record = {
            "id": f"job-{uuid.uuid4().hex[:12]}",
            "name": key,
            "profile": resolved_profile.name,
            "execute": bool(execute),
            "status": "queued",
            "source": source,
            "schedule_id": schedule_id,
            "requested_at": now,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "safety_notes": self._safety_notes(key, resolved_profile.name, execute=execute),
        }
        with self._lock:
            self._jobs.append(record)
            self._save()
        if run_now:
            return self.run(record["id"])
        return dict(record)

    def run(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._find_mutable(job_id)
            if record["status"] == "cancelled":
                return dict(record)
            if record["status"] != "queued":
                return dict(record)
            record["status"] = "running"
            record["started_at"] = time.time()
            self._save()

        try:
            runner = self._runner_factory(profile=record["profile"], state_dir=self.state_dir)
            result = runner.run(record["name"], execute=bool(record["execute"]))
            payload = result.to_dict()
            status = str(payload.get("status") or "ok")
            with self._lock:
                record = self._find_mutable(job_id)
                record["status"] = status
                record["result"] = payload
                record["error"] = None
                record["finished_at"] = time.time()
                self._save()
                return dict(record)
        except Exception as exc:
            with self._lock:
                record = self._find_mutable(job_id)
                record["status"] = "error"
                record["error"] = str(exc)
                record["finished_at"] = time.time()
                self._save()
                return dict(record)

    def run_next(self) -> dict[str, Any] | None:
        with self._lock:
            queued = next((job["id"] for job in self._jobs if job["status"] == "queued"), "")
        if not queued:
            return None
        return self.run(queued)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._find_mutable(job_id)
            if record["status"] != "queued":
                raise ValueError("Only queued autonomy jobs can be cancelled")
            record["status"] = "cancelled"
            record["finished_at"] = time.time()
            self._save()
            return dict(record)

    def _find_mutable(self, job_id: str) -> dict[str, Any]:
        for job in self._jobs:
            if job["id"] == job_id:
                return job
        raise KeyError(f"Unknown autonomy job record '{job_id}'")

    def _normalize_job_name(self, job_name: str) -> str:
        key = str(job_name or "").strip().lower().replace("_", "-")
        if key not in JOB_SPECS:
            available = ", ".join(sorted(JOB_SPECS))
            raise ValueError(f"Unknown autonomy job '{job_name}'. Available jobs: {available}")
        return key

    def _validate_execution(self, job_name: str, profile_name: str, *, execute: bool) -> None:
        spec = JOB_SPECS[job_name]
        profile = get_autonomy_profile(profile_name)
        if execute and spec.high_impact and not profile.allow_background_jobs:
            raise PermissionError(
                f"Profile '{profile.name}' cannot execute high-impact autonomy job '{job_name}'. "
                "Switch to an operator-enabled profile and confirm execute=true."
            )

    def _safety_notes(self, job_name: str, profile_name: str, *, execute: bool) -> list[str]:
        spec = JOB_SPECS[job_name]
        notes = [f"profile={profile_name}", f"high_impact={spec.high_impact}"]
        if not execute:
            notes.append("preview mode: no high-impact command execution requested")
        if spec.high_impact:
            notes.append("high-impact jobs require explicit execute=true and an operator-enabled profile")
        return notes

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._jobs = []
            return
        jobs = data.get("jobs", [])
        self._jobs = [dict(job) for job in jobs if isinstance(job, dict)]

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": "1.0", "saved_at": time.time(), "jobs": self._jobs}
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._state_file)


__all__ = ["AutonomyJobQueue"]
