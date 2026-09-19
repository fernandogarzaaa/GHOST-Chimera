"""GitHub CLI credential import (explicit-consent, local-only).

Reads the user's *own* `gh` login via the supported `gh auth token`
subprocess call (works with keyring and file storage) — never by parsing
credential files. Import is always user-initiated or user-confirmed;
this module never transmits anything anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

GH_PATH_ENV = "GHOSTCHIMERA_GH_PATH"
TIMEOUT_SECONDS = 15.0


class GhCliError(RuntimeError):
    pass


def _gh_bin() -> str:
    override = os.environ.get(GH_PATH_ENV, "").strip()
    if override:
        return override
    found = shutil.which("gh")
    if not found:
        raise GhCliError("GitHub CLI (gh) is not installed")
    return found


def gh_status(*, gh_path: str | None = None) -> dict[str, Any]:
    """Detect a `gh` login without touching the token.

    Returns {"available": bool, "user": str, "scopes": [...], "reason": str}.
    Never raises; all failures report available=False.
    """
    try:
        proc = subprocess.run(
            [gh_path or _gh_bin(), "auth", "status"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (GhCliError, OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "user": "", "scopes": [], "reason": str(exc)[:150]}
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 or "Logged in to" not in output:
        return {"available": False, "user": "", "scopes": [], "reason": "gh is not logged in"}
    user = ""
    scopes: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if "Logged in to" in line and "account" in line:
            parts = line.split("account")
            if len(parts) > 1:
                user = parts[1].strip().split()[0]
        if "Token scopes:" in line:
            scopes = [s.strip().strip("'\"") for s in line.split(":", 1)[1].split(",") if s.strip()]
    return {"available": True, "user": user, "scopes": scopes, "reason": ""}


def gh_token(*, gh_path: str | None = None) -> str:
    """Return the active `gh` OAuth token (caller stores it in the vault)."""
    try:
        proc = subprocess.run(
            [gh_path or _gh_bin(), "auth", "token"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (GhCliError, OSError, subprocess.SubprocessError) as exc:
        raise GhCliError(f"could not read gh token: {exc}") from exc
    if proc.returncode != 0:
        detail = ((proc.stderr or proc.stdout) or "gh auth token failed").strip()[:150]
        raise GhCliError(detail)
    token = (proc.stdout or "").strip().split()[0] if (proc.stdout or "").strip() else ""
    if not token:
        raise GhCliError("gh returned an empty token; run `gh auth login` first")
    return token


__all__ = ["GH_PATH_ENV", "GhCliError", "gh_status", "gh_token"]
