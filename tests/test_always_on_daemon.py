"""Tests for the always-on daemon lifecycle, triggers, and gating."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from ghostchimera.chimera_pilot.always_on.daemon import (
    AlwaysOnDaemon,
    LifecycleState,
)
from ghostchimera.chimera_pilot.subagent import DelegationContract, DelegationResult, SubagentResult
from ghostchimera.safety_layer.approval import ApprovalRequest, get_default_handler


def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _fake_executor(objective: str, session) -> str:
    return f"done: {objective}"


def _make_daemon(tmp: str, **kwargs) -> AlwaysOnDaemon:
    kwargs.setdefault("executor", _fake_executor)
    kwargs.setdefault("cron_poll_interval", 1)
    return AlwaysOnDaemon(state_dir=tmp, **kwargs)


class DaemonLifecycleTests(unittest.TestCase):
    def test_start_stop_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            self.assertFalse(daemon.probe().ok)
            daemon.start()
            try:
                self.assertTrue(daemon.probe().ok)
                agents = daemon.agents_status()
                self.assertEqual(len(agents), 1)
                self.assertEqual(agents[0]["lifecycle_state"], LifecycleState.SLEEPING.value)
            finally:
                daemon.stop()
            self.assertFalse(daemon.probe().ok)
            self.assertEqual(daemon.agents_status()[0]["lifecycle_state"], LifecycleState.SLEEPING.value)

    def test_wake_runs_to_completion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            daemon.start()
            try:
                request = daemon.wake("check the inbox", source="manual")
                self.assertTrue(
                    _wait_until(
                        lambda: (
                            daemon.sessions.get(
                                daemon.sessions.get_or_create_for_agent(request.agent_id).session_id
                            ).lifecycle_state
                            == LifecycleState.COMPLETED.value
                        )
                    ),
                    "wake request did not complete",
                )
                session = daemon.sessions.get_or_create_for_agent(request.agent_id)
                self.assertEqual(len(session.wake_history), 1)
                self.assertEqual(session.wake_history[0]["status"], "completed")
                self.assertEqual(session.wake_history[0]["source"], "manual")
                # transcript persisted
                self.assertEqual(session.messages[0], {"role": "user", "content": "check the inbox"})
                self.assertEqual(session.messages[1]["role"], "assistant")
                # agent settles back to sleeping
                self.assertTrue(
                    _wait_until(lambda: daemon.agents_status()[0]["lifecycle_state"] == LifecycleState.SLEEPING.value)
                )
            finally:
                daemon.stop()

    def test_agent_is_awake_while_executing(self) -> None:
        gate = threading.Event()

        def blocking_executor(objective: str, session) -> str:
            gate.wait(timeout=10)
            return "finished"

        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp, executor=blocking_executor)
            daemon.start()
            try:
                daemon.wake("long task", source="manual")
                self.assertTrue(
                    _wait_until(lambda: daemon.agents_status()[0]["lifecycle_state"] == LifecycleState.AWAKE.value),
                    "agent never entered awake state",
                )
            finally:
                gate.set()
                daemon.stop()

    def test_empty_objective_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            with self.assertRaises(ValueError):
                daemon.wake("   ")

    def test_wake_queue_dir_picks_up_cross_process_wake(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            daemon.start()
            try:
                # A second handle (e.g. the CLI) enqueues without a running worker.
                other = _make_daemon(tmp)
                request = other.wake("cross-process wake", source="cli")
                wake_file = Path(tmp) / "always_on" / "wake_queue" / f"{request.request_id}.json"
                self.assertTrue(wake_file.exists())
                self.assertTrue(
                    _wait_until(
                        lambda: (
                            not wake_file.exists()
                            and len(other.sessions.get_or_create_for_agent(request.agent_id).wake_history) == 1
                        )
                    ),
                    "cross-process wake was not picked up",
                )
            finally:
                daemon.stop()

    def test_session_resumes_after_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            first = _make_daemon(tmp)
            first.start()
            try:
                request = first.wake("remember this", source="manual")
                self.assertTrue(
                    _wait_until(lambda: len(first.sessions.get_or_create_for_agent(request.agent_id).wake_history) == 1)
                )
                agent_id = request.agent_id
            finally:
                first.stop()
            second = _make_daemon(tmp)
            session = second.sessions.get_or_create_for_agent(agent_id)
            self.assertEqual(len(session.messages), 2)
            self.assertEqual(len(second.identities.list()), 1)


class DaemonTriggerTests(unittest.TestCase):
    def test_webhook_wakes_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            daemon.start()
            try:
                daemon.register_webhook(
                    "ci-done",
                    lambda payload: f"verify build {payload.get('build')}",
                    description="CI hook",
                )
                request = daemon.handle_webhook("ci-done", {"build": "42"})
                self.assertEqual(request.source, "webhook:ci-done")
                self.assertTrue(
                    _wait_until(
                        lambda: len(daemon.sessions.get_or_create_for_agent(request.agent_id).wake_history) == 1
                    ),
                    "webhook wake did not complete",
                )
            finally:
                daemon.stop()

    def test_unknown_webhook_raises(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            with self.assertRaises(KeyError):
                daemon.handle_webhook("missing", {})

    def test_cron_schedule_fires_wake(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            daemon.start()
            try:
                job = daemon.add_schedule("nightly", "0 3 * * *", "run nightly check")
                self.assertEqual(len(daemon.list_schedules()), 1)
                # Force the job due and tick the scheduler directly.
                daemon._cron.jobs[job.id].next_run = time.time() - 1
                results = daemon._cron.tick()
                self.assertEqual(len(results), 1)
                self.assertTrue(results[0].success)
                agent_id = daemon.identities.get_or_create_primary().agent_id
                self.assertTrue(
                    _wait_until(lambda: len(daemon.sessions.get_or_create_for_agent(agent_id).wake_history) == 1),
                    "scheduled wake did not complete",
                )
            finally:
                daemon.stop()

    def test_reload_picks_up_externally_added_schedule(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            daemon.start()
            try:
                self.assertEqual(len(daemon.list_schedules()), 0)
                # Another process (console/CLI) adds a schedule to the shared file.
                from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler

                other = CronScheduler(state_dir=tmp)
                other.add_job(name="external", cron_expression="* * * * *", objective="external wake")
                self.assertTrue(
                    _wait_until(lambda: len(daemon.list_schedules()) == 1),
                    "daemon did not pick up the externally added schedule",
                )
                # And an external removal is honored too.
                for job in other.list_jobs():
                    other.remove_job(job.id)
                self.assertTrue(
                    _wait_until(lambda: len(daemon.list_schedules()) == 0),
                    "daemon did not pick up the externally removed schedule",
                )
            finally:
                daemon.stop()

    def test_reload_never_postpones_known_jobs(self) -> None:
        from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler

        with tempfile.TemporaryDirectory(prefix="ghostchimera-cron-") as tmp:
            scheduler = CronScheduler(state_dir=tmp)
            job = scheduler.add_job(name="steady", cron_expression="0 3 * * *", objective="x")
            before = scheduler.jobs[job.id].next_run
            scheduler.reload()
            scheduler.reload()
            self.assertEqual(scheduler.jobs[job.id].next_run, before)


class DaemonDelegationTests(unittest.TestCase):
    def test_delegate_fans_out_and_collects(self) -> None:
        def fake_factory(objective: str):
            result = DelegationResult(
                parent_objective=objective,
                results=[
                    SubagentResult(id="s1", goal="g1", result="r1", success=True),
                    SubagentResult(id="s2", goal="g2", result="r2", success=True),
                ],
                successful_count=2,
                failed_count=0,
            )
            return result

        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp, subagent_pool_factory=fake_factory)
            result = daemon.delegate("parent objective", ["g1", "g2"], contract=DelegationContract(max_workers=2))
            self.assertEqual(result.successful_count, 2)
            self.assertEqual(result.failed_count, 0)

    def test_delegate_requires_goals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp)
            with self.assertRaises(ValueError):
                daemon.delegate("objective", [])


class DaemonApprovalGateTests(unittest.TestCase):
    def test_daemon_installs_queued_handler_while_running(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            before = get_default_handler()
            daemon = _make_daemon(tmp, approval_wait_timeout_seconds=1.0)
            daemon.start()
            try:
                self.assertIs(get_default_handler(), daemon.approval_handler)
                # A high-stakes tool call parks a ticket instead of executing.
                outcomes: list = []
                thread = threading.Thread(
                    target=lambda: outcomes.append(
                        get_default_handler().handle(ApprovalRequest(tool_name="shell", requester="agent-1"))
                    ),
                    daemon=True,
                )
                thread.start()
                self.assertTrue(
                    _wait_until(lambda: len(daemon.approval_store.list_pending()) == 1),
                    "approval ticket was not parked",
                )
                ticket = daemon.approval_store.list_pending()[0]
                daemon.approval_handler.decide(ticket.ticket_id, True, decided_by="test")
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
                self.assertTrue(outcomes[0].approved)
            finally:
                daemon.stop()
            self.assertIs(get_default_handler(), before)

    def test_undecided_high_stakes_call_is_denied_on_timeout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-daemon-") as tmp:
            daemon = _make_daemon(tmp, approval_wait_timeout_seconds=1.0)
            daemon.start()
            try:
                result = get_default_handler().handle(ApprovalRequest(tool_name="shell", requester="agent-1"))
                self.assertFalse(result.approved)
                self.assertIn("timed out", result.reason)
            finally:
                daemon.stop()


if __name__ == "__main__":
    unittest.main()
