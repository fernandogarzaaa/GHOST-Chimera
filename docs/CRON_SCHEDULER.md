# Cron Scheduler

## Architecture

The cron scheduler lives in `ghostchimera/chimera_pilot/cron_scheduler.py`. It implements persistent scheduled task execution using the `croniter` library for expression parsing.

### CronJob

Each scheduled job is a `CronJob` dataclass:

| Field | Type | Purpose |
|-------|------|---------|
| `id` | str | Unique job identifier |
| `name` | str | Human-readable name |
| `cron_expression` | str | Standard cron expression (e.g. "0 9 * * *") |
| `objective` | str | Task to execute |
| `task_kind` | TaskKind | IR task kind (reasoning, tool_call, etc.) |
| `enabled` | bool | Whether the job is active |
| `next_run` | float | Unix timestamp of next scheduled run |
| `last_run` | float | Unix timestamp of last run |
| `run_count` | int | Total runs executed |

### CronScheduler

The `CronScheduler` implements `BackgroundService` from `service_registry.py`:

1. **Job Management**: `add_job()`, `remove_job()`, `enable_job()`, `disable_job()`
2. **Persistence**: Jobs are saved to `state_dir/cron_jobs.json` on every mutation
3. **Execution**: `tick()` checks for due jobs (`next_run <= now`) and executes them
4. **Execution Strategy**: Uses the `job_executor` callback if provided, otherwise falls back to `AgentCore.default().compile_and_run()`
5. **Background Mode**: `start()` runs a loop that calls `tick()` every `poll_interval` seconds (default 60s)

### Cron Expression Support

Uses `croniter` for full standard cron expression support:

| Expression | Meaning |
|------------|---------|
| `*/5 * * * *` | Every 5 minutes |
| `0 9 * * *` | Daily at 9:00 AM |
| `0 0 1 * *` | Monthly on the 1st at midnight |
| `0 0 * * 0` | Weekly on Sunday at midnight |

### Integration with ServiceRegistry

The scheduler registers itself as a `BackgroundService` with:

- `service_id = "cron_scheduler"`
- `service_name = "Cron Scheduler"`
- `probe()` returns health status with job count and enabled count

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/cron_scheduler.py` | CronScheduler, CronJob, CronJobResult |
| `ghostchimera/chimera_pilot/service_registry.py` | BackgroundService, ServiceHealth |
