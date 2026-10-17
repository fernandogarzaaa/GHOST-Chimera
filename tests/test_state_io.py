"""Shared state I/O helper: atomic, private, locked, never wipes on corruption."""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from ghostchimera import state_io

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_atomic_write_json_is_private_regardless_of_umask(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        target = tmp_path / "state" / "data.json"
        state_io.atomic_write_json(target, {"a": 1})
    finally:
        os.umask(old)
    assert json.loads(target.read_text()) == {"a": 1}
    assert _mode(target) == 0o600
    assert _mode(target.parent) == 0o700


@posix_only
def test_append_line_creates_private_file(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        target = tmp_path / "log.jsonl"
        state_io.append_line(target, "{}")
        state_io.append_line(target, "{}")
    finally:
        os.umask(old)
    assert target.read_text() == "{}\n{}\n"
    assert _mode(target) == 0o600


def test_unserialisable_payload_leaves_target_and_no_tmp(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    state_io.atomic_write_json(target, {"ok": True})
    with pytest.raises(TypeError):
        state_io.atomic_write_json(target, {"bad": object()})
    assert json.loads(target.read_text()) == {"ok": True}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_read_json_quarantines_corrupt_file(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    target.write_text('{"half": ')
    assert state_io.read_json(target, {}) == {}
    assert not target.exists()
    backups = list(tmp_path.glob("x.json.corrupt-*"))
    assert len(backups) == 1 and backups[0].read_text() == '{"half": '


def test_read_json_wrong_type_is_quarantined(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    target.write_text("[1, 2]")
    assert state_io.read_json(target, {}, expect=dict) == {}
    assert list(tmp_path.glob("x.json.corrupt-*"))


def test_read_json_default_is_copied(tmp_path: Path) -> None:
    default: dict[str, list[int]] = {"items": []}
    loaded = state_io.read_json(tmp_path / "missing.json", default)
    loaded["items"].append(1)
    assert default == {"items": []}


def test_store_update_is_serialised_across_threads(tmp_path: Path) -> None:
    store = state_io.AtomicJsonStore(tmp_path / "counter.json", default=dict)
    barrier = threading.Barrier(8)

    def bump() -> None:
        barrier.wait()
        for _ in range(25):
            with store.update() as data:
                data["n"] = int(data.get("n", 0)) + 1

    threads = [threading.Thread(target=bump) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.load() == {"n": 200}
    assert not list(tmp_path.glob("*.tmp"))


def test_locked_is_reentrant(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    with state_io.locked(target), state_io.locked(target):
        state_io.atomic_write_json(target, {"nested": True})
    assert state_io.read_json(target, {}) == {"nested": True}
