from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot import (
    ChimeraPilotKernel,
    ChimeraScheduler,
    ResourceRegistry,
    TaskKind,
    TaskSpec,
    get_autonomy_profile,
)
from ghostchimera.chimera_pilot.backends import BackendHealth, DeterministicBackend, PythonRuntimeBackend
from ghostchimera.chimera_pilot.backends.desktop_runtime import DesktopRuntimeBackend
from ghostchimera.chimera_pilot.calibration import CalibrationStore, ChimeraCalibrator
from ghostchimera.chimera_pilot.compiler import RuleBasedTaskCompiler
from ghostchimera.chimera_pilot.desktop_policy import DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN
from ghostchimera.chimera_pilot.executor import ChimeraPilotExecutor, PilotRunState
from ghostchimera.chimera_pilot.policy import PilotPolicy
from ghostchimera.chimera_pilot.schema import validate_task
from ghostchimera.safety_layer.production import ProductionGuardrails


class ChimeraPilotTests(unittest.TestCase):
    def test_scheduler_selects_highest_reliability_backend(self) -> None:
        weak = DeterministicBackend("weak", reliability=0.40, latency_ms=1)
        strong = DeterministicBackend("strong", reliability=0.95, latency_ms=1)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="decide")

        decision = ChimeraScheduler([weak, strong]).select_backend(task)

        self.assertEqual(decision.backend.id, "strong")
        self.assertGreater(decision.score, 0)
        self.assertIn("reliability", decision.breakdown)

    def test_unavailable_backend_is_skipped(self) -> None:
        class UnavailableBackend(DeterministicBackend):
            def probe(self) -> BackendHealth:
                return BackendHealth(available=False, reliability=0.0, latency_ms=999)

            def estimate(self, task: TaskSpec) -> BackendHealth:
                return self.probe()

        unavailable = UnavailableBackend("unavailable")
        available = DeterministicBackend("available")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="decide")

        decision = ChimeraScheduler([unavailable, available]).select_backend(task)

        self.assertEqual(decision.backend.id, "available")

    def test_privacy_sensitive_task_prefers_offline_backend(self) -> None:
        offline = DeterministicBackend("offline", reliability=0.80, supports_offline=True)
        network = DeterministicBackend("network", reliability=0.90, supports_offline=False)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="private plan", privacy_level="sensitive")

        decision = ChimeraScheduler([network, offline]).select_backend(task)

        self.assertEqual(decision.backend.id, "offline")
        self.assertIn("offline_privacy_bonus", decision.reasons)

    def test_executor_falls_back_after_backend_failure(self) -> None:
        failing = DeterministicBackend("failing", fail=True, reliability=1.0)
        succeeding = DeterministicBackend("succeeding", output="done", reliability=0.9)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor = ChimeraPilotExecutor(ChimeraScheduler([failing, succeeding]))

        execution = executor.execute(task)

        self.assertTrue(execution.ok)
        self.assertEqual(execution.result.backend_id, "succeeding")
        self.assertEqual(len(execution.attempts), 2)

    def test_executor_feeds_outcomes_back_to_scheduler(self) -> None:
        failing = DeterministicBackend("failing", fail=True, reliability=1.0)
        scheduler = ChimeraScheduler([failing])
        before = scheduler.weights["reliability"]
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        ChimeraPilotExecutor(scheduler).execute(task)
        after = scheduler.weights["reliability"]
        self.assertLess(after, before)

    def test_calibration_updates_reliability(self) -> None:
        backend = DeterministicBackend("calibrated", reliability=0.75)
        store = CalibrationStore()
        calibrator = ChimeraCalibrator([backend], store)

        calibrator.run_once()

        self.assertIn("calibrated", store.records)
        self.assertGreater(store.reliability("calibrated"), 0.0)

    def test_compiler_detects_python_and_quantum_tasks(self) -> None:
        compiler = RuleBasedTaskCompiler()

        python_task = compiler.compile("python: print('hello')")[0]
        quantum_task = compiler.compile("simulate a 4-qubit GHZ quantum circuit")[0]

        self.assertEqual(python_task.kind, TaskKind.PYTHON)
        self.assertEqual(python_task.inputs["code"], "print('hello')")
        self.assertEqual(quantum_task.kind, TaskKind.QUANTUM_SIM)
        self.assertEqual(quantum_task.inputs["qubits"], 4)

    def test_compiler_detects_desktop_control_task(self) -> None:
        compiler = RuleBasedTaskCompiler()
        desktop_task = compiler.compile("click submit button")[0]
        self.assertEqual(desktop_task.kind, TaskKind.DESKTOP_CONTROL)
        self.assertEqual(desktop_task.inputs["action"], "click")
        self.assertEqual(desktop_task.inputs["action_class"], "mutating")
        ok, errors = validate_task(desktop_task.kind, desktop_task.inputs)
        self.assertTrue(ok, errors)

    def test_compiler_marks_destructive_desktop_action(self) -> None:
        compiler = RuleBasedTaskCompiler()
        task = compiler.compile("live desktop: click delete project")[0]

        self.assertEqual(task.kind, TaskKind.DESKTOP_CONTROL)
        self.assertEqual(task.inputs["action_class"], "destructive")

    def test_compiler_desktop_live_and_dryrun_prefix_constraints(self) -> None:
        compiler = RuleBasedTaskCompiler()
        live_task = compiler.compile("live desktop: click submit")[0]
        dryrun_task = compiler.compile("dryrun desktop: click submit")[0]
        self.assertTrue(bool(live_task.constraints.get("live_desktop")))
        self.assertFalse(bool(dryrun_task.constraints.get("live_desktop")))

    def test_compiler_can_build_multi_step_desktop_plan(self) -> None:
        compiler = RuleBasedTaskCompiler()
        task = compiler.compile("live desktop: click app=chrome window=Docs then type hello then press ctrl+s")[0]
        self.assertEqual(task.kind, TaskKind.DESKTOP_CONTROL)
        self.assertEqual(task.inputs["action"], "plan")
        plan = task.inputs["plan"]
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]["target_descriptor"]["app"], "chrome")
        self.assertEqual(plan[0]["target_descriptor"]["window"], "Docs")
        self.assertEqual(plan[1]["action"], "type")
        self.assertEqual(plan[2]["action"], "hotkey")

    def test_desktop_schema_rejects_invalid_action_and_keys_type(self) -> None:
        ok, errors = validate_task(TaskKind.DESKTOP_CONTROL, {"action": "launch_missiles"})
        self.assertFalse(ok)
        self.assertTrue(any("action" in msg for msg in errors))

        ok2, errors2 = validate_task(TaskKind.DESKTOP_CONTROL, {"action": "hotkey", "keys": "ctrl+s"})
        self.assertFalse(ok2)
        self.assertTrue(any("keys" in msg for msg in errors2))

        ok3, errors3 = validate_task(TaskKind.DESKTOP_CONTROL, {"action": "click", "action_class": "unknown"})
        self.assertFalse(ok3)
        self.assertTrue(any("action_class" in msg for msg in errors3))

    def test_python_runtime_backend_executes_real_python_code(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "print(2 + 3)"})
        result = PythonRuntimeBackend().execute(task)

        self.assertTrue(result.ok)
        self.assertEqual(result.output.strip(), "5")

    def test_kernel_status_and_compile_are_json_serializable(self) -> None:
        registry = ResourceRegistry()
        registry.register(DeterministicBackend())
        kernel = ChimeraPilotKernel(registry=registry)

        status = kernel.status()
        compiled = kernel.compile("retrieve memory about project")

        json.dumps(status)
        self.assertEqual(compiled[0].kind, TaskKind.RAG_QUERY)

    def test_policy_rejects_network_when_disabled(self) -> None:
        task = TaskSpec.create(kind=TaskKind.WEB_RESEARCH, objective="research latest models", requires_network=True)

        with self.assertRaises(PermissionError):
            PilotPolicy(allow_network=False).validate(task)

    def test_kernel_desktop_control_requires_opt_in(self) -> None:
        kernel = ChimeraPilotKernel.default(enable_desktop_backend=True, include_deterministic_backend=True)
        with self.assertRaises(PermissionError):
            kernel.run("click submit")

        allowed = ChimeraPilotKernel.default(
            enable_desktop_backend=True,
            allow_desktop_control=True,
            ghost_mode="possess",
            include_deterministic_backend=True,
        )
        execution = allowed.run("click submit")[0]
        self.assertTrue(execution.ok)

    def test_kernel_desktop_control_requires_possess_mode(self) -> None:
        kernel = ChimeraPilotKernel.default(
            enable_desktop_backend=True,
            allow_desktop_control=True,
            ghost_mode="haunt",
            include_deterministic_backend=True,
        )
        with self.assertRaises(PermissionError):
            kernel.run("click submit")

    def test_policy_blocks_destructive_desktop_class_by_default(self) -> None:
        policy = PilotPolicy(allow_desktop_control=True, ghost_mode="possess")
        task = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="live desktop: click delete project",
            inputs={"action": "click", "target": "delete project", "action_class": "destructive"},
            constraints={"live_desktop": True},
        )

        with self.assertRaises(PermissionError) as ctx:
            policy.validate(task)

        self.assertIn("destructive", str(ctx.exception))

    def test_policy_can_allow_destructive_desktop_class_explicitly(self) -> None:
        policy = PilotPolicy(
            allow_desktop_control=True,
            ghost_mode="possess",
            allowed_desktop_action_classes=("read_only", "mutating", "destructive"),
        )
        task = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="live desktop: click delete project",
            inputs={"action": "click", "target": "delete project", "action_class": "destructive"},
            constraints={"live_desktop": True},
        )

        with self.assertRaises(PermissionError) as ctx:
            policy.validate(task)

        self.assertIn("confirmation token", str(ctx.exception))

        confirmed = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="live desktop: click delete project",
            inputs={"action": "click", "target": "delete project", "action_class": "destructive"},
            constraints={
                "live_desktop": True,
                "confirmation_token": DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN,
            },
        )
        policy.validate(confirmed)

    def test_policy_enforces_desktop_app_allowlist_and_denylist(self) -> None:
        policy = PilotPolicy(
            allow_desktop_control=True,
            ghost_mode="possess",
            allowed_desktop_apps=("chrome",),
            denied_desktop_windows=("admin",),
        )
        allowed = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="click app=chrome window=Docs",
            inputs={"action": "click", "target": "app=chrome window=Docs"},
        )
        policy.validate(allowed)

        blocked_app = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="click app=terminal window=Docs",
            inputs={"action": "click", "target": "app=terminal window=Docs"},
        )
        with self.assertRaises(PermissionError):
            policy.validate(blocked_app)

        blocked_window = TaskSpec.create(
            kind=TaskKind.DESKTOP_CONTROL,
            objective="click app=chrome window=Admin",
            inputs={"action": "click", "target": "app=chrome window=Admin"},
        )
        with self.assertRaises(PermissionError):
            policy.validate(blocked_window)

    def test_kernel_can_register_live_desktop_backend(self) -> None:
        kernel = ChimeraPilotKernel.default(
            enable_desktop_backend=True,
            enable_live_desktop=True,
            allow_desktop_control=True,
            ghost_mode="possess",
        )
        status = kernel.status()
        desktop = next(item for item in status["backends"] if item["id"] == "desktop.runtime")
        self.assertTrue(desktop["available"])
        self.assertEqual(desktop["metadata"]["max_live_actions"], 25)
        self.assertEqual(desktop["metadata"]["max_session_seconds"], 300.0)

    def test_scheduler_weights_can_be_updated(self) -> None:
        backend = DeterministicBackend("d", reliability=0.9)
        scheduler = ChimeraScheduler([backend])
        scheduler.set_weights({"reliability": 0.5})
        self.assertEqual(scheduler.weights["reliability"], 0.5)

    def test_scheduler_adapts_from_outcomes(self) -> None:
        backend = DeterministicBackend("d", reliability=0.9)
        scheduler = ChimeraScheduler([backend])
        base = scheduler.weights["reliability"]
        scheduler.adapt_from_outcome(backend_id="d", success=False, latency_ms=1500)
        self.assertLess(scheduler.weights["reliability"], base)

    def test_scheduler_can_disable_adaptation(self) -> None:
        backend = DeterministicBackend("d", reliability=0.9)
        scheduler = ChimeraScheduler([backend])
        scheduler.set_adaptation_enabled(False)
        base = scheduler.weights["reliability"]
        scheduler.adapt_from_outcome(backend_id="d", success=False, latency_ms=1500)
        self.assertEqual(scheduler.weights["reliability"], base)

    def test_scheduler_save_and_load_weights(self) -> None:
        backend = DeterministicBackend("d", reliability=0.9)
        scheduler = ChimeraScheduler([backend])
        scheduler.set_weights({"reliability": 0.42})
        with tempfile.TemporaryDirectory(prefix="ghostchimera-scheduler-") as tmp:
            path = Path(tmp) / "weights.json"
            scheduler.save_weights(str(path))
            other = ChimeraScheduler([backend])
            loaded = other.load_weights(str(path))
        self.assertEqual(loaded["reliability"], 0.42)

    def test_scheduler_strategy_selector(self) -> None:
        backends = [
            DeterministicBackend("a", reliability=0.8),
            DeterministicBackend("b", reliability=0.7),
            DeterministicBackend("c", reliability=0.9),
        ]
        scheduler = ChimeraScheduler(backends, autonomy_profile=get_autonomy_profile("generalist"))
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="reason")
        self.assertEqual(scheduler.select_strategy(task), "fallback_chain")
        self.assertEqual(scheduler.select_strategy(task, uncertainty=0.8), "moa")
        self.assertEqual(scheduler.select_strategy(task, historical_success_rate=0.2), "parallel")



class ChimeraPilotReleaseHardeningTests(unittest.TestCase):
    def test_kernel_rejects_python_execution_by_default(self) -> None:
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)

        with self.assertRaises(PermissionError):
            kernel.run("python: print(2 + 3)")

    def test_kernel_can_opt_in_to_python_execution(self) -> None:
        kernel = ChimeraPilotKernel.default(allow_python_execution=True)

        execution = kernel.run("python: print(2 + 3)")[0]

        self.assertTrue(execution.ok)
        self.assertEqual(str(execution.result.output).strip(), "5")

    def test_python_runtime_rejects_unsafe_python_calls(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "open('/etc/passwd').read()"})

        result = PythonRuntimeBackend().execute(task)

        self.assertFalse(result.ok)
        self.assertIn("not allowed", result.error or "")

    def test_policy_rejects_unsafe_python_fragment(self) -> None:
        task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python", inputs={"code": "import subprocess\nsubprocess.run(['echo', 'x'])"})

        with self.assertRaises(PermissionError):
            PilotPolicy(allow_python_execution=True).validate(task)

    def test_pilot_cli_status_exposes_desktop_backend_and_ghost_mode(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ghostchimera.chimera_pilot.cli",
                "status",
                "--include-deterministic-backend",
                "--enable-desktop-backend",
                "--allow-desktop-control",
                "--desktop-action-class",
                "read_only",
                "--desktop-action-class",
                "mutating",
                "--desktop-allow-app",
                "chrome",
                "--desktop-deny-window",
                "Admin",
                "--ghost-mode",
                "possess",
                "--desktop-max-actions",
                "3",
                "--desktop-max-duration-seconds",
                "30",
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        backend_ids = [item["id"] for item in payload["backends"]]
        self.assertIn("desktop.runtime", backend_ids)
        desktop = next(item for item in payload["backends"] if item["id"] == "desktop.runtime")
        self.assertEqual(desktop["metadata"]["max_live_actions"], 3)
        self.assertEqual(desktop["metadata"]["max_session_seconds"], 30.0)
        self.assertEqual(payload["policy"]["ghost_mode"], "possess")
        self.assertEqual(payload["policy"]["allowed_desktop_action_classes"], ["read_only", "mutating"])
        self.assertEqual(payload["policy"]["allowed_desktop_apps"], ["chrome"])
        self.assertEqual(payload["policy"]["denied_desktop_windows"], ["Admin"])

    def test_chimera_pilot_cli_desktop_stop_creates_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-stop-") as tmp:
            stop_path = Path(tmp) / "STOP"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.chimera_pilot.cli",
                    "desktop-stop",
                    "--desktop-kill-switch-path",
                    str(stop_path),
                    "--reason",
                    "test_stop",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(stop_path.exists())
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["path"], str(stop_path))


if __name__ == "__main__":
    unittest.main()


class ChimeraPilotStateTransitionTests(unittest.TestCase):
    def test_executor_emits_committed_transition_on_success(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        profile = get_autonomy_profile("generalist")
        execution = ChimeraPilotExecutor(
            ChimeraScheduler([backend], autonomy_profile=profile),
            policy=PilotPolicy(autonomy_profile=profile),
        ).execute(task)

        self.assertIsNotNone(execution.transitions)
        states = [t.state for t in execution.transitions or []]
        self.assertEqual(states[0], PilotRunState.PLANNED)
        self.assertEqual(states[-1], PilotRunState.COMMITTED)

    def test_executor_emits_failed_transition_on_failure(self) -> None:
        backend = DeterministicBackend("bad", fail=True)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        profile = get_autonomy_profile("generalist")
        execution = ChimeraPilotExecutor(
            ChimeraScheduler([backend], autonomy_profile=profile),
            policy=PilotPolicy(autonomy_profile=profile),
        ).execute(task)

        self.assertIsNotNone(execution.transitions)
        states = [t.state for t in execution.transitions or []]
        self.assertEqual(states[0], PilotRunState.PLANNED)
        self.assertEqual(states[-1], PilotRunState.FAILED)

    def test_executor_emits_run_attempt_checkpoint_ids(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        execution = ChimeraPilotExecutor(ChimeraScheduler([backend])).execute(task)

        self.assertTrue((execution.run_id or "").startswith("run-"))
        self.assertTrue((execution.attempt_id or "").startswith("attempt-"))
        self.assertTrue((execution.checkpoint_id or "").startswith("ckpt-"))
        payload = execution.to_dict()
        self.assertEqual(payload["run_id"], execution.run_id)

    def test_resume_run_reuses_run_and_checkpoint_context(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor = ChimeraPilotExecutor(ChimeraScheduler([backend]))
        resumed = executor.resume_run(task, run_id="run-existing", checkpoint_id="ckpt-existing")

        self.assertEqual(resumed.run_id, "run-existing")
        self.assertEqual(resumed.checkpoint_id, "ckpt-existing")
        details = [t.detail for t in resumed.transitions or []]
        self.assertIn("resumed_from=ckpt-existing", details)

    def test_cancelled_run_short_circuits_execution(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor = ChimeraPilotExecutor(ChimeraScheduler([backend]))
        executor.cancel_run("run-cancelled")

        cancelled = executor.resume_run(task, run_id="run-cancelled", checkpoint_id="ckpt-existing")
        states = [t.state for t in cancelled.transitions or []]
        self.assertEqual(states[-1], PilotRunState.CANCELLED)
        self.assertFalse(cancelled.ok)

    def test_replay_bundle_contains_run_decision_and_transitions(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        task = TaskSpec.create(
            kind=TaskKind.REASONING,
            objective="execute",
            inputs={"prompt": "execute"},
            constraints={"uncertainty": 0.9},
        )
        profile = get_autonomy_profile("generalist")
        execution = ChimeraPilotExecutor(
            ChimeraScheduler([backend], autonomy_profile=profile),
            policy=PilotPolicy(autonomy_profile=profile),
        ).execute(task)

        bundle = execution.to_replay_bundle()
        self.assertIn("run", bundle)
        self.assertIn("decision", bundle)
        self.assertIn("attempts", bundle)
        self.assertIn("transitions", bundle)
        self.assertIn("trace_hash", bundle)
        self.assertTrue(bundle["run"]["run_id"].startswith("run-"))
        self.assertEqual(bundle["run"]["strategy"], "moa")
        self.assertIn("output_hash", bundle["attempts"][0])
        self.assertIn("error_hash", bundle["attempts"][0])

    def test_executor_records_replay_bundle_in_telemetry(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        scheduler = ChimeraScheduler([backend])
        executor = ChimeraPilotExecutor(scheduler)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor.execute(task)
        bundles = executor.telemetry.replay_bundles()
        self.assertEqual(len(bundles), 1)
        self.assertIn("run", bundles[0])

    def test_replay_bundle_includes_desktop_artifacts_and_policy_snapshot(self) -> None:
        class FakePyAutoGui:
            def click(self) -> None:
                return None

            def screenshot(self, path: str | None = None):
                if path:
                    Path(path).write_bytes(b"fake-png")
                return None

        previous = sys.modules.get("pyautogui")
        sys.modules["pyautogui"] = FakePyAutoGui()
        try:
            with tempfile.TemporaryDirectory(prefix="ghostchimera-desktop-replay-") as tmp:
                root = Path(tmp)
                backend = DesktopRuntimeBackend(
                    dry_run=False,
                    action_log_path=str(root / "desktop-actions.jsonl"),
                    screenshot_dir=str(root / "screens"),
                )
                policy = PilotPolicy(allow_desktop_control=True, ghost_mode="possess")
                executor = ChimeraPilotExecutor(ChimeraScheduler([backend]), policy=policy)
                task = TaskSpec.create(
                    kind=TaskKind.DESKTOP_CONTROL,
                    objective="live desktop: click submit",
                    inputs={"action": "click"},
                    constraints={"live_desktop": True},
                )

                execution = executor.execute(task)
                bundle = execution.to_replay_bundle()

                self.assertTrue(execution.ok, execution.result.error)
                self.assertTrue(bundle["policy"]["allow_desktop_control"])
                artifacts = bundle["attempts"][0]["artifacts"]
                self.assertEqual(artifacts["action_log_path"], str(root / "desktop-actions.jsonl"))
                self.assertEqual(set(artifacts["screenshots"]), {"before", "after"})
                self.assertTrue(Path(artifacts["screenshots"]["before"]).exists())
                self.assertIn("policy", execution.to_dict())
                self.assertIn("desktop_trace_id", execution.result.metrics)
        finally:
            if previous is None:
                sys.modules.pop("pyautogui", None)
            else:
                sys.modules["pyautogui"] = previous

    def test_telemetry_export_json_includes_replay_bundles(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        scheduler = ChimeraScheduler([backend])
        executor = ChimeraPilotExecutor(scheduler)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor.execute(task)

        with tempfile.TemporaryDirectory(prefix="ghostchimera-telemetry-") as tmp:
            path = Path(tmp) / "telemetry.json"
            content = executor.telemetry.export_json(str(path))
            payload = json.loads(content)
            self.assertIn("replay_bundles", payload)
            self.assertEqual(len(payload["replay_bundles"]), 1)

    def test_telemetry_export_replay_bundles_file(self) -> None:
        backend = DeterministicBackend("ok", output="done")
        scheduler = ChimeraScheduler([backend])
        executor = ChimeraPilotExecutor(scheduler)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        executor.execute(task)

        with tempfile.TemporaryDirectory(prefix="ghostchimera-replay-") as tmp:
            path = Path(tmp) / "replay.json"
            content = executor.telemetry.export_replay_bundles(str(path))
            payload = json.loads(content)
            self.assertIn("replay_bundles", payload)
            self.assertEqual(len(payload["replay_bundles"]), 1)

    def test_executor_records_terminal_checkpoint(self) -> None:
        class RecordingCheckpointManager:
            def __init__(self) -> None:
                self.descriptions: list[str] = []

            def create_checkpoint(self, description: str, agent=None):
                self.descriptions.append(description)
                return object()

        backend = DeterministicBackend("ok", output="done")
        scheduler = ChimeraScheduler([backend])
        ckpt = RecordingCheckpointManager()
        executor = ChimeraPilotExecutor(scheduler, checkpoint_manager=ckpt)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        execution = executor.execute(task)
        self.assertTrue(execution.ok)
        self.assertEqual(len(ckpt.descriptions), 1)
        self.assertIn("committed:", ckpt.descriptions[0])

    def test_executor_records_outcome_in_outcome_store(self) -> None:
        class RecordingOutcomeStore:
            def __init__(self) -> None:
                self.rows: list[dict] = []

            def record_outcome(self, **kwargs):
                self.rows.append(dict(kwargs))
                return len(self.rows)

        backend = DeterministicBackend("ok", output="done")
        scheduler = ChimeraScheduler([backend])
        store = RecordingOutcomeStore()
        executor = ChimeraPilotExecutor(scheduler, outcome_store=store)
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        execution = executor.execute(task)
        self.assertTrue(execution.ok)
        self.assertEqual(len(store.rows), 1)
        self.assertEqual(store.rows[0]["backend_id"], "ok")

    def test_executor_uses_historical_success_rate_for_strategy(self) -> None:
        class HistoricalOutcomeStore:
            def recent_outcomes(self, limit=100):
                return [
                    {"task_kind": "reasoning", "success": False},
                    {"task_kind": "reasoning", "success": False},
                    {"task_kind": "reasoning", "success": True},
                ]

            def record_outcome(self, **kwargs):
                return 1

        backend = DeterministicBackend("ok", output="done")
        profile = get_autonomy_profile("autonomous")
        scheduler = ChimeraScheduler(
            [backend, DeterministicBackend("ok2", output="done"), DeterministicBackend("ok3", output="done")],
            autonomy_profile=profile,
        )
        executor = ChimeraPilotExecutor(
            scheduler,
            policy=PilotPolicy(autonomy_profile=profile),
            outcome_store=HistoricalOutcomeStore(),
        )
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="execute", inputs={"prompt": "execute"})
        execution = executor.execute(task)
        bundle = execution.to_replay_bundle()
        self.assertEqual(bundle["run"]["strategy"], "parallel")

    def test_production_mode_blocks_python_without_guardrails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-prod-pilot-") as tmp:
            backend = PythonRuntimeBackend(cwd=tmp)
            scheduler = ChimeraScheduler([backend])
            policy = PilotPolicy(
                allow_python_execution=True,
                production_guardrails=ProductionGuardrails(deployment_mode="production"),
            )
            executor = ChimeraPilotExecutor(scheduler, policy=policy)
            task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python: print(1)", inputs={"code": "print(1)"})

            with self.assertRaises(PermissionError) as ctx:
                executor.execute(task)

        self.assertIn("Production mode blocks local Python/test execution", str(ctx.exception))

    def test_production_mode_allows_python_with_guardrails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-prod-pilot-") as tmp:
            backend = PythonRuntimeBackend(cwd=tmp)
            scheduler = ChimeraScheduler([backend])
            policy = PilotPolicy(
                allow_python_execution=True,
                production_guardrails=ProductionGuardrails(
                    deployment_mode="production",
                    external_isolation="container",
                    security_reviewed=True,
                    human_approval_required=True,
                    trusted_inputs_only=True,
                ),
            )
            executor = ChimeraPilotExecutor(scheduler, policy=policy)
            task = TaskSpec.create(kind=TaskKind.PYTHON, objective="python: print(1)", inputs={"code": "print(1)"})

            execution = executor.execute(task)

        self.assertTrue(execution.ok, execution.result.error)
