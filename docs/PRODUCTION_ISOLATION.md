# Production Isolation Guidance

Ghost Chimera is a **local-first beta** platform. This document describes the
isolation, hardening, and operational controls required before running it in any
environment that handles real users, sensitive data, or automated unattended
workflows.

> **Status:** Beta. Commercial or high-impact deployment requires external
> isolation, security review, and the controls described here.

---

## Table of Contents

1. [Threat Model and Scope](#threat-model-and-scope)
2. [Container Isolation](#container-isolation)
3. [VM / Sandboxed Process Isolation](#vm--sandboxed-process-isolation)
4. [State Directory and Backup](#state-directory-and-backup)
5. [Audit Log Retention](#audit-log-retention)
6. [Secret Handling](#secret-handling)
7. [Network Isolation](#network-isolation)
8. [Rollback Procedures](#rollback-procedures)
9. [Production Readiness Checklist](#production-readiness-checklist)

---

## Threat Model and Scope

Ghost Chimera processes natural-language objectives and executes them against
registered backends (local runtimes, cloud LLM providers, browser automation,
desktop control). The primary risks in production are:

| Threat | Mitigation |
|--------|-----------|
| Untrusted prompt injection | DPI / LobsterTrap policy layer; deny-by-default |
| Credential leak via LLM output | DPI engine blocks tokens matching secret patterns |
| Unintended shell / file-system access | `ExecutionPolicy` and `PilotPolicy` — both deny by default |
| Unintended desktop mutation | Desktop backend is dry-run by default; live mode requires explicit opt-in |
| Data exfiltration via network | SSRF policy blocks private IPs and metadata endpoints by default |
| Runaway automation | Autonomy budget caps, kill-switch file, session time limits |
| Sensitive state on disk | State directory is local-only; see secret handling section |

---

## Container Isolation

Running Ghost Chimera inside a container is the **recommended minimum** for any
shared-infrastructure deployment.

### Docker quick-start

```bash
# Build the image
docker build -t ghost-chimera:latest .

# Run with a dedicated non-root user and read-only filesystem except for state
docker run --rm \
  --read-only \
  --tmpfs /tmp \
  -v /host/state:/state \
  -e GHOSTCHIMERA_STATE_DIR=/state \
  -e GHOSTCHIMERA_DEPLOYMENT_MODE=production \
  -e GHOSTCHIMERA_EXTERNAL_ISOLATION=container \
  ghost-chimera:latest ghostchimera --pilot-status
```

### Container hardening checklist

- [ ] Run as a non-root user (`USER ghostchimera` in Dockerfile)
- [ ] Mount the state directory from a persistent host volume (not ephemeral)
- [ ] Set `GHOSTCHIMERA_DEPLOYMENT_MODE=production`
- [ ] Set `GHOSTCHIMERA_EXTERNAL_ISOLATION=container`
- [ ] Drop all Linux capabilities you don't need (`--cap-drop ALL`)
- [ ] Apply a seccomp profile to restrict syscalls
- [ ] Do not bind-mount the Docker socket unless explicitly needed
- [ ] Limit container memory and CPU (`--memory`, `--cpus`)
- [ ] Never store API keys in the image; use secrets management (see below)

### Environment variable reference for isolation

| Variable | Value | Effect |
|----------|-------|--------|
| `GHOSTCHIMERA_DEPLOYMENT_MODE` | `production` | Enables production guardrails: blocks shell, file writes, live desktop |
| `GHOSTCHIMERA_EXTERNAL_ISOLATION` | `container` / `vm` / `service-account` / `sandboxed` | Declares isolation level; required for `ProductionGuardrails.ready` to be `True` |
| `GHOSTCHIMERA_SECURITY_REVIEWED` | `1` | Marks that a human security review has been completed |
| `GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED` | `1` | Requires human approval for high-risk tool calls |

---

## VM / Sandboxed Process Isolation

For untrusted code execution (Python runtime backend, shell skill), a VM or
sandboxed process provides stronger isolation than a container alone.

### Recommended options

| Option | Use case | Notes |
|--------|----------|-------|
| **Firecracker microVM** | Untrusted Python execution | Fast boot, memory-safe isolation |
| **gVisor** | Container workloads needing syscall filtering | Works with Docker/Kubernetes |
| **Bubblewrap** | Local operator single-user setups | Lighter weight than a full VM |

### Configuration

```bash
# Declare VM isolation to Ghost Chimera
export GHOSTCHIMERA_EXTERNAL_ISOLATION=vm
export GHOSTCHIMERA_DEPLOYMENT_MODE=production
```

Verify with:

```bash
ghostchimera doctor --production
```

---

## State Directory and Backup

The state directory (`~/.ghostchimera` by default, override with
`GHOSTCHIMERA_STATE_DIR`) contains:

| File | Content | Sensitivity |
|------|---------|-------------|
| `memory.sqlite3` | CWR long-term memory (evidence, reflections) | Medium — may contain task context |
| `operator_workspace.json` | In-memory workspace state snapshot | Medium |
| `audit.json` | Execution audit trail | High — contains policy decisions |
| `config.json` | Persisted autonomy/operator config | Low |

### Backup

```bash
# Snapshot the state directory atomically
rsync -a --delete ~/.ghostchimera/ /backup/ghostchimera/$(date +%Y%m%d)/

# Or with a dedicated script
python scripts/validate_release.py --state-dir ~/.ghostchimera
```

### Restore

```bash
# Stop the agent before restoring
rsync -a /backup/ghostchimera/20260101/ ~/.ghostchimera/
```

**Never restore state across trust boundaries** (e.g., restoring production
state into a development environment) without reviewing the content first.

---

## Audit Log Retention

Ghost Chimera writes execution audit records to `$GHOSTCHIMERA_STATE_DIR/audit.json`.

### Retention recommendations

| Environment | Minimum retention |
|-------------|------------------|
| Development | 7 days |
| Staging | 30 days |
| Production | 1 year (or as required by your compliance framework) |

### Rotating the audit log

```bash
# Archive and rotate the audit log
cp ~/.ghostchimera/audit.json /archive/audit-$(date +%Y%m%d).json
echo '[]' > ~/.ghostchimera/audit.json
```

For structured audit pipelines, forward the JSONL records to your SIEM or log
aggregator in real time. Each record includes `task_id`, `backend_id`, `ok`,
`policy_snapshot`, and timestamps.

---

## Secret Handling

**Never hard-code API keys in source, config files, or Docker images.**

### Recommended approaches

1. **Environment variables via secrets manager** (AWS Secrets Manager, HashiCorp
   Vault, GCP Secret Manager):
   ```bash
   export OPENAI_API_KEY=$(vault kv get -field=value secret/ghostchimera/openai)
   ```

2. **`.env` files** (development only):
   ```bash
   # .env — never commit this file
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Load with `python-dotenv` or `source .env` before starting the agent.

3. **Docker secrets** (swarm or Compose v3):
   ```yaml
   secrets:
     openai_key:
       external: true
   ```

### Keys used by Ghost Chimera

| Variable | Provider |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` | Google / Gemini |
| `GHOSTCHIMERA_MODEL_PROVIDER` | Selects the default provider |

The DPI / LobsterTrap engine scans LLM outputs for leaked keys. This is a
defence-in-depth measure, not a substitute for proper secret management.

---

## Network Isolation

### SSRF policy (built-in)

Ghost Chimera's `SSRFPolicy` blocks requests to:

- Loopback addresses (`127.0.0.0/8`, `::1`)
- Private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
- Link-local ranges (`169.254.0.0/16`) including cloud metadata endpoints

To allow a specific external host (required for cloud LLM APIs):

```python
from ghostchimera.chimera_pilot.policy import PilotPolicy

policy = PilotPolicy(allow_network=True, allowed_hosts=["api.openai.com", "api.anthropic.com"])
```

### Network-level controls

For production, pair the built-in SSRF policy with network-level controls:

- **Container**: use Docker network policies to restrict egress
- **VM**: use iptables / nftables to allowlist only required outbound endpoints
- **Kubernetes**: use `NetworkPolicy` resources

---

## Rollback Procedures

### Rolling back a bad release

1. **Stop the agent** (terminate the process or scale down replicas)
2. **Restore the state directory** from the last known-good backup
3. **Downgrade the package**:
   ```bash
   pip install 'ghostchimera==<previous-version>'
   ```
4. **Verify**:
   ```bash
   ghostchimera doctor --production
   python -m ghostchimera.evals run --suite smoke
   python -m ghostchimera.evals run --suite safety
   ```
5. **Re-enable traffic**

### Rolling back a policy change

Policy is driven by environment variables and the `config.json` file. Revert
by:

```bash
# Restore previous config
cp /backup/ghostchimera/20260101/config.json ~/.ghostchimera/config.json

# Or reset to defaults
ghostchimera workspace clear
ghostchimera autonomy set --level supervised
```

### Incident response

If a production incident occurs (unexpected tool execution, policy bypass, data
exfiltration attempt):

1. **Activate the desktop kill-switch** (if applicable):
   ```bash
   ghostchimera desktop-stop --reason "incident_response"
   ```
2. **Capture the audit log** before rotating it
3. **Review workspace state**:
   ```bash
   ghostchimera workspace show
   ```
4. **File a security report** per [SECURITY.md](../SECURITY.md)

---

## Production Readiness Checklist

Run this checklist before any production deployment:

```bash
# 1. Lint and test
ruff check .
python -m pytest -q
python scripts/validate_release.py

# 2. Eval suites
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python -m ghostchimera.evals run --suite workspace

# 3. Production guardrails
export GHOSTCHIMERA_DEPLOYMENT_MODE=production
export GHOSTCHIMERA_EXTERNAL_ISOLATION=container   # or vm / service-account
ghostchimera doctor --production

# 4. Workspace state quality
ghostchimera workspace show
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 \
  --min-confidence 0.8 --stale-after-days 30

# 5. Local model readiness (if using local inference)
ghostchimera local-model check --profile balanced
ghostchimera local-model guide --profile balanced

# 6. Package smoke test
python -m build
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
```

All checks must pass before promoting to production.

---

*Ghost Chimera is beta software. This document covers current hardening
guidance; additional controls may be required depending on your deployment
context, compliance requirements, and threat model.*
