"""Browser CSV credential import (explicit, local-only, no network).

Chrome/Brave/Edge export saved logins as CSV via Settings → Passwords →
Export (the OS password prompt there is the user's consent). This module
parses that export for preview, suggests a Ghost vault mapping per row,
and shreds files on request. Passwords never leave the machine; previews
and logs carry labels only.
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import urllib.parse
from typing import Any

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
EXPECTED_HEADER = ("name", "url", "username", "password")

# Row sources that map to Ghost concepts. Anything else defaults to BYOK
# (user picks per row in the UI; these are just suggestions).
_MAIL_HOSTS = ("mail.google.com", "gmail.", "outlook.", "live.com", "hotmail.", "yahoo.", "icloud.")
_OAUTH_PREFERRED = ("github.com", "google.com", "slack.com", "notion.", "discord.")


class CredentialImportError(ValueError):
    pass


def _root_host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def suggest_mapping(url: str) -> dict[str, str]:
    """Suggest a vault mapping for a row. Advisory only — the user decides."""
    host = _root_host(url)
    if any(token in host for token in _MAIL_HOSTS):
        return {
            "kind": "app_password",
            "note": "Mail provider: paste the provider-issued app password here, never the account password.",
        }
    if "google.com" in host:
        # A CSV row for Google holds the *account* password, which Google
        # rejects over IMAP/SMTP. Point at the working alternatives instead.
        return {
            "kind": "skip",
            "note": "Account passwords don't work here — use OAuth login above or generate an app password and save it as one.",
        }
    if any(token in host for token in _OAUTH_PREFERRED):
        return {
            "kind": "skip",
            "note": "Use the provider's OAuth login above instead of a stored password.",
        }
    return {"kind": "byok", "note": "Generic key; label it so you know where it is used."}


def parse_browser_csv(text: str) -> list[dict[str, Any]]:
    """Parse a Chrome-style password CSV export.

    Returns preview rows WITHOUT passwords:
    [{index, name, url, username, has_password, suggested_kind, note}].
    Raises CredentialImportError on format/size problems.
    """
    if len(text.encode("utf-8", "replace")) > MAX_CSV_BYTES:
        raise CredentialImportError("export is too large (over 2 MB)")
    try:
        reader = csv.DictReader(io.StringIO(text))
        header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    except Exception as exc:
        raise CredentialImportError(f"could not parse CSV: {exc}") from exc
    if header[:4] != list(EXPECTED_HEADER):
        raise CredentialImportError("not a Chrome-style password export (expected name,url,username,password columns)")
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(reader):
        if index >= MAX_ROWS:
            break
        url = str(record.get("url") or "").strip()
        username = str(record.get("username") or "").strip()
        password = str(record.get("password") or "")
        if not url and not username and not password:
            continue
        suggestion = suggest_mapping(url)
        rows.append(
            {
                "index": index,
                "name": str(record.get("name") or "").strip()[:160],
                "url": url[:300],
                "username": username[:160],
                "has_password": bool(password),
                "suggested_kind": suggestion["kind"],
                "note": suggestion["note"],
            }
        )
    return rows


def extract_passwords(text: str) -> dict[int, str]:
    """Return {index: password} for commit (caller stores, never logs)."""
    reader = csv.DictReader(io.StringIO(text))
    out: dict[int, str] = {}
    for index, record in enumerate(reader):
        if index >= MAX_ROWS:
            break
        password = str((record.get("password") if record else "") or "")
        if password:
            out[index] = password
    return out


def shred_file(path: str) -> bool:
    """Overwrite a file with zeros then delete it. Best-effort; returns ok."""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as handle:
            handle.write(b"\x00" * size)
            handle.flush()
            with contextlib.suppress(OSError):
                os.fsync(handle.fileno())
        os.remove(path)
        return True
    except OSError:
        return False


__all__ = [
    "CredentialImportError",
    "extract_passwords",
    "parse_browser_csv",
    "shred_file",
    "suggest_mapping",
]
