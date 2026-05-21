# Trust Eval Flywheel And Capability Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of the Trust, Evolution, and Operator Platform: Trust Eval Flywheel 2.0 plus a shared Capability Admission System.

**Implementation status:** Complete in this branch. The plan remains as an
execution log and verification guide; see the final verification section for the
commands used before commit.

**Architecture:** Extend the existing `ghostchimera.trust_runtime.TrustRuntimeStore` instead of creating a parallel trust store. Add a focused `ghostchimera.capability_admission` module for admission records, then expose both through the existing CLI and Ghost Console route/UI patterns.

**Tech Stack:** Python standard library dataclasses/JSONL/local filesystem storage, existing Ghost Console static HTML/JS, existing `GatewayServer`, pytest/unittest, and existing release validation script.

---

## File Structure

- Modify `ghostchimera/trust_runtime.py`: add `TrustEvalCase`, eval-case storage, promotion from runs, baseline comparison improvements, and journal hash-chain metadata.
- Create `ghostchimera/capability_admission.py`: local admission records, transitions, inspection helpers, secret redaction, and production readiness posture.
- Modify `ghostchimera/control_plane/cli.py`: add `trust eval-cases ...` and `capability-admission ...` commands.
- Modify `ghostchimera/control_plane/console.py`: add Trust Eval and Capability Admission APIs, wire admission summary into Operator Home.
- Modify `ghostchimera/control_plane/static/index.html`: add Trust Eval Flywheel and Capability Admission panels.
- Modify `ghostchimera/control_plane/static/app.js`: render eval cases, admission records, promotion, approve, revoke, and quarantine actions.
- Modify `scripts/validate_release.py`: require/import the new admission module and docs.
- Create `docs/CAPABILITY_ADMISSION.md`: document admission lifecycle and CLI/API/Console usage.
- Modify `docs/TRUST_RUNTIME.md`: document eval cases and hash-chain baseline behavior.
- Modify `docs/RELEASE_CHECKLIST.md`: add trust eval case and admission checks.
- Create `tests/test_capability_admission.py`: unit tests for admission records and transitions.
- Modify `tests/test_trust_runtime.py`: add eval case promotion, baseline comparison, and hash-chain tests.
- Modify `tests/test_trust_console.py`: add console route tests for eval cases and admission actions.

## Task 1: Trust Eval Cases

**Files:**
- Modify: `ghostchimera/trust_runtime.py`
- Modify: `tests/test_trust_runtime.py`

- [ ] **Step 1: Write failing eval-case tests**

Add tests that create a run, promote it to an eval case, list eval cases, create a baseline from eval cases, compare a later baseline, and confirm raw secrets are redacted.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_trust_runtime.py -q`

Expected: failures for missing `promote_run_to_eval_case` and `list_eval_cases`.

- [ ] **Step 3: Implement eval-case storage**

Add a `TrustEvalCase` dataclass and store cases in `trust_runtime/eval_cases.jsonl`. Use stable IDs and redacted references only.

- [ ] **Step 4: Implement promotion and baseline support**

Add:

```python
TrustRuntimeStore.promote_run_to_eval_case(run_id, label="", severity="P2")
TrustRuntimeStore.list_eval_cases(limit=100)
```

Update `eval_baseline()` so it includes promoted eval cases as first-class cases.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_trust_runtime.py -q`

Expected: all trust runtime tests pass.

## Task 2: Journal Hash Chain

**Files:**
- Modify: `ghostchimera/trust_runtime.py`
- Modify: `tests/test_trust_runtime.py`

- [ ] **Step 1: Write hash-chain tests**

Add a test asserting each journal step includes `record_hash` and `previous_hash`, and that `verify_run_integrity(run_id)` passes for untouched journals and fails after tampering.

- [ ] **Step 2: Implement hash-chain metadata**

When appending a step, compute a canonical JSON payload, previous record hash, and record hash before writing the JSONL row.

- [ ] **Step 3: Implement integrity verification**

Add:

```python
TrustRuntimeStore.verify_run_integrity(run_id)
```

Return `{"ok": True, "verified": True}` or a failure with the first bad step ID.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_trust_runtime.py -q`

Expected: all trust runtime tests pass.

## Task 3: Capability Admission Module

**Files:**
- Create: `ghostchimera/capability_admission.py`
- Create: `tests/test_capability_admission.py`

- [ ] **Step 1: Write admission lifecycle tests**

Test creation, list, inspect, approve, activate, quarantine, revoke, invalid transitions, risk ceiling, and secret redaction.

- [ ] **Step 2: Implement dataclass and store**

Create:

```python
CapabilityAdmissionRecord
CapabilityAdmissionStore
```

Store records in `capability_admission/records.json`.

- [ ] **Step 3: Implement transitions**

Allowed transitions:

- discovered -> inspected
- inspected -> review_required
- inspected -> approved
- review_required -> approved
- approved -> active
- active -> revoked
- active -> quarantined
- approved -> revoked
- quarantined -> revoked

- [ ] **Step 4: Implement production posture**

Add `summary()` returning counts, unreviewed high-risk records, active records, and production readiness warnings.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_capability_admission.py -q`

Expected: all admission tests pass.

## Task 4: CLI Wiring

**Files:**
- Modify: `ghostchimera/control_plane/cli.py`
- Add/modify tests in `tests/test_capability_admission.py` and `tests/test_trust_runtime.py` if CLI helpers are already tested there.

- [ ] **Step 1: Add trust eval-case CLI commands**

Add:

```bash
ghostchimera trust eval-cases list
ghostchimera trust eval-cases promote <run_id>
```

- [ ] **Step 2: Add capability-admission CLI commands**

Add:

```bash
ghostchimera capability-admission list
ghostchimera capability-admission inspect --kind model --name openrouter/gpt-4o-mini --risk medium
ghostchimera capability-admission approve <id>
ghostchimera capability-admission activate <id>
ghostchimera capability-admission revoke <id>
ghostchimera capability-admission quarantine <id>
```

- [ ] **Step 3: Run CLI smoke tests**

Run:

```bash
python -m ghostchimera.control_plane.cli capability-admission --state-dir .ghost-admission-smoke list
python -m ghostchimera.control_plane.cli trust --state-dir .ghost-admission-smoke eval-cases list
```

Expected: JSON output with `ok: true`.

## Task 5: Console API Wiring

**Files:**
- Modify: `ghostchimera/control_plane/console.py`
- Modify: `tests/test_trust_console.py`

- [ ] **Step 1: Add failing API tests**

Test:

- `GET /api/console/trust/eval-cases`
- `POST /api/console/trust/eval-cases/promote`
- `GET /api/console/capability-admission`
- `POST /api/console/capability-admission`
- `POST /api/console/capability-admission/{id}/approve`
- `POST /api/console/capability-admission/{id}/revoke`

- [ ] **Step 2: Implement routes**

Instantiate `CapabilityAdmissionStore(console_state_dir)` beside `TrustRuntimeStore`. Reuse `_api_register`.

- [ ] **Step 3: Update operator summary**

Add admission summary to Operator Home cards with next action `trust` or `evolution`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_trust_console.py -q`

Expected: all console trust tests pass.

## Task 6: Console UI Wiring

**Files:**
- Modify: `ghostchimera/control_plane/static/index.html`
- Modify: `ghostchimera/control_plane/static/app.js`

- [ ] **Step 1: Add UI containers**

In the Trust Runtime tab, add sections for Trust Eval Cases and Capability Admission.

- [ ] **Step 2: Add JS render and actions**

Add functions to refresh, render, promote eval cases, inspect capabilities, and approve/revoke admission records.

- [ ] **Step 3: Static verification**

Run: `node --check ghostchimera/control_plane/static/app.js`

Expected: no syntax errors.

## Task 7: Docs And Release Gate

**Files:**
- Create: `docs/CAPABILITY_ADMISSION.md`
- Modify: `docs/TRUST_RUNTIME.md`
- Modify: `docs/RELEASE_CHECKLIST.md`
- Modify: `scripts/validate_release.py`
- Modify: `README.md` if needed

- [ ] **Step 1: Document capability admission**

Explain lifecycle, CLI, Console, APIs, safety posture, and non-goals.

- [ ] **Step 2: Update Trust Runtime docs**

Add eval-case promotion, hash-chain verification, and baseline comparison notes.

- [ ] **Step 3: Update release validator**

Require `docs/CAPABILITY_ADMISSION.md` and import `ghostchimera.capability_admission`.

- [ ] **Step 4: Run release validator**

Run: `python scripts/validate_release.py`

Expected: `"ok": true`.

## Task 8: Full Verification And Commit

**Files:**
- All touched files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python -m pytest tests/test_trust_runtime.py tests/test_capability_admission.py tests/test_trust_console.py -q
python -m pytest tests/test_console.py tests/test_remote_control.py tests/test_model_discovery.py -q
python -m pytest tests/test_capability_pack_and_sandbox.py tests/test_latency.py -q
```

Expected: all pass.

- [ ] **Step 2: Run lint and static checks**

Run:

```bash
python -m ruff check ghostchimera tests scripts
node --check ghostchimera/control_plane/static/app.js
```

Expected: all pass.

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -q`

Expected: all pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add ghostchimera docs scripts tests README.md
git commit -m "Add trust eval flywheel and capability admission"
```

Expected: commit succeeds. Do not add `.ghost-admin-live/`.
