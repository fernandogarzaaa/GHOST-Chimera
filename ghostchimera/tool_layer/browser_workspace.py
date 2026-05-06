"""Optional browser automation workspace backed by agent-browser."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger("browser_workspace")

Runner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AgentBrowserWorkspace:
    """Thin, policy-conscious adapter around the optional ``agent-browser`` CLI."""

    def __init__(
        self,
        *,
        binary: str | None = None,
        runner: Runner | None = None,
        resolver: Resolver | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.binary = binary or os.environ.get("GHOSTCHIMERA_AGENT_BROWSER_BIN", "agent-browser")
        self.runner = runner or subprocess.run
        self.resolver = resolver or shutil.which
        self.timeout = timeout

    def status(self) -> dict[str, Any]:
        resolved = self._resolve_binary()
        if not resolved:
            return {
                "available": False,
                "binary": self.binary,
                "resolved": "",
                "detail": "agent-browser binary not found; install it or set GHOSTCHIMERA_AGENT_BROWSER_BIN",
            }
        return {
            "available": True,
            "binary": self.binary,
            "resolved": resolved,
            "detail": "agent-browser workspace is available",
        }

    def open(self, url: str, *, session: str = "default") -> dict[str, Any]:
        self._validate_url(url)
        self._validate_session(session)
        return self._run(["--session", session, "open", url], action="open", session=session, url=url)

    def snapshot(self, *, url: str = "", session: str = "default", interactive: bool = True) -> dict[str, Any]:
        self._validate_session(session)
        if url:
            self.open(url, session=session)
        args = ["--session", session, "snapshot"]
        if interactive:
            args.append("-i")
        return self._run(args, action="snapshot", session=session, url=url)

    def close(self, *, session: str = "default") -> dict[str, Any]:
        self._validate_session(session)
        return self._run(["--session", session, "close"], action="close", session=session)

    def _run(self, args: Sequence[str], *, action: str, session: str, url: str = "") -> dict[str, Any]:
        resolved = self._require_binary()
        command = [resolved, *args]
        logger.debug("Running agent-browser action=%s session=%s", action, session)
        completed = self.runner(command, text=True, capture_output=True, check=False, timeout=self.timeout)
        return {
            "ok": completed.returncode == 0,
            "action": action,
            "session": session,
            "url": url,
            "returncode": completed.returncode,
            "output": (completed.stdout or "").strip(),
            "error": (completed.stderr or "").strip(),
        }

    def _resolve_binary(self) -> str | None:
        candidate = self.binary
        if any(sep in candidate for sep in ("/", "\\")):
            path = Path(candidate).expanduser()
            return str(path) if path.exists() else None
        return self.resolver(candidate)

    def _require_binary(self) -> str:
        resolved = self._resolve_binary()
        if not resolved:
            raise FileNotFoundError(f"agent-browser binary not found: {self.binary}")
        return resolved

    @staticmethod
    def _validate_url(url: str) -> None:
        if not url.startswith("https://"):
            raise ValueError(f"Only HTTPS URLs are allowed for browser workspace actions; got: {url}")

    @staticmethod
    def _validate_session(session: str) -> None:
        if not _SESSION_RE.fullmatch(session):
            raise ValueError("Session must contain only letters, numbers, hyphens, or underscores")


__all__ = ["AgentBrowserWorkspace"]
