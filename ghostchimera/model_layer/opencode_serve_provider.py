"""OpenCode Serve provider: free models via a private local OpenCode server.

Runs ``opencode serve`` on 127.0.0.1 with an isolated config, random Basic
auth credentials, stripped secrets, and a permission lockdown that rejects
every tool request. Chat goes through the local HTTP API, so Ghost Chimera
gets OpenCode's free ``opencode/*`` models without touching the user's real
OpenCode setup and without requiring an OpenCode login.

Pattern adapted from Project Away's live agent (``liveagent/opencode.py``).
"""

from __future__ import annotations

import base64
import contextlib
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base_provider import BaseProvider


def _opencode_command() -> str:
    return os.environ.get("GHOSTCHIMERA_OPENCODE_COMMAND", "opencode")


def _resolve_opencode_executable(command: str) -> str | None:
    """Resolve a subprocess-safe OpenCode executable path."""

    if sys.platform.startswith("win") and not Path(command).suffix:
        for candidate in (f"{command}.cmd", f"{command}.exe", command):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return shutil.which(command)


@dataclass
class _ServeHandle:
    """Live handles for one private ``opencode serve`` process."""

    proc: subprocess.Popen[bytes]
    port: int
    auth_header: str
    workdir: str
    xdg_root: str
    lock: threading.Lock


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _scrubbed_env() -> dict[str, str]:
    """Copy os.environ minus anything that looks like a secret."""

    return {
        key: value
        for key, value in os.environ.items()
        if not any(token in key.lower() for token in ("key", "token", "secret", "password", "credential"))
    }


def _write_lockdown_config(config_dir: str) -> None:
    """Write an opencode.json that asks for every permission and shares nothing."""

    config = {
        "permission": {"*": "ask"},
        "share": "disabled",
        "autoupdate": False,
    }
    Path(config_dir, "opencode.json").write_text(json.dumps(config), encoding="utf-8")


class OpenCodeServeProvider(BaseProvider):
    """Provider that chats through a private local ``opencode serve`` instance."""

    name = "opencode_serve"
    default_model = "opencode/big-pickle"

    def __init__(self, profile: Any | None = None) -> None:
        self.command = _opencode_command()
        self.executable = _resolve_opencode_executable(self.command)
        self.model = (
            getattr(profile, "model", "")
            if profile is not None and getattr(profile, "model", "")
            else os.environ.get("GHOSTCHIMERA_OPENCODE_SERVE_MODEL", self.default_model)
        )
        self.startup_timeout = float(os.environ.get("GHOSTCHIMERA_OPENCODE_SERVE_STARTUP_SECONDS", "60"))
        self.request_timeout = float(os.environ.get("GHOSTCHIMERA_OPENCODE_SERVE_TIMEOUT_SECONDS", "180"))
        self._handle: _ServeHandle | None = None
        self._handle_lock = threading.Lock()
        self.available = self.executable is not None

    def validate_config(self) -> list[str]:
        if self.executable is None:
            return [f"OpenCode executable '{self.command}' was not found on PATH."]
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
            "auth": "opencode-serve-local",
            "server_running": self._handle is not None and self._handle.proc.poll() is None,
        }

    def _start_server(self) -> _ServeHandle:
        """Launch a private ``opencode serve`` with isolated config and auth."""

        executable = self.executable
        if executable is None:
            raise RuntimeError("OpenCode executable not found on PATH")

        port = _free_port()
        password = secrets.token_urlsafe(24)
        auth_header = "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()

        xdg_root = tempfile.mkdtemp(prefix="ghostchimera-opencode-serve-")
        config_dir = os.path.join(xdg_root, "config")
        os.makedirs(config_dir, exist_ok=True)
        _write_lockdown_config(config_dir)
        workdir = tempfile.mkdtemp(prefix="ghostchimera-opencode-work-")

        env = _scrubbed_env()
        env.update(
            {
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": password,
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "XDG_CONFIG_HOME": config_dir,
                "XDG_DATA_HOME": os.path.join(xdg_root, "data"),
                "XDG_CACHE_HOME": os.path.join(xdg_root, "cache"),
                "XDG_STATE_HOME": os.path.join(xdg_root, "state"),
                "NO_COLOR": "1",
            }
        )
        for key in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            os.makedirs(env[key], exist_ok=True)

        proc = subprocess.Popen(
            [executable, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
            env=env,
            cwd=workdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        handle = _ServeHandle(
            proc=proc,
            port=port,
            auth_header=auth_header,
            workdir=workdir,
            xdg_root=xdg_root,
            lock=threading.Lock(),
        )
        try:
            self._wait_ready(handle)
        except Exception:
            self._stop_server(handle)
            raise
        return handle

    def _call(self, handle: _ServeHandle, method: str, path: str, body: Any | None = None) -> Any:
        """One authenticated JSON call against the private server."""

        payload = json.dumps(body).encode() if body is not None else None
        conn = http.client.HTTPConnection("127.0.0.1", handle.port, timeout=self.request_timeout)
        try:
            conn.request(
                method,
                path,
                body=payload,
                headers={"Authorization": handle.auth_header, "Content-Type": "application/json"},
            )
            raw = conn.getresponse().read()
        finally:
            conn.close()
        return json.loads(raw) if raw else None

    def _wait_ready(self, handle: _ServeHandle) -> None:
        """Poll until the server answers or the startup timeout expires."""

        deadline = time.monotonic() + self.startup_timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if handle.proc.poll() is not None:
                raise RuntimeError("opencode serve exited during startup")
            try:
                self._call(handle, "POST", "/session", {"title": "ghost-chimera-probe"})
                probe = True
            except Exception as exc:  # noqa: BLE001 - any connection failure means not ready
                last_error = exc
                probe = False
            if probe:
                return
            time.sleep(0.5)
        raise RuntimeError(f"opencode serve did not become ready in time: {last_error}")

    def _reject_pending_permissions(self, handle: _ServeHandle) -> None:
        """Reject every permission request the server is holding."""

        try:
            pending = self._call(handle, "GET", "/permission") or []
        except Exception:  # noqa: BLE001 - permission endpoint is best-effort
            return
        items = pending if isinstance(pending, list) else pending.get("permissions", [])
        for item in items:
            request_id = item.get("id") if isinstance(item, dict) else None
            if not request_id:
                continue
            try:
                self._call(handle, "POST", f"/permission/{request_id}/reply", {"reply": "reject"})
            except Exception:  # noqa: BLE001 - one failed rejection must not break the chat
                continue

    def _ensure_server(self) -> _ServeHandle:
        """Return a running server, starting (or restarting) it as needed."""

        with self._handle_lock:
            handle = self._handle
            if handle is not None and handle.proc.poll() is None:
                return handle
            if handle is not None:
                self._stop_server(handle)
            self._handle = self._start_server()
            return self._handle

    @staticmethod
    def _stop_server(handle: _ServeHandle) -> None:
        """Terminate the server and remove its isolated directories."""

        try:
            handle.proc.terminate()
            handle.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - always attempt cleanup
            with contextlib.suppress(Exception):
                handle.proc.kill()
        shutil.rmtree(handle.xdg_root, ignore_errors=True)
        shutil.rmtree(handle.workdir, ignore_errors=True)

    def shutdown(self) -> None:
        """Stop the private server if one is running."""

        with self._handle_lock:
            handle, self._handle = self._handle, None
        if handle is not None:
            self._stop_server(handle)

    @staticmethod
    def _extract_text(message: Any) -> str:
        """Collect assistant text parts from a /message response."""

        parts = message.get("parts", []) if isinstance(message, dict) else []
        chunks = [
            part.get("text", "").strip()
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text", "").strip()
        ]
        return "\n".join(chunks).strip()

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("OpenCodeServeProvider is not available; opencode was not found on PATH")
        handle = self._ensure_server()
        with handle.lock:
            self._reject_pending_permissions(handle)
            session = self._call(handle, "POST", "/session", {"title": "ghost-chimera"})
            session_id = session["id"]
            try:
                self._reject_pending_permissions(handle)
                message = self._call(
                    handle,
                    "POST",
                    f"/session/{session_id}/message",
                    {
                        "model": {"providerID": "opencode", "modelID": self._model_id()},
                        "system": (
                            "You are being called as a model backend for Ghost Chimera. "
                            "Answer the user request directly. Do not use tools."
                            + (f"\n\n{system_message}" if system_message else "")
                        ),
                        "parts": [{"type": "text", "text": user_message}],
                    },
                )
                answer = self._extract_text(message)
                if answer:
                    return answer
                raise RuntimeError("opencode serve returned no text parts")
            finally:
                with contextlib.suppress(Exception):
                    self._call(handle, "DELETE", f"/session/{session_id}")

    def _model_id(self) -> str:
        """Strip the ``opencode/`` prefix; the API wants the bare model ID."""

        model = (self.model or "").strip()
        if model.startswith("opencode/"):
            return model[len("opencode/") :]
        return model or "big-pickle"


__all__ = ["OpenCodeServeProvider"]
