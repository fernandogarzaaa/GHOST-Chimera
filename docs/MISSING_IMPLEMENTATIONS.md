# Beta Wiring Audit

Date: 2026-05-07

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
- The user-journey eval now exercises the first-run console/operator path:
  CLI help dispatch, config/state reporting, preview job creation, disabled
  schedule creation, operator workspace status, degraded browser workspace
  status, and readiness output.

## Operator Workspace UX

- `ghostchimera workspace show` exposes the local self-model, working memory,
  attention ranking, goals, and uncertainty summary through the real
  control-plane CLI.
- Workspace evidence, reflections, and goals persist under the Ghost Chimera
  state directory in `operator_workspace.json`.
- The browser console exposes the same state through `/api/console/workspace`
  plus evidence, reflection, and goal update routes.
- `ghostchimera workspace sync-memory` and
  `/api/console/workspace/sync-memory` promote high-confidence evidence and
  reflections into the SQLite CWR store with provenance metadata and
  duplicate-safe inserts.
- Workspace sync now reports low-confidence filtered records and marks stale or
  conflicting records with quality metadata before they enter retrieval.
- The implementation keeps truthful beta boundaries: this is inspectable local
  runtime state, not AGI, SGI, subjective consciousness, or unattended
  production operation.

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
- Built-in smoke, safety, autonomy, and user-journey eval suites emit
  release-gate summaries.

## Release Gate

Before pushing beta changes, run:

```powershell
python scripts\validate_release.py
python -m pytest -q
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python scripts\smoke_installed_wheel.py
python scripts\smoke_installed_wheel.py --extras gateway
ghostchimera workspace show
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
```

CI installs `.[gateway,dev]` for full source validation, then smokes the built
wheel twice: once without optional extras and once with gateway extras for the
console/scheduler/user-journey path.

## MiniMind Portability

- Ghost Chimera now embeds MiniMind-compatible architecture contracts for the
  current tiny MiniMind family and attributes the Apache-2.0 upstream project in
  `NOTICE`.
- `ghostchimera minimind architectures` works without a local upstream checkout,
  PyTorch, Transformers, or model weights.
- `ghostchimera minimind status` reports whether package imports, upstream
  workspaces, model files, and optional dependencies are actually present before
  claiming inference availability.
- Remaining boundary: Ghost Chimera does not bundle MiniMind weights. Operators
  must provide `MINIMIND_MODEL_PATH` and install `.[minimind]` for real local
  MiniMind inference.
