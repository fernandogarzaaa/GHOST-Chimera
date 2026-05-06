# Beta Wiring Audit

Date: 2026-05-06

Ghost Chimera is in beta phase. This tracker records the release wiring status
for the orchestration workstreams from `docs/ORCHESTRATION_IMPLEMENTATION_PLAN.md`.

## Local Operator Console

- `ghostchimera console` now exposes a task-oriented localhost UI for status,
  autonomy profile control, safe objective runs, optional browser workspace
  controls, a durable autonomy job center, recurring autonomy schedules, and
  release-readiness checks.
- Console job history is persisted under the Ghost Chimera state directory and
  reuses `AutonomyJobRunner` so high-impact execution remains profile-gated.
- Recurring schedules reuse `CronScheduler` with a console executor that records
  scheduled runs in the same autonomy job history.
- Optional `agent-browser` support remains degraded-friendly; core console
  controls continue to work when the binary is absent.

## Runtime State And Checkpointing

- Run state lifecycle primitives are wired through executor transitions.
- `run_id`, `attempt_id`, and `checkpoint_id` propagate into execution payloads.
- Terminal-state checkpoint recording is connected to telemetry and replay bundle generation.
- Windows-safe checkpoint metadata replacement and fallback diff handling are covered by tests.

## Interrupt And Cancellation Protocol

- Cooperative cancellation is available for executor and parallel execution entry points.
- Cancelled parallel runs return structured failed executions instead of dropping results.
- Long-running desktop sessions now have max-action and max-duration guards.

## Adaptive Scheduler Learning Loop

- Scheduler score breakdowns, configurable weights, and bounded adaptation are live.
- Outcome persistence is wired through the memory store.
- Strategy selection supports `single`, `fallback_chain`, `parallel`, and `moa` modes.

## Delegation And Shared State Arbitration

- Delegation contract primitives and contract-aware spawn APIs are present.
- File lease arbitration and structured merge conflict reports are implemented in
  `ghostchimera.tool_layer.file_system`.
- Lease and conflict behavior is covered by `tests/test_file_system_leases.py`.

## Policy Enforcement And Simulation

- Pilot policy validation is explainable and conservative by default.
- Material policy checks emit trace IDs and structured enforcement results.
- Filesystem containment uses platform-native path relation checks on Windows and POSIX.

## Replayable Observability

- Replay bundles include run, decision, attempts, transitions, and trace hashes.
- Telemetry exports JSON/CSV and replay-bundle files.
- Built-in eval suites emit release-gate summaries.

## Release Gate

Before pushing beta changes, run:

```powershell
python scripts\validate_release.py
python -m pytest -q
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
```

For public artifacts, also install the built wheel in a clean virtual
environment and smoke the console entry points.
