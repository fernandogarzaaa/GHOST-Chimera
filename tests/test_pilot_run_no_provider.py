"""`ghost --pilot-run` must fail cleanly (no traceback) when no provider is configured."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot import NoBackendAvailableError
from ghostchimera.control_plane import cli
from ghostchimera.control_plane.provider_hint import no_provider_message


def test_message_names_nebius_key_and_alternatives() -> None:
    msg = no_provider_message("do a thing", "No available backend", env={})
    assert "NEBIUS_API_KEY" in msg
    assert "export NEBIUS_API_KEY=..." in msg
    assert "ghost demo" in msg
    assert "ghost setup" in msg
    assert "Traceback" not in msg


def test_pilot_run_no_backend_prints_hint_and_exits_nonzero(monkeypatch, capsys) -> None:
    class _Kernel:
        policy = None

        def run(self, objective):
            raise NoBackendAvailableError("reasoning-x", "reasoning")

    monkeypatch.setattr("ghostchimera.chimera_pilot.ChimeraPilotKernel.default", lambda **_k: _Kernel())
    rc = cli._main(["--pilot-run", "summarize this repo"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "NEBIUS_API_KEY" in captured.err
    assert "summarize this repo" in captured.err


def test_no_backend_error_is_runtime_error_subclass() -> None:
    # Existing callers that catch RuntimeError keep working.
    assert issubclass(NoBackendAvailableError, RuntimeError)


@pytest.mark.skipif(sys.platform == "win32", reason="subprocess env isolation is POSIX-specific here")
def test_pilot_run_subprocess_without_keys_has_no_traceback(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["GHOSTCHIMERA_STATE_DIR"] = str(tmp_path / "state")
    proc = subprocess.run(
        [sys.executable, "-m", "ghostchimera.control_plane.cli", "--pilot-run", "summarize this repository"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    out = proc.stdout + proc.stderr
    assert "Traceback" not in out, out
    if proc.returncode != 0:
        # No provider reachable in this environment: friendly hint, clean non-zero exit.
        assert proc.returncode == 2, out
        assert "NEBIUS_API_KEY" in proc.stderr
