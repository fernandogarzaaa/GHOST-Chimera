# Ghost Chimera Trust, Evolution, And Operator Platform Design

## Purpose

This design upgrades Ghost Chimera across three connected workstreams:

1. **Production Trust OS** - make every autonomous action measurable, replayable, gated, and regression-tested.
2. **Self-Evolving Personal Ghost** - let users safely improve their Ghost through approved data, skills, models, and workflow patterns.
3. **Operator UX And Demo Polish** - make the full platform usable from Ghost Console without requiring non-technical users to edit files or environment variables.

The goal is not to add another isolated feature. The goal is to turn Ghost Chimera into a local-first operator platform where every capability has a trust path, every improvement has provenance, and every user can see what their Ghost is ready to do next.

## Current Baseline

Ghost Chimera already includes the major runtime building blocks:

- Ghost Console with Config, Models, Paths, GitHub, Remote Control, Thinking, Jobs, Workspace, Memory, MiniMind, RAG Builder, MCP, Skills, Self-Evolution, Activity, Latency, Local Models, Cognitive Guardrails, Capability Pack, Sandbox, Browser, Security, Schedules, Review, Capabilities, and Readiness surfaces.
- Trust Runtime with durable run journals, approval checkpoints, MCP trust registry, trust eval baselines, and local OTel-compatible trace exports.
- Consent-gated Personal MiniMind, local memory/RAG handoff, path synthesis, model discovery, native capability pack, remote command approval, and release validation.

This design builds on those surfaces. It must not replace them with parallel systems.

## Design Principles

- **Local-first by default:** no mandatory cloud dependency, collector, external MCP registry, hosted queue, or vendor-specific runtime.
- **Consent-gated improvement:** no scraping, indexing, dataset generation, model switching, skill activation, connector use, or training without explicit approval.
- **Trust before evolution:** self-evolution candidates must pass capability admission and trust eval checks before promotion.
- **No hidden chain-of-thought:** expose operational traces, run stages, policy decisions, tool eligibility, evidence references, and model routing reasons, not private reasoning.
- **Modular optionality:** Bob developer tooling, external MCP servers, hosted model providers, GitHub OAuth, mobile messaging, and local model runtimes remain optional modules.
- **Measurable completion:** each implemented upgrade needs backend models, CLI/API/Console wiring, tests, docs, and release-gate coverage.

## Workstream A: Production Trust OS

### A1. Trust Eval Flywheel 2.0

Trust Runtime journals become reusable regression cases. A run can be marked as useful, risky, failed, or representative. Ghost Chimera converts selected data into `TrustEvalCase` records with redacted inputs, expected policy outcomes, expected tool-risk posture, and replay-safe result references.

Eval families:

- **Policy evals:** execution policy, approval requirements, production guardrails, remote direct-execution gates.
- **Tool evals:** tool risk classification, idempotency, schema compliance, output sanitation.
- **MCP evals:** unapproved server blocks, high-risk tool ceilings, tool-poisoning signals, capability escalation.
- **RAG and MiniMind evals:** source consent, provenance, stale source detection, citation quality, dataset preview safety.
- **Model routing evals:** provider readiness, fallback behavior, model disappearance, cost/latency budget fit.
- **Operator UX evals:** guided setup completion, dashboard-only configuration, run replay availability.

Console exposes:

- Trust score trend.
- Latest baseline age.
- P0/P1 safety failures.
- Eval case sources.
- Baseline comparison.
- “Promote this run to eval case” action.

### A2. Capability Admission System

Every activatable capability uses a shared admission record before use:

- Models.
- MCP servers.
- Skills.
- GitHub/self-evolution sources.
- Connectors.
- Local model candidates.
- Remote-control channels.
- Capability-pack extensions.

Admission statuses:

- `discovered`
- `inspected`
- `review_required`
- `approved`
- `active`
- `quarantined`
- `revoked`

Admission checks:

- Manifest presence and source identity.
- Requested permissions.
- Trust class and risk ceiling.
- Static inspection result.
- Sandbox or dry-run result when applicable.
- Provenance and license notes.
- Secret-handling posture.
- Required evals.
- Human approval.

Nothing moves from discovered to active automatically in this phase.

### A3. Trust Runtime Hardening

Trust Runtime should expand from current local journals into stronger runtime guarantees:

- Store resume tokens in a dedicated ledger with single-use state.
- Add journal compaction snapshots while preserving append-only raw records.
- Add tamper-evident hashes for run journals.
- Add trace export bundles per run and per baseline.
- Add production readiness checks for stale trust baselines and unreviewed high-risk capabilities.
- Add explicit run-fork simulation support for future replay studio.

## Workstream B: Self-Evolving Personal Ghost

### B1. Personal Ghost Training Lab

Training Lab is an operator-facing surface for safe improvement planning. It does not auto-train by default.

Core flow:

1. User selects learning sources.
2. Ghost previews source metadata and risk.
3. User approves source scope.
4. Ghost extracts topics, examples, and candidate memories.
5. Ghost generates dataset preview records.
6. Ghost generates eval cases from dataset preview records.
7. User approves dataset export or local training readiness.
8. Ghost records provenance, consent, and trust score impact.

Supported source types:

- GitHub repositories.
- Local folders and files.
- Uploaded text.
- Docs URLs.
- Email exports.
- MCP capabilities.
- Model catalogs.
- Manual notes.

Safety requirements:

- Source-specific consent is required.
- Revoked sources stop contributing to future recommendations.
- Dataset previews redact secrets and flag PII.
- Training readiness does not imply training execution.
- Training execution requires a separate explicit future approval.

### B2. Self-Evolution Candidate Ranking

Self-Evolution candidates should be ranked with transparent criteria:

- Path fit.
- Source trust.
- Permission cost.
- Eval coverage.
- Latency/cost impact.
- Compatibility score.
- Risk level.
- User value.
- Reversibility.

Candidate types:

- RAG knowledge update.
- Ghost Path recommendation.
- Skill scaffold.
- MCP capability.
- Model recommendation.
- Config improvement.
- Connector suggestion.
- Workflow automation.

The output is recommendation-first, not activation-first.

### B3. Model And Context Evolution

Model discovery should feed self-evolution without switching models automatically.

Add:

- Primary and fallback recommendation sets by Ghost Path.
- Context compression profiles by task type.
- Cost class and latency class tracking.
- Model disappearance and pricing-change alerts.
- “Test before save” compatibility pings.
- Local/private model candidates alongside hosted models.

The operator must explicitly save active model choices.

## Workstream C: Operator UX And Demo Polish

### C1. Operator Command Center

Home should become the first screen for all non-technical users. It should show:

- Active Ghost Path.
- Active provider/model.
- Config health.
- MiniMind/RAG readiness.
- MCP trust readiness.
- Skill admission status.
- Connector status.
- Self-Evolution status.
- Trust baseline status.
- Latency/cost posture.
- Production readiness warnings.
- Recommended next action.

Each card links directly to the action that fixes the issue.

### C2. Replay And Simulation Studio

Replay Studio lets users inspect a run without exposing hidden chain-of-thought.

It shows:

- Goal intake.
- Context retrieval.
- Source selection.
- Policy check.
- Model routing.
- Tool eligibility.
- Approval boundary.
- Execution preview.
- Tool results.
- Eval outcome.
- Trace export.

Simulation modes:

- Replay same run.
- Fork from checkpoint.
- Try different model.
- Try stricter policy.
- Disable a tool.
- Compare latency/cost/trust impact.

Mutating actions are preview-only unless explicitly approved.

### C3. Connector Vault

Connector Vault is the no-code permissions center.

Connectors:

- GitHub.
- Email artifacts.
- Calendar later.
- Slack/Discord/Signal/Webhook remote messaging.
- Local folders.
- MCP servers.
- Custom HTTP endpoints later.

Each connector shows:

- Configured/not configured.
- Auth status.
- Secret fields configured without exposing values.
- Approved Ghost Paths.
- Allowed actions.
- Risk ceiling.
- Last health check.
- Expiration or rotation status.
- Revoke button.

### C4. Ghost Teams

Ghost Teams lets a user compose multiple role-specific Ghosts:

- Manager Ghost.
- Engineer Ghost.
- Analyst Ghost.
- Marketing Ghost.
- Virtual Assistant Ghost.
- Security Reviewer Ghost.
- Research Ghost.

Each Ghost has:

- Path profile.
- Model profile.
- Tool permissions.
- Memory scope.
- Connector scope.
- Trust baseline.
- Handoff contract.

Team runs use explicit handoff records and conflict arbitration. A team member cannot access another member’s memory or connector scope unless explicitly allowed.

## Architecture

### New Backend Concepts

- `CapabilityAdmissionRecord`
- `TrustEvalCase`
- `TrustBaselineComparison`
- `TrainingLabSource`
- `DatasetPreviewRecord`
- `EvolutionRank`
- `ConnectorRecord`
- `GhostTeam`
- `GhostTeamMember`
- `ReplayScenario`
- `SimulationResult`

### Storage

Use the Ghost state directory and keep all new state local:

- `trust_runtime/eval_cases.jsonl`
- `trust_runtime/baselines/*.json`
- `capability_admission/records.json`
- `training_lab/sources.json`
- `training_lab/dataset_previews/*.jsonl`
- `connectors/vault.json`
- `ghost_teams/teams.json`
- `replay/scenarios.json`

All stores must redact secret values and keep raw credentials in existing write-only secret paths when needed.

### API Surfaces

Add or extend:

- `/api/console/trust/eval-cases`
- `/api/console/trust/eval-cases/promote`
- `/api/console/capability-admission`
- `/api/console/capability-admission/{id}/approve`
- `/api/console/capability-admission/{id}/revoke`
- `/api/console/training-lab/sources`
- `/api/console/training-lab/preview`
- `/api/console/training-lab/evals`
- `/api/console/connectors`
- `/api/console/connectors/{id}/configure`
- `/api/console/connectors/{id}/revoke`
- `/api/console/replay/runs/{id}`
- `/api/console/replay/runs/{id}/simulate`
- `/api/console/ghost-teams`
- `/api/console/ghost-teams/{id}/run`

Reuse existing Trust Runtime, Self-Evolution, Model Discovery, Remote Control, MCP, GitHub, RAG Builder, and MiniMind APIs where possible.

### CLI Surfaces

Add:

- `ghostchimera trust eval-cases list`
- `ghostchimera trust eval-cases promote <run_id>`
- `ghostchimera capability-admission list`
- `ghostchimera capability-admission approve <id>`
- `ghostchimera training-lab preview`
- `ghostchimera connector list`
- `ghostchimera replay show <run_id>`
- `ghostchimera replay simulate <run_id>`
- `ghostchimera ghost-team list`
- `ghostchimera ghost-team run <team_id> --objective "..."`

### Console Surfaces

Add or upgrade tabs:

- Home -> Operator Command Center.
- Trust Runtime -> eval cases, baselines, comparisons, trace bundles.
- Self-Evolution -> candidate ranking and capability admission status.
- Training Lab -> sources, dataset previews, generated evals.
- Connectors -> Connector Vault.
- Replay -> Replay and Simulation Studio.
- Ghost Teams -> role composition and team run preview.

## Error Handling

- Missing optional integrations degrade to “needs config,” not crashes.
- Secret fields are write-only and never returned by APIs.
- Revoked sources or connectors cannot contribute to recommendations.
- Unapproved capabilities cannot execute high-risk actions.
- Simulation must not mutate state unless the user explicitly approves a real run.
- Stale trust baselines warn but do not block development mode.
- Production readiness fails when there are unreviewed high-risk capabilities, unresolved approvals, or P0 trust eval failures.

## Testing Strategy

### Unit Tests

- Capability admission state transitions.
- Trust eval case generation from journals.
- Dataset preview redaction and provenance.
- Connector secret redaction.
- Ghost Team member scope isolation.
- Replay scenario validation.
- Simulation no-mutation guarantee.

### Integration Tests

- Console run -> trust journal -> eval case promotion -> baseline comparison.
- Model discovery candidate -> capability admission -> explicit activation.
- Learning source -> dataset preview -> generated eval -> source revocation.
- MCP server -> admission review -> trust registry approval -> high-risk tool block/pass.
- Remote `/run` -> trust checkpoint -> replay view.
- Ghost Team run -> handoff record -> conflict arbitration.

### Static/UI Tests

- `node --check ghostchimera/control_plane/static/app.js`
- UI includes Operator Command Center, Training Lab, Connectors, Replay, Ghost Teams, Trust Eval Flywheel, and Capability Admission controls.
- No visible UI path asks non-technical users to edit `.env` for common setup.

### Release Gate

- `python scripts/validate_release.py`
- `python -m pytest -q`
- `ghostchimera trust eval baseline`
- `ghostchimera capability-admission list`
- `ghostchimera connector list`
- `ghostchimera replay show latest`

## Implementation Phases

### Phase 1: Trust Eval Flywheel And Capability Admission

Build eval-case promotion, baseline comparison improvements, admission records, CLI/API/Console surfaces, and release-gate checks.

### Phase 2: Connector Vault And Training Lab

Unify provider keys, GitHub, remote channels, local folders, email artifacts, MCP servers, and future connectors into a no-code vault. Add dataset preview and generated evals.

### Phase 3: Replay Studio And Ghost Teams

Add replay inspection, simulation, run forking, team definitions, scoped handoffs, and team run previews.

### Phase 4: Operator Command Center Polish

Unify home cards, next-action recommendations, demo flows, tutorial links, and readiness messaging.

## Non-Goals

- No automatic scraping.
- No automatic training.
- No automatic model switching.
- No hidden chain-of-thought exposure.
- No required cloud observability collector.
- No required external MCP registry.
- No forced Bob dependency at runtime.
- No claim that Ghost Chimera is AGI or a secure sandbox for arbitrary untrusted code.

## Open Decisions

1. Whether Phase 1 should include tamper-evident journal hash chains immediately or reserve them for a hardening subphase.
2. Whether Connector Vault should store connector config in a new unified file first or migrate existing remote/GitHub/config stores into adapters gradually.
3. Whether Ghost Teams should ship as preview-only first or support real supervised team execution in the first release.

Recommended defaults:

1. Include hash chains in Phase 1 because trust artifacts need integrity.
2. Use adapters first to avoid risky migrations.
3. Ship Ghost Teams preview-first, then enable supervised execution after eval coverage exists.
