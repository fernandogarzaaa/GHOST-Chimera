"""Every console HTML document carries CSP + anti-framing headers (redteam P2-1)."""

from __future__ import annotations

import contextlib
import http.client
import io

import pytest

from ghostchimera.control_plane.console import run_console


@pytest.fixture(scope="module")
def console(tmp_path_factory):
    state = tmp_path_factory.mktemp("console-html")
    with contextlib.redirect_stdout(io.StringIO()):
        server = run_console(host="127.0.0.1", port=0, http_port=0, state_dir=state, open_browser=False, block=False)
    try:
        yield int(server._http_server.server_address[1])
    finally:
        server.stop()


def _get(port: int, path: str) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp


@pytest.mark.parametrize("path", ["/", "/console", "/?state=x&error=access_denied", "/static/index.html"])
def test_html_documents_have_security_headers(console, path) -> None:
    resp = _get(console, path)
    assert resp.getheader("Content-Type", "").startswith("text/html")
    csp = resp.getheader("Content-Security-Policy") or ""
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert resp.getheader("X-Frame-Options") == "DENY"
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert resp.getheader("Referrer-Policy") == "no-referrer"
