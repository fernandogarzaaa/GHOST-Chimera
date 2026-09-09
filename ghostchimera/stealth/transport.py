"""Local IPC transport: stable protocol over localhost HTTP (stdlib-only).

Exposes: emit_event, query_context, observe_session, outcome,
status, explain. Transport stays separate from domain logic — it only
translates HTTP <-> StealthLoop calls. Auth: optional bearer token via
X-Ghost-Token; always bind loopback by default.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..logging_config import get_logger
from .context import InjectionEnvelope
from .events import Event
from .intervention import InterventionOutcome
from .loop import StealthLoop

logger = get_logger("stealth.transport")


class GhostTransport:
    """Localhost HTTP front for a StealthLoop."""

    def __init__(self, loop: StealthLoop, *, host: str = "127.0.0.1", port: int = 0,
                 token: str = "") -> None:
        self.loop = loop
        self.host = host
        self.token = token
        self._server = ThreadingHTTPServer((host, port), self._handler())
        self.url = f"http://{self._server.server_address[0]}:{self._server.server_address[1]}"
        self._thread: threading.Thread | None = None

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output clean
                pass

            def _send(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authed(self) -> bool:
                if not outer.token:
                    return True
                return self.headers.get("X-Ghost-Token") == outer.token

            def _body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if not length:
                    return {}
                try:
                    return json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return {}

            def do_POST(self) -> None:  # noqa: N802
                if not self._authed():
                    self._send({"ok": False, "error": "unauthorized"}, 401)
                    return
                data = self._body()
                try:
                    if self.path == "/emit":
                        result = outer._emit(data)
                    elif self.path == "/query_context":
                        result = outer._query_context(data)
                    elif self.path == "/observe_session":
                        result = outer._observe_session(data)
                    elif self.path.startswith("/outcome/"):
                        result = outer._outcome(self.path.rsplit("/", 1)[1], data)
                    else:
                        self._send({"ok": False, "error": "unknown route"}, 404)
                        return
                    self._send({"ok": True, **result})
                except Exception as exc:
                    logger.warning("Transport route %s failed: %s", self.path, exc)
                    self._send({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

            def do_GET(self) -> None:  # noqa: N802
                if not self._authed():
                    self._send({"ok": False, "error": "unauthorized"}, 401)
                    return
                if self.path == "/status":
                    loop = outer.loop
                    self._send({"ok": True,
                                "events_processed": loop.bus.processed,
                                "interventions": len(loop.interventions),
                                "workflows": len(loop.learner.hypotheses()),
                                "experience": loop.graph.snapshot(),
                                "autonomy": loop.policy.autonomy.name,
                                "enabled": loop.policy.enabled})
                elif self.path.startswith("/explain"):
                    iid = self.path.split("id=")[1] if "id=" in self.path else ""
                    item = outer.loop.interventions.get(iid)
                    if item is None:
                        self._send({"ok": False, "error": "unknown intervention"}, 404)
                    else:
                        self._send({"ok": True, "explanation": item.explain()})
                else:
                    self._send({"ok": False, "error": "unknown route"}, 404)

        return Handler

    # -- route implementations -------------------------------------------
    def _emit(self, data: dict[str, Any]) -> dict[str, Any]:
        event = Event.from_dict(data.get("event", data))
        delivered = self.loop.emit(event)
        result = self.loop.last_result
        return {"delivered": delivered,
                "decision": str(result.decision) if result else "none",
                "intervention_id": result.intervention_id if result else ""}

    def _query_context(self, data: dict[str, Any]) -> dict[str, Any]:
        event = Event.from_dict(data.get("event", data))
        package = self.loop.fabric.assemble(
            event, workflow=str(data.get("workflow", "")),
            confidence=float(data.get("confidence", 0.0)))
        host = str(data.get("host", "unknown"))
        return {"package": package.to_dict(),
                "markdown": InjectionEnvelope(package=package, host=host).render_markdown()}

    def _observe_session(self, data: dict[str, Any]) -> dict[str, Any]:
        from .hosts import HostAdapter

        adapter = HostAdapter(self.loop)
        decision = adapter.observe_session(data.get("session", data))
        return {"decision": decision}

    def _outcome(self, intervention_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.loop.observe_outcome(intervention_id, InterventionOutcome(str(data.get("outcome", "ignored"))))
        return {"recorded": True}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> str:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


__all__ = ["GhostTransport"]
