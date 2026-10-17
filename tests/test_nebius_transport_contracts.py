"""Transport contracts for the Nebius / OpenAI-compatible provider path.

Written from testteeth survivors in ``model_layer/openai_compatible_providers.py``:
HTTP status classification, error-body extraction, retry back-off bounds,
usage parsing and the LangSmith hook around ``NebiusProvider.chat``. The
network is replaced by a scripted ``urlopen`` so every branch is exact.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from ghostchimera.model_layer import openai_compatible_providers as ocp
from ghostchimera.model_layer.auth_profiles import AuthProfile
from ghostchimera.model_layer.openai_compatible_providers import (
    NebiusProvider,
    ProviderConnectionError,
    ProviderHTTPError,
    parse_usage,
)

OK_BODY = {"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


class FakeResp:
    def __init__(self, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body.encode()
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResp:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


def _http_error(code: int, body: str = "", headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(body.encode()))


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch) -> NebiusProvider:
    for name in (
        "GHOSTCHIMERA_PROVIDER_RETRIES",
        "GHOSTCHIMERA_PROVIDER_RETRY_MAX_WAIT_S",
        "GHOSTCHIMERA_PROVIDER_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    return NebiusProvider(AuthProfile(provider="nebius", api_key="k", model="nvidia/test-model"))


@pytest.fixture()
def script(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []
    queue: list[Any] = []

    def fake_urlopen(req, context=None, timeout=None):  # type: ignore[no-untyped-def]
        calls.append({"timeout": timeout, "body": json.loads(req.data), "headers": dict(req.header_items())})
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    sleeps: list[float] = []
    monkeypatch.setattr(ocp.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ocp.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(ocp.random, "uniform", lambda a, b: 0.0)
    return queue, calls, sleeps


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "authentication failed"),
        (403, "authentication failed"),
        (404, "model 'nvidia/test-model' not found"),
        (429, "rate limit hit"),
        (500, "server error"),
        (503, "server error"),
        (400, "rejected the request"),
        (402, "rejected the request"),
        (499, "rejected the request"),
    ],
)
def test_http_error_hints(provider: NebiusProvider, status: int, fragment: str) -> None:
    err = provider._http_error(status, '{"error": {"message": "boom  here"}}', 2.0)
    assert fragment in str(err)
    assert str(err).startswith(f"{provider.name} API returned HTTP {status}: ")
    assert str(err).endswith("| detail: boom here")
    assert err.status == status and err.retry_after == 2.0
    assert err.provider == provider.name and err.model == "nvidia/test-model"
    assert err.args == (str(err),)  # message reaches RuntimeError


def test_retryable_statuses() -> None:
    for status in (429, 500, 502, 503, 504):
        assert ProviderHTTPError("x", status=status).retryable is True
    for status in (400, 401, 404, 501, 505, None):
        assert ProviderHTTPError("x", status=status).retryable is False


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ("", ""),
        ('{"error": {"detail": "d1"}}', "d1"),
        ('{"error": {"code": "c1"}}', "c1"),
        ('{"error": {"message": "", "detail": "d2"}}', "d2"),
        ('{"detail": [{"msg": "field required"}]}', "field required"),
        ('{"detail": ["plain"]}', "plain"),
        ('{"message": "top"}', "top"),
        ("<html><body>502</body></html>", "non-JSON (HTML) error page"),
        ("upstream   timed\nout", "upstream timed out"),
        ('{"error": null}', '{"error": null}'),
    ],
)
def test_error_detail(body: str, detail: str) -> None:
    assert ocp._error_detail(body) == detail


def test_error_detail_is_clipped() -> None:
    assert len(ocp._error_detail("x" * 5000)) == ocp._ERROR_BODY_CHARS


# ---------------------------------------------------------------------------
# _post_once / _post_with_retry
# ---------------------------------------------------------------------------


def test_success_parses_usage_and_sends_shape(provider: NebiusProvider, script) -> None:
    queue, calls, _ = script
    queue.append(FakeResp(200, json.dumps(OK_BODY)))
    assert provider.chat("sys", "usr", max_tokens=77, extra_body={"x": 1}, timeout=12) == "hello"
    sent = calls[0]
    assert sent["timeout"] == 12.0
    assert sent["body"]["temperature"] == 0.0
    assert sent["body"]["max_tokens"] == 77 and sent["body"]["x"] == 1
    assert sent["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert provider.last_usage["total_tokens"] == 5


def test_default_timeout_and_env_override(provider: NebiusProvider, monkeypatch: pytest.MonkeyPatch) -> None:
    assert provider._resolve_timeout(None) == provider._REQUEST_TIMEOUT_S
    assert provider._resolve_timeout(0) == provider._REQUEST_TIMEOUT_S
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_TIMEOUT", "7")
    assert provider._resolve_timeout(None) == 7.0
    assert provider._resolve_timeout(3) == 3.0
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_TIMEOUT", "abc")
    assert provider._resolve_timeout(None) == provider._REQUEST_TIMEOUT_S


def test_non_200_status_without_exception(provider: NebiusProvider, script) -> None:
    queue, _, _ = script
    queue.append(FakeResp(404, '{"error": {"message": "nope"}}'))
    with pytest.raises(ProviderHTTPError) as info:
        provider._post_once(b"{}", 1)
    assert info.value.status == 404


def test_status_missing_defaults_to_200(provider: NebiusProvider, script) -> None:
    queue, _, _ = script
    resp = FakeResp(200, json.dumps(OK_BODY))
    resp.status = None  # type: ignore[assignment]
    queue.append(resp)
    assert provider._post_once(b"{}", 1)["choices"]


def test_error_in_200_body_uses_code_as_status(provider: NebiusProvider, script) -> None:
    queue, _, _ = script
    for code, expected in ((400, 400), (599, 599), (600, 502), (399, 502), ("x", 502)):
        queue.append(FakeResp(200, json.dumps({"error": {"code": code, "message": "m"}})))
        with pytest.raises(ProviderHTTPError) as info:
            provider._post_once(b"{}", 1)
        assert info.value.status == expected, code


def test_non_json_and_wrong_shape_are_502(provider: NebiusProvider, script) -> None:
    queue, _, _ = script
    queue.append(FakeResp(200, "<html>gateway</html>"))
    with pytest.raises(ProviderHTTPError, match="non-JSON response") as info:
        provider._post_once(b"{}", 1)
    assert info.value.status == 502
    queue.append(FakeResp(200, "[1, 2]"))
    with pytest.raises(ProviderHTTPError, match="unexpected response shape"):
        provider._post_once(b"{}", 1)


def test_connection_failures(provider: NebiusProvider, script, monkeypatch: pytest.MonkeyPatch) -> None:
    queue, _, _ = script
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("https_proxy", "http://proxy.corp:3128")
    queue.append(urllib.error.URLError("Name or service not known"))
    with pytest.raises(ProviderConnectionError, match=r"can't reach .* via proxy proxy\.corp:3128"):
        provider._post_once(b"{}", 1)
    queue.append(ConnectionRefusedError("refused"))
    with pytest.raises(ProviderConnectionError, match="refused"):
        provider._post_once(b"{}", 1)
    queue.append(ConnectionResetError("reset"))
    with pytest.raises(ProviderHTTPError, match="connection dropped") as info:
        provider._post_once(b"{}", 1)
    assert info.value.status == 503 and info.value.retryable


def test_retry_backoff_doubles_and_honours_retry_after(provider: NebiusProvider, script) -> None:
    queue, calls, sleeps = script
    queue.extend([_http_error(503), _http_error(502), FakeResp(200, json.dumps(OK_BODY))])
    assert provider._post_with_retry(b"{}", 1)["choices"]
    assert sleeps == [0.5, 1.0]
    sleeps.clear()
    queue.extend([_http_error(429, "", {"Retry-After": "3"}), FakeResp(200, json.dumps(OK_BODY))])
    provider._post_with_retry(b"{}", 1)
    assert sleeps == [3.0]


def test_retry_budget_and_give_up(provider: NebiusProvider, script, monkeypatch: pytest.MonkeyPatch) -> None:
    queue, calls, sleeps = script
    queue.extend([_http_error(500)] * 3)
    with pytest.raises(ProviderHTTPError):
        provider._post_with_retry(b"{}", 1)
    assert len(calls) == 3  # 1 + _DEFAULT_RETRIES
    calls.clear()
    queue.append(_http_error(400))
    with pytest.raises(ProviderHTTPError):
        provider._post_with_retry(b"{}", 1)
    assert len(calls) == 1  # non-retryable


def test_retry_after_longer_than_max_wait_fails_fast(provider: NebiusProvider, script, monkeypatch) -> None:
    queue, calls, sleeps = script
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRY_MAX_WAIT_S", "4")
    queue.append(_http_error(429, "", {"Retry-After": "4.5"}))
    with pytest.raises(ProviderHTTPError):
        provider._post_with_retry(b"{}", 1)
    assert sleeps == [] and len(calls) == 1
    # Exactly max_wait is still waited out.
    queue.extend([_http_error(429, "", {"Retry-After": "4"}), FakeResp(200, json.dumps(OK_BODY))])
    provider._post_with_retry(b"{}", 1)
    assert sleeps == [4.0]


def test_exponential_delay_capped_by_max_wait(provider: NebiusProvider, script, monkeypatch) -> None:
    queue, _, sleeps = script
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRIES", "4")
    monkeypatch.setenv("GHOSTCHIMERA_PROVIDER_RETRY_MAX_WAIT_S", "2")
    queue.extend([_http_error(503)] * 4 + [FakeResp(200, json.dumps(OK_BODY))])
    provider._post_with_retry(b"{}", 1)
    assert sleeps == [0.5, 1.0, 2.0, 2.0]


# ---------------------------------------------------------------------------
# Usage and tracing
# ---------------------------------------------------------------------------


def test_parse_usage_variants() -> None:
    assert parse_usage(None) == {}
    assert parse_usage({"usage": "x"}) == {}
    out = parse_usage(
        {
            "usage": {
                "prompt_tokens": "10",
                "completion_tokens": -4,
                "completion_tokens_details": {"reasoning_tokens": 6},
                "prompt_tokens_details": {"cached_tokens": 2},
                "total_tokens": "bad",
            }
        }
    )
    assert out == {
        "prompt_tokens": 10,
        "completion_tokens": 0,
        "reasoning_tokens": 6,
        "cached_tokens": 2,
        "total_tokens": 10,
    }
    assert parse_usage({"usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 9}})["total_tokens"] == 9


def test_record_usage_accumulates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocp, "_usage_totals", {})
    ocp.record_usage("p", "m", {})
    assert ocp.get_usage_totals() == {}
    ocp.record_usage("p", "m", {"prompt_tokens": 2, "total_tokens": 2})
    ocp.record_usage("p", "m", {"prompt_tokens": 3, "total_tokens": 3})
    totals = ocp.get_usage_totals()["p:m"]
    assert totals["prompt_tokens"] == 5 and totals["calls"] == 2 and totals["completion_tokens"] == 0


class FakeTracer:
    def __init__(self) -> None:
        self.ended: list[dict[str, Any]] = []

    def start_run(self, *_a: Any, **_k: Any) -> str:
        return "run-1"

    def end_run(self, run: Any, **kwargs: Any) -> None:
        self.ended.append({"run": run, **kwargs})


def test_nebius_chat_traces_success_and_error(provider: NebiusProvider, script, monkeypatch) -> None:
    import ghostchimera.observability as obs

    tracer = FakeTracer()
    monkeypatch.setattr(obs, "get_default_tracer", lambda: tracer)
    queue, _, _ = script
    body = {**OK_BODY, "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10, "reasoning_tokens": 1}}
    queue.append(FakeResp(200, json.dumps(body)))
    assert provider.chat("s", "u") == "hello"
    meta = tracer.ended[0]["outputs"]["usage_metadata"]
    assert meta == {"input_tokens": 4, "output_tokens": 6, "total_tokens": 10, "reasoning_tokens": 1}
    queue.append(_http_error(401))
    with pytest.raises(ProviderHTTPError):
        provider.chat("s", "u")
    assert tracer.ended[1]["run"] == "run-1"
    assert tracer.ended[1]["error"].startswith("ProviderHTTPError: ")
