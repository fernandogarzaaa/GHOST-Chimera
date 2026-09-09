"""Connector base: the contract every Ghost event source implements."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..stealth.events import Event


class ConnectorStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    POLLING = "polling"
    ERROR = "error"


EmitFn = Callable[[Event], None]


@dataclass
class Connector:
    """Base class. Subclasses implement poll_once() and normalize()."""

    id: str = "base"
    status: ConnectorStatus = ConnectorStatus.DISCONNECTED
    last_error: str = ""
    _seen: set[str] = field(default_factory=set, repr=False)

    # -- lifecycle ------------------------------------------------------
    def connect(self) -> bool:
        self.status = ConnectorStatus.CONNECTED
        return True

    def authenticate(self) -> dict[str, Any]:
        """Return redacted auth status (never raw tokens)."""
        return {"connector": self.id, "authenticated": False}

    def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    # -- event flow -------------------------------------------------------
    def poll_once(self) -> list[Event]:
        """Fetch new source data and normalize. Must never raise."""
        raise NotImplementedError

    def normalize(self, raw: dict[str, Any]) -> Event | None:
        raise NotImplementedError

    def poll(self, emit: EmitFn, *, max_events: int = 50) -> int:
        """Poll with failure isolation: source errors degrade, never raise."""
        if self.status == ConnectorStatus.DISCONNECTED:
            self.connect()
        self.status = ConnectorStatus.POLLING
        try:
            events = self.poll_once()[:max_events]
        except Exception as exc:
            self.status = ConnectorStatus.ERROR
            self.last_error = f"{type(exc).__name__}: {exc}"
            return 0
        delivered = 0
        for event in events:
            if event.event_id in self._seen:
                continue
            self._seen.add(event.event_id)
            try:
                emit(event)
                delivered += 1
            except Exception:
                continue  # a bad consumer must not kill the connector
        if len(self._seen) > 5000:  # bound dedup memory
            self._seen = set(list(self._seen)[-2500:])
        self.status = ConnectorStatus.CONNECTED
        return delivered


__all__ = ["Connector", "ConnectorStatus", "EmitFn"]
