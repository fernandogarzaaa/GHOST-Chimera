# Architecture Audit — `ghostchimera/stealth`

Date: 2026-09-14. Scope: the stealth package at the tip of the
user-model → temporal feature chain (PRs #55–#61). Method: symbol-level
code reading, full suite (1952 passed, 2 skipped, 124 subtests), `ruff
check` + `ruff format --check`, and the strict project scan (`pass`,
0 high-severity findings).

## What exists and where

| Area | Module | Tests |
|---|---|---|
| Events, envelope, replayable bus | `events.py`, `event_bus.py` (`replay()`) | existing |
| Attention engine | `attention.py` | existing |
| Intent + friction | `intent.py` | existing |
| Experience model/stream/graph | `eve_model.py`, `experience.py` | existing |
| Prediction | `prediction.py` | existing |
| Policy + evaluator | `stealth_policy.py` | existing |
| Maturity governance | `governance.py` | existing |
| Interventions + outcomes | `intervention.py` | existing |
| Hooks (programmatic + declarative) | `hooks.py` | existing |
| Host adapters | `hosts.py` | existing |
| Context fabric + injection | `context.py` | existing |
| Perception hierarchy + live backends | `perception.py`, `computer.py`, `computer_live.py`, `cdp.py` | existing |
| Persistence | `store.py`, `bpo_store.py` | existing |
| Offline evals (retrieval, prediction, intervention, timing, precision, suppression, cost, safety) | `eval.py` | existing |
| Secret fencing | `untrusted.py` | existing |
| User model (4 layers, trait lifecycle, work graph) | `user_model.py` | `tests/test_user_model.py` |
| Standing context projection | `standing_context.py` | `tests/test_standing_context.py` |
| Declarative triggers | `triggers.py` | `tests/test_triggers.py` |
| Graduated proposal tiers | `graduation.py` | `tests/test_graduation.py` |
| Approval requests | `approvals.py` | `tests/test_approvals.py` |
| Cost/attention budgets | `budgets.py` | `tests/test_budgets.py` |
| Temporal context | `temporal.py` | `tests/test_temporal.py` |

`StealthLoop` (`loop.py`) is the sole integrator: every new module is
observed or consulted on the two event hot paths (32 references) with
zero decision impact — proven per-PR by decision-equality tests against
unwired loops.

## Attribution correction

The PR chain (#55–#61) cited master-spec section numbers (§§3–6, 11,
14, 15, 18, 19, 24, 33) from the author's reading. Grep over the repo
shows **no code cites those numbers**, and two collide with anchored
citations:

- "Standing context (§6)" vs `perception.py` / `eve_model.py` §6
  (perception hierarchy).
- "Temporal context (§15)" vs `hosts.py` §15 (universal host contract).

The modules are real, tested, and integrated; only the numbers are
unverified. `MIGRATION_MATRIX.md` separates code-anchored sections from
author-attributed ones so the next reader does not inherit the
confusion.

## Risks

1. **Seven-deep unmerged stack** (#55 → #56 → #57 → #58 → #59 → #60 →
   #61). Merge strictly bottom-up; each stacked PR retargets to `main`
   once its base lands.
2. **Unmetered cost budget.** `COST_BUDGET` ships structured but no
   executor records spend yet; proposals and attention are metered.
3. **No outbound notification channel.** `notification.received` events
   are consumed, but stealth/ has no user-notify sink; ASK approvals
   wait in the queue with no delivery path beyond the API return.

## Residual gaps (verified absent)

- Executor cost-metering hooks for `COST_BUDGET`.
- Outbound user notification delivery for approvals/suggestions.
- Spec-attribution pass against the master document for the
  author-numbered rows in the matrix.
