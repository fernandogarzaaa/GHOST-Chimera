"""UNDERSTAND sends enable_thinking=false to Nemotron by default (audit2 poweruser F20)."""

from __future__ import annotations

import json
from typing import Any

from ghostchimera.demo.replay import RecordingProvider
from ghostchimera.model_layer.openai_compatible_providers import NebiusProvider
from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.nemotron_reasoning import THINKING_OFF, NemotronReasoner, call_provider


class _KwProvider:
    available = True
    model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    api_key = "k"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def chat(self, system: str, user: str, *, extra_body=None, max_tokens=None, timeout=None) -> str:
        self.calls.append({"extra_body": extra_body, "max_tokens": max_tokens, "timeout": timeout})
        return self.reply


class _PlainProvider:
    available = True
    model = "m"

    def chat(self, system: str, user: str) -> str:
        return '{"intent": "x", "confidence": 0.5}'


_EVENT = new_event("github.issue_created", source="github", payload={"title": "Crash on start"})


def test_understand_turns_thinking_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("GHOSTCHIMERA_NEMOTRON_UNDERSTAND_THINKING", raising=False)
    provider = _KwProvider('{"intent": "triage", "confidence": 0.9}')
    reasoner = NemotronReasoner(provider=provider)
    assert reasoner.understand(_EVENT)["intent"] == "triage"
    call = provider.calls[0]
    assert call["extra_body"] == THINKING_OFF
    assert call["max_tokens"] == 512
    assert call["timeout"] == 20.0


def test_understand_thinking_can_be_reenabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_UNDERSTAND_THINKING", "1")
    provider = _KwProvider('{"intent": "triage", "confidence": 0.9}')
    NemotronReasoner(provider=provider).understand(_EVENT)
    assert provider.calls[0]["extra_body"] is None


def test_plain_chat_signature_still_works() -> None:
    assert NemotronReasoner(provider=_PlainProvider()).understand(_EVENT)["intent"] == "x"


def test_recording_provider_forwards_options() -> None:
    inner = _KwProvider("ok")
    rec = RecordingProvider(inner)
    assert call_provider(rec, "s", "event_type: a.b", extra_body=THINKING_OFF, timeout=5.0) == "ok"
    assert inner.calls[0]["extra_body"] == THINKING_OFF


def test_nebius_provider_merges_extra_body_into_request(monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test")
    sent: dict[str, Any] = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()

    def fake_urlopen(req, context=None, timeout=None):
        sent["body"] = json.loads(req.data.decode())
        sent["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("ghostchimera.model_layer.openai_compatible_providers.urllib_request.urlopen", fake_urlopen)
    NebiusProvider().chat("s", "u", extra_body=THINKING_OFF, max_tokens=256, timeout=7.0)
    assert sent["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["body"]["max_tokens"] == 256
    assert sent["timeout"] == 7.0
