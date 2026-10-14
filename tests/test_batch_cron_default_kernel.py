"""codeaudit F4: batch_runner/cron default path called AgentCore.default() (absent).

These run the real worker / scheduler path with a real Chimera Pilot kernel
(the offline deterministic backend), no mocks of the executor or the kernel.
"""

from __future__ import annotations

import json

import pytest

from ghostchimera.chimera_pilot.batch_runner import BatchJob, BatchRunner, _run_job_worker, run_batch
from ghostchimera.chimera_pilot.cron_scheduler import CronScheduler

# Offline, deterministic, no provider: "what is 2+2" is answered locally with "4".
OFFLINE = {
    "include_deterministic_backend": True,
    "deterministic_fulfill": True,
    "include_model_provider_backend": False,
}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GHOSTCHIMERA_STATE_DIR", str(tmp_path / ".ghostchimera"))
    for key in ("NEBIUS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("GHOSTCHIMERA_MODEL_PROVIDER", raising=False)


def test_batch_job_has_job_index_and_runner_numbers_jobs() -> None:
    runner = BatchRunner([BatchJob(objective="a"), BatchJob(objective="b")], workers=1)
    assert [job.job_index for job in runner.jobs] == [0, 1]


def test_worker_runs_objective_on_real_kernel(tmp_path) -> None:
    job = BatchJob(objective="what is 2+2", job_index=7)
    result = _run_job_worker(job, str(tmp_path / "out"), 0, OFFLINE)
    assert result["success"] is True, result
    assert result["job_index"] == 7
    assert json.loads(result["result"])[0]["output"] == "4"
    saved = json.loads((tmp_path / "out" / "job_7.json").read_text(encoding="utf-8"))
    assert saved["objective"] == "what is 2+2"


def test_worker_without_provider_fails_cleanly_not_attributeerror(tmp_path) -> None:
    result = _run_job_worker(BatchJob(objective="what is 2+2"), str(tmp_path / "out"), 0)
    assert result["success"] is False
    assert "has no attribute" not in (result["error"] or "")
    assert "No available backend" in (result["error"] or "")


def test_run_batch_end_to_end_across_worker_processes(tmp_path) -> None:
    summary = run_batch(
        ["what is 2+2", "what is 2+2"],
        workers=2,
        output_dir=str(tmp_path / "batch"),
        timeout=120,
        kernel_options=OFFLINE,
    )
    assert summary.total_jobs == 2
    assert summary.successful_jobs == 2, summary.to_dict()
    assert sorted(job.job_index for job in summary.jobs) == [0, 1]
    assert (tmp_path / "batch" / "summary.json").is_file()


def test_run_batch_without_provider_reports_failures_instead_of_raising(tmp_path) -> None:
    summary = run_batch(["what is 2+2"], workers=1, output_dir=str(tmp_path / "batch"), timeout=120)
    assert summary.total_jobs == 1
    assert summary.failed_jobs == 1
    assert "has no attribute" not in (summary.jobs[0].error or "")


def test_cron_default_executor_runs_real_kernel(tmp_path) -> None:
    scheduler = CronScheduler(state_dir=tmp_path / "cron", kernel_options=OFFLINE)
    job = scheduler.add_job(name="math", cron_expression="0 * * * *", objective="what is 2+2")
    result = scheduler._run_job(job)
    assert result.success is True, result.error
    assert '"output": "4"' in result.output  # output is capped at 3000 chars


def test_cron_default_executor_without_provider_reports_real_error(tmp_path) -> None:
    scheduler = CronScheduler(state_dir=tmp_path / "cron")
    job = scheduler.add_job(name="math", cron_expression="0 * * * *", objective="what is 2+2")
    result = scheduler._run_job(job)
    assert result.success is False
    assert "AgentCore" not in (result.error or "")
