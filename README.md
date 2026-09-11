# Ghost Chimera

![Version](https://img.shields.io/badge/version-0.4.0--beta-blueviolet)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![CI](https://img.shields.io/badge/CI-ubuntu%20%7C%20windows%20%7C%20macos-brightgreen)

> **Ghost is background AI infrastructure.** Ghost Chimera observes events across your digital workflow, learns how you work, and quietly prepares the right context or action for whichever AI agent you're using — without fine-tuning or replacing the underlying model. Your AI agents do the thinking. Ghost remembers what matters and makes sure they know what they need.

Ghost Chimera is a **local-first ambient intelligence runtime** built around the **Stealth Loop** — an event-driven learning and intervention cycle (`ghostchimera/stealth/`): EVENT → UNDERSTAND → UPDATE STATE → RECALL EXPERIENCE → MATCH WORKFLOW → PREDICT → DECIDE → PREPARE / INJECT / ACT → OBSERVE OUTCOME → LEARN. **Chimera Pilot** remains as the execution capability underneath it: it compiles natural-language objectives into steps, runs them across registered backends with safety policy and fallbacks, and records telemetry.

This is beta-stage software for real, user-supervised work in local-first environments. It is not AGI, not a secure sandbox for untrusted code by itself, and not a replacement for licensed quantum operating systems.

## Install

```bash
pip install "ghostchimera[all]"   # Python: everything included
brew tap fernandogarzaaa/ghostchimera && brew install --HEAD ghostchimera
```

Full matrix (extras, publishing): [docs/INSTALL.md](docs/INSTALL.md)

## One-Line Install

The one-line path creates a local checkout, builds a virtual environment, installs the full Ghost Chimera runtime profile, verifies the CLI, and prints the launch command.

**Windows PowerShell:**

```powershell
irm https://raw.githubusercontent.com/fernandogarzaaa/GHOST-Chimera/main/scripts/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/GHOST-Chimera/main/scripts/install.sh | bash
```

Then launch (`scripts/install.ps1` on Windows, `scripts/install.sh` on macOS/Linux):

```bash
cd ~/ghost-chimera
.venv/bin/ghostchimera console
```

Installer options are environment variables. `GHOSTCHIMERA_EXTRAS` defaults to the full Ghost Chimera runtime plus verification tools; override it only for constrained development installs.

## Runtime Specs

**Minimum for Ghost Console and local orchestration:**

| Component | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11, macOS 13+, Ubuntu 22.04+ | Windows 11, macOS 14+, Ubuntu 24.04+ |
| Python | 3.11 | 3.12 or 3.13 |
| RAM | 4 GB | 8-16 GB |
| Disk | 2 GB free | 10+ GB for memory, traces, and local models |
| Browser | Current Chrome, Edge, Firefox, or Safari | Current Chrome or Edge |

The full install covers Python package dependencies — not model weights, API keys, GPU drivers, or build tools. Without provider credentials, Ghost still runs the console, memory tools, trust runtime, evals, and deterministic backends.

## Usage in 5 minutes (no terminal needed)

Ghost Console is the point-and-click dashboard for everyday use:

1. Start Ghost (`ghostchimera console` or Docker) and open `http://localhost:8766/`.
2. The Setup wizard helps you pick an AI provider — choose **OpenCode CLI** or **Local** to start free.
3. In **Operate → Run**, type an objective in plain words ("Summarize my inbox priorities") and press run.
4. Check **Operate → Memory** for what Ghost remembered and **Advanced → Trust** for the run journal with replay.
5. Type `/ghost status` inside Claude Code, OpenCode, Codex, or Gemini CLI to see Ghost working there too.

Full walkthrough with use cases, everyday recipes, and the safety model: **[docs/USAGE_GUIDE.md](docs/USAGE_GUIDE.md)**. Guided first run: [docs/USER_TUTORIAL.md](docs/USER_TUTORIAL.md).

## What it can do for you

- **Personal productivity** — morning briefings, meeting prep, inbox triage drafts (never auto-sent), and asking your own history questions.
- **Operator workflows** — repeatable VA-style runs with approval checkpoints, reusable Standing Orders, and phone control from messaging apps.
- **Developer leverage** — project context auto-injected into your coding agents, free/local model options, and approval-gated computer use (browser and desktop).

## How it works

1. **The Stealth Loop watches and learns.** Events flow through understand → recall → predict → decide. Silence is the default; most events produce nothing visible.
2. **Chimera Pilot does.** Approved objectives compile into steps across deterministic, local-model, browser, and desktop backends — dry-runnable before anything touches the world.
3. **Trust Runtime keeps receipts.** Every run, approval, and outcome is journaled locally and replayable.

## Why Ghost

- **Memory that compounds** across every session and every agent you use.
- **Approval-first autonomy** — observe, prepare, inject, act, with you setting the ceiling.
- **Local-first privacy** — your data lives in a SQLite file on your disk; secrets encrypted; cloud is opt-in per connection.
- **Runs on free models** — local Ollama/llama.cpp or the OpenCode CLI's free tiers; swap providers without rewriting anything.

## Capabilities at a glance

- **Stealth Loop** (`ghostchimera/stealth/`) — Event Fabric, WorldState, Experience Graph, Workflow Learner, Prediction Engine, Stealth Evaluator, Context Fabric, Background Runtime, host adapters (Claude Code, OpenClaw, OpenCode, Codex, Gemini, Hermes), and local IPC transport.
- **Computer use** — browser (console-managed debuggable Chrome), desktop (PyAutoGUI), and vision hierarchy with capability allowlists, risk classification, and explicit approvals.
- **Connectors** (`ghostchimera/connectors/`) — GitHub (poll + webhooks), self-hosted OAuth2 + token vault (Slack, Notion, LinkedIn, GitHub, Google, Zendesk, Freshdesk, Gorgias, HubSpot, Salesforce, Airtable, Hubstaff, Time Doctor). See [docs/CUSTOM_AUTH.md](docs/CUSTOM_AUTH.md).
- **Durable local database** — SQLite/WAL journal for events, interventions, outcomes, and workflows, including the useful-intervention-rate metric. No server required.
- **30+ model providers** — OpenAI, Anthropic, Gemini, OpenRouter, Ollama, local runtimes, and the OpenCode CLI bridge; swap or chain them without rewriting code.
- **Ghost Console** — full no-code operator dashboard: guided setup, RAG Builder, Self-Evolution, Trust Runtime, Live Presence, remote control, conversational loop, local models, production readiness.
- **Trust Runtime** — durable run journals, resumable approval checkpoints, capability admission, and eval flywheels. [Details](docs/TRUST_RUNTIME.md)
- **Standing Orders** — scoped reusable autonomy programs with explicit enable/run controls. [Details](docs/STANDING_ORDERS.md)
- **Conservative safety defaults** — shell, network, desktop, and host self-editing are off by default; opt-in host mode is explicit and audited.

## Documentation

- [Usage Guide](docs/USAGE_GUIDE.md) — use cases, everyday recipes, safety model
- [User Tutorial](docs/USER_TUTORIAL.md) — guided first run
- [Quick Start](docs/quick-start.md) — fastest install and launch path
- [Install](docs/INSTALL.md) — install matrix and extras
- [Architecture](docs/ARCHITECTURE.md) — how the layers fit together
- [Provider Auth Vault](docs/PROVIDER_AUTH_VAULT.md) — dashboard-based provider setup
- [Remote Control](docs/REMOTE_CONTROL.md) — paired mobile/messaging commands
- [Production Deployment](docs/PRODUCTION_DEPLOYMENT.md) — guardrails for always-on use
- [API Reference](docs/api-reference.md) — generated API docs

## Appropriate Uses

- User-supervised automation and assistance for real work in local-first mode.
- Desktop and browser workflows (dry-run by default; live modes require explicit enablement and approvals).
- Governed repository change workflows: evidence retrieval → plan → policy checks → PR-ready output.
- Production automation inside externally isolated, reviewed deployments that pass `ghostchimera doctor --production`.
- Extending Ghost Chimera with new backends, skills, and connectors.

## Non-Goals And Boundaries

- Untrusted prompts, repositories, or code must run inside external isolation, not directly on a host machine.
- Ghost Chimera does not claim AGI, subjective consciousness, or fully autonomous operation.
- Commercial and enterprise deployments are expected to pass production guardrails and add organization-specific controls.
- Optional simulator support is not access to a proprietary quantum operating system.

---

## License

MIT — see `LICENSE`. Third-party attribution in `NOTICE`.
