"""Console state is owner-only: umask 077 + existing files tightened (redteam P2-2)."""

from __future__ import annotations

import contextlib
import io
import os
import stat
from unittest import mock

import pytest

from ghostchimera.control_plane import console as console_mod
from ghostchimera.control_plane.console import harden_state_permissions, run_console

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")


def test_existing_state_is_tightened_and_new_files_are_owner_only(tmp_path) -> None:
    state = tmp_path / "state"
    (state / "trust_runtime").mkdir(parents=True)
    db = state / "memory.sqlite3"
    db.write_text("x")
    db.chmod(0o644)
    journal = state / "trust_runtime" / "run_index.json"
    journal.write_text("{}")
    journal.chmod(0o664)
    tool = state / "hook.sh"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    (state / "trust_runtime").chmod(0o755)
    old = os.umask(0o022)
    try:
        harden_state_permissions(state)
        assert stat.S_IMODE(db.stat().st_mode) == 0o600
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600
        assert stat.S_IMODE(tool.stat().st_mode) == 0o700
        assert stat.S_IMODE((state / "trust_runtime").stat().st_mode) == 0o700
        fresh = state / "audit.jsonl"
        fresh.write_text("{}")
        assert stat.S_IMODE(fresh.stat().st_mode) == 0o600
        newdir = state / "audit"
        newdir.mkdir()
        assert stat.S_IMODE(newdir.stat().st_mode) == 0o700
    finally:
        os.umask(old)


def _current_umask() -> int:
    value = os.umask(0o022)
    os.umask(value)
    return value


def test_set_umask_false_tightens_files_without_touching_process_umask(tmp_path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    db = state / "memory.sqlite3"
    db.write_text("x")
    db.chmod(0o644)
    old = os.umask(0o022)
    try:
        assert harden_state_permissions(state, set_umask=False) is None
        assert _current_umask() == 0o022
        assert stat.S_IMODE(db.stat().st_mode) == 0o600
        assert harden_state_permissions(state) == 0o022  # returns the previous umask
        assert _current_umask() == 0o077
    finally:
        os.umask(old)


def test_embedded_non_blocking_console_does_not_change_host_umask(tmp_path) -> None:
    old = os.umask(0o022)
    server = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            server = run_console(
                host="127.0.0.1", port=0, http_port=0, state_dir=tmp_path / "s", open_browser=False, block=False
            )
        assert _current_umask() == 0o022
        assert stat.S_IMODE((tmp_path / "s").stat().st_mode) == 0o700
    finally:
        if server is not None:
            server.stop()
        os.umask(old)


def test_blocking_console_entry_sets_owner_only_umask(tmp_path) -> None:
    old = os.umask(0o022)
    seen: list[int] = []

    def _interrupt(_seconds: float) -> None:
        seen.append(_current_umask())
        raise KeyboardInterrupt

    try:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            mock.patch.object(console_mod.time, "sleep", side_effect=_interrupt),
        ):
            run_console(host="127.0.0.1", port=0, http_port=0, state_dir=tmp_path / "s", open_browser=False, block=True)
        assert seen == [0o077]
    finally:
        os.umask(old)
