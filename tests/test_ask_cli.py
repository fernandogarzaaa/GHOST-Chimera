"""`ghostchimera ask` must not pass off the offline smoke backend as an answer."""

from __future__ import annotations

import argparse

import pytest

from ghostchimera.control_plane import cli


@pytest.fixture
def no_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("OPENAI_API_KEY", "NEBIUS_API_KEY", "GHOSTCHIMERA_MODEL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli, "load_config", lambda: {})


def _ask(*words: str) -> int:
    return cli._run_ask_cli(argparse.Namespace(objective=list(words), json=False))


def test_ask_without_provider_warns_about_deterministic_backend(no_provider, capsys) -> None:
    # The deterministic backend cannot answer an open-ended request. Since the
    # honest-fulfilment change it reports that (exit 1) instead of printing a
    # placeholder as success, and the CLI still explains why.
    code = _ask("Summarize", "release", "risks")

    captured = capsys.readouterr()
    assert code == 1
    assert "deterministic_unfulfilled" in captured.out
    assert "no model provider is configured" in captured.err
    assert "could not fulfil this task" in captured.err
    assert "ghostchimera setup" in captured.err


def test_ask_without_provider_fulfils_simple_arithmetic(no_provider, capsys) -> None:
    code = _ask("what", "is", "2", "+", "3")

    captured = capsys.readouterr()
    assert code == 0
    assert "5" in captured.out
    assert "no model provider is configured" in captured.err
    assert "only handles simple tasks" in captured.err


def test_ask_requires_objective(capsys) -> None:
    assert _ask() == 2
    assert "objective is required" in capsys.readouterr().out
