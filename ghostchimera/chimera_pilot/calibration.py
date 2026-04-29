"""Calibration and health history for Chimera Pilot backends."""

from __future__ import annotations

from dataclasses import dataclass
from time import time

from .backends.base import BackendHealth, ChimeraBackend


@dataclass(frozen=True)
class CalibrationRecord:
    backend_id: str
    timestamp: float
    health: BackendHealth


class CalibrationStore:
    """Bounded in-memory calibration history."""

    def __init__(self, max_records_per_backend: int = 100) -> None:
        self.max_records_per_backend = max_records_per_backend
        self.records: dict[str, list[CalibrationRecord]] = {}

    def add(self, backend_id: str, health: BackendHealth) -> None:
        bucket = self.records.setdefault(backend_id, [])
        bucket.append(CalibrationRecord(backend_id=backend_id, timestamp=time(), health=health))
        if len(bucket) > self.max_records_per_backend:
            del bucket[: len(bucket) - self.max_records_per_backend]

    def recent(self, backend_id: str, window: int = 20) -> list[CalibrationRecord]:
        return self.records.get(backend_id, [])[-window:]

    def reliability(self, backend_id: str, window: int = 20) -> float:
        records = self.recent(backend_id, window=window)
        if not records:
            return 0.5
        availability = sum(1 for record in records if record.health.available) / len(records)
        reported = sum(max(0.0, min(1.0, record.health.reliability)) for record in records) / len(records)
        return (availability * 0.6) + (reported * 0.4)

    def summary(self) -> dict[str, dict[str, float | int | bool]]:
        payload: dict[str, dict[str, float | int | bool]] = {}
        for backend_id, records in self.records.items():
            latest = records[-1].health
            payload[backend_id] = {
                "records": len(records),
                "latest_available": latest.available,
                "latest_latency_ms": latest.latency_ms,
                "reliability": self.reliability(backend_id),
            }
        return payload


class ChimeraCalibrator:
    """Probe all registered backends and record their health."""

    def __init__(self, backends: list[ChimeraBackend], store: CalibrationStore | None = None) -> None:
        self.backends = list(backends)
        self.store = store or CalibrationStore()

    def run_once(self) -> dict[str, BackendHealth]:
        results: dict[str, BackendHealth] = {}
        for backend in self.backends:
            try:
                health = backend.probe()
            except Exception as exc:  # pragma: no cover - defensive guard for third-party backends
                health = BackendHealth(
                    available=False,
                    reliability=0.0,
                    latency_ms=999_999,
                    estimated_cost_usd=0.0,
                    last_error=str(exc),
                )
            self.store.add(backend.id, health)
            results[backend.id] = health
        return results
