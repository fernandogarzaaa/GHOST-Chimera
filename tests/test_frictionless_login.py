"""Frictionless login: gh import, custom keys, CSV import, browser vault. No real network."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors import gh_cli
from ghostchimera.connectors.auth_engine import CustomAuthEngine
from ghostchimera.connectors.browser_vault import (
    BrowserVaultError,
    login_store_paths,
    preview_chromium,
)
from ghostchimera.connectors.console_routes import register_connector_routes
from ghostchimera.connectors.credential_import import (
    CredentialImportError,
    extract_passwords,
    parse_browser_csv,
    shred_file,
    suggest_mapping,
)

_PORT = [19273]

CSV_SAMPLE = (
    "name,url,username,password,note\n"
    "Gmail,https://mail.google.com/,user@gmail.com,abcdefghijklmnop,\n"
    "GitHub,https://github.com/,octocat,s3cret-token-value,\n"
    "Blog,https://example.com/login,reader,hunter2-hunter,\n"
)


def _server(tmp_path: Path) -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    server._test_http_port = http_port  # type: ignore[attr-defined]
    return server


def _base(server: GatewayServer) -> str:
    return f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _gh_shim(tmp_path: Path) -> str:
    shim = tmp_path / "gh.cmd"
    shim.write_text(
        "@echo off\n"
        'if "%1"=="auth" if "%2"=="status" (\n'
        "  echo Logged in to github.com account shimuser\n"
        "  echo Token scopes: repo, gist\n"
        "  exit /b 0\n"
        ")\n"
        'if "%1"=="auth" if "%2"=="token" (\n'
        "  echo gho_shimtoken1234567890\n"
        "  exit /b 0\n"
        ")\n"
        "exit /b 1\n",
        encoding="utf-8",
    )
    return str(shim)


# -- gh CLI ----------------------------------------------------------------------
def test_gh_status_parses_shim(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", _gh_shim(tmp_path))
    status = gh_cli.gh_status()
    assert status["available"] is True
    assert status["user"] == "shimuser"
    assert "repo" in status["scopes"]


def test_gh_status_missing_binary(monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", "C:/no/such/gh.exe")
    status = gh_cli.gh_status()
    assert status["available"] is False


def test_gh_token_shim(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", _gh_shim(tmp_path))
    assert gh_cli.gh_token() == "gho_shimtoken1234567890"


def test_engine_import_gh_cli(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", _gh_shim(tmp_path))
    engine = CustomAuthEngine(tmp_path)
    try:
        engine._github_user_login = lambda token: "shimuser"  # type: ignore[method-assign]
        out = engine.import_gh_cli("user-1")
        assert out["ok"] is True and out["source"] == "github-cli"
        record = engine.store.get("user-1", "github")
        assert record is not None and record["status"] == "ACTIVE"
        # Token material decryptable internally, redacted in listings.
        listed = engine.store.list_for("user-1")
        assert all("gho_shim" not in json.dumps(item) for item in listed)
    finally:
        engine.close()


def test_engine_import_gh_cli_no_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", "C:/no/such/gh.exe")
    engine = CustomAuthEngine(tmp_path)
    try:
        with pytest.raises(Exception, match="unavailable|not installed"):
            engine.import_gh_cli("user-1")
    finally:
        engine.close()


def test_gh_routes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_GH_PATH", _gh_shim(tmp_path))
    server = _server(tmp_path)
    try:
        status = _post(_base(server) + "/api/auth/gh/status", {})
        assert status["ok"] is True and status["available"] is True
        assert _post(_base(server) + "/api/auth/gh/import", {})["ok"] is False
    finally:
        server.stop()


# -- custom keys -------------------------------------------------------------------
def test_custom_key_round_trip(tmp_path) -> None:
    engine = CustomAuthEngine(tmp_path)
    try:
        saved = engine.save_custom_key("u", "byok", "OpenRouter", "or-v1-secret-value-123")
        assert saved["ok"] is True
        keys = engine.store.list_custom_keys("u")
        assert len(keys) == 1 and keys[0]["label"] == "OpenRouter"
        assert "or-v1" not in json.dumps(keys)
        revealed = engine.reveal_custom_key("u", saved["id"])
        assert revealed["secret"] == "or-v1-secret-value-123"
        assert engine.store.delete_custom_key("u", saved["id"]) is True
        assert engine.store.list_custom_keys("u") == []
    finally:
        engine.close()


def test_custom_key_validation(tmp_path) -> None:
    engine = CustomAuthEngine(tmp_path)
    try:
        with pytest.raises(Exception, match="unknown key kind"):
            engine.save_custom_key("u", "nope", "L", "secret-value-123")
        with pytest.raises(Exception, match="required"):
            engine.save_custom_key("u", "byok", "", "secret-value-123")
        with pytest.raises(Exception, match="length"):
            engine.save_custom_key("u", "byok", "L", "short")
        with pytest.raises(Exception, match="app passwords"):
            engine.save_custom_key("u", "app_password", "Gmail", "shortpass1")
        ok = engine.save_custom_key("u", "app_password", "Gmail", "abcd efgh ijkl mnop")
        assert ok["ok"] is True
    finally:
        engine.close()


def test_keys_routes_redacted(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        base = _base(server)
        saved = _post(
            base + "/api/auth/keys/save",
            {
                "kind": "byok",
                "label": "X",
                "secret": "xai-secret-value-123",
            },
        )
        assert saved["ok"] is True
        listed = _post(base + "/api/auth/keys/list", {})
        assert listed["ok"] is True and len(listed["keys"]) == 1
        assert "xai-secret" not in json.dumps(listed)
        assert _post(base + "/api/auth/keys/delete", {"id": saved["id"]}) == {"ok": True, "deleted": True}
    finally:
        server.stop()


# -- CSV import ----------------------------------------------------------------------
def test_parse_browser_csv() -> None:
    rows = parse_browser_csv(CSV_SAMPLE)
    assert len(rows) == 3
    assert all("password" not in r for r in rows)
    by_url = {r["url"]: r for r in rows}
    assert by_url["https://mail.google.com/"]["suggested_kind"] == "app_password"
    assert by_url["https://github.com/"]["suggested_kind"] == "skip"
    assert by_url["https://example.com/login"]["suggested_kind"] == "byok"


def test_parse_browser_csv_rejects() -> None:
    with pytest.raises(CredentialImportError, match="Chrome-style"):
        parse_browser_csv("a,b,c\n1,2,3\n")
    with pytest.raises(CredentialImportError, match="too large"):
        parse_browser_csv("name,url,username,password\n" + "x" * (3 * 1024 * 1024))


def test_suggest_mapping() -> None:
    assert suggest_mapping("https://mail.google.com/")["kind"] == "app_password"
    assert suggest_mapping("https://accounts.google.com/")["kind"] == "skip"
    assert suggest_mapping("https://github.com/login")["kind"] == "skip"
    assert suggest_mapping("https://my-router.local/")["kind"] == "byok"


def test_extract_passwords_never_logged() -> None:
    passwords = extract_passwords(CSV_SAMPLE)
    assert passwords[1] == "s3cret-token-value"
    assert len(passwords) == 3


def test_shred_file(tmp_path) -> None:
    target = tmp_path / "secret.csv"
    target.write_text("sensitive", encoding="utf-8")
    assert shred_file(str(target)) is True
    assert not target.exists()
    assert shred_file(str(tmp_path / "missing")) is False


def test_csv_commit_route(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _post(
            _base(server) + "/api/auth/import-csv/commit",
            {
                "csv_text": CSV_SAMPLE,
                "selections": [
                    {"index": 0, "kind": "app_password", "label": "Gmail"},
                    {"index": 2, "kind": "byok", "label": "Blog"},
                    {"index": 9, "kind": "byok", "label": "Ghost"},
                ],
            },
        )
        assert data["ok"] is True
        by_index = {s["index"]: s for s in data["saved"]}
        assert by_index[0]["saved"] is True and by_index[2]["saved"] is True
        assert by_index[9]["saved"] is False
        assert "hunter2" not in json.dumps(data) and "abcdef" not in json.dumps(data)
        keys = _post(_base(server) + "/api/auth/keys/list", {})["keys"]
        assert {k["label"] for k in keys} == {"Gmail", "Blog"}
    finally:
        server.stop()


def test_csv_preview_route(tmp_path) -> None:
    server = _server(tmp_path)
    try:
        data = _post(_base(server) + "/api/auth/import-csv/preview", {"csv_text": CSV_SAMPLE})
        assert data["ok"] is True and data["count"] == 3
        assert "hunter2" not in json.dumps(data)
        bad = _post(_base(server) + "/api/auth/import-csv/preview", {"csv_text": "nope"})
        assert bad["ok"] is False
    finally:
        server.stop()


# -- browser vault ---------------------------------------------------------------------
def test_browser_vault_requires_consent() -> None:
    with pytest.raises(BrowserVaultError, match="consent"):
        preview_chromium("chrome", consent=False)


def test_browser_vault_rejects_unknown_browser() -> None:
    with pytest.raises(BrowserVaultError, match="unsupported browser|Windows-only"):
        preview_chromium("firefox", consent=True)


def test_browser_vault_paths_do_not_read() -> None:
    paths = login_store_paths("brave")
    assert set(paths) == {"db", "local_state", "profile"}


def test_browser_vault_modules_make_no_network_calls() -> None:
    import ghostchimera.connectors.browser_vault as bv
    import ghostchimera.connectors.credential_import as ci

    for module in (bv, ci):
        with open(module.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for marker in ("urllib.request", "urlopen", "socket", "requests.", "httpx"):
            assert marker not in source, f"{module.__name__} must stay offline ({marker})"


def test_dpapi_round_trip_windows(tmp_path) -> None:
    """End-to-end decrypt through a fabricated Chromium profile (Windows DPAPI)."""
    import ctypes
    from ctypes import wintypes

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from ghostchimera.connectors.browser_vault import _decrypt_password, _master_key

    if os.name != "nt":
        pytest.skip("DPAPI is Windows-only")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _protect(raw: bytes) -> bytes:
        buf = ctypes.create_string_buffer(raw, len(raw))
        blob_in = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        assert ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    import base64 as _b64

    key = AESGCM.generate_key(bit_length=256)
    local_state = tmp_path / "Local State"
    local_state.write_text(
        json.dumps({"os_crypt": {"encrypted_key": _b64.b64encode(b"DPAPI" + _protect(key)).decode()}}),
        encoding="utf-8",
    )
    assert _master_key(local_state) == key

    nonce = os.urandom(12)
    blob = b"v10" + nonce + AESGCM(key).encrypt(nonce, b"browser-secret-1", None)
    assert _decrypt_password(blob, key) == "browser-secret-1"

    db = tmp_path / "Login Data"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE logins(origin_url TEXT, username_value TEXT, password_value BLOB, blacklisted_by_user INT)"
    )
    conn.execute("INSERT INTO logins VALUES(?,?,?,0)", ("https://example.com/", "reader", blob))
    conn.commit()
    conn.close()

    from ghostchimera.connectors.browser_vault import _read_rows

    rows = _read_rows(db, key, with_passwords=True)
    assert rows[0]["password"] == "browser-secret-1"
    assert not list(tmp_path.glob("ghost-logins-*.db"))
