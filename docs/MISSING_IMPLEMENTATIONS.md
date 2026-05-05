# Missing Implementations Tracker

Date: 2026-05-05

This file tracks orchestration work that is still incomplete relative to `docs/ORCHESTRATION_IMPLEMENTATION_PLAN.md`.

## Status Legend
- ✅ Implemented
- 🟡 Partially implemented
- ❌ Not implemented

---

## Workstream 1 — Runtime State Machine + Checkpointing

- ✅ Run state lifecycle primitives in executor (`planned/scheduled/executing/verifying/committed/failed/cancelled`).
- ✅ `run_id` / `attempt_id` / `checkpoint_id` propagation in execution payloads.
- 🟡 Checkpoints are recorded on terminal states, but resumability is still contextual and not full state restoration.
- ❌ No strict side-effect deduplication proof for resumed runs after interruption.
- ❌ No full integration test matrix yet for interruption at each lifecycle boundary.

## Workstream 2 — Interrupt/Cancellation Protocol

- ✅ Cooperative cancellation for executor and parallel execution entry points.
- 🟡 Cancellation semantics exist, but compensating action/reconciliation stage is minimal.
- ❌ No generalized tool-level cancellation hooks across all long-running tools.
- ❌ No end-to-end interrupt cleanup guarantees for all async/subagent pathways.

## Workstream 3 — Adaptive Scheduler Learning Loop

- ✅ Score breakdowns and configurable weights.
- ✅ Online bounded adaptation hook (`adapt_from_outcome`).
- ✅ Outcome persistence schema/API in memory store.
- ✅ Strategy selector heuristic (`single`/`fallback_chain`/`parallel`/`moa`).
- 🟡 Historical success-rate feedback now influences strategy selection, but broader learning policy remains simple heuristics.
- ❌ No robust strategy policy trained from full multi-dimensional telemetry.
- ❌ No dedicated `tests/test_calibration.py` for new adaptive strategy behavior.

## Workstream 4 — Delegation Contracts + Shared State Arbitration

- ✅ Delegation contract primitives and contract-aware spawn APIs.
- 🟡 Contract enforcement is present at spawn API level, but not fully enforced at every tool boundary.
- ❌ File lease/lock abstraction for concurrent mutation not implemented.
- ❌ Structured merge/conflict report classes not implemented.
- ❌ No race-condition integration suite for shared-file conflict arbitration.

## Workstream 5 — Explainable Policy Enforcement + Simulation Mode

- ✅ `simulate=True` support and structured trace IDs/traces.
- ✅ Explainable pilot/material check traces in enforcement result.
- 🟡 Trace propagation into all envelopes/telemetry surfaces is partial.
- ❌ Snapshot-style policy trace stability tests not yet added.

## Workstream 6 — Replayable Observability + Orchestration KPIs

- ✅ Replay bundles with hashes and telemetry persistence/export.
- ✅ Basic KPI/gate emission in eval runner.
- 🟡 KPI suite currently uses proxies; deeper metrics (fallback depth, interrupt recovery, safe degradation) still missing.
- ❌ Full replay fixture validation in integration tests not implemented.
- ❌ CI enforcement of hard release gates not yet wired.

---

## Cross-Cutting Missing Items

1. ❌ Determinism gate harness proving identical routing under frozen/seeded configuration.
2. ❌ Fault-injection suite for interruption at each executor state boundary.
3. ❌ Delegation gate proving zero scope-escape across contract + tool boundary tests.
4. ❌ Reliability gate evidence (`interrupt recovery >= 95%`) via integration benchmark.
5. ❌ Quality gate evidence (`first-choice success improvement vs baseline`) via benchmark history.

---

## Suggested Next Priority Order

1. Implement file lease/lock + conflict report primitives (Workstream 4 hard gap).
2. Add interrupt fault-injection integration tests with lifecycle boundary coverage (Workstream 1/2 hard gate).
3. Expand KPI suite to real orchestration metrics + CI gate checks (Workstream 6 gate closure).
4. Build deterministic replay harness for seeded/frozen scheduler mode (Workstream 3 + release determinism gate).
