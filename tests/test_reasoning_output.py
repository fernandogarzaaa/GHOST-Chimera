"""Nemotron (and other reasoning models) must yield the answer, not the trace.

Covers the hackathon-critical Nebius path: ``max_tokens`` is always sent,
``<think>`` blocks are stripped, ``reasoning_content`` is ignored, and an
answer that is empty after stripping raises instead of returning ``""``.
"""

from __future__ import annotations

import io
import json
import urllib.request

import pytest

from ghostchimera.model_layer import openai_compatible_providers as ocp
from ghostchimera.model_layer.reasoning_output import (
    DEFAULT_MAX_TOKENS,
    EmptyModelAnswer,
    extract_answer,
    resolve_max_tokens,
    strip_reasoning,
)


class _Resp(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def nebius_call(monkeypatch: pytest.MonkeyPatch):
    """Run NebiusProvider.chat against a canned response; return (answer, sent_body)."""
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("NEBIUS_MAX_TOKENS", raising=False)
    monkeypatch.delenv("GHOSTCHIMERA_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    sent: list[dict] = []

    def run(message: dict, finish_reason: str = "stop"):
        def fake_urlopen(req, *args, **kwargs):
            sent.append(json.loads(req.data.decode()))
            payload = {"choices": [{"message": message, "finish_reason": finish_reason}]}
            return _Resp(json.dumps(payload).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        answer = ocp.NebiusProvider().chat("system", "user")
        return answer, sent[-1]

    return run


def test_inline_think_block_is_stripped(nebius_call) -> None:
    answer, body = nebius_call(
        {"role": "assistant", "content": '<think>The user wants JSON. Let me plan...</think>\n{"intent": "x"}'}
    )
    assert answer == '{"intent": "x"}'
    assert body["max_tokens"] == 4096  # Nebius default leaves room for the trace


def test_reasoning_content_field_is_ignored(nebius_call) -> None:
    answer, _ = nebius_call(
        {"role": "assistant", "reasoning_content": "secret scratchpad, do not show", "content": "final answer"}
    )
    assert answer == "final answer"
    assert "scratchpad" not in answer


def test_reasoning_only_response_raises_instead_of_returning_empty(nebius_call) -> None:
    with pytest.raises(EmptyModelAnswer, match="max_tokens"):
        nebius_call({"role": "assistant", "content": None, "reasoning_content": "thinking..."}, "length")


def test_truncated_think_block_raises(nebius_call) -> None:
    with pytest.raises(EmptyModelAnswer):
        nebius_call({"role": "assistant", "content": "<think>still thinking when the budget ran"}, "length")


def test_empty_string_content_raises(nebius_call) -> None:
    with pytest.raises(EmptyModelAnswer):
        nebius_call({"role": "assistant", "content": ""})


def test_max_tokens_is_configurable(nebius_call, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEBIUS_MAX_TOKENS", "777")
    _, body = nebius_call({"content": "ok"})
    assert body["max_tokens"] == 777


def test_every_openai_compatible_provider_sends_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.delenv("GHOSTCHIMERA_MAX_TOKENS", raising=False)
    sent: list[dict] = []

    def fake_urlopen(req, *args, **kwargs):
        sent.append(json.loads(req.data.decode()))
        return _Resp(json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert ocp.GroqProvider().chat("s", "u") == "hi"
    assert sent[0]["max_tokens"] == DEFAULT_MAX_TOKENS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain answer", "plain answer"),
        ("<think>a</think>b", "b"),
        ("<THINK>\nmulti\nline\n</THINK>\n\nanswer", "answer"),
        ("<think>a</think>x<think>b</think>y", "xy"),
        ("trace without opening tag</think>answer", "answer"),
        ("<think>never closed", ""),
        ("<thinking>alt tag</thinking>ok", "ok"),
        (None, ""),
    ],
)
def test_strip_reasoning(raw, expected) -> None:
    assert strip_reasoning(raw) == expected


def test_extract_answer_handles_content_parts_and_missing_choices() -> None:
    parts = {"choices": [{"message": {"content": [{"type": "text", "text": "<think>x</think>hi"}]}}]}
    assert extract_answer(parts) == "hi"
    with pytest.raises(RuntimeError, match="missing choices"):
        extract_answer({"choices": []}, "nebius")


def test_resolve_max_tokens_ignores_bad_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X_MAX", "nope")
    monkeypatch.setenv("GHOSTCHIMERA_MAX_TOKENS", "-5")
    assert resolve_max_tokens("X_MAX", 123) == 123
    monkeypatch.setenv("GHOSTCHIMERA_MAX_TOKENS", "300")
    assert resolve_max_tokens("X_MAX", 123) == 300
