"""Tests for the strict EVE project scan."""

from __future__ import annotations

from ghostchimera.stealth import GhostPolicy, scan_project
from ghostchimera.stealth.project_scan import main
from ghostchimera.stealth.stealth_policy import AutonomyLevel


def test_strict_policy_is_observe_only_with_high_bar() -> None:
    policy = GhostPolicy.strict_observe()

    assert policy.autonomy == AutonomyLevel.OBSERVE
    assert policy.minimum_confidence == 0.95
    assert policy.enabled is True


def test_clean_directory_passes(tmp_path) -> None:
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")

    report = scan_project(tmp_path, strict=True)

    assert report.ok is True
    assert report.verdict == "pass"
    assert report.files_scanned == 1
    assert report.findings == []
    assert report.decisions.get("none", 0) == 1


def test_secret_outside_tests_fails_strict_scan(tmp_path) -> None:
    (tmp_path / "config.py").write_text('api_key = "ghp_X7kabcQ2mZ789B4vC8nD3fE6hJ1kL5pO0"\n', encoding="utf-8")

    report = scan_project(tmp_path, strict=True)

    assert report.ok is False
    assert report.verdict == "fail"
    assert len(report.findings) == 1
    assert report.findings[0].severity == "high"
    assert "ghp_" not in report.findings[0].detail
    assert report.decisions.get("store", 0) == 1


def test_synthetic_token_is_downgraded_to_medium(tmp_path) -> None:
    (tmp_path / "config.py").write_text('api_key = "ghp_abcdefghijklmnopqrstuvwxyz012345"\n', encoding="utf-8")

    report = scan_project(tmp_path, strict=True)

    assert report.ok is True
    assert len(report.findings) == 1
    assert report.findings[0].severity == "medium"
    assert report.findings[0].reason.startswith("synthetic-secret-like-pattern:")


def test_empty_env_var_name_is_not_a_secret(tmp_path) -> None:
    (tmp_path / "check.py").write_text('REQUIRED = (\n    "GHOSTCHIMERA_SESSION_SECRET=",\n)\n', encoding="utf-8")

    report = scan_project(tmp_path, strict=True)

    assert report.ok is True
    assert report.findings == []


def test_secret_in_test_fixture_is_medium_severity(tmp_path) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "test_example.py").write_text('token = "ghp_abcdefghijklmnopqrstuvwxyz012345"\n', encoding="utf-8")

    report = scan_project(tmp_path, strict=True)

    assert report.ok is True
    assert len(report.findings) == 1
    assert report.findings[0].severity == "medium"


def test_oversized_file_is_flagged(tmp_path) -> None:
    (tmp_path / "data.bin").write_bytes(b"x" * (1024 * 1024 + 1))

    report = scan_project(tmp_path, strict=True)

    assert report.ok is True
    assert len(report.findings) == 1
    assert report.findings[0].reason == "oversized-file"


def test_cli_returns_zero_on_pass_and_one_on_fail(tmp_path, capsys) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "ok.py").write_text("x = 1\n", encoding="utf-8")
    assert main(["--root", str(clean)]) == 0
    capsys.readouterr()

    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "bad.py").write_text('password = "hunter2-hunter2"\n', encoding="utf-8")
    assert main(["--root", str(dirty)]) == 1
