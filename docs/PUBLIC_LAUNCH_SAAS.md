# Public Launch SaaS Mode

Ghost Chimera's public branch adds an Enterprise SaaS launch path while keeping
the local-first runtime intact.

## Launch Defaults

- Identity: generic OIDC first, SAML-ready abstraction later.
- Tenancy: organizations own workspaces, Ghost profiles, runs, approvals,
  provider credentials, audit events, and worker leases.
- Storage: Postgres is the SaaS source of truth. Local files and SQLite remain
  local-mode state and worker cache.
- Execution: web requests enqueue runs; workers claim queued jobs through
  leases. High-impact actions remain approval-first.
- Deployment: Docker Compose VPS first.
- Billing: out of scope for this launch phase.

## Required SaaS Environment

```bash
GHOSTCHIMERA_DEPLOYMENT_TARGET=saas
GHOSTCHIMERA_DATABASE_URL=postgresql://...
GHOSTCHIMERA_OIDC_ISSUER=https://...
GHOSTCHIMERA_OIDC_CLIENT_ID=...
GHOSTCHIMERA_OIDC_CLIENT_SECRET=...
GHOSTCHIMERA_OIDC_REDIRECT_URI=https://your-domain.example.com/oauth/callback
GHOSTCHIMERA_SESSION_SECRET=...
GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY=...
GHOSTCHIMERA_WORKER_TOKEN=...
GHOSTCHIMERA_MODEL_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

Optional:

```bash
GHOSTCHIMERA_OIDC_ALLOWED_DOMAINS=example.com,example.org
GHOSTCHIMERA_ADMIN_BOOTSTRAP_EMAIL=owner@example.com
```

## CLI Surfaces

```bash
ghostchimera saas status
ghostchimera saas init-db --print-sql
ghostchimera saas create-admin --email owner@example.com --org "Acme"
ghostchimera worker status
ghostchimera worker start --worker-id worker-1
```

## Docker Compose VPS Shape

Use the SaaS compose template as the first public-launch deployment target:

```bash
cp .env.saas.example .env.saas
docker compose --env-file .env.saas -f docker-compose.saas.yml config
docker compose --env-file .env.saas -f docker-compose.saas.yml up -d --build
```

The compose file runs Postgres, Ghost Console, and a worker container. It keeps
container privileges dropped and requires all production secrets to be supplied
through `.env.saas`.

`saas init-db --print-sql` emits the initial Postgres schema. The schema covers
organizations, users, memberships, workspaces, Ghost profiles, tenant secret
references, runs, approvals, audit events, worker leases, and eval baselines.

## Approval-First Boundary

SaaS mode does not enable local full bypass by default. Runs are queued, durable,
and approval-aware. High-risk MCP, shell, desktop, file-write, email crawl, and
Self-Evolution promotion actions must be approved by an admin/owner role before
execution.

## Current Implementation Boundary

This branch establishes the SaaS domain contracts, role checks, schema, CLI,
worker lease primitives, and release-gate coverage. The full hosted web session
middleware and production Postgres driver wiring are the next implementation
step after the public branch foundation is reviewed.
