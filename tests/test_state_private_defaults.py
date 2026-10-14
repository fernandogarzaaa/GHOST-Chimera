"""Item 7: state files 0600 and state dirs 0700 regardless of umask.

Every store goes through ghostchimera.state_io, so a permissive umask
(0o000/0o022) no longer leaks chat history, approvals, config keys, memory,
or logs to other local users.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(autouse=True)
def wide_open_umask():  # type: ignore[no-untyped-def]
    old = os.umask(0)
    try:
        yield
    finally:
        os.umask(old)


def test_trust_and_conversation_state_is_private(tmp_path: Path) -> None:
    from ghostchimera.control_plane.conversation import ConversationStore
    from ghostchimera.trust_runtime import TrustRuntimeStore

    state = tmp_path / "state"
    store = TrustRuntimeStore(state)
    run_id = store.create_run("perm check")["run_id"]
    store.create_approval(run_id, step_id="s", summary="x")
    ConversationStore(state).create_session(session_id="c1")

    trust = state / "trust_runtime"
    assert _mode(trust) == 0o700 and _mode(trust / "runs") == 0o700
    for name in ("run_index.json", "approvals.json"):
        assert _mode(trust / name) == 0o600, name
    assert _mode(trust / "runs" / f"{run_id}.jsonl") == 0o600
    assert _mode(state / "conversation_sessions.json") == 0o600
    assert _mode(state) == 0o700


def test_config_and_state_dir_helpers_are_private(tmp_path: Path) -> None:
    from ghostchimera.control_plane.config import ensure_state_dir, load_config, save_config

    state = ensure_state_dir(tmp_path / "gc")
    assert _mode(state) == 0o700
    cfg = state / "config.json"
    save_config({"model": {"api_key": "sk-x"}}, cfg)
    assert _mode(cfg) == 0o600
    assert load_config(cfg)["model"]["api_key"] == "sk-x"


def test_corrupt_config_is_preserved(tmp_path: Path) -> None:
    from ghostchimera.control_plane.config import load_config

    cfg = tmp_path / "config.json"
    cfg.write_text('{"model": ')
    assert load_config(cfg) == {}
    assert list(tmp_path.glob("config.json.corrupt-*"))


def test_runtime_config_state_dirs_are_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.config import GhostChimeraConfig

    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.delenv("GHOSTCHIMERA_MEMORY_DB", raising=False)
    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_FILE", raising=False)
    GhostChimeraConfig.from_env().ensure_state_dirs()
    assert _mode(tmp_path / "s") == 0o700


def test_memory_files_are_private(tmp_path: Path) -> None:
    from ghostchimera.agent_core.memory import MemoryManager
    from ghostchimera.memory_layer.store import MemoryStore

    MemoryStore(tmp_path / "memory.sqlite3")
    assert _mode(tmp_path / "memory.sqlite3") == 0o600
    manager = MemoryManager(str(tmp_path / "memory.json"))
    manager.add_event({"k": "v"})
    assert _mode(tmp_path / "memory.json") == 0o600
    assert json.loads((tmp_path / "memory.json").read_text())[0]["k"] == "v"
