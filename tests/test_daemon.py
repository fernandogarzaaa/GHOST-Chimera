"""Tests for the always-on daemon: lifecycle, webhooks, cron, restart durability."""

from __future__ import annotations

import sys
import types

# croniter is a hard dependency of cron_scheduler but is not installed in
# this sandbox (no PyPI egress; CI installs it). Shim it for tests.
_croniter_mod = types.ModuleType("croniter")


class _FakeCroniter:
    def __init__(self, expr: str, start: float) -> None:
        self.expr = expr
        self.start = start

    def get_next(self) -> float:
        # "* * * * *" -> next minute; anything else -> one hour out.
        if self.expr.strip() == "* * * * *":
            return self.start + 60 - (self.start % 60)
        return self.start + 3600


_croniter_mod.croniter = _FakeCroniter
sys.modules.setdefault("croniter", _croniter_mod)

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import patch  # noqa: E402

from ghostchimera.chimera_pilot.always_on import daemon as daemon_mod  # noqa: E402
from ghostchimera.chimera_pilot.always_on.daemon import (  # noqa: E402
    Daemon,
    HookDefinition,
    load_daemon_identity,
)
from ghostchimera.trust_runtime import TrustRuntimeStore  # noqa: E402


class FakeAIAgent:
    """Stand-in for AIAgent: runs tools, returns canned text, no model calls."""

    instances: list = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.ran_with: tuple | None = None
        FakeAIAgent.instances.append(self)

    def run(self, objective: str, tools: list[dict[str, Any]] | None = None) -> str:
        self.ran_with = (objective, list(tools or []))
        tool_names = [t.get("name", "") for t in (tools or []) if isinstance(t, dict)]
        return f"fake-result tools={','.join(tool_names)}"


def _daemon(state_dir: str, **kwargs: Any) -> Daemon:
    kwargs.setdefault("hook_secret", "test-secret")
    kwargs.setdefault("poll_interval", 60)
    return Daemon(state_dir=state_dir, **kwargs)


class _FakeAgentMixin:
    """Keeps the FakeAIAgent patch active for the whole test."""

    def _patch_agent(self) -> None:
        self._agent_patcher = patch.object(daemon_mod, "AIAgent", FakeAIAgent)
        self._agent_patcher.start()
        self.addCleanup(self._agent_patcher.stop)
        FakeAIAgent.instances.clear()


class IdentityTests(unittest.TestCase):
    def test_fallback_identity_when_store_missing(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "identity_store" in name:
                raise ImportError("nope")
            return real_import(name, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory(prefix="ghost-id-") as tmp,
            patch("builtins.__import__", side_effect=fake_import),
        ):
            identity = load_daemon_identity(tmp)
        self.assertEqual(identity["name"], "ghost-chimera")
        self.assertTrue(identity["ephemeral"])

    def test_real_identity_store_used_when_available(self) -> None:
        import sys
        import types

        # Simulate PR #107's identity_store being present.
        mod = types.ModuleType("ghostchimera.identity_store")

        class FakeIdentity:
            def to_dict(self):
                return {"id": "ghost-abc123", "name": "ghost-chimera"}

        class FakeStore:
            def __init__(self, state_dir):
                self.state_dir = state_dir
                self.calls = 0

            def load_or_create(self):
                self.calls += 1
                return FakeIdentity()

        mod.IdentityStore = FakeStore
        with (
            tempfile.TemporaryDirectory(prefix="ghost-id-") as tmp,
            patch.dict(sys.modules, {"ghostchimera.identity_store": mod}),
        ):
            identity = load_daemon_identity(tmp)
        self.assertEqual(identity["id"], "ghost-abc123")
        self.assertNotIn("ephemeral", identity)

    def test_identity_stable_across_daemon_restarts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghost-id-") as tmp:
            first = _daemon(tmp).identity["id"]
            second = _daemon(tmp).identity["id"]
        self.assertEqual(first, second)


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-daemon-")
        self.state_dir = str(Path(self._dir.name) / "state")
        FakeAIAgent.instances.clear()

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _daemon_threads(self) -> set[str]:
        return {t.name for t in threading.enumerate() if t.is_alive()}

    def test_start_writes_pid_and_stop_removes_it(self) -> None:
        d = _daemon(self.state_dir)
        before = self._daemon_threads()
        d.start()
        try:
            self.assertTrue(d.pid_file.is_file())
            self.assertEqual(Daemon.read_pid(self.state_dir), os.getpid())
            health = d.probe()
            self.assertTrue(health.ok)
            self.assertEqual(health.state, "running")
        finally:
            d.stop()
        self.assertFalse(d.pid_file.exists())
        # No orphaned daemon worker threads left behind.
        time.sleep(0.2)
        leaked = self._daemon_threads() - before - {threading.current_thread().name}
        daemon_workers = {n for n in leaked if n.startswith(("daemon-agent", "gateway", "cron"))}
        self.assertEqual(daemon_workers, set())

    def test_start_is_idempotent(self) -> None:
        d = _daemon(self.state_dir)
        try:
            d.start()
            d.start()  # second start is a no-op
            self.assertTrue(d.probe().ok)
        finally:
            d.stop()

    def test_stop_without_start_is_safe(self) -> None:
        d = _daemon(self.state_dir)
        d.stop()  # must not raise
        self.assertFalse(d.pid_file.exists())

    def test_status_snapshot(self) -> None:
        d = _daemon(self.state_dir)
        try:
            d.start()
            snap = d.status()
            self.assertEqual(snap["service_id"], "ghost_daemon")
            self.assertIn("jobs", snap)
            self.assertIn("gateway_server", snap["details"]["services"])
            self.assertIn("cron_scheduler", snap["details"]["services"])
        finally:
            d.stop()


class WebhookTests(_FakeAgentMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._patch_agent()
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-hook-")
        self.state_dir = str(Path(self._dir.name) / "state")
        FakeAIAgent.instances.clear()
        self.daemon = _daemon(self.state_dir)
        self.daemon.register_hook(HookDefinition(name="deploy", source="generic"))

    def tearDown(self) -> None:
        self.daemon.stop()
        self._dir.cleanup()

    def _ctx(self, name: str, secret: str | None, body: dict) -> dict:
        headers = {}
        if secret is not None:
            headers["x-hook-secret"] = secret
        return {
            "method": "POST",
            "path": f"/hooks/{name}",
            "headers": headers,
            "body": json.dumps(body),
            "query": {},
        }

    def test_unknown_hook_returns_404(self) -> None:
        resp = self.daemon._handle_hook(self._ctx("nope", "test-secret", {}))
        self.assertEqual(resp.status, 404)

    def test_bad_secret_returns_403(self) -> None:
        resp = self.daemon._handle_hook(self._ctx("deploy", "wrong", {}))
        self.assertEqual(resp.status, 403)

    def test_missing_secret_returns_403(self) -> None:
        resp = self.daemon._handle_hook(self._ctx("deploy", None, {}))
        self.assertEqual(resp.status, 403)

    def test_hooks_disabled_without_secret(self) -> None:
        d = _daemon(self.state_dir, hook_secret="")
        try:
            d.register_hook(HookDefinition(name="deploy", source="generic"))
            resp = d._handle_hook(self._ctx("deploy", "anything", {}))
            self.assertEqual(resp.status, 403)
        finally:
            d.stop()

    def test_valid_hook_dispatches_agent_run(self) -> None:
        result = self.daemon._handle_hook(self._ctx("deploy", "test-secret", {"text": "ship it"}))
        self.assertTrue(result["ok"])
        self.assertIn("receipt_id", result)
        # The agent task runs async; wait for the fake agent to be invoked.
        deadline = time.time() + 10
        while not FakeAIAgent.instances and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(FakeAIAgent.instances, "hook agent task never ran")
        agent = FakeAIAgent.instances[-1]
        self.assertIn("ship it", agent.ran_with[0])
        # Result recorded in the trust store.
        runs = TrustRuntimeStore(self.state_dir).list_runs()["runs"]
        hook_runs = [r for r in runs if r.get("source") == "webhook:deploy"]
        self.assertTrue(hook_runs, "hook run not recorded in trust store")

    def test_secret_comparison_is_constant_time(self) -> None:
        with patch.object(daemon_mod.hmac, "compare_digest") as mock_cmp:
            mock_cmp.return_value = True
            self.daemon._check_hook_secret(self._ctx("deploy", "test-secret", {}))
        mock_cmp.assert_called_once()

    def test_malformed_json_returns_400(self) -> None:
        ctx = self._ctx("deploy", "test-secret", {})
        ctx["body"] = "{not json"
        resp = self.daemon._handle_hook(ctx)
        self.assertEqual(resp.status, 400)


class CronTests(_FakeAgentMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._patch_agent()
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-cron-")
        self.state_dir = str(Path(self._dir.name) / "state")
        FakeAIAgent.instances.clear()

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_cron_job_executes_tool_using_agent_run(self) -> None:
        tools_used: list = []

        def tool_provider():
            return [{"name": "read_file", "handler": lambda **kw: "contents"}]

        d = Daemon(state_dir=self.state_dir, hook_secret="s", tool_provider=tool_provider)
        try:
            job = d.scheduler.add_job(
                name="nightly",
                cron_expression="* * * * *",
                objective="summarize inbox",
            )
            job.next_run = time.time() - 1  # force due
            results = d.scheduler.tick()
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].success)
            self.assertEqual(results[0].job_id, job.id)
            # The agent actually ran with the provided tools.
            self.assertTrue(FakeAIAgent.instances)
            agent = FakeAIAgent.instances[-1]
            self.assertIn("summarize inbox", agent.ran_with[0])
            tools_used.extend(agent.ran_with[1])
            self.assertEqual([t["name"] for t in tools_used], ["read_file"])
            # Result recorded in the trust store.
            runs = TrustRuntimeStore(self.state_dir).list_runs()["runs"]
            cron_runs = [r for r in runs if r.get("source") == "cron:nightly"]
            self.assertTrue(cron_runs)
        finally:
            d.stop()

    def test_cron_job_failure_records_error_result(self) -> None:
        class BoomAgent(FakeAIAgent):
            def run(self, objective, tools=None):
                raise RuntimeError("model down")

        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            with patch.object(daemon_mod, "AIAgent", BoomAgent):
                job = d.scheduler.add_job(name="failing", cron_expression="* * * * *", objective="x")
                result = d._execute_cron_job(job)
            self.assertFalse(result.success)
            self.assertIn("model down", result.error)
        finally:
            d.stop()


class RestartDurabilityTests(unittest.TestCase):
    def test_kill9_style_restart_preserves_identity_and_sessions(self) -> None:
        with (
            patch.object(daemon_mod, "AIAgent", FakeAIAgent),
            tempfile.TemporaryDirectory(prefix="ghost-restart-") as tmp,
        ):
            state_dir = str(Path(tmp) / "state")
            d1 = Daemon(state_dir=state_dir, hook_secret="s")
            identity_before = d1.identity["id"]
            # Simulate PR #111's session API with a file-backed fake so the
            # daemon's snapshot path is exercised deterministically.
            sessions_file = Path(state_dir) / "sessions.json"

            def fake_save(payload):
                data = json.loads(sessions_file.read_text()) if sessions_file.exists() else {}
                data[payload["session_id"]] = payload
                sessions_file.write_text(json.dumps(data))
                return {"ok": True, "session_id": payload["session_id"]}

            d1.store.save_session = fake_save
            d1._persist_session_snapshot("webhook:test", "do thing", "done")
            self.assertTrue(sessions_file.is_file())
            # Simulate kill -9: drop every reference without stop().
            del d1
            d2 = Daemon(state_dir=state_dir, hook_secret="s")
            try:
                self.assertEqual(d2.identity["id"], identity_before)
                data = json.loads(sessions_file.read_text())
                snapshots = [p for p in data.values() if p.get("source") == "webhook:test"]
                self.assertEqual(len(snapshots), 1)
                self.assertEqual(snapshots[0]["identity_id"], identity_before)
                self.assertIn("do thing", snapshots[0]["objective"])
            finally:
                d2.stop()

    def test_snapshot_persists_via_session_api(self) -> None:
        # With PR #111 merged, the store always has save_session: the
        # daemon must persist the snapshot, not silently skip it.
        with tempfile.TemporaryDirectory(prefix="ghost-restart-") as tmp:
            state_dir = str(Path(tmp) / "state")
            d = Daemon(state_dir=state_dir, hook_secret="s")
            try:
                self.assertTrue(callable(getattr(d.store, "save_session", None)))
                d._persist_session_snapshot("webhook:test", "do thing", "done")  # must not raise
                stored = d.store.get_session("daemon-" + __import__("hashlib").sha256(b"webhook:test").hexdigest()[:12])
                self.assertIsNotNone(stored)
            finally:
                d.stop()


class CliTests(unittest.TestCase):
    def test_daemon_status_not_running(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "status", "state_dir": tmp, "poll_interval": 60})()
            with patch("builtins.print") as mock_print:
                code = _run_daemon_cli(args)
        self.assertEqual(code, 0)
        payload = json.loads(mock_print.call_args[0][0])
        self.assertFalse(payload["running"])

    def test_daemon_stop_when_not_running(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "stop", "state_dir": tmp, "poll_interval": 60})()
            with patch("builtins.print"):
                code = _run_daemon_cli(args)
        self.assertEqual(code, 0)

    def test_daemon_start_spawns_detached_child(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "start", "state_dir": tmp, "poll_interval": 60})()
            fake_proc = type("P", (), {"pid": 4242})()
            pid_file = Path(tmp) / "daemon.pid"
            with (
                patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
                patch("builtins.print") as mock_print,
            ):
                # Simulate the child writing its PID file after spawn.
                def _write_pid(*a, **k):
                    pid_file.write_text("9999")
                    return fake_proc

                mock_popen.side_effect = _write_pid
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            payload = json.loads(mock_print.call_args[0][0])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["pid"], 9999)
            cmd = mock_popen.call_args[0][0]
            self.assertIn("daemon", cmd)
            self.assertIn("run", cmd)

    def test_daemon_start_refuses_when_already_running(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            Path(tmp, "daemon.pid").write_text(str(os.getpid()))
            args = type("A", (), {"action": "start", "state_dir": tmp, "poll_interval": 60})()
            with patch("builtins.print") as mock_print:
                code = _run_daemon_cli(args)
            self.assertEqual(code, 1)
            payload = json.loads(mock_print.call_args[0][0])
            self.assertFalse(payload["ok"])

    def test_daemon_run_calls_run_forever(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "run", "state_dir": tmp, "poll_interval": 60})()
            with patch.object(daemon_mod.Daemon, "run_forever") as mock_run:
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            mock_run.assert_called_once()

    def test_daemon_start_reports_spawn_details_exactly(self) -> None:
        import sys as _sys

        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "start", "state_dir": tmp, "poll_interval": 60})()
            fake_proc = type("P", (), {"pid": 4242})()
            pid_file = Path(tmp) / "daemon.pid"
            with (
                patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
                patch("builtins.print") as mock_print,
            ):
                mock_popen.side_effect = lambda *a, **k: (pid_file.write_text("9999"), fake_proc)[1]
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            expected_cmd = [
                _sys.executable,
                "-m",
                "ghostchimera",
                "daemon",
                "run",
                "--state-dir",
                tmp,
                "--poll-interval",
                "60",
            ]
            self.assertEqual(mock_popen.call_args[0][0], expected_cmd)
            kwargs = mock_popen.call_args[1]
            import subprocess as _sp

            self.assertIs(kwargs["stdin"], _sp.DEVNULL)
            self.assertIs(kwargs["stdout"], _sp.DEVNULL)
            self.assertIs(kwargs["stderr"], _sp.DEVNULL)
            self.assertTrue(kwargs["start_new_session"])
            expected = json.dumps({"ok": True, "pid": 9999, "launcher_pid": 4242}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_start_fails_when_child_never_writes_pid(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "start", "state_dir": tmp, "poll_interval": 60})()
            fake_proc = type("P", (), {"pid": 4242})()
            with (
                patch("subprocess.Popen", return_value=fake_proc),
                patch.object(daemon_mod.Daemon, "read_pid", return_value=None),
                patch("time.sleep") as mock_sleep,
                patch("builtins.print") as mock_print,
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 1)
            self.assertEqual(mock_sleep.call_count, 50)
            for call in mock_sleep.call_args_list:
                self.assertEqual(call[0][0], 0.1)
            expected = json.dumps({"ok": False, "pid": None, "launcher_pid": 4242}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_start_already_running_exact_output(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            Path(tmp, "daemon.pid").write_text(str(os.getpid()))
            args = type("A", (), {"action": "start", "state_dir": tmp, "poll_interval": 60})()
            with patch("builtins.print") as mock_print:
                code = _run_daemon_cli(args)
            self.assertEqual(code, 1)
            expected = json.dumps(
                {"ok": False, "error": f"daemon already running (pid {os.getpid()})"},
                indent=2,
            )
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_stop_kills_running_daemon(self) -> None:
        import signal as _signal

        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "stop", "state_dir": tmp, "poll_interval": 60})()
            with (
                patch.object(daemon_mod.Daemon, "read_pid", return_value=4242),
                patch.object(daemon_mod.Daemon, "pid_alive", side_effect=[True, False, False]),
                patch("os.kill") as mock_kill,
                patch("time.sleep") as mock_sleep,
                patch("builtins.print") as mock_print,
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            mock_kill.assert_called_once_with(4242, _signal.SIGTERM)
            self.assertEqual(mock_sleep.call_count, 1)
            expected = json.dumps({"ok": True, "stopped": True, "pid": 4242}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_stop_timeout_when_daemon_wont_die(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "stop", "state_dir": tmp, "poll_interval": 60})()
            with (
                patch.object(daemon_mod.Daemon, "read_pid", return_value=4242),
                patch.object(daemon_mod.Daemon, "pid_alive", return_value=True),
                patch("os.kill"),
                patch("time.sleep") as mock_sleep,
                patch("builtins.print") as mock_print,
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 1)
            self.assertEqual(mock_sleep.call_count, 100)
            for call in mock_sleep.call_args_list:
                self.assertEqual(call[0][0], 0.1)
            expected = json.dumps({"ok": True, "stopped": False, "pid": 4242}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_stop_not_running_exact_output(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "stop", "state_dir": tmp, "poll_interval": 60})()
            with patch("builtins.print") as mock_print:
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            expected = json.dumps({"ok": True, "stopped": False, "reason": "not running"}, indent=2)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_status_running_exact_output(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "status", "state_dir": tmp, "poll_interval": 60})()
            with (
                patch.object(daemon_mod.Daemon, "read_pid", return_value=4242),
                patch.object(daemon_mod.Daemon, "pid_alive", return_value=True),
                patch("builtins.print") as mock_print,
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            expected = json.dumps({"ok": True, "running": True, "pid": 4242}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_status_not_running_exact_output(self) -> None:
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            args = type("A", (), {"action": "status", "state_dir": tmp, "poll_interval": 60})()
            with (
                patch.object(daemon_mod.Daemon, "read_pid", return_value=None),
                patch("builtins.print") as mock_print,
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            expected = json.dumps({"ok": True, "running": False, "pid": None}, indent=2, sort_keys=True)
            self.assertEqual(mock_print.call_args[0][0], expected)

    def test_daemon_state_dir_falls_back_to_config(self) -> None:
        import ghostchimera.control_plane.cli as cli_mod
        from ghostchimera.control_plane.cli import _run_daemon_cli

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            cfg = type("C", (), {"state_dir": Path(tmp)})()
            args = type("A", (), {"action": "run", "state_dir": "", "poll_interval": 30})()
            seen: dict = {}
            with (
                patch.object(cli_mod.GhostChimeraConfig, "from_env", return_value=cfg),
                patch.object(daemon_mod.Daemon, "run_forever"),
                patch.object(
                    daemon_mod.Daemon,
                    "__init__",
                    lambda self, **kw: seen.update(kw),
                ),
            ):
                code = _run_daemon_cli(args)
            self.assertEqual(code, 0)
            self.assertEqual(seen["state_dir"], str(Path(tmp)))
            self.assertEqual(seen["poll_interval"], 30)

    def test_main_dispatches_daemon_status(self) -> None:
        from ghostchimera.control_plane.cli import _main

        with tempfile.TemporaryDirectory(prefix="ghost-cli-") as tmp:
            with patch("builtins.print") as mock_print:
                code = _main(["daemon", "status", "--state-dir", tmp])
            self.assertEqual(code, 0)
            payload = json.loads(mock_print.call_args[0][0])
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["running"])


if __name__ == "__main__":
    unittest.main()


class SnapshotTests(_FakeAgentMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._patch_agent()
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-snap-")
        self.state_dir = str(Path(self._dir.name) / "state")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _daemon_with_fake_store(self) -> tuple[Daemon, list]:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        saved: list = []
        d.store.save_session = lambda payload: saved.append(payload) or {"ok": True}  # type: ignore[method-assign]
        return d, saved

    def test_run_agent_task_persists_snapshot(self) -> None:
        d, saved = self._daemon_with_fake_store()
        try:
            d._run_agent_task("do thing", source="webhook:test", metadata={})
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["source"], "webhook:test")
            self.assertEqual(saved[0]["identity_id"], d.identity["id"])
        finally:
            d.stop()

    def test_snapshot_truncates_long_results_at_2000(self) -> None:
        d, saved = self._daemon_with_fake_store()
        try:
            long_result = "x" * 2500
            d._persist_session_snapshot("s", "obj", long_result)
            self.assertEqual(len(saved[0]["result"]), 2000)
            self.assertEqual(len(saved[0]["messages"][1]["content"]), 2000)
        finally:
            d.stop()

    def test_snapshot_failure_is_swallowed_and_logged(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")

        def boom(payload):
            raise RuntimeError("disk gone")

        d.store.save_session = boom  # type: ignore[method-assign]
        try:
            with self.assertLogs("ghostchimera.daemon", level="ERROR"):
                d._persist_session_snapshot("s", "obj", "res")  # must not raise
        finally:
            d.stop()

    def test_run_agent_task_records_error_step_on_agent_failure(self) -> None:
        class BoomAgent(FakeAIAgent):
            def run(self, objective, tools=None):
                raise RuntimeError("model down")

        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            with patch.object(daemon_mod, "AIAgent", BoomAgent), self.assertRaises(RuntimeError):
                d._run_agent_task("do thing", source="cron:test", metadata={})
            runs = TrustRuntimeStore(self.state_dir).list_runs()["runs"]
            cron_runs = [r for r in runs if r.get("source") == "cron:test"]
            self.assertTrue(cron_runs)
        finally:
            d.stop()


class DaemonHardeningTests(_FakeAgentMixin, unittest.TestCase):
    """Kill the mutation survivors in daemon.py."""

    def setUp(self) -> None:
        self._patch_agent()
        self._dir = tempfile.TemporaryDirectory(prefix="ghost-hard-")
        self.state_dir = str(Path(self._dir.name) / "state")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_module_defaults_exact(self) -> None:
        self.assertEqual(daemon_mod.DEFAULT_MAX_WORKERS, 4)
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            self.assertEqual(d.poll_interval, 60)
            self.assertEqual(d._executor._max_workers, 4)
        finally:
            d.stop()

    def test_init_creates_nested_state_dir(self) -> None:
        nested = str(Path(self.state_dir) / "a" / "b")
        d = Daemon(state_dir=nested, hook_secret="s")
        try:
            self.assertTrue(Path(nested).is_dir())
        finally:
            d.stop()

    def test_init_uses_explicit_config(self) -> None:
        from ghostchimera.config import GhostChimeraConfig

        config = GhostChimeraConfig.from_env()
        d = Daemon(state_dir=self.state_dir, config=config, hook_secret="s")
        try:
            self.assertIs(d.config, config)
        finally:
            d.stop()

    def test_start_raises_when_service_fails(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        with (
            patch.object(d.registry, "start_all", return_value={"gateway_server": False}),
            self.assertRaises(RuntimeError),
        ):
            d.start()
        d.stop()  # safe even after failed start

    def test_remove_pid_file_logs_on_oserror(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            with (
                patch.object(Path, "unlink", side_effect=OSError("denied")),
                self.assertLogs("ghostchimera.daemon", level="WARNING"),
            ):
                d._remove_pid_file()  # must not raise
        finally:
            d.stop()

    def test_read_pid_returns_none_on_garbage(self) -> None:
        Path(self.state_dir).mkdir(parents=True, exist_ok=True)
        (Path(self.state_dir) / "daemon.pid").write_text("notanumber")
        self.assertIsNone(Daemon.read_pid(self.state_dir))
        self.assertIsNone(Daemon.read_pid(str(Path(self.state_dir) / "missing")))

    def test_pid_alive_false_on_oserror(self) -> None:
        with patch.object(daemon_mod.os, "kill", side_effect=OSError("nope")):
            self.assertFalse(Daemon.pid_alive(999999))
        self.assertTrue(Daemon.pid_alive(os.getpid()))

    def test_pid_alive_uses_signal_zero(self) -> None:
        with patch.object(daemon_mod.os, "kill", return_value=None) as mock_kill:
            Daemon.pid_alive(1234)
        mock_kill.assert_called_once_with(1234, 0)

    def test_stop_shuts_down_executor_and_sets_flag(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        d.start()
        with patch.object(d.registry, "stop_all", wraps=d.registry.stop_all) as mock_stop:
            d.stop()
            mock_stop.assert_called_once()
        self.assertFalse(d._started)
        self.assertTrue(d._shutdown.is_set())

    def test_run_forever_starts_and_waits(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        with (
            patch.object(d, "start") as mock_start,
            patch.object(d._shutdown, "wait") as mock_wait,
            patch.object(daemon_mod.signal, "signal") as mock_signal,
        ):
            d.run_forever()
        mock_start.assert_called_once()
        self.assertEqual(mock_signal.call_count, 2)
        mock_wait.assert_called_once()
        d.stop()

    def test_handle_signal_stops_daemon(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        d.start()
        with patch.object(d, "stop", wraps=d.stop) as mock_stop:
            d._handle_signal(15, None)
        mock_stop.assert_called_once()

    def test_probe_false_when_stopped(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            d.start()
            self.assertTrue(d.probe().ok)
        finally:
            d.stop()
        self.assertFalse(d.probe().ok)

    def test_hook_route_registered_with_prefix(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            route = d.gateway.routes.find("POST", "/hooks/deploy")
            self.assertIsNotNone(route)
            self.assertTrue(route.prefix)
        finally:
            d.stop()

    def test_hook_non_dict_json_body_returns_400(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            d.register_hook(HookDefinition(name="h", source="generic"))
            ctx = {
                "method": "POST",
                "path": "/hooks/h",
                "headers": {"x-hook-secret": "s"},
                "body": "[1, 2]",
                "query": {},
            }
            resp = d._handle_hook(ctx)
            self.assertEqual(resp.status, 400)
            body = json.loads(resp.body)
            self.assertFalse(body["ok"])
        finally:
            d.stop()

    def test_hook_secret_via_query_param(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            d.register_hook(HookDefinition(name="h", source="generic"))
            ctx = {
                "method": "POST",
                "path": "/hooks/h",
                "headers": {},
                "body": "{}",
                "query": {"secret": "s"},
            }
            result = d._handle_hook(ctx)
            self.assertTrue(result["ok"])
        finally:
            d.stop()
        # Drain the async task.
        deadline = time.time() + 10
        while not FakeAIAgent.instances and time.time() < deadline:
            time.sleep(0.05)

    def test_check_hook_secret_returns_bool(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            self.assertIs(d._check_hook_secret({"headers": {}, "query": {}}), False)
            self.assertIs(d._check_hook_secret({"headers": {"x-hook-secret": "s"}, "query": {}}), True)
        finally:
            d.stop()

    def test_event_summary_uses_subject_and_truncates(self) -> None:
        class Ev:
            event_id = "e1"
            event_type = "note.created"
            payload = {"subject": "y" * 300}

        summary = Daemon._event_summary(Ev(), {})
        self.assertEqual(len(summary), 200)
        self.assertEqual(Daemon._event_summary(None, {}), "payload")
        self.assertEqual(Daemon._event_summary(None, {"text": "hi"}), "hi")

    def test_run_hook_task_failure_is_logged_not_raised(self) -> None:
        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            hook = HookDefinition(name="h", source="generic")
            with (
                patch.object(d, "_run_agent_task", side_effect=RuntimeError("boom")),
                self.assertLogs("ghostchimera.daemon", level="ERROR"),
            ):
                d._run_hook_task("r1", hook, "obj", None, {})  # must not raise
        finally:
            d.stop()

    def test_cron_job_output_truncated(self) -> None:
        class LongAgent(FakeAIAgent):
            def run(self, objective, tools=None):
                self.ran_with = (objective, list(tools or []))
                return "z" * 5000

        d = Daemon(state_dir=self.state_dir, hook_secret="s")
        try:
            with patch.object(daemon_mod, "AIAgent", LongAgent):
                job = d.scheduler.add_job(name="j", cron_expression="* * * * *", objective="x")
                result = d._execute_cron_job(job)
            self.assertTrue(result.success)
            self.assertEqual(len(result.output), 3000)
        finally:
            d.stop()
