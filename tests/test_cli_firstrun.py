"""First-run CLI regressions from the round-2 newcomer/poweruser audits."""

from __future__ import annotations

import sys

import pytest

from ghostchimera.control_plane import cli


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path / ".ghostchimera"))


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


# --- newcomer P1-6 (brief: P1-8): subcommand typos must not run as tasks ---


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("dmeo", "demo"), ("polcy", "policy"), ("doctr", "doctor"), ("stup", "setup"), ("mpc", "mcp")],
)
def test_subcommand_typo_suggests_and_exits_2(typed, expected, monkeypatch, capsys) -> None:
    ran = []
    monkeypatch.setattr(cli, "_run_ask_cli", lambda args: ran.append(args) or 0)
    monkeypatch.setattr(sys, "argv", ["ghost", typed])
    assert cli._main([typed]) == 2
    err = capsys.readouterr().err
    assert f"unknown command '{typed}'" in err
    assert f"Did you mean '{expected}'?" in err
    assert ran == [], "a typo must not be executed as an objective"


def test_typo_with_flags_is_still_caught(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ghost", "dmeo", "--json"])
    assert cli._main(["dmeo", "--json"]) == 2
    assert "Did you mean 'demo'?" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["summarize"], ["hello"], ["use"], ["dmeo the repo"], ["fix", "the", "tests"], ["test", "my", "code"]],
)
def test_objectives_that_are_not_typos_still_run_as_ask(argv, monkeypatch) -> None:
    ran = []
    monkeypatch.setattr(cli, "_run_ask_cli", lambda args: ran.append(" ".join(args.objective)) or 0)
    monkeypatch.setattr(sys, "argv", ["ghost", *argv])
    assert cli._main(argv) == 0
    assert ran == [" ".join(argv)]
