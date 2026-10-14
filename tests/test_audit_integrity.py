"""F11: legacy audit.record() and the HMAC AuditLog share a file safely, and
verification is fail-closed for corrupt, missing, and truncated logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostchimera.safety_layer import audit as audit_mod


@pytest.fixture
def audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GHOSTCHIMERA_AUDIT_KEY", "unit-test-key")
    path = tmp_path / "audit.json"
    monkeypatch.setattr(audit_mod, "AUDIT_FILE", str(path))
    return path


def test_legacy_and_hmac_writers_share_a_verifiable_chain(audit_file: Path) -> None:
    log = audit_mod.AuditLog(str(audit_file))
    log.record("delegate", {"x": 1})
    audit_mod.record({"action": "shell", "command": ["ls"]}, {"ok": False})
    log.record("delegate", {"x": 2})  # used to raise KeyError: 'chain_hash'
    assert log.verify_integrity() == (True, "Chain intact")  # used to raise KeyError: 'action'
    records = json.loads(audit_file.read_text())
    assert records[1]["task"]["action"] == "shell"  # legacy readers keep working
    assert records[1]["result"] == {"ok": False}


def test_unsigned_legacy_mirror_tamper_is_detected(audit_file: Path) -> None:
    audit_mod.record({"action": "shell"}, {"ok": False})
    records = json.loads(audit_file.read_text())
    records[0]["result"] = {"ok": True}
    audit_file.write_text(json.dumps(records))
    ok, message = audit_mod.AuditLog(str(audit_file)).verify_integrity()
    assert not ok and "result" in message


def test_garbage_file_is_not_intact(audit_file: Path) -> None:
    log = audit_mod.AuditLog(str(audit_file))
    log.record("a", {})
    audit_file.write_text("garbage{")
    ok, message = log.verify_integrity()
    assert ok is False and "unreadable" in message


def test_deleted_file_is_not_intact(audit_file: Path) -> None:
    log = audit_mod.AuditLog(str(audit_file))
    log.record("a", {})
    audit_file.unlink()
    ok, message = log.verify_integrity()
    assert ok is False and "missing" in message


def test_truncation_to_valid_prefix_is_detected(audit_file: Path) -> None:
    log = audit_mod.AuditLog(str(audit_file))
    for i in range(3):
        log.record("step", {"i": i})
    records = json.loads(audit_file.read_text())
    audit_file.write_text(json.dumps(records[:2]))
    ok, message = log.verify_integrity()
    assert ok is False and "truncated" in message


def test_fresh_install_without_records_is_ok(audit_file: Path) -> None:
    assert audit_mod.AuditLog(str(audit_file)).verify_integrity() == (True, "No records to verify")


def test_pre_fix_legacy_file_is_preserved_and_chain_restarts(audit_file: Path) -> None:
    audit_file.write_text(json.dumps([{"task": {"action": "shell"}, "result": {}, "timestamp": "t"}]))
    log = audit_mod.AuditLog(str(audit_file))
    log.record("a", {})
    ok, message = log.verify_integrity()
    assert ok and "reset" in message
    assert list(audit_file.parent.glob("audit.json.corrupt-*")), "legacy evidence must be preserved"
    assert log.get_entries()[0]["action"] == "audit.reset"
