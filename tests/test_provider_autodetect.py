"""A lone NEBIUS_API_KEY selects Nebius everywhere (audit2 newcomer P1-1, poweruser F13/F15)."""

from __future__ import annotations

import argparse
import logging

import pytest

from ghostchimera.chimera_pilot import NoBackendAvailableError
from ghostchimera.chimera_pilot.backends.model_provider import ModelProviderBackend
from ghostchimera.control_plane import cli
from ghostchimera.control_plane.doctor import _provider_status
from ghostchimera.control_plane.provider_hint import no_backend_message, no_provider_message
from ghostchimera.model_layer.llm import LLM
from ghostchimera.model_layer.providers import resolve_provider_name


@pytest.fixture
def nebius_only(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GHOSTCHIMERA_MODEL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")


def test_resolve_provider_precedence() -> None:
    assert resolve_provider_name(env={}) == ("openai", "default")
    assert resolve_provider_name(env={"NEBIUS_API_KEY": "k"}) == ("nebius", "auto:NEBIUS_API_KEY")
    # The explicit env var still wins over auto-detect.
    assert resolve_provider_name(env={"NEBIUS_API_KEY": "k", "GHOSTCHIMERA_MODEL_PROVIDER": "OpenAI"}) == (
        "openai",
        "env",
    )
    assert resolve_provider_name("anthropic", env={"NEBIUS_API_KEY": "k"}) == ("anthropic", "explicit")
    assert resolve_provider_name(env={"NEBIUS_API_KEY": "   "}) == ("openai", "default")


def test_model_provider_backend_autoselects_nebius(nebius_only) -> None:
    backend = ModelProviderBackend()
    assert backend.provider_name == "nebius"
    assert backend.probe().available is True
    assert backend.id.startswith("nebius.")


def test_explicit_env_var_wins(nebius_only, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_MODEL_PROVIDER", "openai")
    assert ModelProviderBackend().provider_name == "openai"


def test_llm_autoselects_nebius_and_no_stray_openai_warning(nebius_only, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="ghostchimera.llm"):
        llm = LLM()
    assert llm.provider_name == "nebius"
    assert "OPENAI_API_KEY" not in caplog.text


def test_llm_implicit_openai_default_does_not_warn(monkeypatch, caplog) -> None:
    for var in ("OPENAI_API_KEY", "NEBIUS_API_KEY", "GHOSTCHIMERA_MODEL_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    with caplog.at_level(logging.WARNING, logger="ghostchimera.llm"):
        LLM()
    assert "OPENAI_API_KEY" not in caplog.text


def test_doctor_reports_autodetected_nebius(nebius_only) -> None:
    label, ok, _hint = _provider_status({}, env={"NEBIUS_API_KEY": "k"})
    assert ok is True
    assert "nebius" in label and "NEBIUS_API_KEY" in label


def test_doctor_without_any_key_mentions_nebius() -> None:
    label, ok, hint = _provider_status({}, env={"PATH": "/usr/bin"})
    assert ok is False
    assert "NEBIUS_API_KEY" in hint


def test_ask_uses_nebius_when_only_key_is_set(nebius_only, monkeypatch, capsys) -> None:
    seen: list[str] = []

    def fake_chat(self, system, user):
        seen.append(self.name)
        return "391"

    from ghostchimera.model_layer.openai_compatible_providers import NebiusProvider

    monkeypatch.setattr(NebiusProvider, "chat", fake_chat)
    monkeypatch.setattr(cli, "load_config", lambda: {})
    rc = cli._run_ask_cli(argparse.Namespace(objective=["What", "is", "17*23", "in", "words?"], json=False))
    captured = capsys.readouterr()
    assert seen == ["nebius"], captured
    assert "391" in captured.out
    assert rc == 0
    assert "no model provider is configured" not in captured.err


def test_hint_does_not_ask_to_set_a_key_that_is_already_set() -> None:
    msg = no_provider_message("x", env={"NEBIUS_API_KEY": "k", "GHOSTCHIMERA_MODEL_PROVIDER": "openai"})
    assert "export NEBIUS_API_KEY=..." not in msg
    assert "GHOSTCHIMERA_MODEL_PROVIDER=openai" in msg


def test_file_analysis_without_backend_names_the_task_kind() -> None:
    msg = no_backend_message("analyze file notes.txt", "file_analysis", env={"NEBIUS_API_KEY": "k"})
    assert "no model provider is configured" not in msg
    assert "file_analysis" in msg


def test_reasoning_without_provider_still_gets_provider_hint() -> None:
    msg = no_backend_message("summarize", "reasoning", env={})
    assert "no model provider is configured" in msg


def test_pilot_run_web_research_error_is_accurate(nebius_only, monkeypatch, capsys) -> None:
    class _Kernel:
        policy = None

        def run(self, objective):
            raise NoBackendAvailableError("web-x", "web_research")

    monkeypatch.setattr("ghostchimera.chimera_pilot.ChimeraPilotKernel.default", lambda **_k: _Kernel())
    rc = cli._main(["--pilot-run", "research latest Nemotron 3 release"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "web_research" in err
    assert "no model provider is configured" not in err
