"""F13 + F6: every default state path follows GHOSTCHIMERA_STATE_DIR, nothing
lands in $HOME or the CWD, and the stealth memory retriever's fallback works."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / "state"
    home = tmp_path / "home"
    home.mkdir()
    for var in (
        "GHOSTCHIMERA_MEMORY_DB",
        "GHOSTCHIMERA_AUDIT_FILE",
        "GHOSTCHIMERA_MEMORY_FILE",
        "GHOSTCHIMERA_SECURITY_EVENTS_FILE",
        "GHOSTCHIMERA_CHECKPOINT_DIR",
        "GHOSTCHIMERA_PLUGINS_DIR",
        "GHOSTCHIMERA_SKILLS_DIR",
        "GHOSTCHIMERA_TEMPORAL_GRAPH_DB",
    ):
        monkeypatch.delenv(var, raising=False)
    # Other tests assign these module-level overrides; reset to "lazy".
    import ghostchimera.agent_core.memory as agent_memory
    import ghostchimera.chimera_pilot.checkpoint as checkpoint
    import ghostchimera.chimera_pilot.plugin_manifest as plugin_manifest
    import ghostchimera.safety_layer.audit as audit
    import ghostchimera.safety_layer.security_monitor as security_monitor
    import ghostchimera.skill_layer.registry as registry

    monkeypatch.setattr(audit, "AUDIT_FILE", None)
    monkeypatch.setattr(agent_memory, "DEFAULT_FILE", None)
    monkeypatch.setattr(checkpoint, "CHECKPOINT_BASE", None)
    monkeypatch.setattr(security_monitor, "_DEFAULT_EVENTS_FILE", None)
    monkeypatch.setattr(registry, "_DEFAULT_SKILLS_DIR", None)
    monkeypatch.setattr(plugin_manifest, "_DEFAULT_PLUGINS_DIR", None)
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GHOSTCHIMERA_AUDIT_KEY", "k")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return state_dir


def test_resolver_is_lazy_and_honours_env(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera import paths

    assert paths.state_dir() == state
    assert paths.memory_db_path() == state / "memory.sqlite3"
    other = state.parent / "other"
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(other))
    assert paths.audit_file_path() == other / "audit.json"  # evaluated per call, not at import


def test_module_defaults_follow_state_dir(state: Path) -> None:
    from ghostchimera.agent_core.memory import MemoryManager
    from ghostchimera.chimera_pilot.checkpoint import CheckpointManager
    from ghostchimera.chimera_pilot.plugin_manifest import PluginLoader
    from ghostchimera.config import GhostChimeraConfig
    from ghostchimera.safety_layer.audit import AuditLog
    from ghostchimera.safety_layer.security_monitor import SecurityMonitor
    from ghostchimera.skill_layer.registry import SkillRegistry

    assert Path(AuditLog().audit_file) == state / "audit.json"
    assert Path(MemoryManager().file_path) == state / "memory.json"
    assert Path(SecurityMonitor()._events_file) == state / "security_events.json"
    assert CheckpointManager().checkpoint_dir == state / "checkpoints"
    assert PluginLoader().plugins_dir == state / "plugins"
    assert SkillRegistry().skills_dir == state / "skills"
    cfg = GhostChimeraConfig.from_env()
    assert cfg.state_dir == state and cfg.memory_db == state / "memory.sqlite3"
    assert not any((Path(os.environ["HOME"])).iterdir()), "nothing may be written to $HOME"


def test_personal_memory_db_never_defaults_to_cwd(state: Path) -> None:
    from ghostchimera.model_layer.minimind_beta_orchestrator import load_beta_config
    from ghostchimera.paths import personal_memory_db

    assert personal_memory_db() == state / "memory.sqlite3"
    cfg_file = state.parent / "beta.json"
    cfg_file.write_text("{}")
    assert load_beta_config(cfg_file).memory_db == str(state / "memory.sqlite3")
    assert not list(Path.cwd().iterdir())


def test_personal_memory_db_keeps_existing_legacy_cwd_file(state: Path) -> None:
    from ghostchimera.paths import personal_memory_db

    Path(".ghostchimera-memory.sqlite3").write_bytes(b"")
    assert personal_memory_db() == Path(".ghostchimera-memory.sqlite3")


def test_stealth_memory_retriever_fallback_opens_state_db(state: Path) -> None:
    """F6: MemoryStore() was called without db_path -> TypeError swallowed -> []."""
    from ghostchimera.memory_layer.store import MemoryStore
    from ghostchimera.stealth.context import GhostMemoryRetriever
    from ghostchimera.stealth.events import new_event

    retriever = GhostMemoryRetriever()
    event = new_event("note", source="test", actor="user", payload={"topic": "zebra"})
    assert retriever.retrieve(event, {}) == []
    assert not (state / "memory.sqlite3").exists(), "retrieval must not create the DB"

    store = MemoryStore(state / "memory.sqlite3")
    store.add_document("notes", "zebra crossing notes for the user")
    items = GhostMemoryRetriever().retrieve(event, {})
    assert items, "fallback store must actually be used"
