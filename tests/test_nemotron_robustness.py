"""Tolerant parsing and value validation for Nemotron replies (audit2 poweruser F2, F6, F8, F9, F21)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.nemotron_reasoning import NemotronReasoner, coerce_unit, extract_json


class Reply:
    available = True
    model = "m"
    api_key = "k"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        self.calls += 1
        return self.reply


def _ev(payload=None):
    return new_event("email.received", source="gmail", payload={"subject": "Invoice"} if payload is None else payload)


@pytest.mark.parametrize(
    "reply",
    [
        'Sure! Here is the JSON:\n{"intent":"triage","confidence":0.9}',
        '```json\n{"intent":"triage","confidence":0.9}\n```\nHope this helps!',
        'Thinking done.\n```\n{"intent":"triage","confidence":0.9}\n```',
        '{"intent":"triage","confidence":0.9}\n\nLet me know if you need more.',
    ],
)
def test_understand_extracts_wrapped_json(reply: str) -> None:
    out = NemotronReasoner(provider=Reply(reply)).understand(_ev())
    assert out is not None and out["intent"] == "triage"


def test_understand_coerces_bad_types() -> None:
    reply = '{"intent": "triage", "confidence": "very", "risk_flags": "none", "rationale": null}'
    out = NemotronReasoner(provider=Reply(reply)).understand(_ev())
    assert out["confidence"] == 0.5
    assert out["risk_flags"] == []
    assert out["rationale"] == ""
    out = NemotronReasoner(provider=Reply('{"intent": "x", "confidence": 7, "risk_flags": "a, b"}')).understand(_ev())
    assert out["confidence"] == 1.0
    assert out["risk_flags"] == ["a", "b"]


def test_understand_rejects_null_intent() -> None:
    assert NemotronReasoner(provider=Reply('{"intent": null, "confidence": 0.9}')).understand(_ev()) is None


def test_empty_event_skips_cloud_call() -> None:
    provider = Reply('{"intent":"process_email","confidence":0.88}')
    reasoner = NemotronReasoner(provider=provider)
    assert reasoner.understand(new_event("email.received", source="", payload={})) is None
    assert reasoner.understand(new_event("email.received", source="", payload={"a": "", "b": None})) is None
    assert provider.calls == 0


def _predictor(reply: str) -> NemotronReasoner:
    return NemotronReasoner(provider=Reply("{}"), reasoning_provider=Reply(reply))


def test_predict_accepts_wrapper_object() -> None:
    out = _predictor('{"predictions": [{"action": "run_tests", "probability": 0.6}]}').predict_next("a\nb")
    assert out[0]["action"] == "run_tests"


def test_predict_never_raises_on_bad_probability() -> None:
    out = _predictor('[{"action":"a","probability":"high"},{"action":"b","probability":7}]').predict_next("h")
    assert out is not None
    assert all(0.0 <= item["probability"] <= 1.0 for item in out)


def test_predict_probabilities_renormalized_when_over_one() -> None:
    reply = '[{"action":"a","probability":0.78},{"action":"b","probability":0.62},{"action":"c","probability":0.48}]'
    out = _predictor(reply).predict_next("h")
    assert abs(sum(item["probability"] for item in out) - 1.0) < 0.01
    assert [item["action"] for item in out] == ["a", "b", "c"]


def test_predict_failure_returns_none() -> None:
    class Boom(Reply):
        def chat(self, system, user):
            raise RuntimeError("HTTP Error 502: Bad Gateway")

    assert NemotronReasoner(provider=Reply("{}"), reasoning_provider=Boom("")).predict_next("h") is None


def test_coerce_unit() -> None:
    assert coerce_unit("0.9") == 0.9
    assert coerce_unit("85%") == 0.85
    assert coerce_unit("high") == 0.8
    assert coerce_unit(None, default=0.3) == 0.3
    assert coerce_unit(float("nan"), default=0.3) == 0.3
    assert coerce_unit(-2) == 0.0


def test_extract_json_raises_without_json() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")


@pytest.mark.parametrize("payload", [{"title": "Standup", "confidence": "high"}, {"title": "x", "relevance": None}])
def test_bad_producer_fields_do_not_abort_event(payload) -> None:
    calls = []
    reasoner = SimpleNamespace(
        available=True,
        understand=lambda event, hypothesis=None, predictions=None: calls.append(1) or {"intent": "meeting"},
    )
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="sync")
    try:
        loop.emit(new_event("calendar.event_starting", source="gcal", payload={"title": "prev"}))
        event = new_event("calendar.event_starting", source="gcal", payload=payload)
        loop.emit(event)
        assert loop.last_result is not None
        assert loop.last_result.event_id == event.event_id
        assert loop.last_result.trace["nemotron"]["intent"] == "meeting"
    finally:
        loop.close()
