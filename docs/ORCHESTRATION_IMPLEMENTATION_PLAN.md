# Ghost Chimera Orchestration Implementation Plan

Date: 2026-05-05  
Scope: Turn the comparative audit into an execution-ready engineering plan with concrete milestones, owners, interfaces, and test gates.

## Planning Principles

1. Ship orchestration reliability before feature breadth.
2. Every runtime behavior change must be replayable from telemetry.
3. Every adaptive policy change must be auditable and reversible.
4. Multi-agent delegation requires explicit bounded contracts.

---

## Workstream 1 — Runtime State Machine + Checkpointing (Weeks 1-2)

### Objective
Create a deterministic orchestration lifecycle with resumable execution.

### Target modules
- `ghostchimera/chimera_pilot/agent_loop.py`
- `ghostchimera/chimera_pilot/executor.py`
- `ghostchimera/chimera_pilot/executor_parallel.py`
- `ghostchimera/chimera_pilot/checkpoint.py`
- `ghostchimera/chimera_pilot/result_envelope.py`

### Deliverables
- Introduce `RunState` enum:
  - `planned`, `scheduled`, `executing`, `verifying`, `reflecting`, `committed`, `failed`, `cancelled`.
- Add `run_id`, `attempt_id`, `checkpoint_id` propagation through the full pipeline.
- Persist checkpoint snapshots at each state boundary.
- Add safe resume API:
  - `resume_run(run_id: str, from_checkpoint: str | None)`.

### Acceptance criteria
- Runs can be resumed after forced interruption with no duplicated side-effectful tool execution.
- State transitions are linearizable and logged.

### Test plan
- New tests in:
  - `tests/test_agent_loop.py`
  - `tests/test_checkpoint.py`
  - `tests/integration/test_parallel_execution.py`
- Add failure injection cases:
  - backend timeout during `executing`
  - verifier failure during `verifying`
  - explicit cancel during `executing`

---

## Workstream 2 — Interrupt/Cancellation Protocol (Weeks 2-3)

### Objective
Support safe interruption and compensating actions across all execution paths.

### Target modules
- `ghostchimera/chimera_pilot/agent_loop.py`
- `ghostchimera/chimera_pilot/executor_async.py`
- `ghostchimera/chimera_pilot/executor_parallel.py`
- `ghostchimera/chimera_pilot/toolsets.py`

### Deliverables
- Add cancellation token object with cooperative polling.
- Add tool-level cancellation hooks for long-running operations.
- Add post-cancel reconciliation stage to mark partial outputs and required retry strategy.

### Acceptance criteria
- Cancelled runs end in `cancelled` state within bounded latency.
- No orphaned child tasks/subagents remain alive after cancellation.

### Test plan
- Inject Ctrl+C-style interrupt simulation in integration loop tests.
- Validate cleanup of parallel workers and partial artifacts.

---

## Workstream 3 — Adaptive Scheduler Learning Loop (Weeks 3-5)

### Objective
Make backend selection outcome-aware and self-improving under constraints.

### Target modules
- `ghostchimera/chimera_pilot/scheduler.py`
- `ghostchimera/chimera_pilot/calibration.py`
- `ghostchimera/chimera_pilot/telemetry.py`
- `ghostchimera/memory_layer/store.py`

### Deliverables
- Add outcome table schema:
  - backend id, task kind, latency, success, verifier score, policy warnings.
- Implement online weight adjustment strategy (bounded updates; deterministic seed mode).
- Add strategy selector:
  - single backend / fallback chain / parallel / MoA based on uncertainty and historical performance.

### Acceptance criteria
- Scheduler decisions include explainable score breakdown.
- Cold-start and learned modes can be toggled via config.

### Test plan
- `tests/test_calibration.py` (new)
- Extend `tests/test_backend_registry.py`, `tests/test_executor_parallel.py`.
- Regression fixture ensuring deterministic routing when seed/frozen weights are enabled.

---

## Workstream 4 — Delegation Contracts + Shared State Arbitration (Weeks 5-7)

### Objective
Make subagent orchestration safe, bounded, and mergeable.

### Target modules
- `ghostchimera/chimera_pilot/subagent.py`
- `ghostchimera/chimera_pilot/agent_pool.py`
- `ghostchimera/chimera_pilot/schema.py`
- `ghostchimera/tool_layer/file_system.py`

### Deliverables
- `DelegationContract` schema:
  - capabilities, writable roots, budget caps, review requirements.
- Enforce contract at subagent spawn and tool call boundaries.
- Introduce file lease/lock abstraction for concurrent mutation operations.
- Structured merge report with conflict classes (`non-overlap`, `text-conflict`, `policy-conflict`).

### Acceptance criteria
- Subagents cannot exceed delegated scopes.
- Concurrent edits are either safely merged or deterministically blocked.

### Test plan
- Extend `tests/test_subagent.py`, `tests/test_agent_pool.py`, `tests/test_toolsets.py`.
- New race-condition tests for shared file edits.

---

## Workstream 5 — Explainable Policy Enforcement + Simulation Mode (Weeks 7-8)

### Objective
Turn policy from binary gate into explainable governance substrate.

### Target modules
- `ghostchimera/safety_layer/policy_enforcement.py`
- `ghostchimera/safety_layer/gating.py`
- `ghostchimera/safety_layer/audit.py`

### Deliverables
- Return structured decision traces:
  - matched rule(s), risk factors, threshold, final verdict.
- Add `simulate=True` mode for counterfactual analysis without execution.
- Attach policy trace ids to `ResultEnvelope` and telemetry events.

### Acceptance criteria
- Any deny decision is explainable from trace alone.
- Simulation mode produces stable what-if outputs for the same input.

### Test plan
- Extend `tests/test_safety_policy.py`, `tests/integration/test_safety.py`.
- Snapshot tests for policy traces.

---

## Workstream 6 — Replayable Observability + Orchestration KPIs (Weeks 8-10)

### Objective
Enable full incident replay and objective orchestration quality tracking.

### Target modules
- `ghostchimera/chimera_pilot/telemetry.py`
- `ghostchimera/evals/runner.py`
- `ghostchimera/chimera_pilot/result_envelope.py`

### Deliverables
- Replay bundle format:
  - task input hash, candidate backends + scores, policy traces, tool I/O hashes, verifier output.
- Add KPI suite:
  - first-choice success rate
  - fallback depth
  - interrupt recovery rate
  - safe-degradation rate
  - policy false-positive proxy

### Acceptance criteria
- A failed run can be replayed and root-caused from logs + bundle only.
- KPI report generated in CI for smoke/safety suites.

### Test plan
- Extend `tests/test_evals.py`, `tests/test_release_package.py`.
- Add replay fixture validation in integration tests.

---

## Release Gates

A release candidate is accepted only if all are true:

1. **Reliability gate**: interrupt recovery >= 95% on integration suite.
2. **Safety gate**: zero policy bypass in fault-injection tests.
3. **Determinism gate**: replay reproduces same scheduler decision path in seed mode.
4. **Delegation gate**: zero scope-escape events in subagent contract tests.
5. **Quality gate**: first-choice success improves vs baseline by agreed threshold.

---

## Execution Cadence

- Weekly architecture review with checkpoint metrics.
- Every workstream delivered behind feature flags first.
- No new external integrations until Workstreams 1-3 pass gates.
- Each merged PR must include:
  - state-transition updates (if runtime touched)
  - telemetry event schema updates (if behavior changed)
  - at least one fault-injection or regression test

