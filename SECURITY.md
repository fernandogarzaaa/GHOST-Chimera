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
- POST/PUT/PATCH/DELETE requests with a foreign or `null` `Origin`, or `Sec-Fetch-Site: cross-site`, are refused, and must be `Content-Type: application/json` (signed `/api/webhooks/` deliveries excepted);
- unrestricted host execution is armed only with this install's random arming phrase, stored in the same file and never returned by the API.

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

## Reporting vulnerabilities

Open a private security advisory or contact the repository maintainer. Include:

- affected version or commit;
- reproduction steps;
- expected and observed behavior;
- impact assessment;
- proposed mitigation if known.
