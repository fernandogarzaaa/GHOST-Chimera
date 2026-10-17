"""Secrets typed into run objectives are not stored or exported verbatim (redteam P1-7)."""

from __future__ import annotations

import json

from ghostchimera.control_plane.run_jobs import ConsoleRunManager
from ghostchimera.trust_runtime import TrustRuntimeStore

SECRET = "ghs_abcdefghijklmnopqrstuvwxyz0123"
SLACK = "xoxb-1234567890-abcdefghijkl"


def test_trust_runtime_storage_and_trace_export_redact_objective(tmp_path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run = store.create_run(
        f"deploy with token {SECRET} and {SLACK} to postgres://admin:S3cretPass99@db/x using AKIAABCDEFGHIJKLMNOP",
        source="console",
    )
    run_id = run["run_id"]
    on_disk = "".join(p.read_text() for p in (tmp_path / "trust_runtime").rglob("*") if p.is_file())
    assert SECRET not in on_disk and "abcdefghijkl" not in on_disk
    assert "S3cretPass99" not in on_disk and "AKIAABCDEFGHIJKLMNOP" not in on_disk
    assert "deploy with token" in on_disk
    exported = json.dumps(store.export_trace(run_id))
    assert SECRET not in exported and SLACK not in exported and "S3cretPass99" not in exported
    listed = json.dumps(store.list_runs())
    assert SECRET not in listed


def test_console_runs_listing_redacts_label_result_and_error() -> None:
    manager = ConsoleRunManager()
    record = manager.submit(f"use {SECRET}", lambda: {"echo": f"got {SECRET}"})
    for _ in range(200):
        if manager.get(record.run_id).status in ("completed", "failed"):
            break
        import time

        time.sleep(0.01)
    blob = json.dumps([r for r in manager.list()])
    assert SECRET not in blob
    assert "use [redacted]" in blob
