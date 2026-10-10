"""Tests for README truth-audit hardening fixes.

Covers:
- ghost ask CLI journals runs to the Trust Runtime
- Standing Orders CLI lifecycle (create/list/enable/disable/run)
- Real replay of journaled runs (TrustRuntimeStore.replay_run)
- OpenClawAdapter.install() returns a real configuration snippet
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from ghostchimera.stealth.hosts import OpenClawAdapter
from ghostchimera.trust_runtime import TrustRuntimeStore


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


def _run_trust_cli(argv: list[str], state_dir: Path) -> dict:
    from ghostchimera.control_plane import cli as cli_module

    args = mock.MagicMock()
    args.state_dir = str(state_dir)
    args.trust_command = argv[0]
    args.run_id = argv[1] if len(argv) > 1 else "latest"
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_module._run_trust_cli(args)
    assert rc == 0
    return json.loads(out.getvalue())


def test_replay_run_performs_real_execution(state_dir: Path) -> None:
    store = TrustRuntimeStore(state_dir)
    run = store.create_run("what is 2 + 3", source="ask-cli")
    store.record_step(run["run_id"], step_type="task_executed", status="ok", output_payload={"ok": True})

    result = store.replay_run(run["run_id"])

    assert result["ok"] is True
    assert result["execution_performed"] is True
    assert result["replayed_from"] == run["run_id"]
    assert "replay_run_id" in result
    assert result["comparison"]["replay_ok"] >= 1
    replay = store.get_run(result["replay_run_id"])
    assert replay["ok"] is True
    step_types = {s.get("step_type") for s in replay["steps"]}
    assert "replay_execution" in step_types
    assert "replay_comparison" in step_types


def test_replay_run_unknown_run_id(state_dir: Path) -> None:
    store = TrustRuntimeStore(state_dir)
    result = store.replay_run("nonexistent-run-id")
    assert result["ok"] is False
    assert "error" in result


def test_replay_run_honest_failure_for_unfulfillable(state_dir: Path) -> None:
    store = TrustRuntimeStore(state_dir)
    run = store.create_run("write a poem about the ocean", source="ask-cli")

    result = store.replay_run(run["run_id"])

    assert result["ok"] is True
    assert result["execution_performed"] is True
    assert result["comparison"]["replay_ok"] == 0
    assert result["comparison"]["outcome_match"] is False


def test_replay_run_with_custom_executor(state_dir: Path) -> None:
    store = TrustRuntimeStore(state_dir)
    run = store.create_run("custom objective", source="test")

    result = store.replay_run(
        run["run_id"],
        executor=lambda objective: [{"ok": True, "task_id": "t1", "backend_id": "custom", "output": "done"}],
    )

    assert result["ok"] is True
    assert result["executions"][0]["backend_id"] == "custom"
    assert result["comparison"]["replay_ok"] == 1


def test_openclaw_adapter_install_returns_config() -> None:
    adapter = OpenClawAdapter(loop=mock.MagicMock())
    result = adapter.install()

    assert result["installed"] is True
    assert "openclaw" in result["host"]
    hooks = result["context_engine_snippet"]["lifecycle_hooks"]
    assert "ingest" in hooks
    assert "assemble" in hooks
    assert "after-turn" in hooks
    assert all("ghost-hook" in str(cfg.get("command", "")) for cfg in hooks.values())
    assert result["capabilities"]["observes_outcome"] is True
    assert result["capabilities"]["learns"] is True


def test_ask_cli_journals_trust_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.control_plane import cli as cli_module

    state_dir = tmp_path / "askstate"
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(state_dir))

    args = mock.MagicMock()
    args.objective = ["what", "is", "2", "+", "2"]
    args.json = True
    args.state_dir = ""
    args.autonomy_level = "supervised"

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_module._run_ask_cli(args)
    assert rc == 0

    payload = json.loads(out.getvalue())
    assert isinstance(payload, list)
    assert payload[0].get("trust_run_id")

    journal = state_dir / "trust_runtime" / "runs" / f"{payload[0]['trust_run_id']}.jsonl"
    assert journal.exists()
    steps = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    step_types = {s.get("step_type") for s in steps}
    assert "run_created" in step_types
    assert "task_executed" in step_types


def test_standing_orders_cli_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.control_plane import cli as cli_module

    state_dir = tmp_path / "sostate"
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(state_dir))

    def _run(action: str, order_id: str = "", **kwargs: str) -> dict:
        args = mock.MagicMock()
        args.action = action
        args.order_id = order_id
        args.title = kwargs.get("title", "")
        args.objective = kwargs.get("objective", "")
        args.scope = kwargs.get("scope", "")
        args.state_dir = ""
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_module._run_standing_orders_cli(args)
        assert rc == 0
        return json.loads(out.getvalue())

    created = _run("create", title="Morning brief", objective="Summarize inbox", scope="general")
    assert created["ok"] is True
    order_id = created["order"]["id"]

    listed = _run("list")
    assert any(o["id"] == order_id for o in listed["orders"])

    enabled = _run("enable", order_id)
    assert enabled["ok"] is True

    preview = _run("run", order_id)
    assert preview["ok"] is True

    disabled = _run("disable", order_id)
    assert disabled["ok"] is True


def test_standing_orders_cli_create_requires_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostchimera.control_plane import cli as cli_module

    state_dir = tmp_path / "sostate2"
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(state_dir))

    args = mock.MagicMock()
    args.action = "create"
    args.title = ""
    args.objective = ""
    args.scope = ""
    args.state_dir = ""
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_module._run_standing_orders_cli(args)
    assert rc == 1
    assert json.loads(out.getvalue())["ok"] is False


def test_trust_replay_cli_subcommand(state_dir: Path) -> None:
    store = TrustRuntimeStore(state_dir)
    run = store.create_run("what is 1 + 1", source="ask-cli")

    result = _run_trust_cli(["replay", run["run_id"]], state_dir)

    assert result["ok"] is True
    assert result["execution_performed"] is True
    assert result["replayed_from"] == run["run_id"]
