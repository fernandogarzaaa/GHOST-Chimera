# Security Policy

## Supported status

Ghost Chimera is currently a beta developer release. Security fixes should target the latest published source revision.

## High-risk capabilities

Ghost Chimera contains components that can execute local work when explicitly enabled:

- Chimera Pilot `PythonRuntimeBackend` for Python snippets and unittest discovery.
- `tool_layer.shell` for shell commands.
- filesystem tools for local reads/writes.
- browser/network tools when configured.
- optional local model runtimes loaded through minimind-compatible or llama.cpp adapters.
- optional live desktop control via `DesktopRuntimeBackend` (dry-run by default).

These are powerful primitives. Do not run untrusted prompts, untrusted code, or untrusted repositories without external sandboxing such as a container, VM, or restricted service account.

## Default protections

Chimera Pilot ships with conservative defaults:

- network tasks are denied by default;
- Python/test execution is denied by default;
- Python execution requires an explicit policy/CLI opt-in;
- Python runs with a minimal environment, bounded timeout, isolated interpreter mode, bytecode disabled, and temporary cwd by default;
- high-risk Python fragments and calls are rejected before execution;
- execution telemetry records backend id, success/failure, timing, and error metadata.

The AgentCore tool path also requires an `ExecutionPolicy` before shell, filesystem, or browser tools run. File access is constrained to configured roots, shell commands are parsed without `shell=True`, command execution is timeout-bounded, and local tool attempts are written to the audit log.

The `SSRFPolicy` layer blocks requests to private IP ranges and cloud metadata endpoints by default. The `BuiltinDPIEngine` (LobsterTrap) scans inputs for prompt injection, credential leaks, PII, and data exfiltration instructions before they reach the execution layer.

The Ghost Console HTTP API (`ghostchimera console` / `start`) is never open by default:

- a random console token is generated on first run, stored owner-only (0600) in `~/.ghostchimera/console_secrets.json` (or `<state-dir>/console_secrets.json`), printed once, and required on every `/api/*` route and the WebSocket (`X-Gateway-Token` or `Authorization: Bearer`); `--auth-token` overrides it for a run;
- every request must carry a `Host` of `localhost`, `127.0.0.1` or `[::1]` (any port), the concrete bind host, or a host allowed with `--allow-host` / `GHOSTCHIMERA_CONSOLE_ALLOWED_HOSTS` (DNS-rebinding defence);
- POST/PUT/PATCH/DELETE requests with a foreign or `null` `Origin`, or `Sec-Fetch-Site: cross-site`, are refused, and must be `Content-Type: application/json` (signed `/api/webhooks/` deliveries excepted, see below);
- unrestricted host execution is armed only with this install's random arming phrase, stored in the same file and never returned by the API;
- the console runs with `umask 077` and tightens existing state to owner-only (files 0600, directories 0700) at start, so databases, trust journals and audit logs stay private even under a shared `--state-dir`;
- every HTML document (`/`, `/console`, OAuth landing pages, `/static/*`) is served with a Content-Security-Policy (`script-src 'self'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`;
- request bodies are read only after the route and token checks pass and are capped at 8 MiB (`GHOSTCHIMERA_MAX_HTTP_BODY_BYTES`); an invalid `Content-Length` gets `400`;
- outbound fetches (`NetworkDispatcher`, the Browser tab) allow only `http`/`https`, refuse every non-global address (private, loopback, link-local, CGNAT `100.64.0.0/10`, reserved, and mapped/6to4/Teredo forms), and connect to the exact IP that was vetted, so DNS rebinding cannot swap in an internal address after the check.

### Connector write approvals

`/api/auth/approvals/decide` records the decider as the principal derived from the credential that authenticated the request (`operator` for the console token); a client-supplied `actor` is kept only as a sanitized label. Give agents, tools and MCP servers the separate `GHOSTCHIMERA_AGENT_TOKEN` instead of the console token: it can call `/api/auth/approvals/request` but can never decide. An agent-originated request (made with the agent token, or with `requested_by` naming an agent/automation) cannot be approved by the same credential that requested it unless `GHOSTCHIMERA_ALLOW_SELF_APPROVAL=1`. `decide` also accepts the request `digest` and refuses a mismatch.

### Memory file ingest

`POST /api/console/memory/ingest-file` and the `path` form of `ingest-email` only read files under the directory the console was started in, plus directories listed in `GHOSTCHIMERA_INGEST_ROOTS` (`os.pathsep`-separated; `/` is never accepted). Paths are resolved (symlinks followed) before the check. The Ghost state directory (including `console_secrets.json`), dotfiles and dot-directories (`.ssh`, `.env`, `.git`, ...) and secret-looking names (`*.pem`, `id_rsa`, `credentials`, `*secret*`, ...) are refused, and every stored chunk is scrubbed of credentials and the host-execution arming phrase.

### Inbound provider webhooks

`POST /api/webhooks/{slack,gmail,zendesk}/{va_id}` cannot carry the console token, so each delivery must prove it came from the provider. Nothing is accepted until a secret is configured (fail closed):

| Provider | Verification | Secret |
|---|---|---|
| Slack | `X-Slack-Signature` = `v0=` HMAC-SHA256 of `v0:{timestamp}:{body}`; `X-Slack-Request-Timestamp` within 5 minutes | Slack app signing secret |
| Zendesk | `X-Zendesk-Webhook-Signature` = base64 HMAC-SHA256 of `{timestamp}{body}`; timestamp within 5 minutes | Zendesk webhook signing secret |
| Gmail (Pub/Sub push) | Google-signed OIDC token in `Authorization: Bearer` when `GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_AUDIENCE` is set (optionally pinned with `GHOSTCHIMERA_WEBHOOK_GMAIL_OIDC_EMAIL`); otherwise a shared token in `X-Ghost-Webhook-Token` or the push URL's `?token=` | shared verification token |

Secrets are read from `GHOSTCHIMERA_WEBHOOK_SECRET_<SOURCE>_<VA_ID>` (per VA, preferred), `GHOSTCHIMERA_WEBHOOK_SECRET_<SOURCE>` (all VAs), or `<state-dir>/webhook_secrets.json` (`{"slack": {"*": "...", "va-1": "..."}}`, keep it 0600). Bodies must be `application/json` (Slack may also send `application/x-www-form-urlencoded`), at most 1 MiB. Verified deliveries are rate limited per source and VA (`GHOSTCHIMERA_WEBHOOK_RATE_PER_MIN`, default 60), repeated failures back off with `429`, duplicate deliveries are acknowledged without re-processing, and accepted events are queued for the stealth loop with a `202`: the request never waits for model reasoning.

## Required hardening for production deployments

Before using Ghost Chimera for unattended production automation, add deployment-level controls:

1. Run Ghost Chimera in a container, VM, or locked-down service account.
2. Keep secrets out of inherited process environments where possible.
3. Mount only the directories the agent must access.
4. Disable network access unless the workflow explicitly requires it.
5. Review telemetry and audit logs.
6. Place human approval gates in front of file mutation, shell execution, external API calls, and code execution.
7. Pin dependencies and review optional providers before enabling them.
8. Validate any local model binary path, checksum, and license before enabling local inference.

Ghost Chimera enforces a runtime production-readiness contract for high-impact execution. In production mode, shell execution, local Python/test execution, file writes, network execution, and live desktop control require:

```bash
GHOSTCHIMERA_DEPLOYMENT_MODE=production
GHOSTCHIMERA_EXTERNAL_ISOLATION=container   # or vm, service-account, sandboxed
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
```

Validate the deployment with:

```bash
ghostchimera doctor --production
```

Host execution remains trusted-inputs-only. Do not set `GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=1` for high-impact production workflows.

## Known dependency advisories

- **diskcache 5.6.3 — CVE-2025-69872 / GHSA-w8v5-vhqr-4h9v / PYSEC-2026-2447**
  (unsafe pickle deserialization: anyone who can write to a diskcache
  cache directory can run code in the process that reads it). It is
  pulled in only by `llama-cpp-python`, i.e. the optional `[local]` /
  `[all]` extras; the base install does not include it. **No fixed
  release exists** (5.6.3 is the latest on PyPI and every version is
  listed as affected), so no lower bound can be pinned. Ghost Chimera
  never creates a diskcache/`LlamaDiskCache` cache itself. If you enable
  one in your own llama.cpp integration, keep its directory inside the
  owner-only (0700) state dir and never point it at a shared or
  world-writable path. Re-check with `pip-audit` when a fixed diskcache
  ships, and add a lower bound to the `local` extra then.

## Reporting vulnerabilities

Open a private security advisory or contact the repository maintainer. Include:

- affected version or commit;
- reproduction steps;
- expected and observed behavior;
- impact assessment;
- proposed mitigation if known.
