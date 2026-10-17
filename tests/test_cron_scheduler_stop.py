"""CronScheduler.stop() returns promptly instead of waiting out poll_interval."""

from __future__ import annotations

import sys
import time
import types

if "croniter" not in sys.modules:  # same shim as tests/test_daemon.py when croniter is absent
    try:
        import croniter  # noqa: F401
    except ImportError:  # pragma: no cover - CI installs croniter
        shim = types.ModuleType("croniter")

        class _Croniter:  # minimal stand-in, never iterated here
            def __init__(self, *args, **kwargs) -> None:
                pass

            def get_next(self, *args, **kwargs):
                return time.time() + 3600

        shim.croniter = _Croniter
        sys.modules["croniter"] = shim

from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler  # noqa: E402


def test_stop_wakes_the_loop_instead_of_waiting_out_the_poll_interval(tmp_path) -> None:
    scheduler = CronScheduler(state_dir=tmp_path, poll_interval=60, job_executor=lambda job: None)
    thread = scheduler.start()
    time.sleep(0.2)  # let the loop finish its first tick and start waiting
    started = time.monotonic()
    scheduler.stop()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"stop() took {elapsed:.1f}s"
    assert not thread.is_alive()


def test_scheduler_can_restart_after_stop(tmp_path) -> None:
    scheduler = CronScheduler(state_dir=tmp_path, poll_interval=60, job_executor=lambda job: None)
    scheduler.start()
    scheduler.stop()
    thread = scheduler.start()
    time.sleep(0.1)
    assert thread.is_alive()
    scheduler.stop()
    assert not thread.is_alive()
