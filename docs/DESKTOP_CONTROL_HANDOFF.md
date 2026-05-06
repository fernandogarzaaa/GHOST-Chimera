# Desktop Control Handoff (Ghost Chimera)

## Current State (Implemented)

### Core capability
- `TaskKind.DESKTOP_CONTROL` exists in Task IR.
- `RuleBasedTaskCompiler` compiles desktop intents (`click`, `double click`, `right click`, `type`, `hotkey`) plus prefixes:
  - `live desktop: ...` -> `constraints.live_desktop=true`
  - `dryrun desktop: ...` -> `constraints.live_desktop=false`
- `DesktopRuntimeBackend` exists and is policy-gated.

### Safety and policy
- Default behavior is dry-run.
- Live execution requires all of:
  1. Desktop backend enabled
  2. Desktop control allowed
  3. `ghost_mode=possess`
  4. Task constraint `live_desktop=true`
- Live execution has backend session guards:
  - `max_live_actions` / CLI `--desktop-max-actions`
  - `max_session_seconds` / CLI `--desktop-max-duration-seconds`
- Kill-switch support:
  - task-level `constraints.kill_switch` path
  - backend-level `kill_switch_path`
  - env-level `GHOSTCHIMERA_DESKTOP_KILL_SWITCH`
- Action audit log support (JSONL):
  - backend `action_log_path`
  - env fallback `GHOSTCHIMERA_DESKTOP_ACTION_LOG`

### CLI plumbing
- `chimera-pilot` supports desktop flags on `run` and `status`.
- top-level control-plane CLI also forwards desktop flags to Pilot kernel.

### Test coverage
- Desktop backend dry-run/live/kill-switch/log tests.
- Compiler+schema tests for desktop intents.
- Policy and ghost-mode validation tests.
- CLI status tests confirming desktop backend and `ghost_mode` visibility.

---

## What Is Left to Implement

## 1) True UI targeting (high priority)
Current runtime mainly supports coordinate-level or basic action execution.

Needed:
- semantic target model (window/app/widget/text anchors)
- robust focus/window activation model
- retries with state checks before/after click/type
- deterministic fallback when target not found

## 2) Live execution hardening
Implemented:
- max-action budget per backend session
- max-duration timeout before each live action

Still needed:
- emergency stop command in CLI/session loop
- explicit confirmation token workflow for irreversible actions

## 3) Stronger policy semantics
Needed:
- policy split by action class (read-only vs mutating)
- denylist/allowlist for specific apps/windows/processes
- per-directory/file affinity between desktop actions and file mutations
- policy trace IDs persisted into every desktop action log row

## 4) Better observability + replay
Needed:
- screenshot capture hooks before/after each live action
- replay bundle integration (action log + screenshots + policy snapshot)
- compression/retention strategy for desktop action telemetry

## 5) Integration and fault-injection tests
Needed:
- end-to-end desktop flow test matrix for:
  - kill-switch activation during run
  - missing pyautogui
  - focus loss / stale target
  - cancellation during action sequence
- regression tests for control-plane `--pilot-run` with live desktop options

## 6) Multi-step planner support
Current compiler maps mostly single-step desktop intents.

Needed:
- multi-step task graphs (`open app -> navigate -> type -> submit`)
- verification steps between actions
- rollback/compensation hooks for partial failures

## 7) Documentation completion
Needed:
- dedicated operator runbook for safe live desktop usage
- threat model section for desktop control in `SECURITY.md`
- explicit production guardrails checklist for unattended runs

---

## Suggested Next PR Order
1. Add screenshot hooks + replay integration for each live action.
2. Add action-class policy model (`read_only`, `mutating`, `destructive`).
3. Add emergency stop command and confirmation-token workflow for irreversible live actions.
4. Add multi-step desktop compiler/planner path and integration tests.

