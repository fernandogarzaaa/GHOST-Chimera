from __future__ import annotations

from ghostchimera.tool_layer.file_system import FileLeaseManager


def test_file_lease_acquire_and_release() -> None:
    mgr = FileLeaseManager()
    assert mgr.acquire("/tmp/a.txt", "agent-a") is True
    assert mgr.acquire("/tmp/a.txt", "agent-b") is False
    assert mgr.held_by("/tmp/a.txt") == "agent-a"
    assert mgr.release("/tmp/a.txt", "agent-b") is False
    assert mgr.release("/tmp/a.txt", "agent-a") is True
    assert mgr.held_by("/tmp/a.txt") is None


def test_conflict_classification_policy_and_text_conflict() -> None:
    mgr = FileLeaseManager()
    policy = mgr.classify_conflict(
        path="file.py",
        baseline_hash="a",
        current_hash="b",
        proposed_hash="c",
        policy_allowed=False,
    )
    assert policy.conflict_class == "policy-conflict"

    text = mgr.classify_conflict(
        path="file.py",
        baseline_hash="a",
        current_hash="b",
        proposed_hash="c",
    )
    assert text.conflict_class == "text-conflict"


def test_conflict_classification_non_overlap_cases() -> None:
    mgr = FileLeaseManager()
    same = mgr.classify_conflict(
        path="file.py",
        baseline_hash="a",
        current_hash="b",
        proposed_hash="b",
    )
    assert same.conflict_class == "non-overlap"

    unchanged_since_baseline = mgr.classify_conflict(
        path="file.py",
        baseline_hash="a",
        current_hash="a",
        proposed_hash="z",
    )
    assert unchanged_since_baseline.conflict_class == "non-overlap"
