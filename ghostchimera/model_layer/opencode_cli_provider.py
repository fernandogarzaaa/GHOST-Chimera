"""OpenCode CLI bridge provider.

Lets Ghost Chimera use an already-authenticated OpenCode CLI session without
reading or copying OpenCode's private credential files. OpenCode remains the
owner of its auth lifecycle; Ghost only presence-checks the auth file and
delegates a single prompt through ``opencode run``. The ``opencode/*`` models
include generous free tiers, so this provider needs no API key of its own.

Routing note: direct HTTPS calls to Zen's free-tier models are intentionally
rejected (403) for non-OpenCode clients. Delegating to the genuine
``opencode run`` CLI subprocess is the legitimate free-tier route; Ghost
Chimera never spoofs client identity headers or User-Agent strings.

Data-use warning: free-tier ``opencode/*`` models may use your prompts to
improve their service, and some free models are trial/evaluation-only. Do not
send confidential, personal, or secret data through this provider unless you
have reviewed the model host's terms. The setup wizard and model picker
surface this notice before the provider is selected.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base_provider import BaseProvider

FREE_TIER_DATA_USE_NOTICE = (
    "Data-use notice: free-tier opencode/* models may use your prompts to "
    "improve their service, and some free models are trial/evaluation-only. "
    "Do not send confidential, personal, or secret data through this provider "
    "unless you have reviewed the model host's terms."
)

# Free-tier model names rotate on OpenCode's side. Keep this list current and
# ordered by preference; when the configured default is retired, the provider
# automatically falls through to the next entry instead of failing hard.
KNOWN_FREE_MODELS: tuple[str, ...] = (
    "opencode/mimo-v2.5-free",
    "opencode/ling-3.0-flash-fin-free",
    "opencode/nemotron-3.5-lightning-free",
    "opencode/muse-spark-1.3-contributor-free",
)

_DEFAULT_TIMEOUT_SECONDS = 180.0

_MODEL_UNAVAILABLE_RE = re.compile(
    r"model not found|unknown model|invalid model|"
    r"model\b[^\n]{0,80}\b(?:no longer available|retired|does not exist|not available)",
    re.IGNORECASE,
)


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


def opencode_setup_guidance(status: OpenCodeCliStatus | None = None) -> list[str]:
    """Return human-readable setup steps for the not-installed / not-logged-in cases."""

    checked = status if status is not None else get_opencode_cli_status()
    if not checked.available:
        return [
            "OpenCode CLI was not found on PATH.",
            "Install the OpenCode CLI (https://opencode.ai) and make sure the `opencode` command is on your PATH.",
            f"Then log in with: {opencode_login_command()}",
            "Full setup guide: docs/OPENCODE_FREE_TIER.md",
        ]
    if not checked.logged_in:
        return [
            "OpenCode CLI is installed but no login was detected.",
            f"Run: {opencode_login_command()}",
            "Then re-run setup. Ghost Chimera never reads OpenCode's auth files, it only checks that a login exists.",
        ]
    return []


def _compact_opencode_error(text: str, *, limit: int = 1200) -> str:
    """Return a short, operator-safe OpenCode CLI error."""

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    useful = [line for line in lines if not line.startswith(("WARN", "INFO", "DEBUG"))]
    compact = "\n".join(useful[-12:] if useful else lines[-12:]).strip()
    if len(compact) > limit:
        compact = compact[-limit:]
    return compact or "OpenCode CLI exited without a final message."


def _looks_like_model_unavailable(text: str) -> bool:
    """Heuristic: the configured free model was retired or is unknown."""

    return bool(_MODEL_UNAVAILABLE_RE.search(text or ""))


def _parse_timeout_seconds() -> float:
    """Parse the timeout override env var with an operator-friendly error."""

    raw = os.environ.get("GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS", "")
    if not raw.strip():
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS must be a number of seconds, got {raw!r}.") from None
    if value <= 0:
        raise RuntimeError(f"GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS must be a positive number of seconds, got {raw!r}.")
    return value


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
    default_model = KNOWN_FREE_MODELS[0]

    def __init__(self, profile: Any | None = None) -> None:
        self.command = _opencode_command()
        self.executable = _resolve_opencode_executable(self.command) or self.command
        self.model = (
            getattr(profile, "model", "")
            if profile is not None and getattr(profile, "model", "")
            else os.environ.get("GHOSTCHIMERA_OPENCODE_MODEL", self.default_model)
        )
        self.timeout_seconds = _parse_timeout_seconds()
        self.status = get_opencode_cli_status()
        self.available = self.status.available and self.status.logged_in
        self.last_model_used = ""

    def resolve_model_candidates(self) -> list[str]:
        """Return the ordered model list to try for a chat turn.

        The configured model is always tried first. When it is one of the
        known free-tier models, the remaining known free models are appended
        as fallbacks so a rotated/retired free model does not hard-fail the
        turn. An explicitly configured non-free model is never silently
        replaced: if it is unavailable the operator gets an error telling
        them to update it.
        """

        candidates = [self.model]
        if self.model in KNOWN_FREE_MODELS:
            candidates.extend(m for m in KNOWN_FREE_MODELS if m != self.model)
        return candidates

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
            "model_candidates": self.resolve_model_candidates(),
            "last_model_used": self.last_model_used,
            "auth": "opencode-cli",
            "data_use_notice": FREE_TIER_DATA_USE_NOTICE,
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
        env = {**os.environ, "NO_COLOR": "1"}
        last_error = ""
        for model in self.resolve_model_candidates():
            args = [self.executable, "run", "--format", "json", "--log-level", "ERROR"]
            if model:
                args.extend(["--model", model])
            for path in files:
                args.extend(["--file", path])
            try:
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
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"OpenCode CLI provider timed out after {self.timeout_seconds:g}s "
                    f"(model {model}). Free-tier models can be slow or rate-limited; "
                    "raise GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS or retry later."
                ) from None
            except OSError as exc:
                raise RuntimeError(f"OpenCode CLI provider could not launch {self.executable!r}: {exc}") from None
            answer = _extract_json_answer(result.stdout or "")
            if answer:
                self.last_model_used = model
                return answer
            if result.returncode != 0:
                detail = _compact_opencode_error("\n".join(part for part in (result.stderr, result.stdout) if part))
                last_error = detail
                if _looks_like_model_unavailable(detail):
                    continue
                raise RuntimeError(f"OpenCode CLI provider failed: {detail}")
            # Clean exit but no answer: a CLI/output problem, not a retired
            # model. Fail fast with the truth instead of burning through the
            # remaining candidates and misreporting "retired or unknown".
            raise RuntimeError(
                f"OpenCode CLI provider returned no answer (model {model}, exit code 0). "
                "The CLI exited cleanly but produced no text events, so no fallback "
                "model was tried."
            )
        raise RuntimeError(
            "OpenCode CLI provider failed: the configured free model appears to be "
            f"retired or unknown ({self.model}). Tried: "
            f"{', '.join(self.resolve_model_candidates())}. "
            f"Set GHOSTCHIMERA_OPENCODE_MODEL to a current free model. Last error: {last_error}"
        )


__all__ = [
    "FREE_TIER_DATA_USE_NOTICE",
    "KNOWN_FREE_MODELS",
    "OpenCodeCliProvider",
    "OpenCodeCliStatus",
    "get_opencode_cli_status",
    "opencode_login_command",
    "opencode_setup_guidance",
]
