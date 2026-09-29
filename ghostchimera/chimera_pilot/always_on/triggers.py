"""Wake triggers for always-on agents: webhooks and schedules.

A webhook is a named entry point: an external system POSTs a payload and the
registered handler turns it into an agent wake-up. Schedules reuse the
existing :class:`CronScheduler` — the daemon installs a job executor that
wakes the agent when a cron job fires. Handler callables live in memory;
their names and descriptions are persisted so the console can list the
available webhooks.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import GhostChimeraConfig
from ...logging_config import get_logger

logger = get_logger("always_on.triggers")

WebhookHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class WebhookDefinition:
    """Persisted description of a registered webhook.

    ``objective_template`` is optional. When set, the webhook is fully
    durable: the registry rehydrates its handler from the template on load,
    formatting ``{placeholders}`` against the trigger payload. Webhooks
    registered with a raw callable keep working in-process but are listed as
    having no handler after a restart until re-registered.
    """

    name: str
    description: str
    registered_at: float
    objective_template: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "registered_at": self.registered_at,
            "objective_template": self.objective_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookDefinition:
        return cls(
            name=str(data["name"]),
            description=str(data.get("description") or ""),
            registered_at=float(data.get("registered_at") or 0.0),
            objective_template=str(data.get("objective_template") or ""),
        )


def render_objective_template(template: str, payload: dict[str, Any]) -> str:
    """Render an objective template against a webhook payload.

    ``{placeholders}`` are filled from the payload; unknown placeholders are
    left as-is so a partial payload never breaks the trigger.
    """
    result = str(template or "")

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(payload.get(key, match.group(0)))

    rendered = re.sub(r"\{([a-zA-Z0-9_]+)\}", _replace, result)
    if not rendered.strip():
        raise ValueError("Webhook objective template rendered empty")
    return rendered


class WebhookRegistry:
    """Named webhook entry points that wake the agent.

    ``trigger`` resolves the handler and returns whatever objective the
    handler derives from the payload; the caller (the daemon) is responsible
    for turning that objective into a wake request.
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        base = Path(state_dir or GhostChimeraConfig.from_env().state_dir).expanduser()
        self.state_dir = base
        self._file = base / "always_on" / "webhooks.json"
        self._lock = threading.RLock()
        self._handlers: dict[str, WebhookHandler] = {}
        self._definitions: dict[str, WebhookDefinition] = {}
        self._load()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: WebhookHandler,
        *,
        description: str = "",
        objective_template: str = "",
    ) -> WebhookDefinition:
        """Register (or replace) a webhook handler."""
        key = self._normalize(name)
        definition = WebhookDefinition(
            name=key,
            description=description,
            registered_at=time.time(),
            objective_template=objective_template,
        )
        with self._lock:
            self._handlers[key] = handler
            self._definitions[key] = definition
            self._save()
        logger.info("Registered webhook '%s'", key)
        return definition

    def register_template(self, name: str, objective_template: str, *, description: str = "") -> WebhookDefinition:
        """Register a webhook whose objective is rendered from a template.

        Template webhooks are fully durable: the handler is rehydrated from
        the persisted template whenever the registry loads.
        """
        template = str(objective_template or "").strip()
        if not template:
            raise ValueError("objective_template must not be empty")
        return self.register(
            name,
            lambda payload: render_objective_template(template, payload),
            description=description,
            objective_template=template,
        )

    def unregister(self, name: str) -> bool:
        """Remove a webhook. Returns True when something was removed."""
        key = self._normalize(name)
        with self._lock:
            removed_handler = self._handlers.pop(key, None) is not None
            removed_definition = self._definitions.pop(key, None) is not None
            if removed_handler or removed_definition:
                self._save()
                return True
            return False

    def trigger(self, name: str, payload: dict[str, Any] | None = None) -> str:
        """Run the handler for *name* and return the derived objective."""
        key = self._normalize(name)
        with self._lock:
            handler = self._handlers.get(key)
        if handler is None:
            raise KeyError(f"Unknown webhook '{name}'")
        objective = handler(dict(payload or {}))
        if not str(objective or "").strip():
            raise ValueError(f"Webhook '{name}' handler returned an empty objective")
        logger.info("Webhook '%s' triggered", key)
        return str(objective)

    def list(self) -> list[WebhookDefinition]:
        """All known webhook definitions, sorted by name."""
        with self._lock:
            return sorted(self._definitions.values(), key=lambda d: d.name)

    def has_handler(self, name: str) -> bool:
        with self._lock:
            return self._normalize(name) in self._handlers

    # ------------------------------------------------------------------
    # Persistence (definitions only; handlers are runtime callables)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(name: str) -> str:
        key = str(name or "").strip().lower().replace(" ", "-")
        if not key:
            raise ValueError("webhook name must not be empty")
        return key

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable webhook registry: %s", exc)
            return
        for entry in data.get("webhooks", []):
            try:
                definition = WebhookDefinition.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                continue
            self._definitions[definition.name] = definition
            # Rehydrate durable template handlers so they survive restarts.
            if definition.objective_template and definition.name not in self._handlers:
                template = definition.objective_template
                self._handlers[definition.name] = lambda payload, t=template: render_objective_template(t, payload)

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "1.0",
            "saved_at": time.time(),
            "webhooks": [d.to_dict() for d in sorted(self._definitions.values(), key=lambda d: d.name)],
        }
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._file)


__all__ = ["WebhookRegistry", "WebhookDefinition", "WebhookHandler", "render_objective_template"]
