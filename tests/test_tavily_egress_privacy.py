"""Tavily grounding must never ship secret events or raw PII/secrets (poweruser F12, redteam P1-5)."""

from __future__ import annotations

import pytest

from ghostchimera.stealth import StealthLoop
from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.tavily_grounding import TavilyGrounding

RAW = "OTP 482913 for jane.doe@acme.com acct 4111 1111 1111 1111, key sk-proj-abcdefghijklmnop1234 call 09171234567"


@pytest.fixture
def grounding(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-dummy")
    g = TavilyGrounding(mode="rest")
    sent: list[str] = []
    g._search_inner = lambda q, n: sent.append(q) or []  # type: ignore[method-assign]
    return g, sent


def test_poweruser_poc_secret_event_never_reaches_tavily(grounding, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_NEBIUS_REASONING", "0")
    g, sent = grounding
    loop = StealthLoop(grounding=g)
    loop.emit(
        new_event(
            "email.received",
            source="gmail",
            privacy_classification="secret",
            payload={"ground_with_web": True, "text": RAW},
        )
    )
    assert sent == []


@pytest.mark.parametrize("privacy", ["secret", "sensitive", "private"])
def test_ground_event_refuses_no_egress_classes(grounding, privacy) -> None:
    g, sent = grounding
    event = new_event("web_research", source="t", privacy_classification=privacy, payload={"text": "weather today"})
    assert g.ground_event(event) is None
    assert sent == []


def test_query_is_built_from_redacted_text(grounding) -> None:
    g, sent = grounding
    event = new_event("email.received", source="gmail", payload={"ground_with_web": True, "text": RAW})
    g.ground_event(event)
    assert len(sent) == 1
    query = sent[0]
    for leak in ("jane.doe@acme.com", "4111 1111 1111 1111", "sk-proj-abcdefghijklmnop1234"):
        assert leak not in query
    assert "email.received" in query


def test_direct_search_and_trace_inputs_are_redacted(grounding, monkeypatch) -> None:
    import ghostchimera.observability as obs

    g, sent = grounding
    captured: list[dict] = []

    class Tracer:
        def start_run(self, name, **kwargs):
            captured.append(kwargs.get("inputs") or {})
            return object()

        def end_run(self, run, **kwargs):
            return None

    monkeypatch.setattr(obs, "get_default_tracer", lambda: Tracer())
    g.search("look up jane.doe@acme.com with key sk-proj-abcdefghijklmnop1234")
    assert "jane.doe@acme.com" not in sent[0] and "sk-proj-abcdefghijklmnop1234" not in sent[0]
    assert "jane.doe@acme.com" not in str(captured) and "sk-proj" not in str(captured)


def test_benign_query_unchanged(grounding) -> None:
    g, sent = grounding
    g.search("latest Python 3.13 release notes")
    assert sent == ["latest Python 3.13 release notes"]
