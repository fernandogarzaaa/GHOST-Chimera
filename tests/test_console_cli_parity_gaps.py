"""CLI-parity gap closure for the browser console operator tools.

Covers the 14 tools added to close the remaining CLI-to-console gaps:
workspace-clear, minimind-architectures, minimind-log-failure,
minimind-beta-vision, local-model-profiles, local-model-check,
local-model-guide, cognition-handoff-verify, doctor, eve-scan,
pilot-compile, pilot-runtime-specialization, parallel-run, parallel-batch.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from ghostchimera.chimera_pilot.gateway_server import GatewayServer
from ghostchimera.config import GhostChimeraConfig
from ghostchimera.connectors.console_routes import register_connector_routes

_PORT = [22001]


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
        with urllib.request.urlopen(req, timeout=60) as resp:
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
    "pilot-compile",
    "pilot-runtime-specialization",
    "parallel-run",
    "parallel-batch",
    "local-model-profiles",
    "local-model-check",
    "local-model-guide",
    "minimind-architectures",
    "minimind-log-failure",
    "minimind-beta-vision",
    "cognition-handoff-verify",
    "doctor",
    "eve-scan",
    "workspace-clear",
)


def test_tools_catalog_includes_parity_gap_tools(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        code, body = _get_json(_base(server) + "/api/tools/catalog")
    finally:
        server.stop()
    assert code == 200
    assert body["ok"] is True
    ids = [tool["id"] for tool in body["tools"]]
    for expected in _NEW_TOOLS:
        assert expected in ids, f"tool missing from catalog: {expected}"
    for tool in body["tools"]:
        assert tool["title"] and tool["description"], f"tool {tool['id']} needs a title and description"
    destructive = {"workspace-clear", "parallel-run", "parallel-batch"}
    for tool_id in destructive:
        tool = next(t for t in body["tools"] if t["id"] == tool_id)
        assert tool.get("confirm"), f"destructive tool {tool_id} needs a confirmation prompt"


def test_tool_doctor(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "doctor", {"production": "false"})
    finally:
        server.stop()
    assert body["ok"] is True
    result = body["result"]
    assert isinstance(result["checks"], list) and result["checks"], "doctor must return checks"
    for check in result["checks"]:
        assert {"label", "ok", "hint"} <= set(check)
    assert result["passed"] + result["warned"] + result["errors"] == len(result["checks"])


def test_tool_local_model_profiles(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "local-model-profiles")
    finally:
        server.stop()
    assert body["ok"] is True
    result = body["result"]
    assert result["ok"] is True
    assert result["profiles"], "must list at least one profile"
    assert "resources" in result


def test_tool_local_model_check(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "local-model-check", {"profile": "tiny"})
    finally:
        server.stop()
    assert body["ok"] is True
    result = body["result"]
    assert result["ok"] is True
    assert result["profile"]["profile"] == "tiny"
    assert result["recommendations"], "check must produce recommendations"


def test_tool_local_model_guide(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        good = _run_tool(server, "local-model-guide", {"profile": "tiny"})
        bad = _run_tool(server, "local-model-guide", {"profile": "no-such-profile"})
    finally:
        server.stop()
    assert good["ok"] is True
    assert good["result"]["ok"] is True
    assert good["result"]["steps"], "guide must list install steps"
    assert bad["ok"] is True
    assert bad["result"]["ok"] is False
    assert "Available" in bad["result"]["error"]


def test_tool_minimind_architectures(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "minimind-architectures")
    finally:
        server.stop()
    assert body["ok"] is True
    assert body["result"]["architectures"], "must list at least one architecture"
    assert body["result"]["sources"], "must include source metadata"


def test_tool_minimind_log_failure(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        missing = _run_tool(server, "minimind-log-failure", {"prompt": "only prompt"})
        assert missing["ok"] is False
        assert "prompt and response" in missing["error"]
        logged = _run_tool(
            server,
            "minimind-log-failure",
            {"prompt": "test prompt", "response": "test response", "confidence": "0.1", "threshold": "0.5"},
        )
    finally:
        server.stop()
    assert logged["ok"] is True
    assert logged["result"]["ok"] is True
    assert logged["result"]["logged"] is True
    log_file = tmp_path / "minimind" / "low_confidence.jsonl"
    assert log_file.exists(), "failure log must be written under the console state dir"
    assert "test prompt" in log_file.read_text(encoding="utf-8")


def test_tool_cognition_handoff_verify_validation(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "cognition-handoff-verify", {})
    finally:
        server.stop()
    assert body["ok"] is False
    assert "handoff JSON" in body["error"]


def test_tool_eve_scan(tmp_path: Path) -> None:
    scan_root = tmp_path / "scanme"
    scan_root.mkdir()
    (scan_root / "clean.py").write_text("print('hello')\n", encoding="utf-8")
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "eve-scan", {"root": str(scan_root), "strict": "true"})
    finally:
        server.stop()
    assert body["ok"] is True
    result = body["result"]
    assert "root" in result and "findings" in result and "files_scanned" in result


def test_tool_pilot_compile(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        missing = _run_tool(server, "pilot-compile", {})
        assert missing["ok"] is False
        body = _run_tool(server, "pilot-compile", {"objective": "Summarize this repository's README"})
    finally:
        server.stop()
    assert body["ok"] is True
    tasks = body["result"]
    assert isinstance(tasks, list) and tasks, "compile must return planned tasks"
    for task in tasks:
        assert {"id", "kind", "objective"} <= set(task)


def test_tool_pilot_runtime_specialization(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        missing = _run_tool(server, "pilot-runtime-specialization", {})
        assert missing["ok"] is False
        body = _run_tool(
            server,
            "pilot-runtime-specialization",
            {"prompt": "hello", "profile": "tiny", "estimated_output_tokens": "64"},
        )
    finally:
        server.stop()
    assert body["ok"] is True
    assert isinstance(body["result"], dict) and body["result"], "plan must be a non-empty dict"


def test_tool_workspace_clear(tmp_path: Path) -> None:
    from ghostchimera.cognition_layer.workspace_state import OperatorWorkspaceStore

    store = OperatorWorkspaceStore(state_dir=tmp_path)
    store.add_evidence("test", "some evidence", confidence=0.9)
    assert store.snapshot()["working_memory"]["evidence"], "precondition: workspace has evidence"
    server = _server(tmp_path)
    try:
        body = _run_tool(server, "workspace-clear", {})
    finally:
        server.stop()
    assert body["ok"] is True
    cleared = OperatorWorkspaceStore(state_dir=tmp_path).snapshot()
    assert cleared["working_memory"]["evidence"] == []
    assert cleared["ok"] is True


def test_tool_parallel_validation(tmp_path: Path) -> None:
    server = _server(tmp_path)
    try:
        run_empty = _run_tool(server, "parallel-run", {"objectives": "   "})
        batch_empty = _run_tool(server, "parallel-batch", {"jsonl": ""})
    finally:
        server.stop()
    assert run_empty["ok"] is False
    assert "one objective per line" in run_empty["error"]
    assert batch_empty["ok"] is False
    assert "JSONL" in batch_empty["error"]


def test_doctor_cli_still_prints() -> None:
    from ghostchimera.control_plane.doctor import doctor_checks, run_doctor

    payload = doctor_checks()
    assert payload["checks"], "doctor_checks must return the check suite as data"
    assert run_doctor() in (0, 1)


def test_local_model_cli_still_prints(capsys: pytest.CaptureFixture[str]) -> None:
    from ghostchimera.control_plane.local_model_cli import run_local_model_cli

    assert run_local_model_cli("profiles") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["profiles"]

    assert run_local_model_cli("check", profile="tiny") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["recommendations"]

    assert run_local_model_cli("guide", profile="tiny") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["steps"]

    assert run_local_model_cli("guide", profile="no-such-profile") == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
