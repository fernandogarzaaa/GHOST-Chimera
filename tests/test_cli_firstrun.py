"""First-run CLI regressions from the round-2 newcomer/poweruser audits."""

from __future__ import annotations

import sys

import pytest

from ghostchimera.control_plane import cli


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("GHOSTCHIMERA_HOME", str(tmp_path / ".ghostchimera"))


# --- newcomer P1-4 (brief: P1-6): `ghost policy` argparse mismatch ---


@pytest.mark.parametrize("argv", [["policy"], ["policy", "list"]])
def test_policy_list_works_from_the_top_level_cli(argv, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    out = capsys.readouterr().out
    assert "strict_factual" in out


def test_policy_set_and_scan_receive_their_own_arguments(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", "policy", "set", "coding"])
    assert cli._main(["policy", "set", "coding"]) == 0
    assert "code_review" in capsys.readouterr().out
    argv = ["policy", "scan", "hello world", "--policy", "strict_factual"]
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    assert '"policy_id": "strict_factual"' in capsys.readouterr().out
