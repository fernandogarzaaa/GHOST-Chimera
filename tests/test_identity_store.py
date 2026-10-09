"""Tests for persistent agent identity: identity_store, agent wiring, CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.control_plane.cli import _run_identity_cli
from ghostchimera.identity_store import AgentIdentity, IdentityStore
from ghostchimera.trust_runtime import TrustRuntimeStore


def _store(tmp_path: Path) -> IdentityStore:
    return IdentityStore(str(tmp_path / "state"))


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert _store(tmp_path).load() is None


def test_load_or_create_persists_across_reinstantiation(tmp_path: Path) -> None:
    first = _store(tmp_path).load_or_create()
    assert first.id.startswith("ghost-")
    # Simulated restart: a brand-new store over the same state dir.
    second = _store(tmp_path).load_or_create()
    assert second.id == first.id
    assert second.to_dict() == first.to_dict()


def test_defaults_are_sane(tmp_path: Path) -> None:
    identity = _store(tmp_path).load_or_create()
    assert identity.name == "ghost-chimera"
    assert identity.created_at != ""
    assert identity.capabilities == []
    assert identity.owner == ""
    assert identity.public_key == ""
    assert identity.previous_ids == []


def test_load_or_create_with_name(tmp_path: Path) -> None:
    identity = _store(tmp_path).load_or_create(name="pilot-one")
    assert identity.name == "pilot-one"
    # A second call does not overwrite the stored name.
    assert _store(tmp_path).load_or_create(name="other").name == "pilot-one"


def test_corrupt_file_quarantined_without_crash(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = store.load_or_create()
    store.identity_path.write_bytes(b"\x00\x01 not json at all")
    recovered = store.load_or_create()
    assert recovered.id != created.id  # fresh identity, no crash
    quarantined = list(store.identity_dir.glob("identity.json.corrupt-*"))
    assert len(quarantined) == 1
    # The live path now holds valid JSON again.
    assert AgentIdentity.from_dict(json.loads(store.identity_path.read_text())) is not None


def test_wrong_typed_json_treated_as_corrupt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.load_or_create()
    store.identity_path.write_text(json.dumps({"id": 12345, "name": "x"}), encoding="utf-8")
    recovered = store.load_or_create()
    assert recovered.id.startswith("ghost-")
    assert len(list(store.identity_dir.glob("identity.json.corrupt-*"))) == 1


def test_rotate_changes_id_keeps_name_records_previous(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.load_or_create(name="pilot-one")
    rotated = store.rotate()
    assert rotated.id != original.id
    assert rotated.name == "pilot-one"
    assert rotated.previous_ids == [original.id]
    assert rotated.rotated_at
    # Rotation persists.
    assert _store(tmp_path).load().id == rotated.id


def test_rename_keeps_stable_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.load_or_create()
    renamed = store.rename("new-name")
    assert renamed.id == original.id
    assert renamed.name == "new-name"
    with pytest.raises(ValueError):
        store.rename("   ")


def test_save_rejects_non_identity(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        _store(tmp_path).save({"id": "ghost-x"})  # type: ignore[arg-type]


def test_agent_loop_uses_persistent_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    agent = AIAgent(model_name="claude-haiku-4-20250514", identity_store=store)
    assert agent.self_model.identity == store.load().id
    # Simulated restart: a new agent over the same state dir reports the same id.
    agent2 = AIAgent(
        model_name="claude-haiku-4-20250514",
        identity_store=_store(tmp_path),
    )
    assert agent2.self_model.identity == agent.self_model.identity
    assert agent2.identity.id == agent.identity.id


def test_agent_status_carries_identity(tmp_path: Path) -> None:
    agent = AIAgent(model_name="claude-haiku-4-20250514", identity_store=_store(tmp_path))
    status = agent.status()
    assert status["identity_id"] == agent.identity.id
    assert status["identity_name"] == agent.identity.name


def _cli(args: argparse.Namespace, capsys: pytest.CaptureFixture[str]) -> dict:
    assert _run_identity_cli(args) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_show_init_rotate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = str(tmp_path / "state")
    shown = _cli(argparse.Namespace(identity_command="show", state_dir=state, name=""), capsys)
    assert shown["ok"] is True and shown["exists"] is False and shown["identity"] is None

    inited = _cli(argparse.Namespace(identity_command="init", state_dir=state, name="cli-agent"), capsys)
    assert inited["ok"] is True and inited["created"] is True
    assert inited["identity"]["name"] == "cli-agent"
    identity_id = inited["identity"]["id"]

    reshown = _cli(argparse.Namespace(identity_command="show", state_dir=state, name=""), capsys)
    assert reshown["exists"] is True and reshown["identity"]["id"] == identity_id

    rotated = _cli(argparse.Namespace(identity_command="rotate", state_dir=state, name=""), capsys)
    assert rotated["ok"] is True
    assert rotated["identity"]["id"] != identity_id
    assert rotated["identity"]["name"] == "cli-agent"
    assert rotated["identity"]["previous_ids"] == [identity_id]


def test_cli_unknown_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_identity_cli(argparse.Namespace(
        identity_command="bogus", state_dir=str(tmp_path / "state"), name=""))
    assert rc == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_create_run_records_identity_id(tmp_path: Path) -> None:
    store = TrustRuntimeStore(str(tmp_path / "state"))
    payload = store.create_run(objective="smoke", identity_id="ghost-abc123")
    assert payload["identity_id"] == "ghost-abc123"
    # Backward compatible: omitted identity_id defaults to empty.
    assert store.create_run(objective="smoke2")["identity_id"] == ""


@pytest.mark.parametrize("payload", [
    {"id": ""},
    {"id": 12345},
    {"name": ""},
    {"name": 5},
    {"capabilities": "not-a-list"},
    {"capabilities": [1, 2]},
    {"owner": 5},
    {"public_key": 5},
    {"rotated_at": 5},
    {"previous_ids": "not-a-list"},
    {"previous_ids": [1]},
    {"created_at": 5},
    "not-a-dict",
    None,
    [1, 2],
])
def test_from_dict_rejects_invalid_payloads(payload) -> None:
    with pytest.raises(ValueError):
        AgentIdentity.from_dict(payload)


def test_save_revalidates_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _store(tmp_path).save(AgentIdentity(id=""))


def test_save_writes_sorted_indented_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    identity = store.load_or_create(name="exact")
    expected = json.dumps(identity.to_dict(), indent=2, sort_keys=True) + "\n"
    assert store.identity_path.read_text(encoding="utf-8") == expected


def test_rename_rejects_non_string(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _store(tmp_path).rename(123)  # type: ignore[arg-type]


def test_quarantine_oserror_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)
    store.load_or_create()
    store.identity_path.write_bytes(b"corrupt")

    def _boom(src, dst):
        raise OSError("disk read-only")

    monkeypatch.setattr("ghostchimera.identity_store.os.replace", _boom)
    with caplog.at_level("WARNING", logger="ghostchimera.identity_store"):
        assert store.load() is None  # quarantine rename failed, but no crash
    # Fallback path removed the unreadable file so a fresh identity can be written.
    assert not store.identity_path.exists()
    # The quarantined-to location is reported (falls back to the identity path).
    assert f"quarantined to {store.identity_path}" in caplog.text


def test_quarantine_logs_target_path(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = _store(tmp_path)
    store.load_or_create()
    store.identity_path.write_bytes(b"corrupt")
    with caplog.at_level("WARNING", logger="identity_store"):
        assert store.load() is None
    assert "corrupt-" in caplog.text
