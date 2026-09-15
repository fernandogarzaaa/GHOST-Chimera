# Migration Matrix — master spec to implementation

Status key: **anchored** = a code docstring cites the section;
**attributed** = number comes from the author's spec reading, no code
citation; **partial** = capability exists with a known hole;
**missing** = verified absent by symbol search.

## Code-anchored sections

| Spec | Capability | Status | Location |
|---|---|---|---|
| §4 | Experiential state | anchored | `ghostchimera/stealth/eve_model.py` |
| §5 | Event types, environment state | anchored | `ghostchimera/stealth/events.py`, `eve_model.py` |
| §6 | Perception hierarchy | anchored | `ghostchimera/stealth/perception.py`, `eve_model.py` |
| §7 | Attention engine | anchored | `ghostchimera/stealth/attention.py` |
| §8 | Sequence understanding | anchored | `ghostchimera/stealth/eve_model.py` |
| §9 | Friction detection | anchored | `ghostchimera/stealth/intent.py` |
| §10 | Intent hypotheses | anchored | `ghostchimera/stealth/intent.py` |
| §11 | Prediction, evaluator ladder | anchored | `ghostchimera/stealth/prediction.py`, `stealth_policy.py`, `eve_model.py` |
| §12, §34 | Interventions, modes, provenance | anchored | `ghostchimera/stealth/intervention.py`, `eve_model.py` |
| §15 | Universal host contract | anchored | `ghostchimera/stealth/hosts.py` |
| §16 | Experience stream, /ghost UX | anchored | `ghostchimera/stealth/eve_model.py`, `hosts.py` |
| §19 | Workflow lifecycle/maturity | anchored | `ghostchimera/stealth/governance.py`, `eve_model.py` |
| §20–§22 | Evaluator, outcomes | anchored | `ghostchimera/stealth/stealth_policy.py`, `eve_model.py` |
| §23 | Provenance, outcome feedback | anchored | `ghostchimera/stealth/intervention.py`, `eve_model.py` |
| §24 | Experience-model scope (module list only) | anchored-partial | `ghostchimera/stealth/eve_model.py` |
| §29 | Offline eval dimensions | anchored | `ghostchimera/stealth/eval.py` |
| §36 | Ghost policy configuration | anchored | `ghostchimera/stealth/stealth_policy.py` |

## Implemented, author-attributed (no code citation — verify)

| Spec (claimed) | Capability | Location | Evidence |
|---|---|---|---|
| §3–§5 | Layered user model | `ghostchimera/stealth/user_model.py` | `tests/test_user_model.py` (15 tests) |
| §6-adjacent | Standing context projection | `ghostchimera/stealth/standing_context.py` | `tests/test_standing_context.py` (9 tests); collides with anchored §6 |
| §11-adjacent | Graduated proposal tiers | `ghostchimera/stealth/graduation.py` | `tests/test_graduation.py` (11 tests) |
| §14 | Declarative triggers | `ghostchimera/stealth/triggers.py` | `tests/test_triggers.py` (11 tests) |
| §15-adjacent | Temporal context | `ghostchimera/stealth/temporal.py` | `tests/test_temporal.py` (12 tests); collides with anchored §15 |
| §18–§19 | Cost/attention budgets | `ghostchimera/stealth/budgets.py` | `tests/test_budgets.py` (8 tests); cost side unmetered |
| §24-adjacent | Approval requests | `ghostchimera/stealth/approvals.py` | `tests/test_approvals.py` (10 tests) |
| §33-adjacent | Generated host files | `standing_context.py` (`write_if_changed`) | `tests/test_standing_context.py` |
| §47 | This audit + matrix | `docs/ARCHITECTURE_AUDIT.md` | this file |

## Missing (verified absent)

| Capability | Notes |
|---|---|
| Executor cost metering | `COST_BUDGET` defined in `ghostchimera/stealth/budgets.py`; nothing records spend |
| Outbound user notification | `notification.received` consumed in `attention.py`; no notify sink in stealth/ |

## How to use this file

When the master spec is at hand, resolve each "adjacent/attributed"
row to its true number (or confirm the claim) and promote it to the
anchored table. Do not renumber modules until then — the collision
notes above are load-bearing.
