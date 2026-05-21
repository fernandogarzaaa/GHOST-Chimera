"""Codex CLI OAuth bridge provider.

This provider lets Ghost Chimera use an already-authenticated Codex CLI session
without reading or copying Codex's private token files.  The Codex CLI remains
the owner of the ChatGPT/Codex OAuth lifecycle; Ghost only checks login status
and delegates a single prompt through ``codex exec``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base_provider import BaseProvider


@dataclass(frozen=True)
class CodexCliStatus:
    """Safe status for the local Codex CLI OAuth bridge."""

    available: bool
    logged_in: bool
    command: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "logged_in": self.logged_in,
            "command": self.command,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CodexCliLoginLaunch:
    """Result of launching the official Codex login flow."""

    launched: bool
    command: str
    detail: str
    pid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "launched": self.launched,
            "command": self.command,
            "detail": self.detail,
            "pid": self.pid,
        }


def _codex_command() -> str:
    return os.environ.get("GHOSTCHIMERA_CODEX_COMMAND", "codex")


def _resolve_codex_executable(command: str) -> str | None:
    """Resolve a subprocess-safe Codex executable path."""

    if sys.platform.startswith("win") and not Path(command).suffix:
        for candidate in (f"{command}.cmd", f"{command}.exe", command):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return shutil.which(command)


def get_codex_cli_status(timeout: float = 10.0) -> CodexCliStatus:
    """Return whether the Codex CLI is installed and logged in.

    The function intentionally does not inspect ``~/.codex/auth.json`` or any
    other credential file.  It relies on the official CLI status command.
    """

    command = _codex_command()
    executable = _resolve_codex_executable(command)
    if executable is None:
        return CodexCliStatus(
            available=False,
            logged_in=False,
            command=command,
            detail="Codex CLI was not found on PATH.",
        )
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CodexCliStatus(
            available=True,
            logged_in=False,
            command=command,
            detail=f"Codex login status check failed: {exc}",
        )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    logged_in = result.returncode == 0 and "logged in" in output.lower()
    return CodexCliStatus(
        available=True,
        logged_in=logged_in,
        command=executable,
        detail=output or ("Codex CLI is logged in." if logged_in else "Codex CLI is not logged in."),
    )


def codex_login_command() -> str:
    """Return the command users can run to open the official Codex login flow."""

    return f"{_codex_command()} login --device-auth"


def launch_codex_login_flow() -> CodexCliLoginLaunch:
    """Launch the official Codex browser/device login flow.

    This intentionally uses a fixed command shape and never reads token files.
    On Windows it opens a new console so the user can complete the interactive
    device login if the CLI does not open a browser directly.
    """

    command = _codex_command()
    executable = _resolve_codex_executable(command)
    if executable is None:
        return CodexCliLoginLaunch(
            launched=False,
            command=codex_login_command(),
            detail="Codex CLI was not found on PATH.",
        )
    args = [executable, "login", "--device-auth"]
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    else:
        kwargs.update({"start_new_session": True, "stdin": subprocess.DEVNULL})
    try:
        process = subprocess.Popen(args, **kwargs)  # noqa: S603 - fixed executable and arguments.
    except OSError as exc:
        return CodexCliLoginLaunch(
            launched=False,
            command=codex_login_command(),
            detail=f"Could not launch Codex login flow: {exc}",
        )
    return CodexCliLoginLaunch(
        launched=True,
        command=codex_login_command(),
        detail="Codex login flow launched. Complete the browser/device login, then click Connect again.",
        pid=process.pid,
    )


class CodexCliProvider(BaseProvider):
    """Provider that delegates one model turn to ``codex exec``."""

    name = "codex_cli"
    default_model = "gpt-5.4-mini"

    def __init__(self, profile: Any | None = None) -> None:
        self.command = _codex_command()
        self.executable = _resolve_codex_executable(self.command) or self.command
        self.model = (
            getattr(profile, "model", "")
            if profile is not None and getattr(profile, "model", "")
            else os.environ.get("CODEX_MODEL", self.default_model)
        )
        self.timeout_seconds = float(os.environ.get("GHOSTCHIMERA_CODEX_TIMEOUT_SECONDS", "180"))
        self.status = get_codex_cli_status()
        self.available = self.status.available and self.status.logged_in

    def validate_config(self) -> list[str]:
        if not self.status.available:
            return [self.status.detail]
        if not self.status.logged_in:
            return [f"Codex CLI is not logged in. Run: {codex_login_command()}"]
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
            "auth": "codex-cli-oauth",
            "status": self.status.to_dict(),
        }

    def chat(self, system_message: str, user_message: str) -> str:
        if not self.available:
            raise RuntimeError("CodexCliProvider is not available; run Codex login first")
        prompt = (
            "You are being called as a model backend for Ghost Chimera.\n"
            "Answer the user request directly. Do not modify files, run tools, or ask follow-up questions unless required.\n\n"
            f"<system>\n{system_message}\n</system>\n\n"
            f"<user>\n{user_message}\n</user>\n"
        )
        with tempfile.TemporaryDirectory(prefix="ghostchimera-codex-provider-") as tmp:
            output_path = Path(tmp) / "last_message.txt"
            args = [
                self.executable,
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--output-last-message",
                str(output_path),
            ]
            if self.model:
                args.extend(["--model", self.model])
            args.append("-")
            env = {**os.environ, "NO_COLOR": "1"}
            result = subprocess.run(
                args,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                cwd=tmp,
                env=env,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"Codex CLI provider failed: {detail}")
            if output_path.exists():
                message = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if message:
                    return message
            return (result.stdout or "").strip()


__all__ = [
    "CodexCliLoginLaunch",
    "CodexCliProvider",
    "CodexCliStatus",
    "codex_login_command",
    "get_codex_cli_status",
    "launch_codex_login_flow",
]
