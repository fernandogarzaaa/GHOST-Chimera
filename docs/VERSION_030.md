# Migration Guide: v0.2.0 → v0.3.0

## Overview

Ghost Chimera v0.3.0-beta is a substantial release that transforms the control plane from a CLI-only interface to a full console-based web application with REST API and WebSocket streaming. The core reasoning loop and safety system are unchanged.

## Breaking Changes

### Removed: Inline console in CLI

The previous `ghostchimera console` command launched a minimal inline TUI. This has been replaced by a browser-based console served by the GatewayServer.

```bash
# Old (removed):
ghostchimera console --no-open

# New:
ghostchimera gateway --no-open  # starts HTTP server + opens browser
```

### New: Static file serving

The console SPA lives in `ghostchimera/control_plane/static/`. The GatewayServer automatically serves these files at:

| URL | Content |
|-----|-------|
| `/` | Ghost Console |
| `/console` | Ghost Console (alias) |
| `/static/app.js` | Console JS |
| `/static/styles.css` | Console CSS |

### REST API surface

All console operations now use REST endpoints at `/api/console/*`. The GatewayServer registers these automatically. See `docs/GATEWAY_SERVER.md` for the full route list.

### Removed: External MCP server references

The previous CLAUDE.md referenced an external `chimeralang-mcp` package. This was never published — the control plane is now self-contained.

## New Features

### Ghost Console SPA

A dark-themed single-page application with tabs:

- **Status**: Gateway health, backend count, autonomy profile, policy posture
- **Run**: Objective textarea, profile selector, streaming output via WebSocket
- **Jobs**: Job list, preview/run controls, schedule integration
- **Workspace**: Evidence/reflection management, sync-to-CWR
- **Schedules**: Schedule CRUD for recurring tasks
- **Readiness**: Release checklist from `/api/console/readiness`

### Production Mode Guardrails

`ghostchimera.safety_layer.production.ProductionGuardrails` enforces pre-deployment checks:

- `deployment_mode` (development / production / prod / enterprise)
- `external_isolation` (container, vm, service-account, sandboxed)
- `security_reviewed` and `human_approval_required` environment variables

`ghostchimera doctor --production` reports guardrail readiness status.

### Mixture of Agents (MoA)

New reasoning strategy: spawn N independent agents with diverse prompts, score outputs, detect consensus via Jaccard similarity, report contradictions.

### Cron Scheduler

Persistent scheduled task execution via `croniter` with JSON state persistence and background loop.

### Unit Test Suite Expansion

Added 6 new test files (213 new test cases):

- `test_ssrf_policy.py` — SSRF policy IP blocking, allow/deny lists
- `test_approval_flow.py` — Approval policy, handlers, result types
- `test_cron_scheduler.py` — Cron expression parsing, job lifecycle
- `test_error_classifier.py` — Error taxonomy, classification rules
- `test_provider_routing.py` — Provider instantiation, validation
- `test_mixture_of_agents.py` — MoA scoring, consensus, contradictions

### Coverage Eval Suite

9 eval cases across SSRF, approval, production, MoA, error classification, checkpoint, and telemetry.

## New Documentation

7 new docs in `docs/`:

| File | Topic |
|------|------|
| AGENT_LOOP.md | AIAgent, ContextCompressor, MCPWrapper |
| CREDENTIAL_POOL.md | Multi-provider auth, key rotation |
| SUBAGENT_DELEGATION.md | SubagentPool, spawn patterns |
| MIXTURE_OF_AGENTS.md | MoA strategy, voting, consensus |
| GATEWAY_SERVER.md | WebSocket, REST routes, static files |
| CRON_SCHEDULER.md | Cron expressions, schedule lifecycle |
| VERSION_030.md | This file |

## Upgrading

1. Update dependency: `pip install -e .`
2. No database migration needed (all state is in user's `~/.ghostchimera/`)
3. Existing `ghostchimera doctor`, `ghostchimera run`, `ghostchimera batch` commands unchanged
4. The `ghostchimera console --no-open` path now starts the GatewayServer

## Test Coverage

- 570+ existing tests (unchanged)
- 213 new unit tests
- 9 new coverage eval cases
- 4 new production mode eval cases
