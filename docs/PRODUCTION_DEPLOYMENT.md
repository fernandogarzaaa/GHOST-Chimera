# Production Deployment

This is the generic production deployment path for Ghost Chimera outside the hackathon-specific Vultr runbook.

## 1. Create the production env file

```bash
cp .env.production.example .env.production
```

Replace `GHOSTCHIMERA_CONSOLE_AUTH_TOKEN` with a real random token and choose one model provider:

- `vultr` with `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`, and `VULTR_INFERENCE_BASE_URL`
- `openai` with `OPENAI_API_KEY` and `OPENAI_MODEL`
- `anthropic` with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`

Do not deploy with placeholder values.

## 2. Validate the env file

```bash
python scripts/validate_config.py --env-file .env.production --production
```

This must return `Overall Status: VALID`.

## 3. Validate runtime guardrails

```bash
GHOSTCHIMERA_DEPLOYMENT_MODE=production \
GHOSTCHIMERA_EXTERNAL_ISOLATION=container \
GHOSTCHIMERA_SECURITY_REVIEWED=1 \
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 \
python -m ghostchimera.control_plane.cli doctor --production
```

The provider check is env-aware. If `GHOSTCHIMERA_MODEL_PROVIDER` is set, doctor validates the selected provider instead of relying only on the local setup wizard config file.

## 4. Render the Compose config

```bash
docker compose --env-file .env.production -f docker-compose.yml config
```

This confirms that Compose can resolve the production env file and that the auth token requirement is satisfied.

## 5. Start the console

```bash
docker compose --env-file .env.production -f docker-compose.yml up -d --build
docker compose --env-file .env.production -f docker-compose.yml ps
```

The production compose file:

- requires `GHOSTCHIMERA_CONSOLE_AUTH_TOKEN`
- sets production guardrails by default
- disables untrusted inputs by default
- drops Linux capabilities
- enables `no-new-privileges`
- adds a console healthcheck

If your Docker environment sits behind a TLS-inspecting proxy and image builds fail on PyPI certificate validation, use a targeted build override instead of weakening the default image:

```bash
docker build \
  --build-arg PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org pypi.python.org" \
  -t ghost-chimera:latest .
```

Treat that as an environment-specific workaround, not the default deployment posture.

## 6. Smoke test the running service

Local:

```bash
curl http://127.0.0.1:8766/api/console/token
curl -H "X-Gateway-Token: <token>" http://127.0.0.1:8766/api/console/status
curl -H "X-Gateway-Token: <token>" http://127.0.0.1:8766/api/console/capabilities
```

Inside the container:

```bash
docker compose --env-file .env.production -f docker-compose.yml exec ghost-chimera \
  python -m ghostchimera.control_plane.cli doctor --production
```

## Production blockers

Do not call the deployment ready until these are true:

- the env file validates in strict mode
- `doctor --production` returns zero errors
- a real model provider is configured
- the console token is not a placeholder
- the running service responds on `/api/console/status`
