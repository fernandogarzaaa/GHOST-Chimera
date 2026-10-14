"""F14: one ID helper; approval IDs never overwrite a resolved checkpoint."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import ghostchimera
from ghostchimera import ids
from ghostchimera.trust_runtime import TrustRuntimeStore


def test_stable_id_variants_preserve_historical_digests() -> None:
    assert ids.stable_id("a", "b") == hashlib.sha1(b"a|b").hexdigest()[:16]
    assert ids.stable_id(" A ", "B", normalize=True, length=18) == hashlib.sha1(b"a|b").hexdigest()[:18]
    assert ids.stable_id("a", None, "b") == ids.stable_id("a", "b")


def test_evolution_stable_id_accepts_non_str_parts() -> None:
    from ghostchimera.control_plane.evolution import _stable_id

    assert _stable_id("x", 3, 1.5) == ids.stable_id("x", "3", "1.5", normalize=True)  # used to raise AttributeError


def test_unique_id_differs_for_identical_inputs() -> None:
    assert ids.unique_id("run", "step") != ids.unique_id("run", "step")


def test_no_module_reimplements_the_digest() -> None:
    """The seven copies now delegate to ghostchimera.ids."""
    root = Path(ghostchimera.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def _stable_id(" in text and "stable_id(*parts" not in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
    assert "hashlib" not in inspect.getsource(ghostchimera.trust_runtime._stable_id)


def test_rerequested_approval_does_not_overwrite_resolved_checkpoint(tmp_path: Path) -> None:
    store = TrustRuntimeStore(tmp_path)
    run_id = store.create_run("approval collision")["run_id"]
    first = store.create_approval(run_id, step_id="s1", summary="delete prod db")
    assert store.resolve_approval(first["approval_id"], "denied", reviewer="alice")["ok"]

    second = store.create_approval(run_id, step_id="s1", summary="delete prod db")
    assert second["approval_id"] != first["approval_id"]

    approvals = {item["approval_id"]: item for item in store.pending_approvals(include_resolved=True)["approvals"]}
    assert approvals[first["approval_id"]]["decision"] == "denied"
    assert approvals[first["approval_id"]]["reviewer"] == "alice"
    assert approvals[second["approval_id"]]["status"] == "pending"


def test_run_ids_do_not_collide_within_one_clock_tick(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import ghostchimera.trust_runtime as tr

    monkeypatch.setattr(tr, "_now", lambda: 1000.0)
    store = TrustRuntimeStore(tmp_path)
    a = store.create_run("same objective")["run_id"]
    b = store.create_run("same objective")["run_id"]
    assert a != b
