"""Per-install Ghost Console secrets.

The console API is never open by default: on first run a random console
token is generated and stored owner-only (0600 on POSIX) in
``<state_dir>/console_secrets.json`` (``~/.ghostchimera`` unless
``GHOSTCHIMERA_STATE_DIR`` / ``--state-dir`` says otherwise). ``--auth-token``
still overrides the stored token for a run.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SECRETS_FILENAME = "console_secrets.json"
_MIN_TOKEN_LENGTH = 16


@dataclass(frozen=True)
class ConsoleSecrets:
    """Secrets generated once per install (per state directory)."""

    token: str
    path: Path
    created: bool = False


def secrets_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / SECRETS_FILENAME


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def _chmod_private(path: Path, mode: int) -> None:
    if os.name != "posix":
        return
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def _write_private_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write *data* as JSON, created 0600 from the first byte."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private(path.parent, 0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
    _chmod_private(path, 0o600)


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    _chmod_private(path, 0o600)  # repair a file loosened by hand
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_or_create_console_secrets(state_dir: str | Path) -> ConsoleSecrets:
    """Load this install's console secrets, generating any that are missing.

    ``created`` is True whenever something new was written, so the caller can
    show the new value exactly once.
    """
    path = secrets_path(state_dir)
    data = _read(path)
    token = str(data.get("token") or "").strip()
    created = False
    if len(token) < _MIN_TOKEN_LENGTH:
        token = generate_token()
        created = True
    if created:
        _write_private_json(path, {**data, "token": token})
    return ConsoleSecrets(token=token, path=path, created=created)


__all__ = ["SECRETS_FILENAME", "ConsoleSecrets", "generate_token", "load_or_create_console_secrets", "secrets_path"]
