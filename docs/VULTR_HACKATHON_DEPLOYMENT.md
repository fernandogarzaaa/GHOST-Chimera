# Vultr Hackathon Deployment

This runbook deploys the real Ghost Console as the public demo for the hackathon. The official track is **Agentic Workflows** with **Enterprise Utility** as the pitch angle: Ghost Chimera is a web-based enterprise agent platform that creates role-specific Ghost operators for managers, marketers, assistants, engineers, and analysts.

## What Runs On Vultr

- A Vultr VM is the backend and central system of record for state, planning, coordination, schedules, memory status, and audit logs.
- Docker Compose runs `ghostchimera console` with production guardrails and a persisted `/data/state` volume.
- Vultr Serverless Inference is optional. When `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`, and `VULTR_INFERENCE_BASE_URL` are unset, the provider fails closed and deterministic console/demo routes still load.
- No Vultr GPU is required.

## Create The VM

1. Create an Ubuntu LTS Vultr VM with public IPv4 access.
2. Add your SSH key and restrict SSH to your operator IP where possible.
3. Install Docker and the Compose plugin.
4. Clone the repository onto the VM.

```bash
git clone <your-repo-url> ghost-chimera
cd ghost-chimera
cp .env.vultr.example .env.vultr
```

Edit `.env.vultr` on the VM:

- Replace `GHOSTCHIMERA_CONSOLE_AUTH_TOKEN` with a long random demo token.
- If using Vultr Serverless Inference, set `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`, and `VULTR_INFERENCE_BASE_URL`.
- Keep `GHOSTCHIMERA_DEPLOYMENT_MODE=production`, `GHOSTCHIMERA_EXTERNAL_ISOLATION=container`, `GHOSTCHIMERA_SECURITY_REVIEWED=1`, and `GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1`.

## Run The Public Demo

```bash
docker compose --env-file .env.vultr -f docker-compose.yml -f docker-compose.vultr.yml up -d --build
docker compose --env-file .env.vultr -f docker-compose.yml -f docker-compose.vultr.yml ps
```

Open the firewall for the console:

```bash
sudo ufw allow 8766/tcp
sudo ufw allow 8765/tcp
```

Use the public URL:

```text
http://<vultr-ip>:8766/
```

Enter the demo token from `GHOSTCHIMERA_CONSOLE_AUTH_TOKEN` when prompted. The WebSocket gateway uses port `8765`, so keep it open for live console flows unless you place a reverse proxy in front of both ports.

## Validate The Deployment

From the VM:

```bash
curl http://127.0.0.1:8766/api/console/token
curl -H "X-Gateway-Token: $GHOSTCHIMERA_CONSOLE_AUTH_TOKEN" http://127.0.0.1:8766/api/console/status
curl -H "X-Gateway-Token: $GHOSTCHIMERA_CONSOLE_AUTH_TOKEN" http://127.0.0.1:8766/api/console/capabilities
docker compose --env-file .env.vultr -f docker-compose.yml -f docker-compose.vultr.yml exec ghost-chimera ghostchimera doctor --production
```

From outside the VM:

```bash
curl http://<vultr-ip>:8766/api/console/token
curl -H "X-Gateway-Token: <demo-token>" http://<vultr-ip>:8766/api/console/status
curl -H "X-Gateway-Token: <demo-token>" http://<vultr-ip>:8766/api/console/capabilities
```

## Judge Demo Flow

1. Open the Vultr-hosted public URL.
2. Choose either the **Manager Operator** or **Virtual Assistant** Ghost path.
3. Generate and save a Ghost blueprint that shows role, approved learning sources, tool domains, training pipeline, approval policy, and disclosure boundary.
4. Open the capability matrix and show the `13/13` enterprise-agent capability posture.
5. Open readiness checks and show `ghostchimera doctor --production` as the production gate.
6. Open autonomy jobs in preview mode to show multi-step planning without unsafe live execution.
7. Open Personal MiniMind/RAG status to explain user-approved training data and memory boundaries.
8. Open audit and security posture to show policy-gated enterprise operation.

## Demo Acceptance

- Public URL loads from outside the VM.
- No private local files, shell, desktop, or real email access is exposed.
- A judge can complete the Ghost path demo with only the optional demo token.
- Risky execution remains disabled by production guardrails.
- Audit, readiness, capability, autonomy-preview, path synthesis, and memory/RAG status are visible from the console.

## Optional Streamlit Landing Page

If the hackathon form forces a demo application platform choice among Streamlit, Replit, and Vercel, choose Streamlit only as an optional judge landing page. The actual Ghost Chimera runtime, state, coordination, schedules, memory status, and audit logs remain on the Vultr VM.
