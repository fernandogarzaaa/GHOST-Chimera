"""Console startup output regressions (newcomer P2-8)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest


def test_first_run_token_lines_reach_a_redirected_stdout(tmp_path) -> None:
    """The one-time token line must be flushed, not lost in a pipe buffer."""
    log = tmp_path / "console.log"
    script = (
        "from ghostchimera.control_plane.console import run_console\n"
        f"run_console(host='127.0.0.1', port=0, http_port=0, state_dir={str(tmp_path / 'state')!r},"
        " open_browser=False, block=True)\n"
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "GHOSTCHIMERA_STATE_DIR": str(tmp_path / "state"),
        "NO_PROXY": "127.0.0.1,localhost",
    }
    with log.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen([sys.executable, "-c", script], stdout=out, stderr=subprocess.STDOUT, env=env)
        try:
            deadline = time.monotonic() + 40
            text = ""
            while time.monotonic() < deadline:
                text = log.read_text(encoding="utf-8", errors="replace")
                if "Open the console with:" in text or proc.poll() is not None:
                    break
                time.sleep(0.2)
        finally:
            proc.kill()  # simulate the user stopping the process: no exit-time flush
            proc.wait(timeout=10)
    assert "Ghost Console: http://127.0.0.1:" in text, text[-2000:]
    assert "New console token" in text
    assert "Open the console with: http://127.0.0.1:" in text


def test_console_warns_loudly_when_requested_port_is_busy(tmp_path, capsys) -> None:
    from ghostchimera.control_plane.console import run_console

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy = blocker.getsockname()[1]
    server = None
    try:
        server = run_console(
            host="127.0.0.1",
            port=0,
            http_port=busy,
            state_dir=tmp_path / "state",
            open_browser=False,
            block=False,
        )
        actual = int(server._http_server.server_address[1])
        assert actual != busy
        err = capsys.readouterr().err
        assert "WARNING" in err
        assert f"HTTP port {busy} -> {actual}" in err
        assert f"http://127.0.0.1:{actual}/" in err
    finally:
        if server is not None:
            server.stop()
        blocker.close()


def test_console_is_quiet_about_ports_when_nothing_moved(tmp_path, capsys) -> None:
    from ghostchimera.control_plane.console import run_console

    server = run_console(
        host="127.0.0.1", port=0, http_port=0, state_dir=tmp_path / "state", open_browser=False, block=False
    )
    try:
        assert "moved" not in capsys.readouterr().err
    finally:
        server.stop()


if sys.platform == "win32":  # pragma: no cover
    pytestmark = pytest.mark.skip("POSIX kill semantics")
