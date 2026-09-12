"""OpenCode CLI bridge provider.

Lets Ghost Chimera use an already-authenticated OpenCode CLI session without
reading or copying OpenCode's private credential files. OpenCode remains the
owner of its auth lifecycle; Ghost only checks login status and delegates a
single prompt through ``opencode run``. The ``opencode/*`` models include
generous free tiers, so this provider needs no API key of its own.
"""

from __future__ import annotations

import json
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
class OpenCodeCliStatus:
    """Safe status for the local OpenCode CLI bridge."""

    available: bool
    logged_in: bool
    command: str
    model: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "logged_in": self.logged_in,
            "command": self.command,
            "model": self.model,
            "detail": self.detail,
        }


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


def _auth_file_present() -> bool:
    """Check for OpenCode credentials without ever reading them."""

    candidates = [
        Path.home() / ".local" / "share" / "opencode" / "auth.json",
        Path.home() / ".config" / "opencode" / "auth.json",
    ]
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        candidates.append(Path(appdata) / "opencode" / "auth.json")
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def get_opencode_cli_status(timeout: float = 10.0) -> OpenCodeCliStatus:
    """Return whether the OpenCode CLI is installed and authenticated."""

    del timeout
    command = _opencode_command()
    executable = _resolve_opencode_executable(command)
    if executable is None:
        return OpenCodeCliStatus(
            available=False,
            logged_in=False,
            command=command,
            model="",
            detail="OpenCode CLI was not found on PATH.",
        )
    logged_in = _auth_file_present()
    return OpenCodeCliStatus(
        available=True,
        logged_in=logged_in,
        command=executable,
        model="",
        detail=(
            "OpenCode CLI is authenticated."
            if logged_in
            else "OpenCode CLI found, but no login detected. Run: opencode auth login"
        ),
    )


def opencode_login_command() -> str:
    """Return the command users run to open the official OpenCode login flow."""

    return f"{_opencode_command()} auth login"


def _compact_opencode_error(text: str, *, limit: int = 1200) -> str:
    """Return a short, operator-safe OpenCode CLI error."""

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    useful = [line for line in lines if not line.startswith(("WARN", "INFO", "DEBUG"))]
    compact = "\n".join(useful[-12:] if useful else lines[-12:]).strip()
    if len(compact) > limit:
        compact = compact[-limit:]
    return compact or "OpenCode CLI exited without a final message."


def _extract_json_answer(stdout: str) -> str:
    """Collect assistant text parts from ``opencode run --format json`` output."""

    chunks: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        text = event.get("text", "") if not isinstance(part, dict) else part.get("text", "")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks).strip()


class OpenCodeCliProvider(BaseProvider):
    """Provider that delegates one model turn to ``opencode run``."""

    name = "opencode_cli"
    default_model = "opencode/mimo-v2.5-free"

    def __init__(self, profile: Any | None = None) -> None:
        self.command = _opencode_command()
        self.executable = _resolve_opencode_executable(self.command) or self.command
        self.model = (
            getattr(profile, "model", "")
            if profile is not None and getattr(profile, "model", "")
            else os.environ.get("GHOSTCHIMERA_OPENCODE_MODEL", self.default_model)
        )
        self.timeout_seconds = float(os.environ.get("GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS", "180"))
        self.status = get_opencode_cli_status()
        self.available = self.status.available and self.status.logged_in

    def validate_config(self) -> list[str]:
        if not self.status.available:
            return [self.status.detail]
        if not self.status.logged_in:
            return [f"OpenCode CLI is not logged in. Run: {opencode_login_command()}"]
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.model,
            "auth": "opencode-cli",
            "status": self.status.to_dict(),
        }

    def chat(self, system_message: str, user_message: str) -> str:
        return self.chat_with_files(system_message, user_message, [])

    def chat_with_files(self, system_message: str, user_message: str, files: list[str]) -> str:
        """Chat turn with optional file attachments (screenshots, documents)."""

        if not self.available:
            raise RuntimeError("OpenCodeCliProvider is not available; run OpenCode login first")
        prompt = (
            "You are being called as a model backend for Ghost Chimera.\n"
            "Answer the user request directly. Do not modify files, run tools, or ask follow-up questions unless required.\n\n"
            f"<system>\n{system_message}\n</system>\n\n"
            f"<user>\n{user_message}\n</user>\n"
        )
        args = [self.executable, "run", "--format", "json", "--log-level", "ERROR"]
        if self.model:
            args.extend(["--model", self.model])
        for path in files:
            args.extend(["--file", path])
        env = {**os.environ, "NO_COLOR": "1"}
        with tempfile.TemporaryDirectory(prefix="ghostchimera-opencode-provider-") as tmp:
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
        answer = _extract_json_answer(result.stdout or "")
        if answer:
            return answer
        if result.returncode != 0:
            detail = _compact_opencode_error("\n".join(part for part in (result.stderr, result.stdout) if part))
            raise RuntimeError(f"OpenCode CLI provider failed: {detail}")
        return (result.stdout or "").strip()


__all__ = [
    "OpenCodeCliProvider",
    "OpenCodeCliStatus",
    "get_opencode_cli_status",
    "opencode_login_command",
]
