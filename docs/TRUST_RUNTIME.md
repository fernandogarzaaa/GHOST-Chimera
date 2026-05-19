# Trust Runtime

Ghost Chimera's Trust Runtime is a local-first safety and observability layer for long-running agent work. It adds durable run journals, resumable approval checkpoints, MCP trust controls, local trust eval baselines, and OTel-compatible JSON trace exports without requiring LangGraph, Temporal, an OpenTelemetry collector, or an external MCP registry.

## What It Stores

Trust Runtime state lives under the configured Ghost state directory:

- `trust_runtime/run_index.json` - compact run index.
- `trust_runtime/runs/*.jsonl` - append-only step journals.
- `trust_runtime/runs/*.tools.jsonl` - tool and MCP call records.
- `trust_runtime/approvals.json` - approval checkpoints.
- `trust_runtime/mcp_trust.json` - local MCP trust registry.
- `trust_runtime/trust_eval_baseline.json` - latest local trust baseline.
- `trust_runtime/eval_cases.jsonl` - promoted reusable eval cases.
- `capability_admission/records.json` - explicit review records for models, MCP servers, skills, RAG sources, config changes, and tools.

Stored inputs and outputs are reduced to hashes and redacted previews. Raw credentials, hidden chain-of-thought, full private files, and raw prompts are not exported by default.

Run journals are append-only JSONL records with a local hash chain. Each record
stores `previous_hash` and `record_hash`, so tampering is visible through the
integrity check without needing a network service.

## CLI

```bash
ghostchimera trust status
ghostchimera trust runs list
ghostchimera trust runs show <run_id>
ghostchimera trust runs resume <run_id>
ghostchimera trust trace export latest
ghostchimera trust eval baseline
ghostchimera trust eval compare
ghostchimera trust eval-cases list
ghostchimera trust eval-cases promote <run_id> --label "Remote approval regression" --severity P1
ghostchimera mcp trust list
ghostchimera mcp trust approve chimeralang --risk-ceiling medium
ghostchimera mcp trust revoke chimeralang
ghostchimera capability-admission list
ghostchimera capability-admission inspect --kind model --name openrouter/fast-model --source openrouter --risk medium
ghostchimera capability-admission approve <record_id>
ghostchimera capability-admission activate <record_id>
```

`resume` only succeeds at safe boundaries. A pending approval must be resolved first, failed mutating work is not replayed blindly, and idempotency keys prevent duplicate step records.

## Console

Ghost Console exposes a **Trust Runtime** tab and API routes:

- `GET /api/console/trust/summary`
- `GET /api/console/trust/runs`
- `GET /api/console/trust/runs/{id}`
- `POST /api/console/trust/runs/{id}/resume`
- `GET /api/console/trust/approvals`
- `POST /api/console/trust/approvals/{id}/approve`
- `POST /api/console/trust/approvals/{id}/deny`
- `GET /api/console/trust/traces/{id}/export`
- `GET /api/console/trust/evals`
- `POST /api/console/trust/evals/baseline`
- `GET /api/console/trust/eval-cases`
- `POST /api/console/trust/eval-cases/promote`
- `GET /api/console/capability-admission`
- `POST /api/console/capability-admission`
- `POST /api/console/capability-admission/{id}/approve`
- `POST /api/console/capability-admission/{id}/activate`
- `POST /api/console/capability-admission/{id}/revoke`
- `POST /api/console/capability-admission/{id}/quarantine`
- `GET /api/console/mcp/trust`
- `POST /api/console/mcp/trust/{server_id}/approve`
- `POST /api/console/mcp/trust/{server_id}/revoke`

Console runs and paired remote `/run` commands create durable journal records. Remote `/run` requests also create a Trust Runtime approval checkpoint unless direct execution is explicitly enabled for a paired admin.

## MCP Zero Trust

External MCP output is treated as untrusted by default. Tool calls receive a `ToolTrustEnvelope` with risk level, source trust, expected schema, required approval, sanitation status, and violations. The runtime blocks high-risk MCP tools unless the local MCP trust registry approves the server and risk ceiling.

The sanitation pass detects common prompt-injection language, schema mismatch, secret-like output, and unexpected high-risk tool posture. This is a defense-in-depth check, not a replacement for human review of new MCP servers.

## Eval Flywheel

Trust baselines convert recent durable runs, approval checkpoints, MCP trust records, and blocked safety steps into reusable local eval cases:

```bash
ghostchimera trust eval baseline
ghostchimera trust eval compare
ghostchimera trust eval-cases promote <run_id>
ghostchimera trust eval-cases list
```

Promotion is explicit. A run does not become part of future trust baselines
until an operator promotes it from the CLI or Console. This makes real operator
incidents, red-team cases, remote-control approvals, and MCP violations reusable
without silently training or changing runtime behavior.

Production readiness should require a fresh trust baseline, no unresolved approvals, no unreviewed high-risk MCP servers, and zero P0 trust failures.

## Capability Admission

Capability Admission is the review gate for new capability sources. It is
local-first and does not activate anything automatically. Operators can record
models, MCP servers, skills, RAG sources, config changes, and tools with a risk
level, permission list, source, and redacted metadata. Records move through:

`discovered -> inspected -> review_required -> approved -> active`

Records can also be revoked or quarantined. Critical or high-risk records keep
production readiness in `review` until a human approves or disables them.

Activation-sensitive flows call this gate directly. Model Discovery will not
save a newly selected model until its model admission record is active.
Self-Evolution will not promote a candidate until its candidate admission record
is active. MCP trust approvals keep the MCP trust registry and admission record
in sync.

## Trace Export

Trace export returns local JSON with stable Ghost fields and `gen_ai.*`-style attributes:

```bash
ghostchimera trust trace export latest
```

Network OTLP export is intentionally not enabled in this phase. Operators can review the JSON bundle locally and decide whether to bridge it into external observability tooling later.
