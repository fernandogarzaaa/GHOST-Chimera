"""Free-text model answers are not reported as verified; refusals fail (audit2 poweruser F14, F25)."""

from __future__ import annotations

import argparse

import pytest

from ghostchimera.chimera_pilot import ChimeraPilotKernel
from ghostchimera.chimera_pilot.backends.model_provider import ModelProviderBackend, looks_like_refusal
from ghostchimera.control_plane import cli
from ghostchimera.model_layer.openai_compatible_providers import NebiusProvider


@pytest.fixture
def nebius(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("GHOSTCHIMERA_MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")
    monkeypatch.setattr(cli, "load_config", lambda: {})

    def reply_with(text: str) -> None:
        monkeypatch.setattr(NebiusProvider, "chat", lambda self, system, user, **kw: text)

    return reply_with


@pytest.mark.parametrize(
    "text",
    [
        "I'm unable to view or read the contents of notes.txt.",
        "I can't access files on your computer.",
        "I'm sorry, but I am not able to open that file.",
        "As an AI language model, I cannot browse the internet.",
        "I don't have access to your file system.",
    ],
)
def test_refusals_are_detected(text: str) -> None:
    assert looks_like_refusal(text)


@pytest.mark.parametrize("text", ["391", "Nemotron is NVIDIA's family of open models.", ""])
def test_answers_are_not_refusals(text: str) -> None:
    assert not looks_like_refusal(text)


def test_refusal_is_not_a_verified_success(nebius) -> None:
    nebius("I'm unable to view or read the contents of notes.txt")
    kernel = ChimeraPilotKernel.default()
    executions = kernel.run("Summarize what notes.txt contains in one sentence")
    item = executions[0].to_dict()
    assert item["ok"] is False
    claims = {c["claim"]: c["passed"] for c in item["envelope"]["claims"]}
    assert claims.get("verification_passed") is not True
    assert item["envelope"]["confidence"] < 1.0


def test_free_text_answer_is_marked_unverified(nebius) -> None:
    nebius("Nemotron is a family of open NVIDIA models.")
    kernel = ChimeraPilotKernel.default()
    item = kernel.run("In one sentence, what is NVIDIA Nemotron?")[0].to_dict()
    assert item["ok"] is True
    envelope = item["envelope"]
    assert envelope["confidence_source"] == "model_unverified"
    assert envelope["confidence"] < 1.0
    claims = {c["claim"]: c["passed"] for c in envelope["claims"]}
    assert claims["verification_passed"] is False


def test_ask_exits_nonzero_when_the_model_refuses(nebius, capsys) -> None:
    nebius("I can't access files on your computer.")
    rc = cli._run_ask_cli(argparse.Namespace(objective=["read", "notes.txt", "and", "summarize", "it"], json=False))
    assert rc != 0


def test_model_backend_system_prompt_forbids_inventing_file_contents(nebius, monkeypatch) -> None:
    seen = {}

    def chat(self, system, user, **kw):
        seen["system"] = system
        return "ok"

    monkeypatch.setattr(NebiusProvider, "chat", chat)
    from ghostchimera.chimera_pilot.task_ir import TaskKind, TaskSpec

    ModelProviderBackend().execute(TaskSpec.create(kind=TaskKind.REASONING, objective="x", inputs={"prompt": "x"}))
    assert "never invent file contents" in seen["system"]
