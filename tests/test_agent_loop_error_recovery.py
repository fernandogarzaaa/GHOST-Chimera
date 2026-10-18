"""AIAgent error recovery with the *production* classifier (audit2 codeaudit F2, F3).

The old ErrorRecoveryTests fed ``error_classifier.ErrorClassifier`` (a different
class) into ``_recover``; these drive ``agent_loop.ErrorClassifier``, the one
``AIAgent.run`` actually uses.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ghostchimera.chimera_pilot.agent_loop import AIAgent, Classification, ErrorClassifier
from ghostchimera.model_layer.router import ModelRouter


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("HTTP Error 429: Too Many Requests", "rate_limit"),
        ("Error code: 429 - {'error': {'message': 'Rate limit reached for requests'}}", "rate_limit"),
        ("rate limit exceeded", "rate_limit"),
        ("nebius API returned HTTP 503: Service Unavailable", "overloaded"),
        ("HTTP Error 502: Bad Gateway", "overloaded"),
        ("The read operation timed out", "overloaded"),
        ("<urlopen error [Errno 111] Connection refused>", "overloaded"),
        ("HTTP Error 404: Not Found", "model_not_found"),
        ("The model `nvidia/does-not-exist` does not exist", "model_not_found"),
        ("HTTP Error 401: Unauthorized", "authentication"),
        (
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota', 'code': 'insufficient_quota'}}",
            "insufficient_quota",
        ),
        ("This model's maximum context length is 131072 tokens", "context_length"),
        ("HTTP Error 400: Bad Request", "default"),
        ("something odd happened", "default"),
    ],
)
def test_classifier_matches_real_provider_errors(message: str, expected: str) -> None:
    got = ErrorClassifier.classify(message)
    assert got == ErrorClassifier._by_key(expected), (message, got)


def test_classifier_uses_exception_status_attribute() -> None:
    class ProviderError(Exception):
        status_code = 429

    assert ErrorClassifier.classify_exception(ProviderError("boom")).retry is True


def test_classification_has_is_recoverable_alias() -> None:
    assert Classification(recoverable=True).is_recoverable is True


def test_recover_with_production_classifier_does_not_crash() -> None:
    agent = AIAgent(model_name="x")
    classification = agent.error_classifier.classify("429 rate limit exceeded")
    with patch("ghostchimera.chimera_pilot.agent_loop.time.sleep") as sleep:
        assert agent._recover(Exception("429"), classification) is True
    sleep.assert_called_once()


def test_run_retries_after_429_then_succeeds() -> None:
    calls = {"n": 0}

    class FlakyRouter:
        def complete(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("HTTP Error 429: Too Many Requests")
            return {"content": "ok after retry", "finish_reason": "stop"}

    agent = AIAgent(model_name="m", router=FlakyRouter(), fallback_chain=["m"])
    with patch("ghostchimera.chimera_pilot.agent_loop.time.sleep"):
        assert "ok after retry" in agent.run("hello")
    assert calls["n"] == 2


def test_run_surfaces_unrecoverable_error_not_attribute_error() -> None:
    class DeadRouter:
        def complete(self, **kwargs):
            raise RuntimeError("HTTP Error 401: Unauthorized")

    agent = AIAgent(model_name="m", router=DeadRouter(), fallback_chain=["m"])
    with pytest.raises(RuntimeError, match="All models in fallback chain failed"):
        agent.run("hello")


def test_real_model_router_is_adapted_via_route() -> None:
    router = ModelRouter([])
    seen: dict[str, str] = {}

    def fake_route(system_message: str, user_message: str) -> str:
        seen["system"] = system_message
        seen["user"] = user_message
        return "routed answer"

    router.route = fake_route  # type: ignore[method-assign]
    agent = AIAgent(model_name="m", router=router, fallback_chain=["m"], system_prompt="be brief")
    assert "routed answer" in agent.run("what is up?")
    assert "what is up?" in seen["user"]
