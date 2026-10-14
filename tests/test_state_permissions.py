"""Console state is owner-only: umask 077 + existing files tightened (redteam P2-2)."""

from __future__ import annotations

import os
import stat

import pytest

from ghostchimera.control_plane.console import harden_state_permissions

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
