"""F8: TrustRuntimeStore must stay consistent under concurrent writers.

Threads (gateway ThreadingHTTPServer, daemon pool) and separate processes
(CLI + daemon) share one state dir. Before the fix, unlocked
read-modify-write lost approvals/index updates and the hash chain forked,
so verify_run_integrity reported "previous_hash mismatch" on an untampered
run.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
from pathlib import Path

from ghostchimera.trust_runtime import TrustRuntimeStore

THREADS = 8
STEPS_PER_THREAD = 12


def _hammer_steps(store: TrustRuntimeStore, run_id: str, worker: int, barrier: threading.Barrier | None) -> None:
    if barrier is not None:
        barrier.wait()
    for i in range(STEPS_PER_THREAD):
        store.record_step(run_id, step_type="tool_call", status="ok", input_payload={"w": worker, "i": i})


def test_concurrent_threads_keep_hash_chain_and_counts(tmp_path: Path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run_id = store.create_run("concurrency")["run_id"]
    barrier = threading.Barrier(THREADS)
    threads = [
        threading.Thread(target=_hammer_steps, args=(TrustRuntimeStore(tmp_path), run_id, n, barrier))
        for n in range(THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    integrity = store.verify_run_integrity(run_id)
    assert integrity["verified"], integrity
    expected = 1 + THREADS * STEPS_PER_THREAD  # run_created + steps
    assert integrity["step_count"] == expected
    assert store.get_run(run_id)["run"]["step_count"] == expected


def test_concurrent_approvals_are_not_lost(tmp_path: Path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run_id = store.create_run("approvals")["run_id"]
    barrier = threading.Barrier(THREADS)
    ids: list[str] = []
    ids_lock = threading.Lock()

    def worker(n: int) -> None:
        local = TrustRuntimeStore(tmp_path)
        barrier.wait()
        for i in range(5):
            cp = local.create_approval(run_id, step_id=f"s{n}-{i}", summary=f"approve {n}-{i}")
            with ids_lock:
                ids.append(cp["approval_id"])

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    pending = {item["approval_id"] for item in store.pending_approvals()["approvals"]}
    assert set(ids) <= pending
    assert len(pending) == THREADS * 5
    assert store.verify_run_integrity(run_id)["verified"]
    assert not list((tmp_path / "trust_runtime").glob("*.tmp")), "temp files must not leak"


def _process_worker(state_dir: str, run_id: str, worker: int) -> None:
    store = TrustRuntimeStore(state_dir)
    for i in range(STEPS_PER_THREAD):
        store.record_step(run_id, step_type="tool_call", status="ok", input_payload={"p": worker, "i": i})
        store.create_approval(run_id, step_id=f"p{worker}-{i}", summary=f"proc {worker} {i}")


def test_concurrent_processes_keep_hash_chain(tmp_path: Path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run_id = store.create_run("multi-process")["run_id"]
    ctx = multiprocessing.get_context("spawn")
    env_pp = os.environ.get("PYTHONPATH")
    procs = [ctx.Process(target=_process_worker, args=(str(tmp_path), run_id, n)) for n in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0, (p.exitcode, env_pp)

    integrity = store.verify_run_integrity(run_id)
    assert integrity["verified"], integrity
    # run_created + per worker: N steps + N approval checkpoints
    assert integrity["step_count"] == 1 + 3 * STEPS_PER_THREAD * 2
    assert len(store.pending_approvals()["approvals"]) == 3 * STEPS_PER_THREAD
