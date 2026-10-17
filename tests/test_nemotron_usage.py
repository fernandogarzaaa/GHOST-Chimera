"""Nebius token usage is captured, budgeted and exposed (audit2 poweruser F11)."""

from __future__ import annotations

import json
from typing import Any

from ghostchimera.model_layer.openai_compatible_providers import (
    NebiusProvider,
    get_usage_totals,
    parse_usage,
    reset_usage_totals,
)
from ghostchimera.stealth import StealthLoop, new_event
from ghostchimera.stealth.budgets import COST_BUDGET
from ghostchimera.stealth.nemotron_reasoning import NemotronReasoner

_USAGE = {
    "prompt_tokens": 120,
    "completion_tokens": 300,
    "total_tokens": 420,
    "completion_tokens_details": {"reasoning_tokens": 250},
    "prompt_tokens_details": {"cached_tokens": 64},
}


def _fake_urlopen(content: str, usage: dict[str, Any]):
    class _Resp:
        status = 200
        headers: dict[str, str] = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": content}}], "usage": usage}).encode()

    return lambda req, context=None, timeout=None: _Resp()


def test_parse_usage_includes_reasoning_and_cached_tokens() -> None:
    assert parse_usage({"usage": _USAGE}) == {
        "prompt_tokens": 120,
        "completion_tokens": 300,
        "reasoning_tokens": 250,
        "cached_tokens": 64,
        "total_tokens": 420,
    }
    assert parse_usage({"usage": {"prompt_tokens": 2, "completion_tokens": 3}})["total_tokens"] == 5
    assert parse_usage({}) == {}


def test_provider_records_usage(monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test")
    monkeypatch.setattr(
        "ghostchimera.model_layer.openai_compatible_providers.urllib_request.urlopen", _fake_urlopen("hi", _USAGE)
    )
    reset_usage_totals()
    provider = NebiusProvider()
    assert provider.chat("s", "u") == "hi"
    assert provider.last_usage["reasoning_tokens"] == 250
    totals = get_usage_totals()[f"nebius:{provider.model}"]
    assert totals["total_tokens"] == 420 and totals["calls"] == 1


def test_usage_lands_in_trace_budget_and_status(monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test")
    monkeypatch.setattr(
        "ghostchimera.model_layer.openai_compatible_providers.urllib_request.urlopen",
        _fake_urlopen('{"intent": "triage", "confidence": 0.9}', _USAGE),
    )
    reasoner = NemotronReasoner()
    loop = StealthLoop(reasoner=reasoner, own_runtime=False, cloud_mode="async")
    try:
        loop.emit(new_event("github.issue_created", source="gh", payload={"title": "500"}))
        assert loop.wait_for_cloud(5.0)
        insight = loop.last_result.trace["nemotron"]
        assert insight["usage"]["total_tokens"] == 420
        assert "latency_ms" in insight
        spent = loop.budgets.get(COST_BUDGET).spent()
        assert spent >= 420
        status = loop.cloud_status()
        assert status["tokens_metered"] >= 420
        assert status["cost_budget"]["spent"] >= 420
        assert any(v.get("reasoning_tokens") for v in status["usage"].values())
    finally:
        loop.close()


def test_exhausted_cost_budget_stops_cloud_calls(monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test")
    monkeypatch.setenv("GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR", "500")
    calls = []

    def urlopen(req, context=None, timeout=None):
        calls.append(1)
        return _fake_urlopen('{"intent": "x", "confidence": 0.5}', _USAGE)(req)

    monkeypatch.setattr("ghostchimera.model_layer.openai_compatible_providers.urllib_request.urlopen", urlopen)
    loop = StealthLoop(reasoner=NemotronReasoner(), own_runtime=False, cloud_mode="sync")
    try:
        loop.nemotron_predict_interval_s = 10**9
        for i in range(4):
            loop.emit(new_event("file.modified", source="fs", session_id="s", payload={"i": i}))
        # 420 tokens per call against a 500-token hourly cap: two calls fit
        # (the second starts with budget left), then the loop stops calling.
        assert len(calls) == 2
    finally:
        loop.close()
