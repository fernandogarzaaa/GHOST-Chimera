"""Direct Chromium login-store reader (OPT-IN, isolated, local-only).

Reads the user's *own* browser-saved logins (Chrome/Brave/Edge share the
Chromium format) only after explicit in-UI consent. Windows-only in v1
(DPAPI); other platforms raise with a pointer to CSV import.

Risk posture (deliberate):
- This module is import-isolated: nothing imports it except the explicit
  console routes. Packagers can exclude the file to drop the capability.
- No network calls anywhere in this file (asserted by tests).
- Stdlib + the repo's existing `cryptography` dependency only.
- Every read is user-initiated, audit-logged by the caller, and the temp
  DB copy is shredded after use.

Like password-manager importers (Bitwarden, 1Password all ship this),
the OS account-unlock/consent screen is the authorization boundary.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

CONSENT_TEXT = (
    "Read my browser's saved logins on this machine only. Nothing leaves this computer; I can map or skip each entry."
)


class BrowserVaultError(RuntimeError):
    pass


_BROWSERS = ("chrome", "brave", "edge")


def _candidate_dirs(browser: str) -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        mapping = {
            "chrome": base / "Google" / "Chrome" / "User Data",
            "brave": base / "BraveSoftware" / "Brave-Browser" / "User Data",
            "edge": base / "Microsoft" / "Edge" / "User Data",
        }
    elif sys.platform == "darwin":
        mapping = {
            "chrome": home / "Library" / "Application Support" / "Google" / "Chrome",
            "brave": home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser",
            "edge": home / "Library" / "Application Support" / "Microsoft Edge",
        }
    else:
        mapping = {
            "chrome": home / ".config" / "google-chrome",
            "brave": home / ".config" / "BraveSoftware" / "Brave-Browser",
            "edge": home / ".config" / "microsoft-edge",
        }
    return [mapping.get(browser, mapping["chrome"])]


def login_store_paths(browser: str) -> dict[str, Path | None]:
    """Locate (not read) the login DB + Local State key file."""
    if browser not in _BROWSERS:
        raise BrowserVaultError(f"unsupported browser: {browser}")
    profiles = ["Default", "Profile 1", "Profile 2"]
    for root in _candidate_dirs(browser):
        local_state = root / "Local State"
        if not local_state.is_file():
            continue
        for profile in profiles:
            db = root / profile / "Login Data"
            if db.is_file():
                return {"db": db, "local_state": local_state, "profile": profile}
    return {"db": None, "local_state": None, "profile": ""}


def _dpapi_unprotect(blob: bytes) -> bytes:
    """DPAPI-decrypt bytes for the current Windows user (ctypes, stdlib)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(blob, len(blob))
    blob_in = DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise BrowserVaultError("OS key unlock failed (DPAPI)")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _master_key(local_state: Path) -> bytes:
    try:
        data = json.loads(local_state.read_text(encoding="utf-8"))
        protected = base64.b64decode(data["os_crypt"]["encrypted_key"])
    except Exception as exc:
        raise BrowserVaultError(f"cannot read browser key file: {exc}") from exc
    if not protected.startswith(b"DPAPI"):
        raise BrowserVaultError("unexpected browser key envelope")
    return _dpapi_unprotect(protected[5:])


def _decrypt_password(blob: bytes, key: bytes) -> str:
    if blob.startswith(b"v10") or blob.startswith(b"v11"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce, payload = blob[3:15], blob[15:]
        try:
            return AESGCM(key).decrypt(nonce, payload, None).decode("utf-8", "replace")
        except Exception as exc:
            raise BrowserVaultError(f"entry decrypt failed: {exc}") from exc
    # Legacy DPAPI-direct blob (old Chromium).
    try:
        return _dpapi_unprotect(blob).decode("utf-8", "replace")
    except Exception as exc:
        raise BrowserVaultError(f"entry decrypt failed: {exc}") from exc


def _read_rows(db: Path, key: bytes, *, with_passwords: bool) -> list[dict[str, Any]]:
    fd, tmp = tempfile.mkstemp(prefix="ghost-logins-", suffix=".db")
    os.close(fd)
    try:
        shutil.copy2(db, tmp)
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT origin_url, username_value, password_value FROM logins WHERE blacklisted_by_user = 0"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BrowserVaultError(f"cannot read login store (is the browser open? close it and retry): {exc}") from exc
    finally:
        # Shred the temp copy regardless of outcome.
        try:
            size = os.path.getsize(tmp)
            with open(tmp, "r+b") as handle:
                handle.write(b"\x00" * size)
            os.remove(tmp)
        except OSError:
            pass
    out: list[dict[str, Any]] = []
    for index, (url, username, blob) in enumerate(rows):
        if not username and not blob:
            continue
        entry: dict[str, Any] = {"index": index, "url": str(url or "")[:300], "username": str(username or "")[:160]}
        if with_passwords:
            try:
                entry["password"] = _decrypt_password(bytes(blob), key)
            except BrowserVaultError:
                entry["password"] = ""
        out.append(entry)
    return out


def preview_chromium(browser: str, *, consent: bool = False) -> dict[str, Any]:
    """List saved-login labels (no passwords) after explicit consent."""
    if sys.platform != "win32":
        raise BrowserVaultError("direct reading is Windows-only in v1; use CSV import on this platform")
    if consent is not True:
        raise BrowserVaultError("explicit consent is required")
    if browser not in _BROWSERS:
        raise BrowserVaultError(f"unsupported browser: {browser}")
    paths = login_store_paths(browser)
    if paths["db"] is None:
        raise BrowserVaultError(f"no {browser} login store found for this user")
    assert paths["local_state"] is not None
    key = _master_key(paths["local_state"])
    assert paths["db"] is not None
    rows = _read_rows(paths["db"], key, with_passwords=False)
    from .credential_import import suggest_mapping

    entries = []
    for r in rows:
        suggestion = suggest_mapping(r["url"])
        entries.append(
            {
                "index": r["index"],
                "url": r["url"],
                "username": r["username"],
                "has_password": True,
                "suggested_kind": suggestion["kind"],
                "note": suggestion["note"],
            }
        )
    return {"browser": browser, "profile": paths["profile"], "entries": entries}


def import_chromium(browser: str, *, consent: bool = False, indices: list[int] | None = None) -> list[dict[str, str]]:
    """Decrypt ONLY the selected entries. Returns [{url, username, password}].

    The caller stores them in the vault immediately and never logs them.
    """
    if sys.platform != "win32":
        raise BrowserVaultError("direct reading is Windows-only in v1; use CSV import on this platform")
    if consent is not True:
        raise BrowserVaultError("explicit consent is required")
    if browser not in _BROWSERS:
        raise BrowserVaultError(f"unsupported browser: {browser}")
    paths = login_store_paths(browser)
    if paths["db"] is None:
        raise BrowserVaultError(f"no {browser} login store found for this user")
    assert paths["local_state"] is not None and paths["db"] is not None
    key = _master_key(paths["local_state"])
    wanted = set(indices or [])
    rows = _read_rows(paths["db"], key, with_passwords=True)
    return [
        {"index": r["index"], "url": r["url"], "username": r.get("username", ""), "password": r.get("password", "")}
        for r in rows
        if (not wanted or r["index"] in wanted) and r.get("password")
    ]


__all__ = [
    "BrowserVaultError",
    "CONSENT_TEXT",
    "import_chromium",
    "login_store_paths",
    "preview_chromium",
]
