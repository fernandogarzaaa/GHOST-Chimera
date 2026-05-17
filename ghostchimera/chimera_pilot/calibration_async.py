"""Parallel backend calibration for Chimera Pilot."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from .backends.base import BackendHealth, ChimeraBackend
from .calibration import CalibrationStore

logger = logging.getLogger(__name__)


def _probe_one(
    backend: ChimeraBackend,
    results: dict,
    lock: threading.Lock,
    errors: dict[str, str],
) -> None:
    """Probe a single backend and store its health record thread-safely."""
    try:
        health = backend.probe()
    except Exception as exc:
        errors[backend.id] = str(exc)
        health = BackendHealth(
            available=False,
            reliability=0.0,
            latency_ms=999_999,
            estimated_cost_usd=0.0,
            last_error=str(exc),
        )
    with lock:
        results[backend.id] = health


def calibrate_backends_parallel(
    backends: list[ChimeraBackend],
    store: CalibrationStore | None = None,
    max_workers: int | None = None,
) -> dict[str, BackendHealth]:
    """Probe all backends concurrently and record their health.

    Each backend is probed in its own thread via a ThreadPoolExecutor.
    Results are collected thread-safely via a threading.Lock and optionally
    written to a CalibrationStore.

    Args:
        backends: List of backends to probe.
        store: Optional calibration store for persisting health records.
        max_workers: Maximum number of concurrent probe threads.
            Defaults to the number of backends (one thread per backend).

    Returns:
        A dict mapping backend_id to its BackendHealth.
    """
    results: dict[str, BackendHealth] = {}
    lock = threading.Lock()
    # Use a mutable container to pass exceptions out of threads
    errors: dict[str, str] = {}
    store = store or CalibrationStore()

    workers = max_workers if max_workers is not None else len(backends)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_probe_one, backend, results, lock, errors) for backend in backends]
        for future in futures:
            future.result()  # propagate any unexpected executor-level errors

    # Record health in the store
    for backend_id, health in results.items():
        store.add(backend_id, health)

    if errors:
        for backend_id, exc_msg in errors.items():
            logger.warning("Backend %s failed calibration: %s", backend_id, exc_msg)

    return results
