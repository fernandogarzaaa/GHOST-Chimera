"""`ghostchimera ask` must not pass off the offline smoke backend as an answer."""

from __future__ import annotations

import argparse

from ghostchimera.control_plane import cli


def test_ask_without_provider_warns_about_deterministic_backend(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("OPENAI_API_KEY", "NEBIUS_API_KEY", "GHOSTCHIMERA_MODEL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli, "load_config", lambda: {})

    code = cli._run_ask_cli(argparse.Namespace(objective=["Summarize", "release", "risks"], json=False))

    captured = capsys.readouterr()
    assert code == 0
    assert "no model provider is configured" in captured.err
    assert "ghostchimera setup" in captured.err
