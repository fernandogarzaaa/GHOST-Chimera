"""Tests for NemotronReasoner and its Stealth Loop integration."""

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ghostchimera.stealth.nemotron_reasoning import (
    NANO_MODEL,
    NemotronReasoner,
    build_cloud_enhancements,
)


class FakeProvider:
    def __init__(self, reply="", available=True, model=NANO_MODEL, api_key="nb-test"):
        self._reply = reply
        self.available = available
        self.model = model
        self.api_key = api_key
        self.calls: list[tuple[str, str]] = []

    def chat(self, system, user):
        self.calls.append((system, user))
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


class FakeGrounding:
    def __init__(self, grounded=None):
        self._grounded = grounded
        self.available = True
        self.calls = 0

    def ground_event(self, event):
        self.calls += 1
        return self._grounded


def _event(payload=None, privacy="internal", event_type="user.message"):
    return SimpleNamespace(
        event_type=event_type,
        source="test",
        payload=dict(payload or {}),
        privacy_classification=privacy,
    )


_UNDERSTAND_JSON = json.dumps(
    {
        "intent": "research",
        "confidence": 0.82,
        "suggested_workflow": "deep-research",
        "risk_flags": [],
        "rationale": "User is asking about a fast-moving topic.",
    }
)


class TestUnderstand(unittest.TestCase):
    def test_understand_returns_structured_insight(self):
        provider = FakeProvider(reply=_UNDERSTAND_JSON)
        r = NemotronReasoner(provider=provider)
        self.assertTrue(r.available)
        out = r.understand(_event({"summary": "what is nemotron 3?"}))
        self.assertIsNotNone(out)
        self.assertEqual(out["intent"], "research")
        self.assertEqual(out["confidence"], 0.82)
        self.assertEqual(out["provider"], "nebius")
        system, user = provider.calls[0]
        self.assertIn("STRICT JSON", system)
        self.assertIn("user.message", user)

    def test_understand_includes_web_context(self):
        provider = FakeProvider(reply=_UNDERSTAND_JSON)
        grounding = FakeGrounding(
            {
                "query": "q",
                "results": [{"title": "T", "url": "https://t.co", "snippet": "fresh fact"}],
                "transport": "rest",
                "tool": "tavily-search",
            }
        )
        r = NemotronReasoner(provider=provider, grounding=grounding)
        out = r.understand(_event({"ground_with_web": True, "web_query": "q"}))
        self.assertTrue(out["grounded_with_web"])
        self.assertIn("fresh fact", provider.calls[0][1])
        self.assertEqual(grounding.calls, 1)

    def test_unavailable_provider_returns_none(self):
        r = NemotronReasoner(provider=FakeProvider(available=False))
        self.assertFalse(r.available)
        self.assertIsNone(r.understand(_event()))

    def test_provider_error_returns_none(self):
        r = NemotronReasoner(provider=FakeProvider(reply=RuntimeError("down")))
        self.assertIsNone(r.understand(_event()))

    def test_bad_json_returns_none(self):
        r = NemotronReasoner(provider=FakeProvider(reply="not json at all"))
        self.assertIsNone(r.understand(_event()))

    def test_secret_event_never_sent_to_cloud(self):
        provider = FakeProvider(reply=_UNDERSTAND_JSON)
        r = NemotronReasoner(provider=provider)
        self.assertIsNone(r.understand(_event(privacy="secret")))
        self.assertEqual(provider.calls, [])

    def test_fenced_json_is_stripped(self):
        provider = FakeProvider(reply="```json\n" + _UNDERSTAND_JSON + "\n```")
        r = NemotronReasoner(provider=provider)
        out = r.understand(_event())
        self.assertEqual(out["intent"], "research")


class TestPredictNext(unittest.TestCase):
    def test_predict_next_uses_reasoning_model(self):
        fast = FakeProvider(reply=_UNDERSTAND_JSON)
        r = NemotronReasoner(provider=fast)
        seen = {}

        def fake_get_provider(name, profile=None):
            seen["model"] = profile.model if profile else None
            return FakeProvider(
                reply=json.dumps([{"action": "open-email", "probability": 0.7, "rationale": "r"}]),
                model=seen["model"],
            )

        with patch("ghostchimera.model_layer.providers.get_provider", fake_get_provider):
            out = r.predict_next("user opened inbox\nuser searched", hypothesis="email-triage")
        self.assertIsNotNone(out)
        self.assertEqual(out[0]["action"], "open-email")
        self.assertEqual(out[0]["model"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(seen["model"], "nvidia/nemotron-3-super-120b-a12b")

    def test_predict_next_no_provider_returns_none(self):
        r = NemotronReasoner(provider=FakeProvider(available=False))
        self.assertIsNone(r.predict_next("history"))


class TestBuildCloudEnhancements(unittest.TestCase):
    def test_no_keys_returns_nones(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("NEBIUS_API_KEY", None)
            os.environ.pop("TAVILY_API_KEY", None)
            reasoner, grounding = build_cloud_enhancements()
        self.assertIsNone(reasoner)
        self.assertIsNone(grounding)

    def test_tavily_key_only_builds_grounding(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-x"}, clear=True):
            os.environ.pop("NEBIUS_API_KEY", None)
            reasoner, grounding = build_cloud_enhancements()
        self.assertIsNone(reasoner)
        self.assertIsNotNone(grounding)
        self.assertTrue(grounding.available)

    def test_reasoning_flag_off(self):
        env = {"NEBIUS_API_KEY": "nb-x", "GHOSTCHIMERA_NEBIUS_REASONING": "0"}
        with patch.dict(os.environ, env, clear=True):
            os.environ.pop("TAVILY_API_KEY", None)
            reasoner, grounding = build_cloud_enhancements()
        self.assertIsNone(reasoner)
        self.assertIsNone(grounding)


class TestLoopIntegration(unittest.TestCase):
    def _loop(self, **kwargs):
        from ghostchimera.stealth import StealthLoop, new_event

        loop = StealthLoop(**kwargs)
        self.addCleanup(loop.close)
        return loop, new_event

    def test_grounding_lands_in_trace(self):
        loop, new_event = self._loop()
        grounding = FakeGrounding({"query": "q", "results": [], "transport": "rest", "tool": "tavily-search"})
        loop._grounding = grounding
        loop.emit(
            new_event(
                "user.message",
                source="test",
                payload={"ground_with_web": True, "web_query": "q"},
            )
        )
        result = loop.last_result
        self.assertIsNotNone(result)
        self.assertIn("web_grounding", result.trace)
        self.assertEqual(grounding.calls, 1)

    def test_reasoner_insight_lands_in_trace(self):
        loop, new_event = self._loop()
        reasoner = SimpleNamespace(
            available=True,
            understand=lambda event, hypothesis=None, predictions=None: {"intent": "triage"},
        )
        loop._reasoner = reasoner
        loop.emit(new_event("user.message", source="test", payload={"summary": "hi"}))
        result = loop.last_result
        self.assertIn("nemotron", result.trace)
        self.assertEqual(result.trace["nemotron"]["intent"], "triage")

    def test_reasoner_suppresses_duplicate_grounding(self):
        # When the reasoner is attached, the loop must not ALSO call grounding
        # directly (the reasoner already grounds internally).
        loop, new_event = self._loop()
        grounding = FakeGrounding({"query": "q", "results": []})
        reasoner = SimpleNamespace(available=True, understand=lambda *a, **k: {"intent": "x"})
        loop._grounding = grounding
        loop._reasoner = reasoner
        loop.emit(
            new_event(
                "user.message",
                source="test",
                payload={"ground_with_web": True, "web_query": "q"},
            )
        )
        self.assertEqual(grounding.calls, 0)
        self.assertIn("nemotron", loop.last_result.trace)
        self.assertNotIn("web_grounding", loop.last_result.trace)

    def test_loop_unchanged_without_enhancements(self):
        loop, new_event = self._loop()
        loop.emit(new_event("file.modified", source="fs", confidence=0.2))
        result = loop.last_result
        self.assertNotIn("nemotron", result.trace)
        self.assertNotIn("web_grounding", result.trace)


if __name__ == "__main__":
    unittest.main()
