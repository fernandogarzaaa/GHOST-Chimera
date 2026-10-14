"""/api/console/memory/ingest-file must be confined and redacted (redteam P0-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.control_plane.console import register_console_routes
from ghostchimera.memory_layer.store import MemoryStore


@pytest.fixture
def console(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv("GHOSTCHIMERA_INGEST_ROOTS", raising=False)
    env = GhostChimeraConfig.from_env()
    config = GhostChimeraConfig(
        state_dir=state,
        memory_db=state / "memory.sqlite3",
        audit_file=state / "audit.json",
        policy=env.policy,
        local_model_path="",
        local_model_profile="tiny",
        local_model_gpu_layers=0,
        autonomy_level="supervised",
    )
    server = GatewayServer(config=config)
    register_console_routes(server, state_dir=state)

    def call(path: str, payload: dict) -> dict:
        route = server.routes.find("POST", path)
        assert route is not None
        return route.handler({"method": "POST", "path": path, "headers": {}, "body": json.dumps(payload), "query": {}})

    return call, state, work, outside, config


def test_redteam_poc_console_secrets_cannot_be_ingested(console) -> None:
    call, state, _work, _outside, config = console
    secrets_file = state / "console_secrets.json"
    secrets_file.write_text(
        json.dumps({"token": "tok-abcdef1234567890", "arming_phrase": "I ACCEPT HOST EXECUTION RISK ab12-cd34"})
    )
    result = call("/api/console/memory/ingest-file", {"path": str(secrets_file)})
    assert result["ok"] is False
    assert "state directory" in result["error"]
    hits = MemoryStore(config.memory_db).search("arming_phrase token", limit=5)
    assert not any("ACCEPT HOST" in json.dumps(hit) for hit in hits)


def test_paths_outside_allowed_roots_are_refused(console) -> None:
    call, _state, _work, outside, _config = console
    target = outside / "notes.md"
    target.write_text("private notes")
    result = call("/api/console/memory/ingest-file", {"path": str(target)})
    assert result["ok"] is False and "outside the allowed" in result["error"]
    email = call("/api/console/memory/ingest-email", {"path": str(outside / "x.eml")})
    assert email["ok"] is False


def test_symlink_escape_and_dotfiles_are_refused(console) -> None:
    call, state, work, outside, _config = console
    (outside / "secret.txt").write_text("nope")
    link = work / "link.txt"
    link.symlink_to(outside / "secret.txt")
    assert call("/api/console/memory/ingest-file", {"path": str(link)})["ok"] is False
    (work / ".env.json").write_text('{"API_KEY": "x"}')
    assert call("/api/console/memory/ingest-file", {"path": str(work / ".env.json")})["ok"] is False
    (work / "ssh").mkdir()
    (work / "ssh" / "id_rsa").write_text("key")
    assert call("/api/console/memory/ingest-file", {"path": str(work / "ssh" / "id_rsa")})["ok"] is False


def test_allowed_file_is_ingested_with_secrets_redacted(console) -> None:
    call, _state, work, _outside, config = console
    doc = work / "runbook.md"
    doc.write_text(
        "Deploy notes. Use key sk-proj-abcdefghijklmnop1234 and password=hunter2hunter2. "
        "Arm with I ACCEPT HOST EXECUTION RISK ab12-cd34 if needed."
    )
    result = call("/api/console/memory/ingest-file", {"path": str(doc)})
    assert result["ok"] is True and result["ingested"] == 1
    hits = MemoryStore(config.memory_db).search("Deploy notes", limit=5)
    blob = json.dumps(hits)
    assert "Deploy notes" in blob
    assert "sk-proj-abcdefghijklmnop1234" not in blob
    assert "hunter2hunter2" not in blob
    assert "ab12-cd34" not in blob


def test_directory_ingest_skips_hidden_and_state(console, monkeypatch) -> None:
    call, _state, work, _outside, config = console
    (work / "a.txt").write_text("alpha document visible")
    (work / ".git").mkdir()
    (work / ".git" / "config.txt").write_text("hidden git config")
    nested_state = work / "nested-state"
    nested_state.mkdir()
    (nested_state / "creds.txt").write_text("state file content")
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(nested_state))
    result = call("/api/console/memory/ingest-file", {"path": str(work)})
    assert result["ok"] is True
    blob = json.dumps(MemoryStore(config.memory_db).search("document config content", limit=10))
    assert "alpha document visible" in blob
    assert "hidden git config" not in blob
    assert "state file content" not in blob


def test_root_cannot_be_an_ingest_root(console, monkeypatch) -> None:
    call, _state, _work, outside, _config = console
    monkeypatch.setenv("GHOSTCHIMERA_INGEST_ROOTS", str(Path("/")))
    (outside / "n.txt").write_text("x")
    assert call("/api/console/memory/ingest-file", {"path": str(outside / "n.txt")})["ok"] is False
