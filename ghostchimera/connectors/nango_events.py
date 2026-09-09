"""Nango webhook inbox connector: deliveries -> ghost.* events.

Nango POSTs to /api/connectors/nango/webhook (console_routes); this
connector tails the redacted JSONL inbox and emits one Ghost event per
unseen delivery. Closes the loop: connect (frontend) -> act (proxy) ->
observe (webhook) -> learn (StealthLoop).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..stealth.events import Event, new_event
from .base import Connector


class NangoInboxConnector(Connector):
    id = "nango-inbox"

    def __init__(self, state_dir: str | Path) -> None:
        super().__init__(id="nango-inbox")
        self._inbox = Path(state_dir) / "connector_oauth" / "nango_webhooks.jsonl"
        self._offset = 0

    def authenticate(self) -> dict[str, Any]:
        return {"connector": self.id, "authenticated": True, "mode": "local-inbox"}

    def normalize(self, raw: dict[str, Any]) -> Event | None:
        delivery_type = str(raw.get("type", "unknown"))
        provider = str(raw.get("providerConfigKey", "unknown"))
        connection = str(raw.get("connectionId", ""))
        return new_event("ghost.intervention_consumed" if delivery_type == "action" else "agent.tool_called",
                         source=f"nango:{provider}", actor=connection,
                         payload={"delivery_type": delivery_type, "provider": provider,
                                  "connection_id": connection},
                         event_id=f"nango-{provider}-{connection}-{raw.get('received_at', '')}",
                         confidence=0.9)

    def poll_once(self) -> list[Event]:
        try:
            lines = self._inbox.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        fresh = lines[self._offset:]
        self._offset = len(lines)
        events: list[Event] = []
        for line in fresh:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                event = self.normalize(raw)
                if event is not None:
                    events.append(event)
        return events


__all__ = ["NangoInboxConnector"]
