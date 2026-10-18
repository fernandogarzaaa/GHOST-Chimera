"""Contracts for the Nemotron reasoner's parsing, breaker and fallback chain.

Written from testteeth survivors in ``ghostchimera/stealth/nemotron_reasoning.py``:
the PREDICT path (``predict_next``) must return clean, capped, sorted,
normalised predictions; the breaker must open/close on exact boundaries; the
fallback chain must count usage and surface the last error.
"""

from __future__ import annotations

from typing import Any

import pytest

from ghostchimera.stealth import nemotron_reasoning as nr
from ghostchimera.stealth.nemotron_reasoning import (
    CircuitBreaker,
    CircuitOpenError,
    NemotronReasoner,
    coerce_unit,
    extract_json,
    normalize_predictions,
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeProvider:
    available = True
    api_key = "test-key"

    def __init__(self, model: str, replies: list[Any] | None = None, usage: dict | None = None) -> None:
        self.model = model
        self.replies = list(replies or [])
        self.calls: list[tuple[str, str, dict]] = []
        self.last_usage = usage

    def chat(self, system: str, user: str, **options: Any) -> str:
        self.calls.append((system, user, options))
        reply = self.replies.pop(0) if self.replies else "[]"
        if isinstance(reply, Exception):
            raise reply
        return reply


# ---------------------------------------------------------------------------
# Breaker
# ---------------------------------------------------------------------------


def test_breaker_defaults_and_threshold() -> None:
    clock = Clock()
    breaker = CircuitBreaker(clock=clock)
    assert breaker.threshold == 3 and breaker.cooldown_s == 30.0
    assert breaker.failures == 0 and breaker.open_until == 0.0
    assert breaker.failure() is False
    assert breaker.failure() is False
    assert breaker.allow() is True
    assert breaker.failure() is True  # third failure opens it
    assert breaker.allow() is False
    assert breaker.to_dict() == {"failures": 3, "open": True, "open_for_s": 30.0}
    # Already open: a further failure does not report "just opened".
    assert breaker.failure() is False


def test_breaker_reopens_exactly_at_cooldown() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=10, clock=clock)
    assert breaker.failure() is True
    clock.now = 109.9
    assert breaker.allow() is False
    assert breaker.to_dict()["open"] is True
    assert breaker.to_dict()["open_for_s"] == 0.1
    clock.now = 110.0
    assert breaker.allow() is True  # half-open exactly at open_until
    assert breaker.to_dict() == {"failures": 1, "open": False, "open_for_s": 0.0}


def test_breaker_failure_at_boundary_counts_as_reopening() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_s=10, clock=clock)
    breaker.failure()
    clock.now = 110.0  # exactly when it closed
    assert breaker.failure() is True


def test_breaker_clamps_inputs_and_retry_after() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=0, cooldown_s=-5, clock=clock)
    assert breaker.threshold == 1 and breaker.cooldown_s == 0.0
    big = CircuitBreaker(threshold=9, clock=clock)
    assert big.failure(retry_after=10_000) is True
    assert big.open_until == 100.0 + 300.0


# ---------------------------------------------------------------------------
# JSON extraction / coercion
# ---------------------------------------------------------------------------


def test_extract_json_shapes() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("```\n[1, 2]\n```") == [1, 2]
    assert extract_json('Sure!\n```json\n{"a": 2}\n```\nHope this helps!') == {"a": 2}
    assert extract_json('Here you go: {"a": 3} thanks') == {"a": 3}
    assert extract_json('noise ```{"broken": ``` then [4]') == [4]
    with pytest.raises(ValueError):
        extract_json("")
    with pytest.raises(ValueError):
        extract_json("no json here at all")


def test_strip_fences_exact() -> None:
    assert nr._strip_fences("```json\n{}\n```") == "{}"
    assert nr._strip_fences("```\nabc\n```  ") == "abc"
    assert nr._strip_fences("```\nabc") == "abc"
    assert nr._strip_fences("plain") == "plain"
    assert nr._strip_fences("```\nline1\nline2\n```") == "line1\nline2"


def test_coerce_unit() -> None:
    assert coerce_unit(True) == 1.0 and coerce_unit(False) == 0.0
    assert coerce_unit("85%") == 0.85
    assert coerce_unit("high") == 0.8
    assert coerce_unit("garbage", default=0.3) == 0.3
    assert coerce_unit(float("nan"), default=0.4) == 0.4
    assert coerce_unit(7) == 1.0 and coerce_unit(-1) == 0.0


def test_as_str_list() -> None:
    assert nr._as_str_list(None) == []
    assert nr._as_str_list(" n/a ") == []
    assert nr._as_str_list("a, b,,c") == ["a", "b", "c"]
    assert nr._as_str_list(["x", None, " ", "y"]) == ["x", "y"]
    assert nr._as_str_list(3) == ["3"]


def test_has_signal() -> None:
    assert nr._has_signal({}) is False
    assert nr._has_signal({"a": "", "b": [None, "  "]}) is False
    assert nr._has_signal({"a": {"b": "x"}}) is True
    assert nr._has_signal(False) is False
    assert nr._has_signal(0) is True


def test_normalize_understand() -> None:
    assert nr._normalize_understand({"intent": "  "}) is None
    assert nr._normalize_understand([]) is None
    out = nr._normalize_understand({"intent": " book flight ", "confidence": "low", "risk_flags": "pii"})
    assert out["intent"] == "book flight"
    assert out["confidence"] == 0.2
    assert out["risk_flags"] == ["pii"]
    assert out["suggested_workflow"] == "" and out["rationale"] == ""
    out = nr._normalize_understand({"intent": "x", "suggested_workflow": "wf", "rationale": 5})
    assert out["suggested_workflow"] == "wf" and out["rationale"] == "5"
    assert nr._normalize_understand({"intent": "x"})["confidence"] == 0.5


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------


def test_prediction_items_shapes() -> None:
    assert nr._prediction_items([{"action": "a"}]) == [{"action": "a"}]
    assert nr._prediction_items({"next_actions": [1]}) == [1]
    assert nr._prediction_items({"whatever": [2]}) == [2]
    assert nr._prediction_items({"x": [1], "y": [2]}) is None
    assert nr._prediction_items({"action": "solo"}) == [{"action": "solo"}]
    assert nr._prediction_items({"note": "no list"}) is None
    assert nr._prediction_items("nope") is None


def test_normalize_predictions_filters_caps_sorts_and_renormalises() -> None:
    items = [
        "not a dict",
        {"action": None},
        {"action": "   "},
        {"action": " open inbox ", "probability": 0.2},
        {"action": "reply", "probability": "90%", "rationale": "pattern"},
        {"action": "archive"},
        {"action": "fourth", "probability": 0.99},
    ]
    out = normalize_predictions(items, model="m")
    assert [p["action"] for p in out] == ["reply", "open inbox", "archive"]  # capped at 3, sorted
    assert [p["probability"] for p in out] == [0.8182, 0.1818, 0.0]  # 0.9+0.2 > 1 -> renormalised
    assert out[0]["rationale"] == "pattern" and out[1]["rationale"] == ""
    assert {p["model"] for p in out} == {"m"}
    assert {p["provider"] for p in out} == {nr.NEBIUS_PROVIDER_ID}


def test_normalize_predictions_keeps_probabilities_when_sum_le_one() -> None:
    out = normalize_predictions([{"action": "a", "probability": 0.3}, {"action": "b", "probability": 0.7}])
    assert out == [
        {"action": "b", "probability": 0.7, "rationale": "", "provider": nr.NEBIUS_PROVIDER_ID, "model": ""},
        {"action": "a", "probability": 0.3, "rationale": "", "provider": nr.NEBIUS_PROVIDER_ID, "model": ""},
    ]


# ---------------------------------------------------------------------------
# Fallback chain, usage accounting, predict_next
# ---------------------------------------------------------------------------


def _reasoner(primary: FakeProvider, reasoning: FakeProvider | None = None, **kw: Any) -> NemotronReasoner:
    return NemotronReasoner(provider=primary, reasoning_provider=reasoning or primary, **kw)


def test_chat_resilient_success_resets_breaker_and_counts_usage() -> None:
    primary = FakeProvider("nano", [RuntimeError("boom"), "ok"], usage={"prompt_tokens": "7", "bad": "x"})
    reasoner = _reasoner(primary, fallback_models=[], breaker_threshold=5)
    with pytest.raises(RuntimeError, match="boom"):
        reasoner._chat_resilient(primary, "s", "u", {})
    assert reasoner._breaker("nano").failures == 1
    reply, model = reasoner._chat_resilient(primary, "s", "u", {})
    assert (reply, model) == ("ok", "nano")
    assert reasoner._breaker("nano").failures == 0
    assert reasoner.usage_totals() == {"nano": {"calls": 1, "prompt_tokens": 7}}
    last = reasoner.last_call()
    assert last["model"] == "nano" and last["usage"] == {"prompt_tokens": 7}
    assert 0 <= last["latency_ms"] < 5000
    reasoner._chat_resilient(primary, "s", "u", {})
    assert reasoner.usage_totals()["nano"] == {"calls": 2, "prompt_tokens": 14}


def test_chat_resilient_uses_fallback_and_raises_when_all_open(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = FakeProvider("super", [RuntimeError("down")] * 5)
    backup = FakeProvider("lightning", ["from-backup"])
    reasoner = _reasoner(primary, fallback_models=["super", "lightning"], breaker_threshold=1, breaker_cooldown_s=60)
    monkeypatch.setattr(reasoner, "_fallback_provider", lambda model: backup if model == "lightning" else None)
    assert reasoner._chat_resilient(primary, "s", "u", {}) == ("from-backup", "lightning")
    assert len(primary.calls) == 1  # "super" not duplicated in the chain
    backup.replies = [RuntimeError("also down")]
    with pytest.raises(RuntimeError, match="also down"):
        # primary breaker is open (skipped); the backup's real error is surfaced
        reasoner._chat_resilient(primary, "s", "u", {})
    assert len(primary.calls) == 1
    with pytest.raises(CircuitOpenError):  # everything cooling down now
        reasoner._chat_resilient(primary, "s", "u", {})


def test_chat_resilient_no_models_available() -> None:
    primary = FakeProvider("p")
    reasoner = _reasoner(primary, fallback_models=[], breaker_threshold=1, breaker_cooldown_s=60)
    reasoner._breaker("p").failure()
    with pytest.raises(CircuitOpenError, match="circuit open for p"):
        reasoner._chat_resilient(primary, "s", "u", {})


def test_predict_next_end_to_end_and_redaction() -> None:
    reply = '```json\n{"predictions": [{"action": "send report", "probability": 0.6}]}\n```'
    nano = FakeProvider("nano")
    sup = FakeProvider("super", [reply])
    reasoner = _reasoner(nano, sup, fallback_models=[], reasoning_model="nvidia/super")
    out = reasoner.predict_next("opened inbox; user a@b.co", hypothesis="weekly report")
    assert out == [
        {
            "action": "send report",
            "probability": 0.6,
            "rationale": "",
            "provider": nr.NEBIUS_PROVIDER_ID,
            "model": "nvidia/super",
        }
    ]
    _system, user, _opts = sup.calls[0]
    assert "a@b.co" not in user and "[redacted:email]" in user
    assert "Workflow hypothesis: weekly report" in user
    assert nano.calls == []


def test_predict_next_failures_return_none() -> None:
    nano = FakeProvider("nano")
    assert _reasoner(nano, FakeProvider("s", ['{"note": "nothing"}'])).predict_next("h") is None
    assert _reasoner(nano, FakeProvider("s", ["[]"])).predict_next("h") is None
    assert _reasoner(nano, FakeProvider("s", [RuntimeError("x")]), fallback_models=[]).predict_next("h") is None
    unavailable = FakeProvider("s")
    unavailable.available = False
    assert _reasoner(nano, unavailable).predict_next("h") is None


def test_predict_history_is_clipped() -> None:
    sup = FakeProvider("super", ['[{"action": "x"}]'])
    _reasoner(FakeProvider("nano"), sup).predict_next("q" * 5000)
    user = sup.calls[0][1]
    assert user.count("q") == 2000


def test_env_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_T_NUM", "0")
    assert nr._env_number("GC_T_NUM", 9.0) == 9.0
    monkeypatch.setenv("GC_T_NUM", "abc")
    assert nr._env_number("GC_T_NUM", 9.0) == 9.0
    monkeypatch.setenv("GC_T_NUM", "2.5")
    assert nr._env_number("GC_T_NUM", 9.0) == 2.5


def test_call_provider_options() -> None:
    class Plain:
        def chat(self, system, user):
            return f"{system}|{user}"

    class Kw:
        def chat(self, system, user, **kw):
            return f"{sorted(kw)}"

    assert nr.call_provider(Plain(), "s", "u", timeout=3) == "s|u"
    assert nr.call_provider(Kw(), "s", "u", timeout=3, max_tokens=None) == "['timeout']"
    assert nr._accepts_kwargs(42, ("x",)) is False
