# Hackathon Submission Guide

## Track

Primary track: **Agentic Workflows**

Pitch angle: **Enterprise Utility**

Ghost Chimera moves beyond copilots by creating role-specific Ghost operators that plan multi-step work, synthesize an approved operating path, coordinate tools through policy gates, and preserve auditable state for enterprise workflows.

## Short Description

Ghost Chimera is a Vultr-hosted enterprise agent platform that creates role-specific Ghost operators for managers, assistants, marketers, analysts, and engineers, with governed memory, tool policy, and auditable autonomous workflows.

## Long Description

Ghost Chimera is a web-based enterprise agent platform for creating role-specific AI operators, or "Ghosts," that work on behalf of a user inside clear policy and disclosure boundaries. A manager, virtual assistant, marketer, analyst, or engineer can define the Ghost's role, approved learning sources, allowed tool domains, training pipeline, approval policy, and memory posture. The system then turns that path into an auditable workflow surface: capability matrix, readiness gates, autonomy preview jobs, Personal MiniMind/RAG status, and production guardrails. For the hackathon, the real Ghost Console runs on a Vultr VM, making Vultr the backend and central system of record for state, planning, coordination, schedules, memory status, and audit logs. Optional Vultr Serverless Inference can provide the reasoning model through an OpenAI-compatible endpoint.

## Technologies Used

- Python 3.12
- Ghost Chimera control plane, Chimera Pilot, path synthesis, readiness checks, and Ghost Console
- Docker and Docker Compose
- Vultr VM deployment
- Optional Vultr Serverless Inference through an OpenAI-compatible provider
- WebSocket and HTTP console gateway
- Local state volume for schedules, audit posture, memory/RAG status, and demo coordination

## Demo Application Platform

Choose **Streamlit** only if the form forces one of Streamlit, Replit, or Vercel. Describe Streamlit as an optional judge landing page. The production-style application and backend are the Vultr-hosted Ghost Console.

Recommended wording:

> The demo is deployed on a Vultr VM as the real Ghost Console. If this form requires Streamlit/Replit/Vercel, we selected Streamlit only as an optional judge landing page that links to the Vultr-hosted enterprise agent platform.

## Public Demo URL

Use the Vultr VM URL:

```text
http://<vultr-ip>:8766/
```

The live demo should be recorded from this URL.

## Repository Materials

Commit setup and deployment materials required by the challenge:

- `docker-compose.vultr.yml`
- `.env.vultr.example`
- `docs/VULTR_HACKATHON_DEPLOYMENT.md`
- `docs/HACKATHON_SUBMISSION_GUIDE.md`

Keep slides, cover image, and video files local-only unless the hackathon platform explicitly requires uploading them outside the repository.

## Demo Script

1. Open the Vultr-hosted Ghost Console.
2. Select **Manager Operator** or **Virtual Assistant**.
3. Generate a Ghost blueprint with role, learning sources, tool domains, training pipeline, approval policy, and disclosure boundary.
4. Show the capability matrix at `13/13`.
5. Show readiness checks and `ghostchimera doctor --production`.
6. Show autonomy jobs in preview mode.
7. Show Personal MiniMind/RAG status.
8. Show audit and policy posture.
9. Close by stating that Ghost Chimera turns enterprise intent into governed, auditable agent workflows instead of another chat copilot.
