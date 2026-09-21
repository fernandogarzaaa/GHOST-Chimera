"""P0 audit fixes: chain genesis, key provisioning, MoA units, approval digests,
capability identity. No network."""

from __future__ import annotations

import json
import os
import stat

import pytest


# -- AuditLog ---------------------------------------------------------------------------
def _audit_log(tmp_path, monkeypatch, *, key=None):
    from ghostchimera.safety_layer import audit as audit_mod

    if key is None:
        monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    else:
        monkeypatch.setenv("GHOSTCHIMERA_AUDIT_KEY", key)
    return audit_mod.AuditLog(str(tmp_path / "audit.json"))


def test_chain_verifies_against_genesis(tmp_path, monkeypatch) -> None:
    log = _audit_log(tmp_path, monkeypatch, key="test-key-123")
    log.record("a", {"x": 1})
    log.record("b", {"y": 2})
    assert log.verify_integrity() == (True, "Chain intact")


def test_first_entry_tamper_detected(tmp_path, monkeypatch) -> None:
    """Before the fix, entry 0 was checked against itself and always passed."""
    log = _audit_log(tmp_path, monkeypatch, key="test-key-123")
    log.record("a", {"x": 1})
    log.record("b", {"y": 2})
    entries = log.get_entries()
    entries[0]["action"] = "forged"
    with open(log.audit_file, "w", encoding="utf-8") as handle:
        json.dump(entries, handle)
    ok, message = log.verify_integrity()
    assert ok is False and "entry 0" in message


def test_mid_chain_tamper_detected(tmp_path, monkeypatch) -> None:
    log = _audit_log(tmp_path, monkeypatch, key="test-key-123")
    for i in range(3):
        log.record(f"step-{i}", {"i": i})
    entries = log.get_entries()
    entries[1]["details"] = {"i": 999}
    with open(log.audit_file, "w", encoding="utf-8") as handle:
        json.dump(entries, handle)
    ok, message = log.verify_integrity()
    assert ok is False and "entry 1" in message


def test_no_test_key_fallback_generates_install_key(tmp_path, monkeypatch) -> None:
    from ghostchimera.safety_layer import audit as audit_mod

    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    log = audit_mod.AuditLog(str(tmp_path / "audit.json"))
    assert log.key != b"ghostchimera-test-key"
    assert len(log.key) >= 16
    key_file = str(tmp_path / "audit.json.key")
    assert os.path.exists(key_file)
    log.record("a", {})
    assert log.verify_integrity()[0] is True
    # Second instance reuses the persisted key: chain stays verifiable.
    log2 = audit_mod.AuditLog(str(tmp_path / "audit.json"))
    assert log2.key == log.key
    assert log2.verify_integrity()[0] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_install_key_file_owner_only(tmp_path, monkeypatch) -> None:
    from ghostchimera.safety_layer import audit as audit_mod

    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    audit_mod.AuditLog(str(tmp_path / "audit.json"))
    mode = stat.S_IMODE(os.stat(str(tmp_path / "audit.json.key")).st_mode)
    assert mode == 0o600


def test_verify_entry_requires_key(monkeypatch) -> None:
    from ghostchimera.safety_layer.audit import AuditLog

    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    with pytest.raises(ValueError, match="key required"):
        AuditLog.verify_entry({"action": "a", "details": {}, "chain_hash": "x"}, None)


def test_verify_entry_with_explicit_key(tmp_path, monkeypatch) -> None:
    from ghostchimera.safety_layer.audit import AuditLog

    monkeypatch.setenv("GHOSTCHIMERA_AUDIT_KEY", "k1")
    log = AuditLog(str(tmp_path / "audit.json"))
    entry = log.record("a", {"x": 1})
    assert AuditLog.verify_entry(entry, None, key=b"k1") is True
    assert AuditLog.verify_entry(entry, None, key=b"wrong") is False


def test_verify_entry_strips_env_whitespace(tmp_path, monkeypatch) -> None:
    """Thread 6: padded env keys verify against stripped keys."""
    from ghostchimera.safety_layer.audit import AuditLog

    monkeypatch.setenv("GHOSTCHIMERA_AUDIT_KEY", "  k1  ")
    log = AuditLog(str(tmp_path / "audit.json"))
    entry = log.record("a", {"x": 1})
    assert AuditLog.verify_entry(entry, None, key=b"k1") is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_lax_key_file_permissions_repaired(tmp_path, monkeypatch) -> None:
    """Thread 4: group-readable key files are locked down, not trusted as-is."""
    from ghostchimera.safety_layer import audit as audit_mod

    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    key_path = str(tmp_path / "audit.json.key")
    with open(key_path, "wb") as handle:
        handle.write(b"x" * 32)
    os.chmod(key_path, 0o640)
    log = audit_mod.AuditLog(str(tmp_path / "audit.json"))
    assert log.key == b"x" * 32
    assert stat.S_IMODE(os.stat(key_path).st_mode) == 0o600


def test_concurrent_key_creation_keeps_one_key(tmp_path, monkeypatch) -> None:
    """Thread 5: exclusive creation — losers reread, nobody overwrites."""
    from ghostchimera.safety_layer import audit as audit_mod

    monkeypatch.delenv("GHOSTCHIMERA_AUDIT_KEY", raising=False)
    first = audit_mod._resolve_key(str(tmp_path / "audit.json"))
    second = audit_mod._resolve_key(str(tmp_path / "audit.json"))
    assert first == second and len(first) == 32


# -- MoA revote units ----------------------------------------------------------------------
def _moa_result(pct, agreeing=True):
    from ghostchimera.chimera_pilot.mixture_of_agents import MoAResult

    votes = [
        {"agent_output": "same answer here", "success": True, "agrees_with_consensus": agreeing},
        {"agent_output": "same answer here", "success": True, "agrees_with_consensus": agreeing},
        {"agent_output": "totally different view", "success": True, "agrees_with_consensus": False},
    ]
    return MoAResult(
        query="q",
        votes=votes,
        consensus_answer="same answer here",
        consensus_pct=pct,
        num_agents=3,
        num_agreeing=2 if agreeing else 0,
        contradictions=[],
        duration_seconds=0.0,
        avg_tokens=0,
        avg_duration=0.0,
    )


def test_revote_runs_below_threshold(monkeypatch) -> None:
    from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents

    moa = MixtureOfAgents()
    calls: list = []
    monkeypatch.setattr(moa, "vote", lambda query, **kw: _moa_result(33.3))
    monkeypatch.setattr(moa, "_detect_contradictions", lambda results: [])
    monkeypatch.setattr(
        moa,
        "_revote_agent",
        lambda old_vote, prompt: (
            calls.append(prompt) or {"agent_output": "same answer here", "success": True, "agrees_with_consensus": True}
        ),
    )
    out = moa.vote_with_revote("q", max_rounds=2, confidence_threshold=0.65)
    assert len(calls) >= 1  # 33.3% < 65%: revision must run (old code exited immediately)
    assert out.consensus_pct >= 0


def test_revote_skipped_above_threshold(monkeypatch) -> None:
    from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents

    moa = MixtureOfAgents()
    calls: list = []
    monkeypatch.setattr(moa, "vote", lambda query, **kw: _moa_result(100.0))
    monkeypatch.setattr(moa, "_revote_agent", lambda old_vote, prompt: calls.append(prompt))
    moa.vote_with_revote("q", max_rounds=2, confidence_threshold=0.65)
    assert calls == []


def test_negation_contradiction_detected() -> None:
    """Thread 3: 'sky is blue' vs 'sky is not blue' must contradict."""
    from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents

    moa = MixtureOfAgents()
    found = moa._detect_contradictions_for_text(["sky is blue", "ocean is not blue"])
    assert found == []
    found = moa._detect_contradictions_for_text(["sky is blue", "sky is not blue"])
    assert len(found) == 1 and found[0]["type"] == "direct_negation"


def test_same_polarity_not_flagged() -> None:
    from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents

    moa = MixtureOfAgents()
    assert moa._detect_contradictions_for_text(["sky is blue", "sky is blue"]) == []


# -- ComputerApproval digest ------------------------------------------------------------------
def test_approval_digest_binding() -> None:
    from ghostchimera.stealth.computer import ComputerAction, ComputerApproval

    action = ComputerAction(operation="browser.click", target="Approve invoice")
    approval = ComputerApproval(approved_by="op", action_id=action.action_id, action_digest=action.action_digest())
    assert approval.covers(action) is True
    mutated = ComputerAction(operation="browser.click", target="Delete account", action_id=action.action_id)
    assert approval.covers(mutated) is False  # same id, different action: denied
    param_mutated = ComputerAction(
        operation="browser.click",
        target="Approve invoice",
        parameters={"amount": 999999},
        action_id=action.action_id,
    )
    assert approval.covers(param_mutated) is False


def test_approval_legacy_id_only_still_works() -> None:
    from ghostchimera.stealth.computer import ComputerAction, ComputerApproval

    action = ComputerAction(operation="browser.read", target="https://x/")
    approval = ComputerApproval(approved_by="op", action_id=action.action_id)
    assert approval.covers(action) is True
    assert approval.covers(ComputerAction(operation="browser.read", target="https://x/", action_id="other")) is False


def test_approval_expiry_still_enforced() -> None:
    import time

    from ghostchimera.stealth.computer import ComputerAction, ComputerApproval

    action = ComputerAction(operation="browser.read", target="https://x/")
    approval = ComputerApproval(
        approved_by="op",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        expires_at=time.time() - 1,
    )
    assert approval.covers(action) is False


# -- Capability identity ---------------------------------------------------------------------------
def test_version_change_forks_identity(tmp_path) -> None:
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="mcp", name="srv", version="1.0.0")
    second = store.create_record(capability_kind="mcp", name="srv", version="1.1.0")
    assert first["ok"] is True and second["ok"] is True
    assert first["record"]["id"] != second["record"]["id"]
    assert second["record"]["status"] == "discovered"


def test_permission_change_forks_identity(tmp_path) -> None:
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="skill", name="s", requested_permissions=["read"])
    second = store.create_record(capability_kind="skill", name="s", requested_permissions=["read", "write"])
    assert first["record"]["id"] != second["record"]["id"]


def test_reregister_unchanged_updates_in_place(tmp_path) -> None:
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="mcp", name="srv", version="2.0.0", requested_permissions=["a"])
    updated = store.register_or_update(
        capability_kind="mcp", name="srv", version="2.0.0", requested_permissions=["a"], risk_level="low"
    )
    assert updated["record"]["id"] == first["record"]["id"]
    assert updated.get("reused_identity") is True


def test_register_mutated_forks_fresh_record(tmp_path) -> None:
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="mcp", name="srv", version="2.0.0")
    assert first["ok"] is True
    mutated = store.register_or_update(capability_kind="mcp", name="srv", version="3.0.0")
    assert mutated["ok"] is True
    assert mutated["record"]["id"] != first["record"]["id"]
    assert mutated["record"]["status"] == "discovered"


def test_identity_includes_artifact_digest(tmp_path) -> None:
    from ghostchimera.capability_admission import capability_identity

    assert capability_identity("mcp", "local", "s", artifact_digest="aaa") != capability_identity(
        "mcp", "local", "s", artifact_digest="bbb"
    )
    assert capability_identity("mcp", "local", "s", version="1") == capability_identity(
        "mcp", "local", "s", metadata={"version": "1"}
    )


def test_metadata_version_beats_sibling_version(tmp_path) -> None:
    """Thread 1: current-call metadata wins over the sibling's version."""
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="mcp", name="srv", version="v1")
    assert first["ok"] is True
    upgraded = store.register_or_update(capability_kind="mcp", name="srv", metadata={"version": "v2"})
    assert upgraded["ok"] is True
    assert upgraded["record"]["id"] != first["record"]["id"]
    assert upgraded["record"]["version"] == "v2"


def test_explicit_empty_permissions_not_backfilled(tmp_path) -> None:
    """Thread 2: requested_permissions=[] is a real empty set, not 'unspecified'."""
    from ghostchimera.capability_admission import CapabilityAdmissionStore

    store = CapabilityAdmissionStore(tmp_path)
    first = store.create_record(capability_kind="skill", name="s", requested_permissions=["read", "write"])
    emptied = store.register_or_update(capability_kind="skill", name="s", requested_permissions=[])
    assert emptied["record"]["id"] != first["record"]["id"]
    assert emptied["record"]["requested_permissions"] == []
    assert emptied["record"]["status"] == "discovered"
