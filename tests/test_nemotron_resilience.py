"""Retry/Retry-After, error bodies, circuit breaker and model fallback (audit2 poweruser F7, F10, F18; newcomer P1-9).

Exercised against a local fake OpenAI-compatible server on 127.0.0.1.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from ghostchimera.model_layer.openai_compatible_providers import (
    NebiusProvider,
    ProviderConnectionError,
    ProviderHTTPError,
    parse_retry_after,
)
from ghostchimera.stealth.events import new_event
from ghostchimera.stealth.nemotron_reasoning import CircuitBreaker, NemotronReasoner


class FakeNebius:
    """Scripted responses keyed by model: list of (status, body, headers)."""

    def __init__(self) -> None:
        self.script: dict[str, list[tuple[int, str, dict[str, str]]]] = {}
        self.hits: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                model = str(body.get("model"))
                fake.hits.append(model)
                fake.bodies.append(body)
                queue = fake.script.get(model) or fake.script.get("*") or []
                status, text, headers = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else (200, "", {}))
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(text.encode())))
                self.end_headers()
                self.wfile.write(text.encode())

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _ok(content: str) -> tuple[int, str, dict[str, str]]:
    return 200, json.dumps({"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 3}}), {}


@pytest.fixture
def fake(monkeypatch):
    server = FakeNebius()
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")
    monkeypatch.setattr(NebiusProvider, "_DEFAULT_BASE_URL", server.url)
    monkeypatch.setattr("ghostchimera.model_layer.openai_compatible_providers.time.sleep", lambda s: None)
    monkeypatch.setattr("ghostchimera.model_layer.openai_compatible_providers.ssl.create_default_context", lambda: None)
    yield server
    server.close()


def test_retries_429_with_retry_after_then_succeeds(fake) -> None:
    fake.script["*"] = [(429, '{"detail":"slow down"}', {"Retry-After": "2"}), _ok("pong")]
    assert NebiusProvider().chat("s", "u") == "pong"
    assert len(fake.hits) == 2


def test_retries_5xx_but_bounded(fake, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "2")
    fake.script["*"] = [(503, "<html>down</html>", {})]
    with pytest.raises(ProviderHTTPError) as info:
        NebiusProvider().chat("s", "u")
    assert info.value.status == 503
    assert len(fake.hits) == 3


def test_long_retry_after_is_not_waited_out(fake) -> None:
    fake.script["*"] = [(429, "{}", {"Retry-After": "120"})]
    with pytest.raises(ProviderHTTPError) as info:
        NebiusProvider().chat("s", "u")
    assert info.value.retry_after == 120
    assert len(fake.hits) == 1


def test_404_names_the_model_and_keeps_the_body(fake, monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_MODEL", "nvidia/does-not-exist")
    fake.script["*"] = [(404, '{"detail":"Model nvidia/does-not-exist not found"}', {})]
    with pytest.raises(ProviderHTTPError) as info:
        NebiusProvider().chat("s", "u")
    text = str(info.value)
    assert "nvidia/does-not-exist" in text and "NEBIUS_MODEL" in text
    assert "detail: Model nvidia/does-not-exist not found" in text
    assert "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B" in text
    assert len(fake.hits) == 1


def test_200_with_error_body_and_html_are_errors(fake) -> None:
    fake.script["*"] = [(200, '{"error": {"message": "upstream exploded"}}', {})]
    with pytest.raises(ProviderHTTPError, match="upstream exploded"):
        NebiusProvider().chat("s", "u")


def test_connection_refused_hint(monkeypatch) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-not-real")
    monkeypatch.setattr(NebiusProvider, "_DEFAULT_BASE_URL", "http://127.0.0.1:9/v1/chat/completions")
    with pytest.raises(ProviderConnectionError, match="can't reach 127.0.0.1:9"):
        NebiusProvider().chat("s", "u")


def test_parse_retry_after() -> None:
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_reasoner_falls_back_to_lightning(fake, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "0")
    fake.script["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"] = [(503, "busy", {})]
    fake.script["nvidia/Nemotron-3_5-Lightning"] = [_ok('{"intent": "triage", "confidence": 0.7}')]
    reasoner = NemotronReasoner(fallback_models=["nvidia/Nemotron-3_5-Lightning"])
    out = reasoner.understand(new_event("github.issue_created", source="gh", payload={"title": "500"}))
    assert out["intent"] == "triage"
    assert out["model"] == "nvidia/Nemotron-3_5-Lightning"
    assert fake.hits == ["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "nvidia/Nemotron-3_5-Lightning"]


def test_breaker_stops_hammering_a_failing_endpoint(fake, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "0")
    fake.script["*"] = [(502, "<html>bad gateway</html>", {})]
    reasoner = NemotronReasoner(breaker_threshold=2, breaker_cooldown_s=60, fallback_models=[])
    for i in range(6):
        assert reasoner.understand(new_event("x.y", source="s", payload={"i": i})) is None
    assert len(fake.hits) == 2
    status = reasoner.resilience_status()["breakers"]["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
    assert status["open"] is True


def test_429_retry_after_opens_breaker_immediately() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=5, cooldown_s=30, clock=lambda: now[0])
    assert breaker.failure(retry_after=10) is True
    assert breaker.allow() is False
    now[0] = 10.5
    assert breaker.allow() is True
    breaker.success()
    assert breaker.failures == 0
