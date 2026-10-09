"""Final CLI-to-console parity sweep for the browser console operator tools.

Covers the last two CLI surfaces found unwired in the independent final
sweep: the deterministic harness runner (``harness run --cases``) and the
policy management subcommands (``ghost policy list/scan/set``). Wired as
four new operator tools: harness-run, policy-list, policy-scan, policy-set.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [23001]


def _server(tmp_path: Path) -> GatewayServer:
    _PORT[0] += 2
    ws_port, http_port = _PORT[0], _PORT[0] + 1
    config = GhostChimeraConfig.from_env()
    config = replace(config, state_dir=tmp_path, memory_db=tmp_path / "m.sqlite3", audit_file=tmp_path / "a.json")
    server = GatewayServer(host="127.0.0.1", port=ws_port, http_port=http_port, config=config)
    register_connector_routes(server, tmp_path)
    server.start()
    server._test_http_port = server.http_port  # type: ignore[attr-defined]
    return server


def _base(server: GatewayServer) -> str:
    return f"http://127.0.0.1:{server._test_http_port}"  # type: ignore[attr-defined]


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", 0) or 0
        try:
            return code, json.loads(exc.read().decode())
        except Exception:
            return code, {}


def _run_tool(server: GatewayServer, tool: str, args: dict | None = None) -> dict:
    code, body = _post(_base(server) + "/api/tools/run", {"tool": tool, "args": args or {}})
    assert code == 200, f"HTTP {code} for tool {tool}: {body}"
    return body


_NEW_TOOLS = (
    "harness-run",
    "policy-list",
    "policy-scan",
    "policy-set",
)


def test_tools_catalog_includes_final_parity_tools(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/tools/catalog")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    by_id = {tool["id"]: tool for tool in body["tools"]}
    for expected in _NEW_TOOLS:
        assert expected in by_id, f"tool missing from catalog: {expected}"
    for tool_id in _NEW_TOOLS:
        tool = by_id[tool_id]
        assert tool["title"] and tool["description"], f"tool {tool_id} needs title and description"
    harness = by_id["harness-run"]
    input_names = [inp["name"] for inp in harness["inputs"]]
    assert "cases_json" in input_names
    assert any(inp.get("type") == "textarea" for inp in harness["inputs"] if inp["name"] == "cases_json")
    policy_set = by_id["policy-set"]
    task_type = next(inp for inp in policy_set["inputs"] if inp["name"] == "task_type")
    assert task_type["type"] == "select"
    assert "coding" in task_type["options"]


def test_tool_harness_run_json_array(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(
            server,
            "harness-run",
            {"cases_json": json.dumps([{"id": "smoke-1", "objective": "summarize: hello"}])},
        )
    finally:
        server.stop()
    assert body["ok"] is True, body
    result = body["result"]
    assert result["total"] == 1
    assert result["passed"] + result["failed"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == "smoke-1"
    assert Path(result["output_dir"]).exists()


def test_tool_harness_run_jsonl(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(
            server,
            "harness-run",
            {
                "cases_json": '{"id": "a", "objective": "summarize: one"}\n{"id": "b", "objective": "summarize: two"}\n',
            },
        )
    finally:
        server.stop()
    assert body["ok"] is True, body
    assert body["result"]["total"] == 2


def test_tool_harness_run_rejects_empty_and_overflow(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        empty = _run_tool(server, "harness-run", {"cases_json": "   "})
        assert empty["ok"] is False
        assert "cases" in empty["error"].lower()
        big = [{"id": f"c{i}", "objective": "summarize: x"} for i in range(26)]
        overflow = _run_tool(server, "harness-run", {"cases_json": json.dumps(big)})
        assert overflow["ok"] is False
        assert "25" in overflow["error"]
    finally:
        server.stop()


def test_tool_policy_list(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "policy-list")
    finally:
        server.stop()
    assert body["ok"] is True, body
    policies = body["result"]["policies"]
    assert isinstance(policies, list) and policies, "must list at least one policy"
    ids = [p["id"] for p in policies]
    assert "strict_factual" in ids
    for p in policies:
        assert p["description"], f"policy {p['id']} needs a description"


def test_tool_policy_scan(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "policy-scan", {"text": "The capital of France is Paris."})
        missing = _run_tool(server, "policy-scan", {"text": "   "})
    finally:
        server.stop()
    assert body["ok"] is True, body
    result = body["result"]
    assert result["policy_id"] == "strict_factual"
    assert "overall_risk" in result
    assert missing["ok"] is False


def test_tool_policy_set(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "policy-set", {"task_type": "coding"})
        default = _run_tool(server, "policy-set", {})
    finally:
        server.stop()
    assert body["ok"] is True, body
    assert body["result"] == {"task_type": "coding", "recommended_policy": "code_review"}
    assert default["result"]["recommended_policy"] == "strict_factual"
