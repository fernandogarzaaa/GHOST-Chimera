"""Gapfill tests from testteeth survivors in model_layer/openai_compatible_providers.py.

Covers the exact boundaries the mutation run proved unnoticed: module
defaults, ProviderHTTPError stringification, Retry-After parsing, usage
normalisation, retry budgets/backoff, transport error mapping, the
Nebius usage-metadata defaults, and the keyless/local provider chats
(Ollama, Cohere, LM Studio, Pollinations) with a scripted urlopen.
No live network anywhere.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ghostchimera.model_layer import openai_compatible_providers as ocp
from ghostchimera.model_layer.auth_profiles import AuthProfile
from ghostchimera.model_layer.openai_compatible_providers import (
    CohereProvider,
    LMStudioProvider,
    NebiusProvider,
    OllamaProvider,
    PollinationsProvider,
    ProviderConnectionError,
    ProviderHTTPError,
    _env_number,
    get_usage_totals,
    parse_retry_after,
    parse_usage,
    reset_usage_totals,
)

OK_BODY = {"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 3}}


class FakeResp:
    def __init__(self, status: int | None, body: str, headers: dict | None = None) -> None:
        self.status = status
        self._body = body.encode()
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResp:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


def _profile(**kw: Any) -> AuthProfile:
    kw.setdefault("api_key", "<redacted>")
    kw.setdefault("model", "m")
    return AuthProfile(provider="test", **kw)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "GHOSTCHIMERA_PROVIDER_RETRIES",
        "GHOSTCHIMERA_PROVIDER_RETRY_MAX_WAIT_S",
        "GHOSTCHIMERA_PROVIDER_TIMEOUT",
        "NEBIUS_API_KEY",
        "NEBIUS_MAX_TOKENS",
        "COHERE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_usage_totals()
    yield
    reset_usage_totals()


def _script(monkeypatch: pytest.MonkeyPatch, items: list) -> tuple[list, list]:
    calls: list = []
    queue = list(items)
    sleeps: list = []

    def fake_urlopen(req, context=None, timeout=None):
        calls.append(req)
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(ocp.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ocp.time, "sleep", sleeps.append)
    return calls, sleeps


# ---------------------------------------------------------------------------
# Module defaults
# ---------------------------------------------------------------------------


def test_module_retry_defaults() -> None:
    assert ocp._DEFAULT_RETRIES == 2
    assert ocp._MAX_RETRIES == 5
    assert ocp._DEFAULT_RETRY_MAX_WAIT_S == 8.0
    assert ocp._ERROR_BODY_CHARS == 400


def test_provider_default_max_tokens() -> None:
    assert ocp.NebiusProvider._DEFAULT_MAX_TOKENS == 4096


def test_nvidia_default_max_tokens() -> None:
    assert ocp.NvidiaProvider._DEFAULT_MAX_TOKENS == 4096


def test_max_tokens_property_uses_default() -> None:
    provider = NebiusProvider(_profile())
    assert provider.max_tokens == 4096


# ---------------------------------------------------------------------------
# ProviderHTTPError
# ---------------------------------------------------------------------------


def test_http_error_str_carries_message() -> None:
    err = ProviderHTTPError("boom", status=500)
    assert str(err) == "boom"
    assert err.status == 500
    assert err.retryable is True
    assert ProviderHTTPError("x", status=400).retryable is False


# ---------------------------------------------------------------------------
# parse_retry_after / _env_number
# ---------------------------------------------------------------------------


def test_parse_retry_after_shapes() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("-5") == 0.0  # clamped, never negative
    assert parse_retry_after("garbage") is None


def test_env_number_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _env_number("GC_T_MISSING", 4.0) == 4.0
    monkeypatch.setenv("GC_T_NUM", "2.5")
    assert _env_number("GC_T_NUM", 4.0) == 2.5
    monkeypatch.setenv("GC_T_NUM", "junk")
    assert _env_number("GC_T_NUM", 4.0) == 4.0


# ---------------------------------------------------------------------------
# parse_usage
# ---------------------------------------------------------------------------


def test_parse_usage_garbage_ints_become_zero() -> None:
    out = parse_usage({"usage": {"prompt_tokens": "x", "completion_tokens": None, "total_tokens": [1]}})
    assert out["prompt_tokens"] == 0
    assert out["completion_tokens"] == 0
    assert out["total_tokens"] == 0


def test_parse_usage_reasoning_and_cached_fallbacks() -> None:
    out = parse_usage({"usage": {"prompt_tokens": 2}})
    assert out["reasoning_tokens"] == 0
    assert out["cached_tokens"] == 0
    out = parse_usage(
        {
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": 7},
                "prompt_tokens_details": {"cached_tokens": 9},
            }
        }
    )
    assert out["reasoning_tokens"] == 7
    assert out["cached_tokens"] == 9
    assert out["total_tokens"] == 0


def test_parse_usage_non_dict_is_empty() -> None:
    assert parse_usage(None) == {}
    assert parse_usage({"usage": "nope"}) == {}


# ---------------------------------------------------------------------------
# Base provider: timeout, availability, usage recording, budgets
# ---------------------------------------------------------------------------


def test_resolve_timeout_fractional_passes_through() -> None:
    provider = NebiusProvider(_profile())
    assert provider._resolve_timeout(0.5) == 0.5
    assert provider._resolve_timeout(0) == provider._REQUEST_TIMEOUT_S
    assert provider._resolve_timeout(None) == provider._REQUEST_TIMEOUT_S


def test_chat_unavailable_raises_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = NebiusProvider(_profile())
    provider.available = False
    monkeypatch.setattr(
        provider, "_post_with_retry", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network"))
    )
    with pytest.raises(RuntimeError, match="is not available"):
        provider.chat("s", "u")


def test_chat_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = NebiusProvider(_profile())
    monkeypatch.setattr(
        provider,
        "_post_with_retry",
        lambda data, timeout: {"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 4}},
    )
    assert provider.chat("s", "u") == "hi"
    totals = get_usage_totals()
    key = f"nebius:{provider.model}"
    assert totals[key]["calls"] == 1
    assert totals[key]["prompt_tokens"] == 4


def test_retry_budget_env_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = NebiusProvider(_profile())
    assert provider._retry_budget() == (2, 8.0)
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "0")
    assert provider._retry_budget()[0] == 0
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "99")
    assert provider._retry_budget()[0] == 5
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRY_MAX_WAIT_S", "0.5")
    assert provider._retry_budget()[1] == 0.5


def test_post_with_retry_backoff_uses_jitter_additively(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = NebiusProvider(_profile())
    monkeypatch.setattr(ocp.random, "uniform", lambda a, b: 0.1)
    calls, sleeps = _script(monkeypatch, [])
    monkeypatch.setattr(
        provider,
        "_post_once",
        lambda data, timeout: calls.append(1) or (_ for _ in ()).throw(ProviderHTTPError("x", status=503)),
    )
    with pytest.raises(ProviderHTTPError):
        provider._post_with_retry(b"{}", 1)
    assert sleeps[0] == pytest.approx(0.6)
    assert sleeps[1] == pytest.approx(1.1)


def test_post_once_missing_status_defaults_to_200(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = NebiusProvider(_profile())

    class NoStatusResp(FakeResp):
        def __init__(self, body: str) -> None:
            self._body = body.encode()
            self.headers = {}

        # note: no .status attribute at all

    calls, _ = _script(monkeypatch, [NoStatusResp(json.dumps(OK_BODY))])
    assert provider._post_once(b"{}", 1)["choices"]


# ---------------------------------------------------------------------------
# Transport error mapping
# ---------------------------------------------------------------------------


def test_http_error_body_preserved() -> None:
    provider = NebiusProvider(_profile())
    err = provider._http_error(500, "boom", None)
    assert err.body == "boom"
    assert "boom" in str(err)
    assert provider._http_error(500, "", None).body == ""


def test_connection_error_uses_host_not_full_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    provider = NebiusProvider(_profile())
    err = provider._connection_error("refused")
    assert isinstance(err, ProviderConnectionError)
    assert "can't reach api.tokenfactory.nebius.com (" in str(err)
    assert "https://api.tokenfactory.nebius.com" not in str(err)


# ---------------------------------------------------------------------------
# Nebius chat: usage-metadata defaults
# ---------------------------------------------------------------------------


def test_nebius_chat_usage_metadata_zero_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera import observability as obs

    runs: list = []

    class FakeTracer:
        def start_run(self, *a, **k):
            return {"id": 1}

        def end_run(self, run, outputs=None, error=None):
            runs.append(outputs or {})

    monkeypatch.setattr(obs, "get_default_tracer", lambda: FakeTracer())
    monkeypatch.setattr(ocp.OpenAICompatibleProvider, "chat", lambda self, s, u, **k: "hello")
    provider = NebiusProvider(_profile())
    provider._usage_tls().last = {"prompt_tokens": 5}
    assert provider.chat("s", "u") == "hello"
    meta = runs[-1]["usage_metadata"]
    assert meta == {"input_tokens": 5, "output_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def test_ollama_validate_config_notes_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OllamaProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    notes = provider.validate_config()
    assert any("unreachable" in n for n in notes)


def test_ollama_validate_config_clean_when_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OllamaProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, "{}"))
    assert provider.validate_config() == []


def test_ollama_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OllamaProvider()
    body = json.dumps({"choices": [{"message": {"content": "hey"}}]})
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, body))
    assert provider.chat("sys", "hi") == "hey"


def test_ollama_chat_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OllamaProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(500, "{}"))
    with pytest.raises(RuntimeError, match="Ollama API returned HTTP 500"):
        provider.chat("sys", "hi")


def test_ollama_chat_oserror_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OllamaProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(RuntimeError, match="could not reach"):
        provider.chat("sys", "hi")


# ---------------------------------------------------------------------------
# Cohere
# ---------------------------------------------------------------------------


def test_cohere_unavailable_without_key() -> None:
    provider = CohereProvider()
    assert provider.available is False
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        provider.chat("s", "u")


def test_cohere_validate_config_flags_missing_key() -> None:
    assert "COHERE_API_KEY is not set" in CohereProvider().validate_config()


def test_cohere_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CohereProvider(_profile(api_key="<redacted>"))
    body = json.dumps({"message": {"content": [{"type": "text", "text": "  yo  "}]}})
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, body))
    assert provider.chat("sys", "hi") == "yo"


def test_cohere_chat_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CohereProvider(_profile(api_key="<redacted>"))
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(401, "{}"))
    with pytest.raises(RuntimeError, match="Cohere API returned HTTP 401"):
        provider.chat("sys", "hi")


def test_cohere_chat_missing_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = CohereProvider(_profile(api_key="<redacted>"))
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, '{"message": {}}'))
    with pytest.raises(RuntimeError, match="missing content"):
        provider.chat("sys", "hi")


# ---------------------------------------------------------------------------
# LM Studio
# ---------------------------------------------------------------------------


def test_lmstudio_validate_config_notes_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LMStudioProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    notes = provider.validate_config()
    assert any("unreachable" in n for n in notes)


def test_lmstudio_validate_config_clean_when_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LMStudioProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, "{}"))
    assert provider.validate_config() == []


def test_lmstudio_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LMStudioProvider()
    body = json.dumps({"choices": [{"message": {"content": "local hi"}}]})
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(200, body))
    assert provider.chat("sys", "hi") == "local hi"


def test_lmstudio_chat_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LMStudioProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(500, "{}"))
    with pytest.raises(RuntimeError, match="LM Studio API returned HTTP 500"):
        provider.chat("sys", "hi")


def test_lmstudio_chat_oserror_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LMStudioProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(RuntimeError, match="could not reach"):
        provider.chat("sys", "hi")


# ---------------------------------------------------------------------------
# Pollinations
# ---------------------------------------------------------------------------


def test_pollinations_chat_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PollinationsProvider()
    seen: list = []

    def fake_urlopen(req, context=None, timeout=None):
        seen.append(req.full_url)
        return FakeResp(200, "  keyless hello  ")

    monkeypatch.setattr(ocp.urllib_request, "urlopen", fake_urlopen)
    assert provider.chat("sys", "hi there") == "keyless hello"
    assert seen[0].startswith("https://text.pollinations.ai/")
    assert "hi%20there" in seen[0]


def test_pollinations_chat_truncates_prompt_to_4000(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PollinationsProvider()
    seen: list = []

    def fake_urlopen(req, context=None, timeout=None):
        seen.append(req.full_url)
        return FakeResp(200, "ok")

    monkeypatch.setattr(ocp.urllib_request, "urlopen", fake_urlopen)
    provider.chat("", "x" * 5000)
    import urllib.parse as up

    assert len(up.unquote(seen[0].split("https://text.pollinations.ai/")[1].split("?")[0])) == 4000


def test_pollinations_chat_non_200_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PollinationsProvider()
    monkeypatch.setattr(ocp.urllib_request, "urlopen", lambda *a, **k: FakeResp(429, "slow"))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        provider.chat("s", "u")


def test_pollinations_refuses_sensitive_content() -> None:
    provider = PollinationsProvider()
    with pytest.raises(RuntimeError, match="refuses sensitive"):
        provider.chat("here is my password: hunter2", "u")
