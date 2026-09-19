"""Loopback OAuth receiver (RFC 8252): localhost browser logins, no preregistration.

Binds 127.0.0.1 on an ephemeral port, captures the provider's
``?code=...&state=...`` redirect, then shuts down. Used for Desktop/native
OAuth clients (Google "Desktop app", Slack PKCE, Entra public client) where
the redirect port varies per run. Stdlib-only. LAN browsers cannot reach a
loopback listener — those installs must use the device flow or a registered
LAN redirect URI instead.
"""

from __future__ import annotations

import contextlib
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

DEFAULT_PATH = "/callback"


class LoopbackError(RuntimeError):
    pass


class LoopbackListener:
    """One-shot 127.0.0.1 listener capturing a single OAuth redirect."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 0, path: str = DEFAULT_PATH) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise LoopbackError("loopback listener refuses non-local bind addresses")
        self.host = host
        self.path = path if path.startswith("/") else "/" + path
        self._captured: dict[str, str] | None = None
        self._event = threading.Event()
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                query = dict(urllib.parse.parse_qsl(parsed.query))
                if parsed.path == outer.path and ("code" in query or "error" in query):
                    outer._captured = query
                    outer._event.set()
                    body = (
                        b"<html><body><h2>Ghost connected.</h2>"
                        b"<p>You can close this tab and return to the console.</p></body></html>"
                    )
                else:
                    body = b"<html><body><p>Waiting for the login redirect...</p></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002, ANN002, ANN003
                return

        try:
            self._server = HTTPServer((host, port), _Handler)
        except OSError as exc:
            raise LoopbackError(f"cannot bind loopback listener: {exc}") from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def redirect_uri(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}{self.path}"

    def start(self) -> LoopbackListener:
        self._thread.start()
        return self

    def wait(self, *, timeout: float = 300.0) -> dict[str, str]:
        """Block until the redirect arrives; raises LoopbackError on timeout."""
        if not self._event.wait(timeout=timeout):
            raise LoopbackError("timed out waiting for the login redirect; start over")
        assert self._captured is not None
        if self._captured.get("error"):
            raise LoopbackError(f"provider refused the login: {self._captured.get('error')}")
        if not self._captured.get("code"):
            raise LoopbackError("redirect carried no authorization code")
        return dict(self._captured)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._server.shutdown()
        with contextlib.suppress(Exception):
            self._server.server_close()

    def __enter__(self) -> LoopbackListener:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.close()


def wait_for_loopback_code(
    *, host: str = "127.0.0.1", port: int = 0, path: str = DEFAULT_PATH, timeout: float = 300.0
) -> tuple[str, dict[str, str], str]:
    """Capture one OAuth redirect. Returns (redirect_uri, query, note)."""
    listener = LoopbackListener(host=host, port=port, path=path)
    started = time.time()
    with listener:
        query = listener.wait(timeout=timeout)
    return listener.redirect_uri, query, f"captured in {time.time() - started:.1f}s"


__all__ = ["DEFAULT_PATH", "LoopbackError", "LoopbackListener", "wait_for_loopback_code"]
