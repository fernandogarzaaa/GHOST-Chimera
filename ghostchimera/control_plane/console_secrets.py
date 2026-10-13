"""Per-install Ghost Console secrets.

The console API is never open by default: on first run a random console
token is generated and stored owner-only (0600 on POSIX) in
``<state_dir>/console_secrets.json`` (``~/.ghostchimera`` unless
``GHOSTCHIMERA_STATE_DIR`` / ``--state-dir`` says otherwise). ``--auth-token``
still overrides the stored token for a run.

The same file holds this install's random host-execution arming phrase,
which replaces the public ``I ACCEPT HOST EXECUTION RISK`` constant for the
console, so arming cannot be scripted from a phrase published in the source.
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
ARMING_PHRASE_PREFIX = "I ACCEPT HOST EXECUTION RISK"
_MIN_TOKEN_LENGTH = 16


@dataclass(frozen=True)
class ConsoleSecrets:
    """Secrets generated once per install (per state directory)."""

    token: str
    path: Path
    created: bool = False
    arming_phrase: str = ""


def secrets_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / SECRETS_FILENAME


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def generate_arming_phrase() -> str:
    """A typeable phrase with a 32-bit random suffix, e.g. ``... RISK 7F3A-C21B``."""
    code = secrets.token_hex(4).upper()
    return f"{ARMING_PHRASE_PREFIX} {code[:4]}-{code[4:]}"


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
    phrase = str(data.get("arming_phrase") or "").strip()
    if not phrase.startswith(ARMING_PHRASE_PREFIX + " ") or len(phrase) < len(ARMING_PHRASE_PREFIX) + 8:
        phrase = generate_arming_phrase()
        created = True
    if created:
        _write_private_json(path, {**data, "token": token, "arming_phrase": phrase})
    return ConsoleSecrets(token=token, path=path, created=created, arming_phrase=phrase)


__all__ = [
    "ARMING_PHRASE_PREFIX",
    "SECRETS_FILENAME",
    "ConsoleSecrets",
    "generate_arming_phrase",
    "generate_token",
    "load_or_create_console_secrets",
    "secrets_path",
]
