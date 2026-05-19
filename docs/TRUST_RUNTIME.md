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

Stored inputs and outputs are reduced to hashes and redacted previews. Raw credentials, hidden chain-of-thought, full private files, and raw prompts are not exported by default.

## CLI

```bash
ghostchimera trust status
ghostchimera trust runs list
ghostchimera trust runs show <run_id>
ghostchimera trust runs resume <run_id>
ghostchimera trust trace export latest
ghostchimera trust eval baseline
ghostchimera trust eval compare
ghostchimera mcp trust list
ghostchimera mcp trust approve chimeralang --risk-ceiling medium
ghostchimera mcp trust revoke chimeralang
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
```

Production readiness should require a fresh trust baseline, no unresolved approvals, no unreviewed high-risk MCP servers, and zero P0 trust failures.

## Trace Export

Trace export returns local JSON with stable Ghost fields and `gen_ai.*`-style attributes:

```bash
ghostchimera trust trace export latest
```

Network OTLP export is intentionally not enabled in this phase. Operators can review the JSON bundle locally and decide whether to bridge it into external observability tooling later.
