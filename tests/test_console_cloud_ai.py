"""Cloud AI (Nebius x NVIDIA) console integration + operator tools wiring.

Covers /api/hackathon/* and /api/tools/* routes, secret hygiene, the
Stealth service cloud-enhancement attachment, and the frontend ids.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors import console_routes, stealth_service
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [21001]

_ENV_KEYS = ("NEBIUS_API_KEY", "TAVILY_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")


def _server(tmp_path: Path) -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    # The gateway auto-moves to the next free port when the preferred one is
    # taken (or in TIME_WAIT); always use the port it actually bound.
    server._test_http_port = server.http_port  # type: ignore[attr-defined]
    return server


def _base(server: GatewayServer) -> str:
    return f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


@pytest.fixture()
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("TAVILY_MCP_MODE", raising=False)


def _assert_no_secrets(body: dict, secrets: tuple[str, ...] = ()) -> None:
    """Secret *values* must never appear in a response.

    Env var *names* (e.g. NEBIUS_API_KEY) intentionally appear in setup_hint
    guidance; that is help text, not a leak.
    """
    dumped = json.dumps(body)
    for secret in secrets:
        assert secret not in dumped, f"secret value leaked into response: {secret[:8]}..."


# ── /api/hackathon/status ─────────────────────────────────────────────────


def test_hackathon_status_zero_keys(tmp_path: Path, no_keys: None) -> None:
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/hackathon/status")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert body["nebius"]["configured"] is False
    assert body["tavily"]["configured"] is False
    assert body["langsmith"]["configured"] is False
    # Zero-key state must still explain how to enable each integration.
    assert body["nebius"]["setup_hint"]
    assert body["tavily"]["setup_hint"]
    assert body["langsmith"]["setup_hint"]
    # Model ids come from the real module constants.
    assert "Nemotron" in body["nemotron"]["understand_model"] or "nvidia" in body["nemotron"]["understand_model"]
    _assert_no_secrets(body)


def test_hackathon_status_never_leaks_key_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "FAKE-TAVILY-SECRET-9f8e7d6c")
    monkeypatch.setenv("LANGSMITH_API_KEY", "FAKE-LS-SECRET-1a2b3c4d")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    # Keep the test hermetic: a fake key must never trigger a real search.
    monkeypatch.setattr(console_routes, "_hackathon_grounding", lambda base: None)
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/hackathon/status")
        _, reason_body = _post(_base(server) + "/api/hackathon/reason", {"summary": "x"})
        _, ground_body = _post(_base(server) + "/api/hackathon/ground", {"query": "x"})
    finally:
        server.stop()
    assert code == 200
    assert body["tavily"]["configured"] is True
    assert body["langsmith"]["configured"] is True
    for payload in (body, reason_body, ground_body):
        _assert_no_secrets(payload, ("FAKE-TAVILY-SECRET-9f8e7d6c", "FAKE-LS-SECRET-1a2b3c4d"))


# ── /api/hackathon/reason and /api/hackathon/ground ───────────────────────


def test_hackathon_reason_needs_setup_without_keys(tmp_path: Path, no_keys: None) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/hackathon/reason", {"summary": "user opened pricing"})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is False
    assert "NEBIUS_API_KEY" in body["error"] or "not configured" in body["error"].lower()
    _assert_no_secrets(body)


def test_hackathon_reason_rejects_empty_summary(tmp_path: Path, no_keys: None) -> None:
    server = _server(tmp_path)
    try:
        _, body = _post(_base(server) + "/api/hackathon/reason", {"summary": "  "})
    finally:
        server.stop()
    assert body["ok"] is False


def test_hackathon_ground_needs_setup_without_keys(tmp_path: Path, no_keys: None) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/hackathon/ground", {"query": "nvidia nemotron"})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is False
    assert "TAVILY_API_KEY" in body["error"] or "not configured" in body["error"].lower()
    _assert_no_secrets(body)


def _fake_reasoner() -> SimpleNamespace:
    insight = {
        "intent": "research",
        "confidence": 0.9,
        "risk_flags": ["new_domain"],
        "suggested_workflow": "deep_research",
        "rationale": "User is comparing options.",
        "model": "nvidia/nemotron-nano-9b-v2",
        "grounded_with_web": False,
    }
    return SimpleNamespace(
        understand=lambda event: dict(insight),
        understand_model="nvidia/nemotron-nano-9b-v2",
        reasoning_model="nvidia/nemotron-nano-9b-v2",
    )


def test_hackathon_reason_with_fake_reasoner(tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console_routes, "_hackathon_reasoner", lambda base: _fake_reasoner())
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/hackathon/reason", {"summary": "user opened pricing"})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    insight = body["insight"]
    assert insight["intent"] == "research"
    assert insight["confidence"] == 0.9
    assert insight["risk_flags"] == ["new_domain"]
    _assert_no_secrets(body)


def test_hackathon_ground_with_fake_grounding(tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        search=lambda query, max_results=5: [
            {"title": "Nemotron 3", "url": "https://example.com/nemotron", "snippet": "Reasoning model."},
        ],
        _last_transport="rest",
    )
    monkeypatch.setattr(console_routes, "_hackathon_grounding", lambda base: fake)
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/hackathon/ground", {"query": "nemotron"})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert body["transport"] == "rest"
    assert len(body["results"]) == 1
    assert body["results"][0]["title"] == "Nemotron 3"
    assert body["results"][0]["url"] == "https://example.com/nemotron"
    _assert_no_secrets(body)


# ── /api/hackathon/traces ─────────────────────────────────────────────────


def _fake_loop_with_traces() -> SimpleNamespace:
    intervention = SimpleNamespace(
        state="intervened",
        workflow="deep_research",
        reason="High-value research moment.",
        provenance={
            "trace": {
                "nemotron": {
                    "intent": "research",
                    "confidence": 0.88,
                    "risk_flags": ["new_domain"],
                    "suggested_workflow": "deep_research",
                    "rationale": "User opened three pricing pages.",
                    "model": "nvidia/nemotron-nano-9b-v2",
                    "grounded_with_web": True,
                },
                "web_grounding": {
                    "query": "pricing pages",
                    "transport": "rest",
                    "results": [
                        {"title": "Pricing", "url": "https://example.com/pricing", "snippet": "Plans."},
                    ],
                },
            },
            "predictions": ["deep_research", "summarize"],
        },
    )
    return SimpleNamespace(
        reasoner=_fake_reasoner(),
        grounding=SimpleNamespace(),
        interventions={"evt-1": intervention},
    )


def test_hackathon_traces_sanitized(tmp_path: Path, no_keys: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        console_routes,
        "_stealth_loop_with_authority",
        lambda base: _fake_loop_with_traces(),
    )
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/hackathon/traces")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert len(body["traces"]) == 1
    trace = body["traces"][0]
    assert trace["workflow"] == "deep_research"
    assert trace["nemotron"]["intent"] == "research"
    assert trace["nemotron"]["confidence"] == 0.88
    assert trace["web_grounding"]["query"] == "pricing pages"
    assert trace["web_grounding"]["results"][0]["url"] == "https://example.com/pricing"
    assert trace["local_predictions"] == ["deep_research", "summarize"]
    _assert_no_secrets(body)


def test_hackathon_traces_empty_loop(tmp_path: Path, no_keys: None) -> None:
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/hackathon/traces")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert isinstance(body["traces"], list)


# ── stealth_service cloud attachment ──────────────────────────────────────


def test_stealth_service_zero_keys_attaches_nothing(tmp_path: Path, no_keys: None) -> None:
    reasoner, grounding = stealth_service._attach_cloud_enhancements()
    assert reasoner is None
    assert grounding is None


def test_stealth_service_loop_receives_enhancements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel_reasoner, sentinel_grounding = object(), object()
    monkeypatch.setattr(
        stealth_service,
        "_attach_cloud_enhancements",
        lambda: (sentinel_reasoner, sentinel_grounding),
    )
    loop = stealth_service.get_service_loop(tmp_path / "cloud-loop")
    assert loop._reasoner is sentinel_reasoner
    assert loop._grounding is sentinel_grounding


# ── /api/tools/* ───────────────────────────────────────────────────────────


def test_tools_catalog(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/tools/catalog")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    ids = [tool["id"] for tool in body["tools"]]
    for expected in (
        "pilot-status",
        "pilot-calibrate",
        "autonomy-profiles",
        "model-profiles",
        "runtime-warmup",
        "desktop-stop",
        "ux-audit",
        "saas-status",
        "worker-status",
        "evals-run",
        "production-gaps",
        "context-compress",
    ):
        assert expected in ids, f"tool missing from catalog: {expected}"
    evals_tool = next(tool for tool in body["tools"] if tool["id"] == "evals-run")
    suite_input = next(inp for inp in evals_tool["inputs"] if inp["name"] == "suite")
    assert suite_input["type"] == "select"
    assert suite_input["options"], "eval suite options must not be empty"
    desktop = next(tool for tool in body["tools"] if tool["id"] == "desktop-stop")
    assert desktop["confirm"], "destructive desktop-stop needs a confirmation prompt"
    for tool in body["tools"]:
        assert tool["title"] and tool["description"], f"tool {tool['id']} needs a title and description"


def test_tools_run_unknown_rejected(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/tools/run", {"tool": "rm -rf /"})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is False
    assert "Unknown tool" in body["error"]


def test_tools_run_pilot_status(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/tools/run", {"tool": "pilot-status", "args": {}})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert body["tool"] == "pilot-status"
    assert isinstance(body["result"], dict)


def test_tools_run_ux_audit(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/tools/run", {"tool": "ux-audit", "args": {}})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert "scorecard" in body["result"]


def test_tools_run_context_compress(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(
            _base(server) + "/api/tools/run",
            {"tool": "context-compress", "args": {"text": "alpha beta gamma", "budget_tokens": 100}},
        )
        _, empty_body = _post(_base(server) + "/api/tools/run", {"tool": "context-compress", "args": {"text": "  "}})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert empty_body["ok"] is False


def test_tools_run_evals_rejects_unknown_suite(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _post(_base(server) + "/api/tools/run", {"tool": "evals-run", "args": {"suite": "nope"}})
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is False
    assert "Unknown eval suite" in body["error"]


def test_tools_run_desktop_stop(tmp_path: Path) -> None:
    target = tmp_path / "killswitch.json"
    server = _server(tmp_path)
    try:
        code, body = _post(
            _base(server) + "/api/tools/run",
            {"tool": "desktop-stop", "args": {"path": str(target), "reason": "console_tool_test"}},
        )
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    assert body["result"]["path"] == str(target)
    payload = json.loads(target.read_text())
    assert payload["reason"] == "console_tool_test"


def test_tools_run_saas_and_worker_status(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        _, saas_body = _post(_base(server) + "/api/tools/run", {"tool": "saas-status", "args": {}})
        _, worker_body = _post(_base(server) + "/api/tools/run", {"tool": "worker-status", "args": {}})
    finally:
        server.stop()
    assert saas_body["ok"] is True
    assert worker_body["ok"] is True


def test_tools_run_autonomy_and_model_profiles(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        _, auto_body = _post(_base(server) + "/api/tools/run", {"tool": "autonomy-profiles", "args": {}})
        _, model_body = _post(_base(server) + "/api/tools/run", {"tool": "model-profiles", "args": {}})
    finally:
        server.stop()
    assert auto_body["ok"] is True
    assert auto_body["result"]["profiles"], "autonomy profiles must not be empty"
    assert model_body["ok"] is True
    assert model_body["result"]["profiles"], "model profiles must not be empty"


# ── frontend wiring ───────────────────────────────────────────────────────


def test_frontend_cloud_and_tools_ids_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "ghostchimera" / "control_plane" / "static" / "index.html").read_text()
    js = (root / "ghostchimera" / "control_plane" / "static" / "app.js").read_text()
    for tab in ('data-tab="cloud"', 'data-tab="tools"'):
        assert tab in html, f"missing tab button: {tab}"
    for element_id in (
        "tab-cloud",
        "tab-tools",
        "cloudStatusCards",
        "cloudReasonOut",
        "cloudGroundOut",
        "cloudTracesOut",
        "cloudTraceOut",
        "toolsGrid",
    ):
        assert f'id="{element_id}"' in html, f"missing frontend element: {element_id}"
    for route in (
        "/api/hackathon/status",
        "/api/hackathon/reason",
        "/api/hackathon/ground",
        "/api/hackathon/traces",
        "/api/tools/catalog",
        "/api/tools/run",
    ):
        assert route in js, f"frontend never calls {route}"
