"""F9: JSON state stores must be locked, atomic, and never wipe on corruption.

Before the fix ConversationStore (and eight stores with the same pattern)
did unlocked load->modify->save with a truncate-then-write, and any parse
error returned defaults so the next save erased every session.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.toolsets import ToolsetManager
from ghostchimera.connectors.automations import AutomationsEngine
from ghostchimera.control_plane.conversation import ConversationStore
from ghostchimera.control_plane.flow_dictation import PersonalDictionary
from ghostchimera.control_plane.live_presence import LivePresenceStore
from ghostchimera.control_plane.standing_orders import StandingOrderStore
from ghostchimera.integrations.remote_control import RemoteControlStore
from ghostchimera.integrations.triage import load_vip_senders, save_vip_senders
from ghostchimera.stealth.user_model import UserModel


def _corrupt(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"sessions": {"keep-me": ', encoding="utf-8")


def _backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(path.name + ".corrupt-*"))


def test_conversation_concurrent_turns_are_not_lost(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    sid = store.create_session(session_id="s1")["session_id"]
    workers, per_worker = 6, 15
    barrier = threading.Barrier(workers)

    def worker(n: int) -> None:
        local = ConversationStore(tmp_path)
        barrier.wait()
        for i in range(per_worker):
            local.append_turn(sid, role="user", content=f"turn {n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    turns = store.get_session(sid)["turns"]
    assert len(turns) == workers * per_worker
    assert not list(tmp_path.glob("*.tmp"))


def test_conversation_corrupt_file_is_backed_up_not_wiped(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    _corrupt(store.path)
    original = store.path.read_text()
    store.create_session(session_id="fresh")
    backups = _backups(store.path)
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert store.get_session("fresh")["session_id"] == "fresh"


@pytest.mark.parametrize(
    "factory, path_of, mutate",
    [
        (
            lambda d: LivePresenceStore(d),
            lambda s, d: s.path,
            lambda s: s.create_session(title="t"),
        ),
        (
            lambda d: StandingOrderStore(d),
            lambda s, d: s.path,
            lambda s: s.create_order({"title": "t", "objective": "o"}),
        ),
        (
            lambda d: RemoteControlStore(d),
            lambda s, d: s.path,
            lambda s: s.update_policy({"enabled": True}),
        ),
        (
            lambda d: PersonalDictionary(d),
            lambda s, d: d / "personal_dictionary.json",
            lambda s: s.learn("ghost kimera", "Ghost Chimera"),
        ),
    ],
)
def test_corrupt_store_is_quarantined(tmp_path: Path, factory, path_of, mutate) -> None:  # type: ignore[no-untyped-def]
    store = factory(tmp_path)
    path = path_of(store, tmp_path)
    _corrupt(path)
    mutate(store)
    assert len(_backups(path)) == 1, "corrupt file must be preserved"
    json.loads(path.read_text())  # rewritten atomically and valid


def test_automations_corrupt_file_is_quarantined(tmp_path: Path) -> None:
    path = tmp_path / "automations.json"
    _corrupt(path)
    AutomationsEngine(tmp_path)
    assert len(_backups(path)) == 1


def test_user_model_and_triage_and_toolsets_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "user_model.json"
    _corrupt(model_path)
    UserModel.load(model_path).save(model_path)
    assert len(_backups(model_path)) == 1

    vip = tmp_path / "triage.json"
    _corrupt(vip)
    assert load_vip_senders(tmp_path) == []
    assert save_vip_senders(tmp_path, ["a@example.com"]) == ["a@example.com"]
    assert len(_backups(vip)) == 1

    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path))
    toolsets = tmp_path / "active_toolsets.json"
    _corrupt(toolsets)
    ToolsetManager()
    assert len(_backups(toolsets)) == 1


def test_remote_control_approval_executes_once(tmp_path: Path) -> None:
    store = RemoteControlStore(tmp_path)
    data = store._load()
    data["approvals"]["a1"] = {"id": "a1", "status": "pending", "objective": "do it"}
    store._save(data)
    calls: list[str] = []
    gate = threading.Event()

    def runner(objective: str) -> dict[str, object]:
        calls.append(objective)
        gate.wait(2)
        return {"ok": True}

    results: list[dict[str, object]] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(store.resolve_approval("a1", approved=True, objective_runner=runner))
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert calls == ["do it"]
    assert store._load()["approvals"]["a1"]["status"] == "executed"
