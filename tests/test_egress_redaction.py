"""Secrets and PII are scrubbed before event data reaches Nebius or LangSmith."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ghostchimera.observability import langsmith_tracing as lt
from ghostchimera.observability.langsmith_tracing import LangSmithConfig, LangSmithTracer
from ghostchimera.redaction import redact_for_egress, redact_pii_text
from ghostchimera.stealth.nemotron_reasoning import NemotronReasoner

SECRET = "sk-live1234567890abcdefXYZ"
EMAIL = "jane.doe@example.com"
PHONE = "+63 976 126 7704"
CARD = "4111 1111 1111 1111"  # Luhn-valid test card


class TestRedactForEgress(unittest.TestCase):
    def test_pii_is_replaced_with_labels(self):
        out = redact_pii_text(f"mail {EMAIL}, call {PHONE} or (555) 123-4567, ssn 123-45-6789, card {CARD}")
        for raw in (EMAIL, PHONE, "123-4567", "123-45-6789", CARD):
            self.assertNotIn(raw, out)
        for label in ("email", "phone", "ssn", "card"):
            self.assertIn(f"[redacted:{label}]", out)

    def test_ordinary_numbers_survive(self):
        text = "at 2026-10-14 02:22, ts 1760400000000, order 123456789012345, v0.4.0"
        self.assertEqual(redact_pii_text(text), text)

    def test_nested_values_and_secret_keys(self):
        value = {
            "message": f"my key is {SECRET} and password=hunter2222",
            "api_key": "abc",
            "items": [{"note": f"from {EMAIL}"}, ("tuple", "gsk_ABCDEFGHIJKLMNOPQR")],
            "count": 3,
        }
        out = redact_for_egress(value)
        dumped = json.dumps(out)
        for raw in (SECRET, "hunter2222", "abc", EMAIL, "gsk_ABCDEFGHIJKLMNOPQR"):
            self.assertNotIn(raw, dumped)
        self.assertEqual(out["count"], 3)
        self.assertEqual(value["api_key"], "abc", "input must not be mutated")


class _Provider:
    available = True
    model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    api_key = "nb-test"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return json.dumps({"intent": "x", "confidence": 0.5})


class TestNebiusEgress(unittest.TestCase):
    def test_understand_scrubs_event_payload_before_nebius(self):
        provider = _Provider()
        event = SimpleNamespace(
            event_type="user.message",
            source=f"mail:{EMAIL}",
            payload={"text": f"email {EMAIL}, phone {PHONE}, token {SECRET}", "authorization": "Bearer abc"},
            privacy_classification="internal",
        )
        self.assertIsNotNone(NemotronReasoner(provider=provider).understand(event))
        _, user = provider.calls[0]
        for raw in (EMAIL, PHONE, SECRET, "Bearer abc"):
            self.assertNotIn(raw, user)
        self.assertIn("[redacted:email]", user)

    def test_predict_scrubs_history_before_nebius(self):
        provider = _Provider()
        provider.chat = MagicMock(return_value="[]")
        reasoner = NemotronReasoner(provider=provider)
        reasoner._reasoning_provider = provider
        reasoner.predict_next(f"sent invoice to {EMAIL} with key {SECRET}", hypothesis=f"call {PHONE}")
        user = provider.chat.call_args[0][1]
        for raw in (EMAIL, SECRET, PHONE):
            self.assertNotIn(raw, user)


class _Http:
    def __init__(self):
        self.bodies: list[str] = []

    def Request(self, url, data=None, headers=None, method=None):
        self.bodies.append(data.decode("utf-8"))
        return (url, data, headers, method)

    def urlopen(self, req, timeout=None, context=None):
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp


class TestLangSmithEgress(unittest.TestCase):
    def test_run_inputs_outputs_and_errors_are_scrubbed(self):
        http = _Http()
        tracer = LangSmithTracer(LangSmithConfig(api_key="lsv2-key"))
        with patch.object(lt, "urllib_request", http):
            run = tracer.start_run(
                "nebius.chat_completion",
                inputs={"user": f"contact {EMAIL} / {PHONE}", "system": f"key {SECRET}"},
                metadata={"endpoint": "https://api.tokenfactory.nebius.com/v1", "owner": EMAIL},
            )
            tracer.end_run(run, outputs={"response": f"card {CARD}"})
            tracer.end_run(run, error=f"failed for {EMAIL}")
        joined = "\n".join(http.bodies)
        for raw in (EMAIL, PHONE, SECRET, CARD):
            self.assertNotIn(raw, joined)
        start = json.loads(http.bodies[0])
        self.assertEqual(start["name"], "nebius.chat_completion")
        self.assertEqual(start["id"], run["id"])
        self.assertEqual(start["metadata"]["endpoint"], "https://api.tokenfactory.nebius.com/v1")


if __name__ == "__main__":
    unittest.main()
