from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ghostchimera.chimera_pilot import ChimeraPilotKernel, ChimeraScheduler, TaskKind, TaskSpec, get_autonomy_profile
from ghostchimera.chimera_pilot.agent_loop import AIAgent
from ghostchimera.chimera_pilot.autonomy_jobs import AutonomyJobRunner
from ghostchimera.chimera_pilot.backends import DeterministicBackend
from ghostchimera.control_plane.config import get_autonomy_config, save_config
from ghostchimera.model_layer.minimind_lifecycle import MiniMindLifecycle


class AutonomyProfileTests(unittest.TestCase):
    @staticmethod
    def _sandboxed_cli_env(base: Path) -> dict[str, str]:
        (base / "home").mkdir(parents=True, exist_ok=True)
        (base / ".ghostchimera-state").mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["GHOSTCHIMERA_STATE_DIR"] = str(base / ".ghostchimera-state")
        env["HOME"] = str(base / "home")
        return env

    def test_aliases_map_to_generalist_without_changing_positioning(self) -> None:
        profile = get_autonomy_profile("sgi")

        self.assertEqual(profile.name, "generalist")
        self.assertIn("not AGI", profile.positioning)
        self.assertFalse(profile.allow_self_training)

    def test_scheduler_strategy_is_capped_by_profile(self) -> None:
        backends = [
            DeterministicBackend("a", reliability=0.8),
            DeterministicBackend("b", reliability=0.7),
            DeterministicBackend("c", reliability=0.9),
        ]
        scheduler = ChimeraScheduler(backends, autonomy_profile=get_autonomy_profile("assist"))
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="reason", constraints={"uncertainty": 0.9})

        self.assertEqual(scheduler.select_strategy(task, uncertainty=0.9), "single")

    def test_generalist_profile_allows_moa_strategy(self) -> None:
        backends = [
            DeterministicBackend("a", reliability=0.8),
            DeterministicBackend("b", reliability=0.7),
            DeterministicBackend("c", reliability=0.9),
        ]
        scheduler = ChimeraScheduler(backends, autonomy_profile=get_autonomy_profile("generalist"))
        task = TaskSpec.create(kind=TaskKind.REASONING, objective="reason")

        self.assertEqual(scheduler.select_strategy(task, uncertainty=0.9), "moa")

    def test_kernel_status_exposes_active_autonomy_profile(self) -> None:
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True, autonomy_level="autonomous")
        status = kernel.status()

        self.assertEqual(status["autonomy"]["name"], "autonomous")
        self.assertEqual(status["policy"]["autonomy"]["name"], "autonomous")

    def test_agent_loop_uses_autonomy_tool_round_budget(self) -> None:
        agent = AIAgent(autonomy_profile=get_autonomy_profile("assist"))

        self.assertEqual(agent.max_tool_rounds, 6)

    def test_chimera_pilot_cli_lists_autonomy_profiles(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "ghostchimera.chimera_pilot.cli", "autonomy-profiles"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        names = {profile["name"] for profile in payload["profiles"]}
        self.assertIn("assist", names)
        self.assertIn("generalist", names)

    def test_autonomy_runner_returns_repair_preview_without_execution(self) -> None:
        runner = AutonomyJobRunner(profile="generalist")

        result = runner.run("repair-preview")

        self.assertEqual(result.status, "preview")
        self.assertIn("plan", result.artifacts)

    def test_autonomy_runner_previews_regression_for_supervised_profile(self) -> None:
        runner = AutonomyJobRunner(profile="supervised")

        result = runner.run("test-regression", execute=True)

        self.assertEqual(result.status, "preview")
        self.assertTrue(result.artifacts["requires_execute"])

    def test_autonomy_runner_uses_configurable_regression_timeout(self) -> None:
        runner = AutonomyJobRunner(profile="generalist")
        completed = subprocess.CompletedProcess(
            args=[sys.executable, "-m", "pytest", "-q"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with mock.patch.dict(os.environ, {"GHOSTCHIMERA_AUTONOMY_TEST_TIMEOUT": "420"}), mock.patch(
            "ghostchimera.chimera_pilot.autonomy_jobs.subprocess.run", return_value=completed
        ) as run_mock:
            result = runner.run("test-regression", execute=True)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.artifacts["timeout_seconds"], 420)
        self.assertEqual(run_mock.call_args.kwargs["timeout"], 420)

    def test_autonomy_runner_reports_regression_timeout_cleanly(self) -> None:
        runner = AutonomyJobRunner(profile="generalist")
        timeout = subprocess.TimeoutExpired(cmd=[sys.executable, "-m", "pytest", "-q"], timeout=60)

        with mock.patch.dict(os.environ, {"GHOSTCHIMERA_AUTONOMY_TEST_TIMEOUT": "10"}), mock.patch(
            "ghostchimera.chimera_pilot.autonomy_jobs.subprocess.run", side_effect=timeout
        ):
            result = runner.run("test-regression", execute=True)

        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.summary)
        self.assertEqual(result.artifacts["timeout_seconds"], 60)

    def test_dependency_scan_distinguishes_minimind_architecture_from_inference(self) -> None:
        runner = AutonomyJobRunner(profile="supervised")

        result = runner.run("dependency-scan")

        dependencies = result.artifacts["dependencies"]
        minimind_status = result.artifacts["minimind_status"]
        self.assertTrue(dependencies["minimind_architecture"])
        self.assertEqual(dependencies["minimind"], minimind_status["inference_available"])

    def test_persistent_autonomy_config_round_trips(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-autonomy-config-") as tmp:
            path = Path(tmp) / "config.json"
            save_config({"autonomy": {"level": "autonomous", "local_model_profile": "stronger"}}, path=path)
            config = json.loads(path.read_text(encoding="utf-8"))

        autonomy = get_autonomy_config(config)
        self.assertEqual(autonomy["level"], "autonomous")
        self.assertEqual(autonomy["local_model_profile"], "stronger")

    def test_minimind_lifecycle_dataset_and_low_confidence_logging(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-minimind-") as tmp:
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            dataset = lifecycle.generate_dataset([{"prompt": "p", "response": "r"}])
            logged = lifecycle.log_low_confidence(prompt="p", response="r", confidence=0.2)

            self.assertTrue(dataset.exists())
            self.assertTrue(logged)
            self.assertTrue((Path(tmp) / "minimind" / "low_confidence.jsonl").exists())

    def test_minimind_lifecycle_trains_local_adapter_and_infers_from_dataset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-minimind-adapter-") as tmp:
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            lifecycle.generate_dataset(
                [
                    {
                        "prompt": "What should Ghost do after training?",
                        "response": "Run a readiness check and stage a reviewed self-evolution candidate.",
                    },
                    {
                        "prompt": "How should email be handled?",
                        "response": "Do not scrape email unless the user explicitly connects and approves it.",
                    },
                ]
            )

            trained = lifecycle.train_local_adapter()
            status = lifecycle.status().to_dict()
            inferred = lifecycle.infer("After training, what should Ghost do?")

            self.assertTrue(trained["ok"])
            self.assertEqual(trained["adapter"]["kind"], "dataset-retrieval-adapter")
            self.assertTrue(status["inference_available"])
            self.assertEqual(status["runtime_hint"], "dataset-adapter")
            self.assertIn("self-evolution candidate", inferred["answer"])
            self.assertGreater(inferred["confidence"], 0.0)

    def test_minimind_lifecycle_trains_neural_personal_adapter_weights(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-minimind-neural-") as tmp:
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            lifecycle.generate_dataset(
                [
                    {
                        "prompt": "How should Ghost handle release readiness?",
                        "response": "Run the release validator, inspect blockers, and report exact remediation steps.",
                    },
                    {
                        "prompt": "How should Ghost handle email data?",
                        "response": "Use email only after OAuth and explicit MiniMind email consent are approved.",
                    },
                ]
            )

            trained = lifecycle.train_neural_adapter(epochs=8, learning_rate=0.35)
            status = lifecycle.status().to_dict()
            inferred = lifecycle.infer("release readiness blockers")

            self.assertTrue(trained["ok"])
            self.assertEqual(trained["adapter"]["kind"], "neural-personal-adapter")
            self.assertTrue(trained["adapter"]["metadata"]["neural_weight_training"])
            self.assertGreater(trained["adapter"]["metadata"]["weight_update_steps"], 0)
            self.assertTrue(trained["adapter"]["metadata"]["weight_checksum"])
            self.assertTrue((Path(tmp) / "minimind" / "adapters" / "neural_adapter.json").exists())
            self.assertTrue(status["inference_available"])
            self.assertEqual(status["runtime_hint"], "neural-adapter")
            self.assertIn("release validator", inferred["answer"])
            self.assertEqual(inferred["adapter_kind"], "neural-personal-adapter")
            self.assertGreater(inferred["confidence"], 0.0)

    def test_minimind_bootstrap_personal_ingests_files_with_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-minimind-bootstrap-") as tmp:
            base = Path(tmp)
            notes = base / "notes.txt"
            notes.write_text("todo: ship release checklist", encoding="utf-8")
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=True,
                allow_email=False,
                file_paths=[str(notes)],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 1)
            self.assertGreaterEqual(summary["memory_documents"], 1)

    # ------------------------------------------------------------------
    # bootstrap_personal_dataset – new in this PR
    # ------------------------------------------------------------------

    def test_minimind_bootstrap_email_only_ingests_eml(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-email-") as tmp:
            base = Path(tmp)
            eml = base / "test.eml"
            eml.write_text(
                "Subject: Follow-up\nFrom: a@b.com\n\nAction: check the deadline.",
                encoding="utf-8",
            )
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=True,
                email_paths=[str(eml)],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 1)
            self.assertEqual(len(summary["emails"]), 1)
            self.assertEqual(summary["files"], [])

    def test_minimind_bootstrap_no_paths_returns_zero_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-noop-") as tmp:
            base = Path(tmp)
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=True,
                allow_email=True,
                file_paths=[],
                email_paths=[],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 0)
            self.assertEqual(summary["dataset_path"], "")

    def test_minimind_bootstrap_whitespace_only_paths_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-ws-") as tmp:
            base = Path(tmp)
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=True,
                allow_email=True,
                file_paths=["   ", "\t"],
                email_paths=["   "],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 0)

    def test_minimind_bootstrap_allow_files_false_skips_file_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-skip-") as tmp:
            base = Path(tmp)
            note = base / "skip.txt"
            note.write_text("Some content here.", encoding="utf-8")
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=False,
                file_paths=[str(note)],
                email_paths=[],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 0)
            self.assertEqual(summary["files"], [])

    def test_minimind_bootstrap_marks_not_ok_when_ingestion_errors_present(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-errors-") as tmp:
            base = Path(tmp)
            missing = base / "missing.eml"
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=True,
                email_paths=[str(missing)],
            )
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["dataset_records"], 0)
            self.assertEqual(len(summary["emails"]), 1)
            self.assertGreaterEqual(len(summary["emails"][0]["errors"]), 1)

    def test_minimind_bootstrap_summary_contains_expected_keys(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-keys-") as tmp:
            base = Path(tmp)
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=False,
            )
            expected_keys = {
                "ok",
                "memory_db",
                "allow_files",
                "allow_email",
                "files",
                "emails",
                "dataset_path",
                "dataset_records",
                "memory_documents",
            }
            self.assertEqual(set(summary.keys()), expected_keys)

    def test_minimind_bootstrap_memory_db_path_in_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-dbpath-") as tmp:
            base = Path(tmp)
            memory_db = base / "my_memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=False,
            )
            self.assertIn("my_memory.sqlite3", summary["memory_db"])

    def test_minimind_bootstrap_mbox_file_ingestion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-mbox-") as tmp:
            base = Path(tmp)
            mbox = base / "archive.mbox"
            mbox.write_text(
                "From sender@example.com Mon Jan  1 00:00:00 2024\n"
                "Subject: Deadline Notice\n"
                "From: sender@example.com\n"
                "\n"
                "Deadline: please submit the report by Friday.\n\n",
                encoding="utf-8",
            )
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=False,
                allow_email=True,
                email_paths=[str(mbox)],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 1)

    def test_minimind_bootstrap_file_directory_ingestion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-dir-") as tmp:
            base = Path(tmp)
            docs_dir = base / "docs"
            docs_dir.mkdir()
            (docs_dir / "a.txt").write_text("Note A: action required.", encoding="utf-8")
            (docs_dir / "b.txt").write_text("Note B: follow up tomorrow.", encoding="utf-8")
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=True,
                allow_email=False,
                file_paths=[str(docs_dir)],
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["dataset_records"], 1)
            self.assertGreaterEqual(summary["memory_documents"], 1)

    def test_minimind_bootstrap_both_files_and_emails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-bootstrap-both-") as tmp:
            base = Path(tmp)
            note = base / "note.txt"
            note.write_text("Meeting recap: action item for next sprint.", encoding="utf-8")
            eml = base / "msg.eml"
            eml.write_text(
                "Subject: Sprint follow-up\nFrom: pm@example.com\n\nTodo: close outstanding tickets.",
                encoding="utf-8",
            )
            memory_db = base / "memory.sqlite3"
            lifecycle = MiniMindLifecycle(profile_name="tiny", state_dir=tmp)
            summary = lifecycle.bootstrap_personal_dataset(
                memory_db=memory_db,
                allow_files=True,
                allow_email=True,
                file_paths=[str(note)],
                email_paths=[str(eml)],
            )
            self.assertTrue(summary["ok"])
            # One record for the file, one for the email
            self.assertEqual(summary["dataset_records"], 2)
            self.assertEqual(len(summary["files"]), 1)
            self.assertEqual(len(summary["emails"]), 1)

    # ------------------------------------------------------------------
    # CLI – bootstrap-personal and beta-vision actions (new in this PR)
    # ------------------------------------------------------------------

    def test_cli_bootstrap_personal_requires_allow_flag(self) -> None:
        """bootstrap-personal with no --allow-files or --allow-email returns error."""
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bp-") as tmp:
            base = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "bootstrap-personal",
                    "--memory-db",
                    str(base / "mem.sqlite3"),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("error", payload)

    def test_cli_bootstrap_personal_with_allow_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bp-files-") as tmp:
            base = Path(tmp)
            note = base / "note.txt"
            note.write_text("action: update the docs.", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "bootstrap-personal",
                    "--memory-db",
                    str(base / "mem.sqlite3"),
                    "--allow-files",
                    "--file-path",
                    str(note),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertGreaterEqual(payload["dataset_records"], 1)

    def test_cli_bootstrap_personal_allow_email_only_with_eml(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bp-email-") as tmp:
            base = Path(tmp)
            eml = base / "msg.eml"
            eml.write_text(
                "Subject: Reminder\nFrom: a@b.com\n\nDeadline: finish the report.",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "bootstrap-personal",
                    "--memory-db",
                    str(base / "mem.sqlite3"),
                    "--allow-email",
                    "--email-path",
                    str(eml),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["dataset_records"], 1)

    def test_cli_beta_vision_with_config_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bv-") as tmp:
            base = Path(tmp)
            note = base / "note.txt"
            note.write_text("TODO: prepare release notes.", encoding="utf-8")
            config_path = base / "bv.json"
            config_path.write_text(
                json.dumps(
                    {
                        "memory_db": str(base / "mem.sqlite3"),
                        "file_paths": [str(note)],
                        "email_paths": [],
                        "run_autonomy_jobs": False,
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "beta-vision",
                    "--config",
                    str(config_path),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("bootstrap", payload)
            self.assertIn("task_hints", payload)
            self.assertIn("queued_jobs", payload)

    def test_cli_beta_vision_inline_args_no_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bv-inline-") as tmp:
            base = Path(tmp)
            note = base / "note.txt"
            note.write_text("Action: deploy hotfix to production.", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "beta-vision",
                    "--memory-db",
                    str(base / "mem.sqlite3"),
                    "--file-path",
                    str(note),
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["queued_jobs"], [])

    def test_cli_beta_vision_inline_args_explicitly_run_autonomy_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-bv-inline-jobs-") as tmp:
            base = Path(tmp)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ghostchimera.control_plane.cli",
                    "minimind",
                    "beta-vision",
                    "--memory-db",
                    str(base / "mem.sqlite3"),
                    "--run-autonomy-jobs",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["queued_jobs"]), 2)

    def test_control_plane_cli_exposes_autonomy_jobs_and_minimind_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-autonomy-status-") as tmp:
            base = Path(tmp)
            env = self._sandboxed_cli_env(base)
            jobs = subprocess.run(
                [sys.executable, "-m", "ghostchimera.control_plane.cli", "autonomy", "jobs"],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=env,
            )
            self.assertEqual(jobs.returncode, 0, jobs.stderr)
            self.assertIn("repair-preview", jobs.stdout)

            status = subprocess.run(
                [sys.executable, "-m", "ghostchimera.control_plane.cli", "minimind", "status"],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=env,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIn("available", status_payload)
            self.assertTrue(status_payload["architecture_embedded"])
            self.assertIn("architecture", status_payload)

    def test_control_plane_cli_exposes_embedded_minimind_architectures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-cli-architectures-") as tmp:
            base = Path(tmp)
            completed = subprocess.run(
                [sys.executable, "-m", "ghostchimera.control_plane.cli", "minimind", "architectures"],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
                env=self._sandboxed_cli_env(base),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["source"]["license"], "Apache-2.0")
            names = {architecture["name"] for architecture in payload["architectures"]}
            self.assertIn("minimind-3", names)


if __name__ == "__main__":
    unittest.main()
