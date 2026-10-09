# Gateway Server Architecture

## Architecture

The Gateway Server lives in `ghostchimera/chimera_pilot/gateway_server.py` and serves as the network-facing layer of Ghost Chimera.

### Server Types

1. **GatewayServer**: Main REST + WebSocket server (`server_type="gateway"`). Serves the Ghost Console UI at `/`, REST API at `/api/console/*`, and WebSocket streaming at `/api/console/stream`.
2. **Backend server**: Lightweight backend service that exposes `probe()`, `can_run()`, `execute()` endpoints.

### REST API Routes

All console routes are registered via `register_console_routes()` and include:

| Route | Method | Description |
|-------|--------|-------------|
| `/api/console/status` | GET | Gateway health, backend count, autonomy profile, policy posture |
| `/api/console/autonomy` | POST | Change autonomy profile level |
| `/api/console/autonomy/jobs` | GET | List autonomy job history |
| `/api/console/autonomy/jobs` | POST | Run an autonomy job (preview or execute) |
| `/api/console/autonomy/schedules` | GET/POST | Schedule CRUD |
| `/api/console/autonomy/schedules/{id}/{action}` | POST | Enable/disable/delete/run schedule |
| `/api/console/workspace` | GET | Current workspace state (evidence, reflections) |
| `/api/console/workspace/evidence` | POST | Add evidence |
| `/api/console/workspace/sync-memory` | POST | Sync workspace to CWR memory |
| `/api/console/memory/status` | GET | Local personal memory status |
| `/api/console/memory/ingest-email` | POST | Ingest raw, `.eml`, or `.mbox` email into memory |
| `/api/console/memory/ingest-file` | POST | Ingest approved local file or directory into memory |
| `/api/console/minimind/status` | GET | MiniMind architecture/runtime status |
| `/api/console/minimind/personal/status` | GET | Personal MiniMind consent, memory, dataset, and handoff readiness |
| `/api/console/minimind/personal/consent` | POST | Grant Personal MiniMind admin, source-scope, whole-machine, and email-crawl consent |
| `/api/console/minimind/personal/revoke` | POST | Revoke Personal MiniMind consent |
| `/api/console/minimind/personal/bootstrap` | POST | Bootstrap Personal MiniMind from consented local sources |
| `/api/console/minimind/personal/handoff` | POST | Build a personal RAG handoff prompt for the primary model |
| `/api/console/readiness` | GET | Release readiness checklist |
| `/api/console/browser/status` | GET | Browser workspace status |

### WebSocket Streaming

The `/api/console/stream` endpoint provides real-time output streaming:

1. Client connects via WebSocket with an `objective` parameter
2. The GatewayServer creates a `ResultEnvelope` and streams updates
3. Each turn sends a JSON message: `{"type": "turn", "turn": N, "output": "..."}`
4. Final message: `{"type": "done", "result": { ... }}`

### Durable sessions

Gateway sessions survive restarts. Every session snapshot (message history,
token totals, compression count, confidence history, gateway bookkeeping) is
persisted to the trust runtime store at
`<state_dir>/trust_runtime/sessions.json` (see `TrustRuntimeStore.save_session`
/ `get_session` / `list_sessions` / `delete_session`):

- `create_session()` snapshots immediately; every agent turn re-snapshots in a
  `finally` block, so a `kill -9` loses at most one turn.
- Writes are atomic (temp file + rename) and **unredacted**: redaction would
  corrupt message fidelity on resume. The state dir is local-only.
- `get_session()` rehydrates lazily: a restarted gateway rebuilds the
  `GatewaySession` + `AIAgent` from the snapshot the first time the
  session id is requested, so restarts cost nothing until a client
  reconnects.
- `GET /sessions` merges live sessions with stored snapshots; stored-only
  sessions are marked `"resumable": true`.
- WebSocket message type `"resume"` (or `GatewayServer.resume_session()`)
  returns a resume receipt: session id, `resume_from_message`, history depth,
  and token totals, so a dropped client can verify continuity.

`SessionState.to_dict()` / `from_dict()` / `save(store)` / `load(store, id)`
in `ghostchimera/chimera_pilot/agent_loop.py` implement the serialization.

### Audit state-dir decision

Approval decisions made in the agent loop (`AIAgent._execute_tool_calls`)
are appended to the same audit trail the connector write-gate path uses:
`<state_dir>/audit/connector-audit.jsonl` (event `approval_decision`,
provider `agent-loop`). The state dir resolves in this order: explicit
`state_dir` constructor argument, then `config.state_dir`, then
`~/.ghostchimera`. Pass `audit_trail=` to inject a custom sink (used by
tests).

### Static File Serving

The GatewayServer serves the Ghost Console static files from `ghostchimera/control_plane/static/`:

- `/` → `index.html`
- `/console` → `index.html` (fallback)
- `/static/app.js` → `app.js`
- `/static/styles.css` → `styles.css`

The `_register_static_routes()` function reads each file once at startup and registers it as a static route.

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/gateway_server.py` | GatewayServer, HTTP/WS routes |
| `ghostchimera/control_plane/console.py` | register_console_routes(), release checks |
| `ghostchimera/control_plane/static/` | Ghost Console SPA |
