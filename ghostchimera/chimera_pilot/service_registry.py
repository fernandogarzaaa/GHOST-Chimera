"""Background service interface and registry for Ghost Chimera.

Mirrors OpenClaw's ``registerService`` contract which gives every
long-running component a unified ``start / stop / probe / status``
lifecycle.

Usage::

    from ghostchimera.chimera_pilot.service_registry import (
        BackgroundService,
        ServiceHealth,
        ServiceRegistry,
        get_registry,
    )

    class MyDaemon(BackgroundService):
        service_id   = "my_daemon"
        service_name = "My Daemon"

        def start(self) -> None:
            ...

        def stop(self) -> None:
            ...

        def probe(self) -> ServiceHealth:
            return ServiceHealth(ok=True, state="running")

    get_registry().register(MyDaemon())
    get_registry().start_all()
    ...
    get_registry().stop_all()
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger

logger = get_logger("service_registry")


# ---------------------------------------------------------------------------
# ServiceHealth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceHealth:
    """Snapshot returned by :meth:`BackgroundService.probe`.

    Parameters
    ----------
    ok:
        ``True`` when the service is operational.
    state:
        Human-readable state string, e.g. ``"running"``, ``"stopped"``,
        ``"degraded"``.
    details:
        Optional extra diagnostics.
    """

    ok: bool = False
    state: str = "unknown"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "state": self.state, "details": self.details}


# ---------------------------------------------------------------------------
# BackgroundService ABC
# ---------------------------------------------------------------------------


class BackgroundService(ABC):
    """Abstract base for long-running services.

    Subclasses must set :attr:`service_id` and :attr:`service_name` as
    class-level strings and implement :meth:`start`, :meth:`stop`, and
    :meth:`probe`.
    """

    service_id: str = "base_service"
    service_name: str = "Base Service"
    service_description: str = ""

    @abstractmethod
    def start(self) -> None:
        """Start the service.  Should be non-blocking (spawn a thread)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the service."""

    @abstractmethod
    def probe(self) -> ServiceHealth:
        """Return the current health of the service."""

    def status(self) -> dict[str, Any]:
        """Return a status snapshot (default: wraps :meth:`probe`)."""
        health = self.probe()
        return {
            "service_id": self.service_id,
            "service_name": self.service_name,
            "ok": health.ok,
            "state": health.state,
            "details": health.details,
        }


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------


class ServiceRegistry:
    """Registry and lifecycle coordinator for :class:`BackgroundService` instances.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._services: dict[str, BackgroundService] = {}
        self._lock = threading.Lock()

    def register(self, service: BackgroundService) -> None:
        """Register a service.  Replaces any previous entry with the same ID."""
        with self._lock:
            self._services[service.service_id] = service
        logger.info("Registered service '%s'", service.service_id)

    def deregister(self, service_id: str) -> bool:
        """Remove a service from the registry. Returns True if found."""
        with self._lock:
            if service_id in self._services:
                del self._services[service_id]
                return True
        return False

    def get(self, service_id: str) -> BackgroundService | None:
        with self._lock:
            return self._services.get(service_id)

    def list(self) -> list[BackgroundService]:
        with self._lock:
            return list(self._services.values())

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._services.keys())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> dict[str, bool]:
        """Start every registered service.

        Returns
        -------
        dict[str, bool]
            Mapping of service_id → started successfully.
        """
        results: dict[str, bool] = {}
        with self._lock:
            services = list(self._services.values())
        for svc in services:
            try:
                svc.start()
                results[svc.service_id] = True
                logger.info("Started service '%s'", svc.service_id)
            except Exception as exc:
                results[svc.service_id] = False
                logger.error("Failed to start service '%s': %s", svc.service_id, exc)
        return results

    def stop_all(self) -> dict[str, bool]:
        """Stop every registered service.

        Returns
        -------
        dict[str, bool]
            Mapping of service_id → stopped successfully.
        """
        results: dict[str, bool] = {}
        with self._lock:
            services = list(self._services.values())
        for svc in reversed(services):  # reverse order for orderly shutdown
            try:
                svc.stop()
                results[svc.service_id] = True
                logger.info("Stopped service '%s'", svc.service_id)
            except Exception as exc:
                results[svc.service_id] = False
                logger.error("Failed to stop service '%s': %s", svc.service_id, exc)
        return results

    def probe_all(self) -> dict[str, ServiceHealth]:
        """Probe every registered service.

        Returns
        -------
        dict[str, ServiceHealth]
            Mapping of service_id → health snapshot.
        """
        results: dict[str, ServiceHealth] = {}
        with self._lock:
            services = list(self._services.values())
        for svc in services:
            try:
                results[svc.service_id] = svc.probe()
            except Exception as exc:
                results[svc.service_id] = ServiceHealth(ok=False, state="probe_error",
                                                         details={"error": str(exc)})
        return results

    def status_all(self) -> list[dict[str, Any]]:
        """Return status for all registered services."""
        health = self.probe_all()
        return [
            {
                "service_id": svc.service_id,
                "service_name": svc.service_name,
                **health.get(svc.service_id, ServiceHealth()).to_dict(),
            }
            for svc in self.list()
        ]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: ServiceRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ServiceRegistry:
    """Return the process-wide singleton :class:`ServiceRegistry`."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ServiceRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the singleton registry (useful in tests)."""
    global _registry
    with _registry_lock:
        _registry = None


__all__ = [
    "BackgroundService",
    "ServiceHealth",
    "ServiceRegistry",
    "get_registry",
    "reset_registry",
]
