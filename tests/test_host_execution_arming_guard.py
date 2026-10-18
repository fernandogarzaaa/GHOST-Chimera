"""Host-mode arming phrase: brute-force lockout and scope changes need the phrase (redteam P1-6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghostchimera.control_plane import host_execution as he
from ghostchimera.control_plane.host_execution import HostExecutionStore

PHRASE = "I ACCEPT HOST EXECUTION RISK ab12-cd34"


@pytest.fixture
def store(tmp_path):
    return HostExecutionStore(tmp_path / "state", confirmation_phrase=PHRASE)


def test_wrong_guesses_lock_out_even_the_right_phrase(store, tmp_path, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(he, "_now", lambda: clock[0])
    for _ in range(store.MAX_FREE_FAILURES):
        assert store.update_settings({"unrestricted_host_mode": True, "confirmation_phrase": "guess"})["ok"] is False
    locked = store.update_settings(
        {"unrestricted_host_mode": True, "confirmation_phrase": PHRASE, "allowed_root": str(tmp_path)}
    )
    assert locked["ok"] is False and "locked" in locked["error"]
    # lockout persists across store instances (it is on disk)
    again = HostExecutionStore(tmp_path / "state", confirmation_phrase=PHRASE)
    assert "locked" in again.update_settings({"unrestricted_host_mode": True, "confirmation_phrase": PHRASE})["error"]
    clock[0] += 3601
    ok = store.update_settings(
        {"unrestricted_host_mode": True, "confirmation_phrase": PHRASE, "allowed_root": str(tmp_path)}
    )
    assert ok["ok"] is True


def test_backoff_grows(store, monkeypatch) -> None:
    clock = [5000.0]
    monkeypatch.setattr(he, "_now", lambda: clock[0])
    windows = []
    for _ in range(store.MAX_FREE_FAILURES + 3):
        store.update_settings({"unrestricted_host_mode": True, "confirmation_phrase": "nope"})
        state = store._lockout_state()
        windows.append(state["locked_until"] - clock[0] if state["locked_until"] else 0)
        clock[0] = max(clock[0], state["locked_until"]) + 0.01
    nonzero = [w for w in windows if w > 0]
    assert nonzero == sorted(nonzero) and len(set(nonzero)) > 1


def test_redteam_poc_scope_change_while_disarmed_needs_phrase(store, tmp_path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    result = store.update_settings(
        {"allowed_root": str(other), "audit_dir": str(tmp_path / "x"), "allow_source_mutation": True}
    )
    assert result["ok"] is False and "requires the arming phrase" in result["error"]
    assert store.settings()["allowed_root"] != str(other.resolve())
    ok = store.update_settings({"allowed_root": str(other), "confirmation_phrase": PHRASE})
    assert ok["ok"] is True and ok["settings"]["unrestricted_host_mode"] is False


def test_root_is_rejected(store) -> None:
    result = store.update_settings({"allowed_root": "/", "unrestricted_host_mode": True, "confirmation_phrase": PHRASE})
    assert result["ok"] is False and "filesystem root" in result["error"]


def test_saving_unchanged_ui_form_while_disarmed_needs_no_phrase(store) -> None:
    current = store.settings()
    result = store.update_settings(
        {
            "unrestricted_host_mode": False,
            "allowed_root": current["allowed_root"],
            "audit_dir": current["audit_dir"],
            "allow_source_mutation": True,
            "allow_network_commands": True,
            "disclaimer_acknowledged": True,
        }
    )
    assert result["ok"] is True


def test_run_refuses_filesystem_root_even_if_stored(store, tmp_path) -> None:
    store.update_settings(
        {"unrestricted_host_mode": True, "confirmation_phrase": PHRASE, "allowed_root": str(tmp_path)}
    )
    raw = store._raw_settings()
    raw["allowed_root"] = str(Path("/"))
    store._save_settings(raw)
    assert "filesystem root" in store.run_command(["true"])["error"]
