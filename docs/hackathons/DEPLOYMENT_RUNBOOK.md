# Deployment Runbook (Public Demo URL)

## Local container run

```bash
docker compose up --build
```

Console URL:

- `http://localhost:8766/`

## Managed deployment recipe

1. Build and push container image from this repository.
2. Deploy one container service exposing port `8766` (HTTP).
3. Persist `/data/state` to durable volume storage.
4. Set production guardrails as environment variables:
   - `GHOSTCHIMERA_DEPLOYMENT_MODE=production`
   - `GHOSTCHIMERA_EXTERNAL_ISOLATION=container`
   - `GHOSTCHIMERA_SECURITY_REVIEWED=1`
   - `GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1`
5. Use the platform-provided service URL as the hackathon demo URL.

## Verification

After deployment, verify:

- `/` and `/console` render
- `/api/console/status` returns healthy JSON
- `/api/console/readiness` returns release-runbook checks

## Demo-safe defaults

- Keep untrusted-input execution disabled.
- Keep network/python/desktop execution policy-gated unless explicitly needed in the demo scenario.
