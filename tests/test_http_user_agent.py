"""Every outbound HTTP request carries ``User-Agent: GHOST-Chimera/<version>``.

Groq (and some CDNs) answer HTTP 403 when the header is missing, so this is
a correctness requirement, not cosmetics.
"""

from __future__ import annotations

import ast
import io
import json
import pathlib
import urllib.request

import pytest

import ghostchimera
from ghostchimera.http_identity import USER_AGENT, ensure_user_agent, with_user_agent

PACKAGE_ROOT = pathlib.Path(ghostchimera.__file__).parent


def test_user_agent_names_package_and_version() -> None:
    expected = f"GHOST-Chimera/{ghostchimera.__version__}"
    assert expected == USER_AGENT


def test_ensure_user_agent_wraps_url_strings() -> None:
    req = ensure_user_agent("https://example.com/x")
    assert isinstance(req, urllib.request.Request)
    assert req.get_header("User-agent") == USER_AGENT


def test_ensure_user_agent_keeps_an_explicit_agent() -> None:
    req = urllib.request.Request("https://example.com", headers={"User-Agent": "Mozilla/5.0 custom"})
    assert ensure_user_agent(req).get_header("User-agent") == "Mozilla/5.0 custom"


def test_with_user_agent_is_case_insensitive_and_copies() -> None:
    original = {"user-agent": "x"}
    assert with_user_agent(original) == {"user-agent": "x"}
    added = with_user_agent({"Accept": "a"})
    assert added["User-Agent"] == USER_AGENT
    assert with_user_agent(None) == {"User-Agent": USER_AGENT}


class _FakeResponse(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_openai_compatible_provider_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Groq 403 regression: the chat request must carry the header."""
    from ghostchimera.model_layer.openai_compatible_providers import GroqProvider

    seen: list[urllib.request.Request] = []

    def fake_urlopen(req, *args, **kwargs):
        seen.append(req)
        body = {"choices": [{"message": {"content": "pong"}}]}
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert GroqProvider().chat("sys", "ping") == "pong"
    assert seen and seen[0].get_header("User-agent") == USER_AGENT


def test_ssrf_dispatcher_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.safety_layer import ssrf

    seen: list[urllib.request.Request] = []

    class _Opener:
        def open(self, req, timeout=None):
            seen.append(req)
            return _FakeResponse(b"ok")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Opener())
    dispatcher = ssrf.NetworkDispatcher(ssrf.SSRFPolicy())
    monkeypatch.setattr(dispatcher.policy, "is_permitted", lambda url: (True, ""))
    result = dispatcher.fetch("https://example.com/")
    assert result.status_code == 200
    assert seen[0].get_header("User-agent") == USER_AGENT


def _urlopen_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "urlopen":
            yield node


def test_every_urlopen_in_the_package_goes_through_ensure_user_agent() -> None:
    """Static guard so a new HTTP call site cannot silently drop the header."""
    offenders: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _urlopen_calls(tree):
            first = call.args[0] if call.args else None
            ok = (
                isinstance(first, ast.Call)
                and isinstance(first.func, ast.Name)
                and first.func.id == "ensure_user_agent"
            )
            if not ok:
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{call.lineno}")
    assert offenders == [], f"urlopen() without ensure_user_agent(): {offenders}"
