"""Console frontend P0 fixes: tab whitelist, token storage, CSP. No network."""

from __future__ import annotations

import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.control_plane.console import CONSOLE_CSP, _register_static_routes

STATIC = Path("ghostchimera/control_plane/static")


def _js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def test_no_selector_interpolation_of_tab_names() -> None:
    js = _js()
    assert ".tab[data-tab='\" +" not in js
    assert ".tab[data-tab=\"'" + " +" not in js
    assert '"#tab-" +' not in js
    assert "'#tab-' +" not in js
    # Whitelist machinery present instead.
    assert "knownTabs" in js and "tabElement" in js
    assert "getElementById" in js


def test_token_prefers_session_storage() -> None:
    js = _js()
    assert "sessionStorage.setItem(TOKEN_KEY" in js
    assert 'localStorage.setItem("ghostchimera_console_token"' not in js
    assert "localStorage.setItem('ghostchimera_console_token'" not in js
    # Migration path for pre-existing saved tokens stays.
    assert "readStoredToken" in js and "clearStoredToken" in js


def test_csp_covers_console_assets() -> None:
    assert "script-src 'self'" in CONSOLE_CSP
    assert "object-src 'none'" in CONSOLE_CSP
    assert "frame-ancestors 'self'" in CONSOLE_CSP
    # No inline scripts exist, so script-src needs no 'unsafe-inline'.
    # Both scripts are first-party assets (transport must load before app).
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<script src="/static/api_transport.js">' in html
    assert '<script src="/static/app.js">' in html
    assert html.count("<script") == 2


def test_static_responses_carry_csp(tmp_path) -> None:
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=0, http_port=0, config=config)
    _register_static_routes(server)
    server.start()
    try:
        http_port = server._http_server.server_address[1] if server._http_server else server.http_port
        for path, content_type in (
            ("/", "text/html"),
            ("/static/app.js", "application/javascript"),
            ("/static/styles.css", "text/css"),
        ):
            req = urllib.request.Request(f"http://127.0.0.1:{http_port}{path}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status == 200
                assert content_type in resp.headers.get("Content-Type", "")
                csp = resp.headers.get("Content-Security-Policy", "")
                assert "script-src 'self'" in csp, f"{path} missing CSP"
    finally:
        server.stop()
