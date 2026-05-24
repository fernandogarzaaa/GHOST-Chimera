"""Queued worker primitives for SaaS execution mode."""

from __future__ import annotations

from time import time

from .models import SaasRun, WorkerLease


class WorkerQueue:
    """Small lease-based queue abstraction over a SaaS store-like object."""

    def __init__(self, store) -> None:
        self.store = store
        self.leases: dict[str, WorkerLease] = {}

    def claim_next(self, worker_id: str, *, lease_seconds: float = 300.0) -> WorkerLease | None:
        now = time()
        active_run_ids = {lease.run_id for lease in self.leases.values() if lease.lease_until > now}
        queued = [
            run
            for run in self.store.runs.values()
            if isinstance(run, SaasRun) and run.status == "queued" and run.run_id not in active_run_ids
        ]
        if not queued:
            return None
        run = sorted(queued, key=lambda item: item.created_at)[0]
        lease = WorkerLease(
            org_id=run.org_id,
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            worker_id=worker_id,
            lease_until=now + max(1.0, lease_seconds),
        )
        self.leases[lease.lease_id] = lease
        return lease

    def release(self, lease_id: str) -> bool:
        return self.leases.pop(lease_id, None) is not None

    def status(self) -> dict[str, object]:
        now = time()
        active = [lease for lease in self.leases.values() if lease.lease_until > now]
        return {
            "ok": True,
            "active_leases": len(active),
            "queued_runs": len([run for run in self.store.runs.values() if run.status == "queued"]),
        }
