"""Several processes opening one fresh memory DB at once must not fail.

Batch workers (``run_batch`` with workers>1) each open the shared
``memory.sqlite3``. ``PRAGMA journal_mode=WAL`` skips SQLite's busy handler,
so concurrent openers got an immediate "database is locked"
(tests/test_batch_cron_default_kernel.py::test_run_batch_end_to_end_across_worker_processes
failed intermittently in the full suite).
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import sys
import traceback

import pytest

from ghostchimera.memory_layer import store as store_mod
from ghostchimera.memory_layer.store import MemoryStore

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses fork for a tight start barrier")


def _open(path: str, barrier, results) -> None:
    barrier.wait()
    try:
        MemoryStore(path).add_document("test", "hello world")
        results.put("")
    except Exception:
        results.put(traceback.format_exc())


def test_concurrent_processes_open_a_fresh_db_without_locking_errors(tmp_path) -> None:
    ctx = mp.get_context("fork")
    failures: list[str] = []
    for round_index in range(8):
        path = str(tmp_path / f"r{round_index}" / "memory.sqlite3")
        barrier = ctx.Barrier(4)
        results = ctx.Queue()
        procs = [ctx.Process(target=_open, args=(path, barrier, results)) for _ in range(4)]
        for proc in procs:
            proc.start()
        failures.extend(err for err in (results.get(timeout=60) for _ in procs) if err)
        for proc in procs:
            proc.join(timeout=60)
    assert not failures, failures[0]


def test_enable_wal_retries_a_locked_switch_then_succeeds(tmp_path, monkeypatch) -> None:
    conn = sqlite3.connect(tmp_path / "x.sqlite3")
    calls = {"n": 0}

    class _Conn:
        def execute(self, sql):
            if sql == "PRAGMA journal_mode=WAL":
                calls["n"] += 1
                if calls["n"] < 3:
                    raise sqlite3.OperationalError("database is locked")
            return conn.execute(sql)

    monkeypatch.setattr(store_mod.time, "sleep", lambda _s: None)
    store_mod._enable_wal(_Conn())
    assert calls["n"] == 3
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    conn.close()


def test_enable_wal_does_not_swallow_other_errors(tmp_path) -> None:
    class _Conn:
        def execute(self, sql):
            raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        store_mod._enable_wal(_Conn())
