# Ghost Chimera

![Version](https://img.shields.io/badge/version-0.4.0--beta-blueviolet)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![CI](https://img.shields.io/badge/CI-ubuntu%20%7C%20windows%20%7C%20macos-brightgreen)

Ghost Chimera is a **local-first agent orchestration runtime** built around **Chimera Pilot** â€” a resource-control layer that compiles natural-language objectives into a task IR, schedules them across registered backends using weighted scoring, enforces safety policy, executes with fallback, and records telemetry.

Key capabilities:
- **27 model providers** (OpenAI, Anthropic, Gemini, Groq, Mistral, Ollama, and 21 more) â€” swap or chain them without rewriting code.
- **10 Chimera Pilot backends** â€” deterministic, Python, memory retrieval, Gemini reasoning, local GGUF, analytics, simulation, desktop control, MCP, and quantum simulator.
- **Browser console (Ghost Console)** - full no-code operator dashboard with guided setup, provider/model configuration, RAG Builder, Self-Evolution, Trust Runtime, remote control, conversational loop, local models, and production readiness. No terminal needed for day-to-day use.
- **Conservative safety defaults** â€” Python, shell, network, and desktop execution are all off by default. Production mode adds deployment-level guardrails.
- **Personal MiniMind** â€” consent-gated local memory bootstrap with system specs, approved files/email exports, optional whole-machine/email-artifact crawling, MiniMind JSONL dataset generation, and primary-model RAG handoff.
- **Native Chimera capability pack** - built-in cognition guardrails, tamper-evident handoffs, query-aware context compression, local model inventory/resolution, MCP normalization, and sandbox journeys with no external project dependency. [Details](docs/NATIVE_ABSORPTION.md)
- **Trust Runtime** - durable local run journals, resumable approval checkpoints, MCP zero-trust envelopes, explicit capability admission, eval flywheels, and OTel-compatible JSON trace exports. [Details](docs/TRUST_RUNTIME.md) | [Capability Admission](docs/CAPABILITY_ADMISSION.md)
- **Daily production maintenance** - scheduled GitHub automation refreshes dependency audits and the compatible model-provider catalog, then opens a review PR without activating models automatically.
- **Public Launch SaaS foundation** - OIDC-ready organizations, users, roles, workspaces, Postgres schema, approval-first runs, worker leases, and audit-safe tenant primitives on the `public` branch. [Details](docs/PUBLIC_LAUNCH_SAAS.md)

- **Competitive capability intelligence** - CLI, console, docs, and eval gates compare Ghost Chimera against Codex, Claude Code, LangGraph, CrewAI, Hermes-style tool gateways, and OpenClaw-style local autonomy patterns.
- **Public superiority scorecard** - bounded proof across Operator UX, platform breadth, and autonomy depth through `ghostchimera superiority score`, `GET /api/console/superiority`, and the Operator Workbench browser E2E proof.
- **Automated PR review** - deterministic `ghostchimera review-pr` checks for secrets, destructive commands, missing tests, release-checklist drift, generated artifacts, and unfinished beta code.
- **Optional IBM Bob Developer Accelerator** - repo-aware hackathon/developer tools that analyze codebase health, test coverage, documentation completeness, and onboarding guidance without being required by the Ghost Chimera runtime. **[Boundary](docs/BOB_OPTIONAL_TOOLING.md)** | **[Hackathon Submission](docs/IBM_BOB_SUBMISSION.md)** | [Workflow Guide](docs/IBM_BOB_WORKFLOW.md)

This is beta-stage software for real, user-supervised work in local-first environments. It is not AGI, not a secure sandbox for untrusted code by itself, and not a replacement for licensed quantum operating systems.

## Start Here

If you are new to Ghost Chimera, use the tutorial first:

- [User Tutorial](docs/USER_TUTORIAL.md) - first-run walkthrough for Ghost Console, Ghost Paths, MiniMind, and your first objective
- [Quick Start](docs/quick-start.md) - fastest install and launch path
- [Provider Auth Vault](docs/PROVIDER_AUTH_VAULT.md) - dashboard-based provider setup, OAuth connector slots, and local Ollama/LM Studio auth posture
- [Remote Control](docs/REMOTE_CONTROL.md) - paired mobile/messaging commands with dashboard-controlled direct execution
- [GitHub-Connected Workflow](docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md) - optional GitHub planning and issue-to-objective flow
- [Production Deployment](docs/PRODUCTION_DEPLOYMENT.md) - final deployment guardrails, smoke tests, and production blockers
- [Public Launch SaaS](docs/PUBLIC_LAUNCH_SAAS.md) - Enterprise SaaS launch-mode foundation for organizations, OIDC, Postgres, and workers
- [Model Provider Catalog](docs/model_provider_catalog.md) - generated compatible/candidate model catalog
- [Dependency Audit](docs/dependency_audit.md) - generated dependency-specification risk report

---

## Table of Contents

- [User Tutorial](#start-here)
- [Architecture](#architecture)
- [One-Line Install](#one-line-install)
- [Runtime Specs](#runtime-specs)
- [Quick Start â€” Docker](#quick-start--docker)
- [Developer Install](#developer-install)
- [Ghost Console â€” Browser UI](#ghost-console--browser-ui)
- [CLI Reference](#cli-reference)
- [Python SDK](#python-sdk)
- [Model Providers](#model-providers)
- [Chimera Pilot Backends](#chimera-pilot-backends)
- [Autonomy Profiles](#autonomy-profiles)
- [Personal Memory & Personalization](#personal-memory--personalization)
- [Desktop Control](#desktop-control)
- [Execution Safety](#execution-safety)
- [Production Mode](#production-mode)
- [Public Launch SaaS](#public-launch-saas)
- [Daily Production Maintenance](#daily-production-maintenance)
- [Local Models](#local-models)
- [Ghost MiniMind](#ghost-minimind)
- [Competitive Capability Matrix](#competitive-capability-matrix)
- [Extension Surfaces](#extension-surfaces)
- [Verification and Confidence](#verification-and-confidence)
- [Release Validation & Eval Suites](#release-validation--eval-suites)
- [Development](#development)
- [Documentation](#documentation)
- [Appropriate Uses](#appropriate-uses)

---

## Architecture

Ghost Chimera is organized into independent layers. Each layer has a narrow contract with the layers above and below it.

| Layer | Package | Purpose |
|---|---|---|
| **Agent Core** | `agent_core` | Planner, task linearization, skill dispatch, and Chimera Pilot handoff. Two execution paths: Chimera Pilot (structured IR + backend scheduling) or legacy planner fallback with the same `ExecutionPolicy`. |
| **Chimera Pilot** | `chimera_pilot` | Task IR (`TaskSpec`, `TaskKind`), rule-based compiler, backend registry, weighted scheduler, policy gate, fallback executor, verifier, telemetry, checkpointing, batch orchestration, subagent pool, Mixture-of-Agents, credential pool, context compressor, gateway server, cron scheduler, toolsets, lifecycle hooks, tool middleware, plugin manifests, and service registry. |
| **Cognition Layer** | `cognition_layer` | Confidence values, hallucination flags, task ordering, self-model, working memory, attention, reflection primitives, and durable operator workspace state. |
| **Control Plane** | `control_plane` | User-facing CLIs (`ghostchimera`, `chimera-pilot`, `ghostchimera-parallel`, `ghostchimera-eval`), setup wizard, doctor/health checks, model picker, policy management, parallel execution, and the Ghost Console gateway server + static UI. |
| **Evals** | `evals` | 12 built-in evaluation suites: `smoke`, `safety`, `autonomy`, `user-journey`, `workspace`, `competitive`, `superiority`, `coverage`, `redteam`, `track2`, `track3`, `track4`. |
| **Harness** | `harness` | Offline-first regression harness for deterministic case runs. Emits structured JSONL artifacts with compile events, execution traces, fallback records, and pass/fail metadata. |
| **MCP** | `mcp` | Lightweight JSON-RPC MCP server/client surfaces and the `MCPBackend` Chimera Pilot backend. |
| **Memory Layer** | `memory_layer` | SQLite FTS5 local memory store. Namespaced documents, freshness scoring (exponential decay), citation quality, `stale_after_days` filter, and `count()`. |
| **Model Layer** | `model_layer` | Provider abstraction and routing for 27 providers, auth profiles, model catalog with pricing/context metadata, media-provider interfaces, Ghost-native MiniMind architecture/runtime adapters, CuTeDSL-inspired runtime specialization planner, and optional llama.cpp/GGUF runtime. |
| **Personalization** | `personalization` | `PersonalContextProvider` (FTS memory snippets -> system context), `DocumentIngester` (text/CSV/Markdown chunking), `EmailIngester` (RFC 2822 / mbox parsing), role profiles, path synthesis, and persisted active Ghost Path state. |
| **Safety Layer** | `safety_layer` | `ExecutionPolicy` gating, `ApprovalHandler`/`ApprovalPolicy`, `MaterialRegistry` patterns, HMAC-SHA256 audit chain, `BuiltinDPIEngine`/`LobsterTrapProvider` DPI scanning, `SecurityMonitor`, `SSRFPolicy`/`NetworkDispatcher`, and rate limiting. |
| **SDK** | `sdk` | `GhostClient` Python API for programmatic access without the CLI. |
| **Skill Layer** | `skill_layer` | Built-in skills: `browser_operator`, `code_search`, `software_engineer`, `tech_support`, `to_issues`. External skills auto-discovered from `~/.ghostchimera/skills/<name>/skill.py`. |
| **Tool Layer** | `tool_layer` | Policy-gated filesystem, shell, and browser tools. File access constrained to configured roots; shell commands run without `shell=True`; all tool calls written to the audit log. |

### Chimera Pilot pipeline

```
Objective
  â†’ RuleBasedTaskCompiler â†’ TaskSpec list
  â†’ ChimeraScheduler (weighted scoring + health cache)
  â†’ best backend (with fallback)
  â†’ ChimeraPilotExecutor
  â†’ SemanticVerifier
  â†’ Telemetry / ResultEnvelope
```

**Safety boundary:** the scheduler decides *where* to run; the policy decides *whether* it is allowed. `PilotPolicy` (Chimera Pilot layer) and `ExecutionPolicy` (tool layer) are separate gates.

---

## One-Line Install

The user-facing install path creates a local checkout, builds a virtual environment, installs the full Ghost Chimera runtime profile (`.[all]`), verifies the CLI, and prints the launch command. This includes Ghost Console, MCP, local GGUF/llama.cpp support, MiniMind PyTorch/Transformers support, quantum simulator support, and platform-compatible specialization helpers.

**Windows PowerShell:**

```powershell
irm https://raw.githubusercontent.com/fernandogarzaaa/GHOST-Chimera/main/scripts/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/fernandogarzaaa/GHOST-Chimera/main/scripts/install.sh | bash
```

Then launch:

```bash
cd ~/ghost-chimera
.venv/bin/ghostchimera console
```

On Windows, the installed launcher is:

```powershell
cd "$HOME\ghost-chimera"
.\.venv\Scripts\ghostchimera.exe console
```

Installer options are environment variables so the one-line command stays copy/paste friendly. Normal users should keep the default full install.

| Variable | Default | Purpose |
|---|---|---|
| `GHOSTCHIMERA_INSTALL_DIR` | `~/ghost-chimera` | Install/update directory. |
| `GHOSTCHIMERA_EXTRAS` | `all` | Runtime profile to install. Defaults to the full Ghost Chimera runtime; advanced users may override this only for constrained development installs. |
| `GHOSTCHIMERA_REF` | `main` | GitHub branch or ref to install. |
| `GHOSTCHIMERA_DRY_RUN` | `0` | Bash dry run when set to `1`. |

PowerShell also supports:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -InstallDir D:\GhostChimera -Extras all
```

---

## Runtime Specs

**Minimum for Ghost Console and local orchestration:**

| Component | Minimum | Recommended |
|---|---:|---:|
| OS | Windows 10/11, macOS 13+, Ubuntu 22.04+ | Windows 11, macOS 14+, Ubuntu 24.04+ |
| Python | 3.11 | 3.12 or 3.13 |
| RAM | 4 GB | 8-16 GB |
| Disk | 2 GB free | 10+ GB if storing memory, traces, datasets, and local models |
| CPU | 2 cores | 4+ cores |
| Browser | Current Chrome, Edge, Firefox, or Safari | Current Chrome or Edge |

**Included by the full one-line install:**

| Capability | Extra | Practical spec |
|---|---|---|
| Ghost Console, cron, WebSocket gateway | `gateway` | Installed by default. |
| MCP package integration | `mcp` | Installed by default. |
| Personal MiniMind PyTorch/Transformers inference | `minimind` | Installed by default where Python version markers allow it; 8+ GB RAM recommended. |
| GGUF / llama.cpp local model runtime | `local` | Installed by default; 8+ GB RAM for small quantized models, more for larger models. |
| Quantum simulator backend | `quantum` | Installed by default; CPU-only is fine for small simulator cases. |
| NVIDIA CuTe DSL detection | `cute` | Installed by default only on compatible Linux + Python 3.12 systems. |

The full install covers Python package dependencies. It does not bundle model weights, API keys, provider accounts, GPU drivers, CUDA, Visual Studio Build Tools, Xcode Command Line Tools, or system package managers. Those remain machine-specific prerequisites when a selected local runtime needs native compilation or external credentials.

Provider API keys and OAuth connections are optional. Without provider credentials, Ghost Chimera still runs the console, local policy gates, memory tools, capability pack, trust runtime, evals, and deterministic backends.

---

## Quick Start â€” Docker

Build and run the browser console with the included Docker artifacts â€” no local Python install required:

```bash
docker compose up --build
```

Open **http://localhost:8766/** in your browser. The Ghost Console provides a full point-and-click UI â€” no terminal needed for day-to-day operation.

---

## Developer Install

From a clean checkout (Python 3.11â€“3.13 required):

```bash
python -m venv .venv
source .venv/bin/activate          # On Windows: .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

**Optional extras:**

```bash
python -m pip install -e ".[gateway]"   # WebSocket gateway + cron scheduling (required for console)
python -m pip install -e ".[mcp]"       # MCP package integration
python -m pip install -e ".[local]"     # llama.cpp / GGUF local model runtime
python -m pip install -e ".[minimind]"  # MiniMind PyTorch/Transformers inference adapter
python -m pip install -e ".[cute]"      # NVIDIA CuTe DSL detection (Linux + Python 3.12)
python -m pip install -e ".[quantum]"   # pyqpanda3 quantum simulator backend
python -m pip install -e ".[dev]"       # ruff, pytest, build tools
python -m pip install -e ".[all]"       # everything
```

The base package is stdlib-first with zero mandatory dependencies. Heavy runtimes (`llama-cpp-python`, PyTorch, `nvidia-cutlass-dsl`, `pyqpanda3`) are opt-in.

---

## Ghost Console â€” Browser UI

The Ghost Console is a gateway-backed browser UI that exposes all major Ghost Chimera controls without the terminal. Start it with:

```bash
python -m pip install -e ".[gateway]"
ghostchimera console
```

Then open **http://localhost:8766/**. To protect the console with a bearer token:

```bash
ghostchimera console --auth-token mysecrettoken
```

The token is printed on startup and entered in the browser prompt once. All `/api/*` routes require the `X-Gateway-Token` header when a token is set.

**Console tabs:**

| Tab | What you can do |
|---|---|
| **Home** | Operator readiness cards, active Ghost Path, active model/provider, config health, MiniMind/RAG, MCP, skills, Self-Evolution, Trust Runtime, production warnings, and Guided Setup entry points. |
| **Ghost Conversation** | Always-available text/voice conversation panel with transcript, operational trace, hands-free mode, approval prompts, Stop All, and explicit True Autonomy / Full Bypass controls. |
| **Setup Ghost** | No-code setup wizard: choose path, configure provider/model, confirm MiniMind permissions, select learning sources, generate RAG plan, review MCP/tools, review skills, and run readiness checks. |
| **Run** | Quick Actions, custom objective box with **Ctrl+Enter / Cmd+Enter**, run output, durable run history, and sandbox-safe execution previews. |
| **Jobs** | Profile-aware autonomy jobs (`self-audit`, `dependency-scan`, `test-regression`, `memory-refresh`, `model-health-check`, `repair-preview`) with durable history. |
| **Config** | Provider Auth Vault, write-only secrets, OAuth connector slots, environment-free provider setup, production guardrails, and modular runtime settings. |
| **Models** | Model discovery, provider catalog filters, compatibility pings, model recommendations by Ghost Path, primary/fallback selections, and local Ollama/LM Studio posture. |
| **RAG Builder / MiniMind** | Consent-gated source selection, dataset preview, local file/email-artifact import, MiniMind bootstrap, RAG plan generation, provenance, and revocable permissions. |
| **MCP** | MCP server review, capability normalization, zero-trust status, approval boundaries, health checks, and enable/disable controls. |
| **Skills** | Bundled/workspace skill browser, GitHub skill discovery queue, compatibility notes, generated skill previews, and approval-before-activation controls. |
| **Self-Evolution** | Learning sources, evolution candidates, lifecycle status, review/promote/reject actions, model recommendations, RAG updates, skill candidates, and activity provenance. |
| **Remote Control** | Pair mobile or messaging senders, review safe slash commands, toggle global direct-execution policy, enable direct execution per paired admin, and approve or deny remote `/run` requests. |
| **Trust Runtime** | Durable run journals, pending approvals, resumable checkpoints, MCP trust registry, eval baselines, capability admission records, and redacted OTel-style trace exports. |
| **Latency** | Cost/latency posture, context-compression recommendations, provider timing, model health, and slow-path diagnostics. |
| **Cognitive Guardrails** | Belief confidence, variance guards, provenance handoff verification, hallucination risk signals, and safe operational trace nodes. |
| **Capability Pack** | Built-in deterministic tools for compression, claim extraction, local model inspection, MCP normalization, sandbox journeys, and trust checks. |
| **Sandbox / Local Models** | User-journey sandbox reports, local hardware profile, GGUF/SafeTensors discovery, Hugging Face model resolver, license posture, and quantization recommendations. |
| **Security / Schedules / Review / Capabilities / Readiness** | Security metrics, HMAC audit chain, cron schedules, deterministic PR review, competitive matrix, and final release-readiness commands. |

The **Home** tab is the Operator Workbench: command search, next best actions, superiority scorecards, browser E2E status, guided setup, and the conversational loop are surfaced before the advanced tabs.

**All actions produce toast notifications** (green ok / yellow warn / red error), activity timeline entries, and trust/runtime records where relevant. You should not need to watch the terminal for normal operation.

### Multi-Purpose Ghost Paths

Use the Path tab to choose what Ghost Chimera should become for the current
operator. Built-in paths include Autonomous Engineer, AI Engineer Proxy,
Manager Operator, Marketing Specialist, Virtual Assistant, Enterprise Operator,
Personal Operations Assistant, Research Analyst, and Custom Ghost.

Each path configures Ghost as an authorized operator proxy for a work domain. It
synthesizes a `ghost_blueprint` with what the Ghost becomes, what it learns from,
what it can operate, which training pipeline is active, source scopes, learning
strategy, dashboard tabs, eval gates, and proxy policy. External GitHub
repositories require license metadata, URL, commit SHA, and intended-use tracking
before dataset generation or fine-tuning.

Use **Save Path** in the console to persist the active profile. Personal
MiniMind handoff prompts inherit the active path automatically, so a saved AI
Engineer Proxy path turns the RAG handoff into an authorized engineering-proxy
brief for the configured primary model.

CLI access:

```powershell
ghostchimera path list
ghostchimera path set --profile ai-engineer-proxy --training-mode rag-first --approval-level supervised
ghostchimera path set --profile virtual-assistant --training-mode dataset_generation --approval-level assist
ghostchimera path show
```

See [Multi-Purpose Ghost Paths](docs/MULTIPURPOSE_GHOST_PATHS.md) for the
source and disclosure policy.

### GitHub-Connected Beta Workflow

GitHub-connected mode lets Ghost Chimera turn issues into objectives, preview
policy requirements, and prepare issue-to-PR work from the local runner.

```powershell
$env:GHOSTCHIMERA_GITHUB_TOKEN="..."
ghostchimera github status
ghostchimera github plan --repo owner/repo --issue 42 --title "Fix CI"
ghostchimera console
```

The console GitHub tab exposes connection status, issue planning, and policy
simulation. See
[GitHub-Connected Autonomous Engineer](docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md).

Console options:

```bash
ghostchimera console --host 0.0.0.0 --port 9001 --http-port 9002
ghostchimera console --state-dir /data/ghost-state --no-open
```

---

## CLI Reference

### `ghostchimera` â€” main control-plane CLI

```bash
ghostchimera setup                    # interactive setup wizard
ghostchimera doctor                   # health checks
ghostchimera doctor --production      # production-mode gate
ghostchimera model                    # list / switch model provider
ghostchimera policy                   # manage security policies
ghostchimera --config-show            # print current config
ghostchimera --pilot-status           # Chimera Pilot status
ghostchimera --pilot-run "objective"  # run via Chimera Pilot

# Autonomy
ghostchimera autonomy show
ghostchimera autonomy set --level autonomous --local-model-profile stronger
ghostchimera autonomy jobs
ghostchimera autonomy run repair-preview

# Workspace
ghostchimera workspace show
ghostchimera workspace add-evidence --source audit --content "..." --confidence 0.92
ghostchimera workspace reflect --reflection-action "..." --outcome "..." --confidence 0.9
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8

# MiniMind
ghostchimera path list
ghostchimera path set --profile ai-engineer-proxy --training-mode rag-first --approval-level supervised
ghostchimera path show
ghostchimera minimind architectures
ghostchimera minimind status
ghostchimera minimind dataset --prompt "..." --response "..."
ghostchimera minimind log-failure --prompt "..." --response "..." --confidence 0.2
ghostchimera minimind personal-consent --admin-controls --allow-system-specs --allow-files --allow-email --allow-training --file-path ~/Documents --email-path ~/mail/export.mbox
ghostchimera minimind personal-consent --admin-controls --allow-machine-crawl --allow-email-crawl --allow-training --crawl-root ~/Documents
ghostchimera minimind personal-bootstrap --include-system-specs
ghostchimera minimind personal-handoff --objective "What should Ghost do next?"

# Competitive capability matrix
ghostchimera capabilities --format json
ghostchimera capabilities --format markdown --save docs/capability-report.md

# Public superiority scorecard
ghostchimera superiority score --format json
ghostchimera superiority score --format markdown --save docs/superiority-scorecard.md
python scripts/run_operator_workbench_e2e.py --no-screenshot

# PR / diff review
ghostchimera review-pr --base origin/main --head HEAD
ghostchimera review-pr --base origin/main --head WORKTREE  # include staged/unstaged changes
ghostchimera review-pr --base HEAD --head HEAD --format markdown

# Local model bootstrap
ghostchimera local-model check
ghostchimera local-model guide
ghostchimera local-model profiles

# Runtime specialization warmup
ghostchimera runtime-warmup --runtime-specialization-cache-dir .ghost/rs --local-model-profile stronger

# Desktop kill switch
ghostchimera desktop-stop --desktop-kill-switch-path .ghost/DESKTOP_STOP
```

### `chimera-pilot` â€” Pilot-specific CLI

```bash
chimera-pilot status --include-deterministic-backend
chimera-pilot compile "objective"
chimera-pilot calibrate --include-deterministic-backend
chimera-pilot run "objective" --include-deterministic-backend
chimera-pilot run "objective" --autonomy-level autonomous --memory-db .ghostchimera-memory.sqlite3
chimera-pilot autonomy-profiles
chimera-pilot model-profiles
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source notes --content "..."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "query"
chimera-pilot runtime-specialization "prompt" --local-model-profile tiny
chimera-pilot runtime-warmup --runtime-specialization-cache-dir .ghost/rs --local-model-profile tiny
```

### `ghostchimera-parallel` â€” parallel and batch execution

```bash
ghostchimera-parallel run "obj1" "obj2" "obj3" --parallel 3 --output-dir ./out
ghostchimera-parallel batch objectives.jsonl --workers 4 --output-dir ./batch-out
```

### `ghostchimera-eval` â€” evaluation runner

```bash
ghostchimera-eval run --suite smoke
ghostchimera-eval run --suite safety
ghostchimera-eval run --suite autonomy
ghostchimera-eval run --suite user-journey
ghostchimera-eval run --suite workspace
ghostchimera-eval run --suite competitive
ghostchimera-eval run --suite superiority
ghostchimera-eval run --suite coverage
ghostchimera-eval run --suite redteam
ghostchimera-eval run --suite track2   # Gemini integration
ghostchimera-eval run --suite track3   # simulation / robotics
ghostchimera-eval run --suite track4   # analytics / data pipeline
```

---

## Python SDK

Use `GhostClient` for programmatic access without the CLI:

```python
from ghostchimera.sdk import GhostClient

client = GhostClient(state_dir="~/.ghostchimera")

# Run an objective
result = client.run("summarize recent project activity")
print(result.summary)

# Ingest knowledge into local memory
client.ingest_document("path/to/spec.md", source="spec", namespace="project")
client.ingest_file("path/to/notes.txt")
client.ingest_directory("path/to/docs/")
client.ingest_email_file("path/to/message.eml")
client.ingest_raw_email("From: ...\nSubject: ...\n\nbody text")

# Search local memory
results = client.search("project milestones", limit=5)

# Teach Ghost â€” record a prompt/response training example
client.teach(prompt="What is Ghost Chimera?", response="A local-first agent runtime.")

# Check training dataset status
status = client.training_status()

# Preview context that would be injected for an objective
preview = client.preview_context("summarize project status", limit=3)

# Low-level memory store access
count = client.memory_count()
store = client.memory    # MemoryStore instance
```

---

## Model Providers

Ghost Chimera supports **27 model providers** plus a custom OpenAI-compatible endpoint. All are optional. Non-technical users can connect providers from the Ghost Console **Config -> Provider Auth Vault** without editing `.env`; developers can still set environment variables directly.

OAuth is modular. The dashboard shows OAuth-capable connector slots when a provider has an official flow: OpenAI ChatGPT/Codex can use the local `codex` CLI OAuth session through the `codex_cli` bridge, OpenRouter can complete PKCE into a write-only user API key, Hugging Face can use device-code OAuth with a configured OAuth client ID, and Google/Gemini can launch ADC setup. Ghost Chimera does not scrape browser sessions or treat subscriptions as API keys. See [Provider Auth Vault](docs/PROVIDER_AUTH_VAULT.md).

| Provider | Env var | Default model |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | (user-configured) |
| Anthropic | `ANTHROPIC_API_KEY` | (user-configured) |
| Google Gemini | `GOOGLE_API_KEY` | (user-configured) |
| Groq | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| xAI / Grok | `XAI_API_KEY` | `grok-3-mini` |
| Mistral | `MISTRAL_API_KEY` | `mistral-small-latest` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Together AI | `TOGETHER_API_KEY` | `meta-llama/Llama-3-70b-chat-hf` |
| OpenRouter | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` |
| Ollama (local) | `OLLAMA_BASE_URL` | `llama3.2` |
| Cohere | `COHERE_API_KEY` | `command-r-plus` |
| Perplexity | `PERPLEXITY_API_KEY` | `llama-3.1-sonar-small-128k-online` |
| Fireworks | `FIREWORKS_API_KEY` | `accounts/fireworks/models/llama-v3p1-70b-instruct` |
| Cerebras | `CEREBRAS_API_KEY` | `llama3.1-70b` |
| AI21 | `AI21_API_KEY` | `jamba-1.5-mini` |
| Hugging Face | `HF_TOKEN` | `meta-llama/Llama-3.3-70B-Instruct` |
| NVIDIA NIM | `NVIDIA_API_KEY` | `meta/llama-3.1-70b-instruct` |
| Moonshot / Kimi | `MOONSHOT_API_KEY` | `moonshot-v1-8k` |
| DeepInfra | `DEEPINFRA_API_KEY` | `meta-llama/Meta-Llama-3.1-70B-Instruct` |
| Alibaba Qwen | `DASHSCOPE_API_KEY` | `qwen-turbo` |
| Volcengine Doubao | `ARK_API_KEY` | `doubao-pro-4k` |
| StepFun | `STEPFUN_API_KEY` | `step-1-8k` |
| ZhipuAI GLM | `ZHIPUAI_API_KEY` | `glm-4-flash` |
| Venice AI | `VENICE_API_KEY` | `llama-3.3-70b` |
| LM Studio (local) | `LMSTUDIO_BASE_URL` | (user-configured) |
| llama.cpp (local) | `MINIMIND_MODEL_PATH` | (user-configured GGUF path) |
| MiniMind (local) | `MINIMIND_MODEL_PATH` | (user-configured checkpoint) |

Set `GHOSTCHIMERA_MODEL_PROVIDER` to a comma-separated list to enable model routing with fallback (`provider1,provider2,provider3`).

---

## Chimera Pilot Backends

Every backend exposes `id`, `name`, `capabilities`, `probe()`, `can_run(task)`, `estimate(task)`, and `execute()`. This unifies local runtimes, cloud models, MCP connectors, and simulators behind one scheduling interface.

| Backend | Purpose |
|---|---|
| `DeterministicBackend` | CI, smoke checks, and guaranteed-pass fallback testing. |
| `PythonRuntimeBackend` | Explicitly allowed local Python and `unittest` execution. Requires `--allow-python`. |
| `CWRBackend` | SQLite-backed CWR local memory retrieval. |
| `GeminiBackend` | Gemini / Google AI Studio reasoning, long-context document analysis, and multi-agent task history (1M-token context models). |
| `LlamaCppBackend` | GGUF reasoning through a local model path. Requires `.[local]`. |
| `AnalyticsBackend` | Count/sum/avg group queries, linear-trend forecasting, z-score anomaly detection, CSV parsing, schema validation, and knowledge-graph triple extraction. |
| `SimulationBackend` | Kinematics trajectory planner, digital-twin sensor emulation, and policy-test episode runner with collision detection. |
| `DesktopRuntimeBackend` | Dry-run desktop control (default) and gated live desktop control. |
| `MCPBackend` | MCP-style tool execution through JSON-RPC MCP servers. Requires `.[mcp]`. |
| `PyQPanda3Backend` | Optional pyqpanda3 quantum circuit simulator tasks. Requires `.[quantum]`. |

---

## Autonomy Profiles

Ghost Chimera exposes autonomy as an operator-adjustable profile â€” not as a claim of AGI or consciousness.

| Profile | Behavior |
|---|---|
| `assist` | Single-backend execution, small tool-loop budgets. |
| `supervised` | Default beta posture â€” fallback routing, approval requirements. |
| `autonomous` | Larger tool-loop budgets, scheduler adaptation, bounded parallel execution. |
| `generalist` | Highest local-first beta profile â€” MoA-style strategy selection, preview-only self-improvement. |

```bash
ghostchimera autonomy show
ghostchimera autonomy set --level autonomous --local-model-profile stronger
chimera-pilot autonomy-profiles
```

`GHOSTCHIMERA_AUTONOMY_LEVEL` sets the default profile. The aliases `agi` and `sgi` are accepted as shorthand for `generalist` â€” Ghost Chimera still does not claim AGI or fully autonomous operation.

**Profile-aware autonomy jobs:** `self-audit`, `dependency-scan`, `test-regression`, `memory-refresh`, `model-health-check`, `repair-preview`. Conservative profiles return preview plans; `autonomous`/`generalist` may run bounded checks when `--execute` is passed, but source mutation, training, network access, Python execution, shell execution, and desktop control still require their existing policy opt-ins.

---

## Personal Memory & Personalization

Ghost Chimera includes a **local-first personal memory system** backed by SQLite FTS5:

- **Document ingestion** â€” `DocumentIngester` chunks `.txt`, `.md`, `.py`, `.json`, and CSV files. Duplicate-safe insert via `add_document_once`.
- **Email ingestion** â€” `EmailIngester` parses RFC 2822 / mbox files, extracts all MIME parts, and stores them as memory records.
- **Freshness scoring** â€” `MemoryStore.search()` returns `freshness_score` (exponential decay, 30-day half-life), `citation_quality` (freshness Ã— content-length heuristic), and `created_at`. Accepts a `stale_after_days` filter.
- **Personal context injection** â€” `PersonalContextProvider` retrieves top FTS matches and injects them into the system prompt for `REASONING`, `LONG_CONTEXT_DOC`, and `CODE_EDIT` tasks, or into `inputs["context"]` for `WEB_RESEARCH`, `FILE_ANALYSIS`, `RAG_QUERY`, and `ANALYTICS_QUERY`.
- **Teaching pipeline** â€” record prompt/response pairs through the Memory tab or `GhostClient.teach()`. Pairs accumulate in `~/.ghostchimera/minimind/datasets/dataset.jsonl` for local MiniMind fine-tuning.
- **Personal MiniMind bootstrap** â€” `MiniMindPersonalAgent` stores explicit admin consent, ingests approved system specs/files/email exports, optionally discovers readable local files and `.eml`/`.mbox` email artifacts under crawl roots, builds a personal dataset from local memory, and returns a primary-model handoff prompt so the configured Ghost model can execute with personal context.

```bash
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source notes --content "..."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "query"
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
ghostchimera minimind personal-status
```

---

## Desktop Control

Desktop control is dry-run by default. Live mutation requires explicit opt-ins at every level.

```bash
# Dry-run (inspect plan, no actual clicks)
chimera-pilot run "click submit button" --enable-desktop-backend --allow-desktop-control --ghost-mode possess

# Live mode
chimera-pilot run "live desktop: click submit" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess

# Destructive actions require explicit class allowlist + confirmation token
chimera-pilot run "live desktop: click delete project" \
  --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess \
  --desktop-action-class read_only --desktop-action-class mutating --desktop-action-class destructive \
  --desktop-confirm-token confirm-destructive-desktop

# Multi-step chains with app/window policy
chimera-pilot run "live desktop: click app=chrome window=Docs then type hello world then press ctrl+s" \
  --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess \
  --desktop-allow-app chrome --desktop-allow-window Docs

# Emergency stop â€” creates kill-switch file before the next action fires
chimera-pilot desktop-stop --desktop-kill-switch-path .ghost/DESKTOP_STOP

# Replayable sessions with before/after screenshots
chimera-pilot run "live desktop: click submit" \
  --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess \
  --desktop-action-log-path .ghost/desktop-actions.jsonl --desktop-screenshot-dir .ghost/desktop-screens
```

Desktop actions are classified as `read_only`, `mutating`, or `destructive`. The default policy allows only the first two.

For unattended or high-impact use, run Ghost Chimera inside an external sandbox. See `SECURITY.md`.

---

## Execution Safety

All execution surfaces are **denied by default**. They must be enabled explicitly per run or via policy.

| Surface | Default | How to enable |
|---|---|---|
| Python execution | blocked | `--allow-python` |
| Shell execution | blocked | policy opt-in |
| Network / web fetch | blocked | policy opt-in or SSRF allowlist |
| File writes | blocked | `ExecutionPolicy` |
| Desktop control | dry-run only | `--enable-live-desktop --allow-desktop-control` |
| Live desktop mutation | blocked | additionally `--ghost-mode possess` |

The `BuiltinDPIEngine` (LobsterTrap) scans all inputs for prompt injection, credential leaks, PII, and data exfiltration instructions before they reach the execution layer. The `SSRFPolicy` blocks requests to private IP ranges and cloud metadata endpoints by default.

---

## Production Mode

Set `GHOSTCHIMERA_DEPLOYMENT_MODE=production` and validate the deployment:

```bash
ghostchimera doctor --production
```

Production mode additionally requires:

```bash
GHOSTCHIMERA_EXTERNAL_ISOLATION=container   # or: vm | service-account | sandboxed
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
```

Shell execution, local Python/test execution, file writes, network execution, and live desktop control are blocked in production mode unless all guardrails are declared. Setting `GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=1` also fails the production gate.

Before deploying, run the repository release gate and review the production runbook:

```bash
python scripts/validate_release.py
```

See [Production Deployment](docs/PRODUCTION_DEPLOYMENT.md) for the env-file flow, Docker smoke tests, and production blockers.

---

## Public Launch SaaS

The `public` branch adds a SaaS launch foundation while preserving local-first mode. SaaS mode is designed around OIDC identity, organization/user/role tenancy, Postgres as source of truth, queued worker execution, approval-first governance, and Docker Compose VPS deployment.

Inspect readiness:

```bash
ghostchimera saas status
ghostchimera saas init-db --print-sql
ghostchimera worker status
```

Render the Docker Compose VPS launch shape:

```bash
cp .env.saas.example .env.saas
docker compose --env-file .env.saas -f docker-compose.saas.yml config
```

Create a local bootstrap owner record for smoke testing:

```bash
ghostchimera saas create-admin --email owner@example.com --org "Acme"
```

Set `GHOSTCHIMERA_DEPLOYMENT_TARGET=saas` only when Postgres, OIDC, session secret, secrets encryption key, and worker token are configured. See [Public Launch SaaS](docs/PUBLIC_LAUNCH_SAAS.md).

---

## Daily Production Maintenance

Ghost Chimera includes GitHub automation for keeping production support files current without silently changing runtime behavior:

- `.github/dependabot.yml` opens daily dependency update PRs for Python packages and GitHub Actions.
- `.github/workflows/daily-maintenance.yml` refreshes `docs/model_provider_catalog.json`, `docs/model_provider_catalog.md`, and `docs/dependency_audit.md`, then opens a review PR.
- `scripts/update_model_provider_catalog.py` refreshes OpenRouter and Hugging Face candidates by default, and adds Vultr models when `VULTR_INFERENCE_API_KEY` is configured as a GitHub secret.
- Model changes are review-then-activate. The maintenance job never writes API keys, never commits secrets, and never switches the active provider/model.

Run the same maintenance locally before a release:

```bash
python scripts/update_model_provider_catalog.py --sources openrouter,huggingface,vultr --output-json docs/model_provider_catalog.json --output-markdown docs/model_provider_catalog.md
python scripts/audit_dependencies.py --format markdown --output docs/dependency_audit.md
python -m pytest tests/test_update_model_provider_catalog.py tests/test_model_discovery.py -q
```

The release gate verifies these artifacts are present and secret-safe:

```bash
python scripts/validate_release.py
```

---

## Local Models

### llama.cpp / GGUF

```bash
python -m pip install -e ".[local]"

chimera-pilot status --local-model-path /models/qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
chimera-pilot run "explain the project" --local-model-path /models/qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
```

**Local model profiles** (`tiny`, `balanced`, `stronger`) map to GGUF configuration presets optimized for constrained hardware.

### Runtime specialization

Ghost Chimera includes a CuTeDSL-inspired specialization planner for MiniMind/llama.cpp. It classifies prompts as `prefill`, `decode`, or `hybrid` and derives `llama_cpp` batch hints:

```bash
# Inspect a plan without loading a model
chimera-pilot runtime-specialization "short prompt" --local-model-profile tiny --gpu-architecture sm100

# Pre-warm the plan cache before serving
chimera-pilot runtime-warmup --runtime-specialization-cache-dir .ghost/rs --local-model-profile tiny --local-model-profile balanced
```

Installing `.[cute]` enables detection of `nvidia-cutlass-dsl` on Linux/Python 3.12 systems.

### Local model bootstrap

```bash
ghostchimera local-model check     # report system resources vs profile requirements
ghostchimera local-model guide     # step-by-step download guide
ghostchimera local-model profiles  # list available profiles
```

---

## Ghost MiniMind

Ghost Chimera includes a Ghost-native MiniMind compatibility layer. The base package embeds architecture contracts for `minimind-3`, `minimind-3-moe`, `minimind2-small`, `minimind2-moe`, and `minimind2`. No weights are bundled.

To run MiniMind inference:

```bash
python -m pip install -e ".[minimind]"
export MINIMIND_MODEL_PATH=/models/minimind-3
ghostchimera minimind status
ghostchimera minimind architectures
```

MiniMind helpers for the training pipeline:

```bash
ghostchimera minimind dataset --prompt "..." --response "..."
ghostchimera minimind log-failure --prompt "..." --response "..." --confidence 0.2
ghostchimera minimind personal-consent --admin-controls --allow-system-specs --allow-files --allow-email --allow-autonomy --allow-training --file-path ~/Documents --email-path ~/mail/export.mbox
ghostchimera minimind personal-consent --admin-controls --allow-machine-crawl --allow-email-crawl --allow-training --crawl-root ~ --exclude-path ~/.ssh
ghostchimera minimind personal-bootstrap --include-system-specs
ghostchimera minimind personal-handoff --objective "Review my personal context and identify pending work."
```

Training data accumulates (append-only) at `~/.ghostchimera/minimind/datasets/dataset.jsonl`. `MINIMIND_ROOT` is optional for users who keep an upstream MiniMind workspace nearby.

Personal MiniMind in `0.4.0-beta` is the local-first bridge between the user's private context and the configured primary AI model:

- Admin controls are off until the operator grants consent from the MiniMind tab, CLI, or SDK.
- System specs, explicit files, explicit email exports, whole-machine crawling, email-artifact crawling, autonomy handoff, and training are separate consent scopes.
- Whole-machine crawl uses the current OS user permissions, default exclusions, configured roots, and file/email limits. It does not bypass permissions or decrypt protected stores.
- The local memory corpus becomes both RAG context and MiniMind JSONL training data.
- `personal-handoff` returns a ready prompt bundle containing relevant memory snippets, task hints, and the active Ghost Path policy for the configured main model.
- See `docs/PERSONAL_MINIMIND_PRIVACY.md` before enabling broad crawl on a machine that contains sensitive or regulated data.

MiniMind does not require a cloud AI provider for local personalization. The memory store, dataset generation, and handoff prompt are local. Real MiniMind inference can run on the user's machine when weights and runtime dependencies are installed, including a Transformers/PyTorch checkpoint via `.[minimind]` or compatible quantized local weights through the llama.cpp/GGUF path when available. The primary Ghost model can be a remote provider or a local model; Personal MiniMind only supplies the personal RAG context and task hints.

The integration is derived from the public Apache-2.0 MiniMind project and attributed in `NOTICE`.

**Important safety boundary:** Personal MiniMind is powerful and privacy-sensitive. It only reads local sources after explicit admin consent and approved path scopes, keeps the resulting memory/datasets local, and exposes revocation through the dashboard and CLI. Operators still provide MiniMind weights for real local inference and run any fine-tuning workflow in their own environment.

---

## Competitive Capability Matrix

Ghost Chimera ships a repo-grounded matrix that compares the project to Codex,
Claude Code, LangGraph, CrewAI, Hermes-style tool gateways, and OpenClaw-style
local autonomy patterns. The matrix checks real files and symbols, then reports
complete, partial, and missing surfaces.

```bash
ghostchimera capabilities --format json
python -m ghostchimera.evals run --suite competitive
```

The dashboard exposes the same report in the **Capabilities** tab. See
`docs/COMPETITIVE_CAPABILITY_MATRIX.md` for benchmark context and beta
positioning.

The matrix includes first-party PR review automation. Run it before merging or
pushing a beta branch:

```bash
ghostchimera review-pr --base origin/main --head HEAD
```

## Public Superiority Scorecard

Ghost Chimera uses a bounded scorecard instead of vague claims. It measures Operator UX, platform breadth, and autonomy depth from real Console, CLI, eval, and browser-facing surfaces.

```bash
ghostchimera superiority score --format json
python -m ghostchimera.evals run --suite superiority
python scripts/run_operator_workbench_e2e.py --no-screenshot
```

The same scorecard is available through `GET /api/console/superiority` and the Home tab Operator Workbench. It does not claim sentience, consciousness, AGI, or universal superiority over every AI system.

---

## Extension Surfaces

The `0.4.0-beta` line keeps the OpenClaw parity contracts from `0.3.0-beta` and adds Personal MiniMind as a dashboard-first local personalization layer:

| Contract | Purpose |
|---|---|
| `HookRegistry` | `before_tool_call`, `after_tool_call`, `llm_input`, `llm_output` lifecycle events. |
| `ToolMiddlewareChain` | Normalize, truncate, and wrap tool results before they enter agent context. |
| `PluginManifest` + `PluginLoader` | Declare plugin capabilities, activation rules, and contracts. |
| `BackgroundService` + `ServiceRegistry` | Long-running components with `start`, `stop`, `probe`, `status`. |
| `ApprovalHandler` + `ApprovalPolicy` | Human-reviewable gate for any tool call. |
| `SSRFPolicy` + `NetworkDispatcher` | Fail-closed outbound network with IP-range blocklist. |
| `AuthProfile` + `OAuthCredential` + `ExternalAuthProvider` | OpenClaw-style provider credential assembly. |
| Media provider interfaces | Image generation, speech, web search, web fetch, media understanding, document extraction. |
| `ModelCatalogEntry` | Known model pricing/context metadata used by the scheduler and router. |
| `TEXT_PROVIDERS` + `register_text_provider` | Typed provider registry enabling provider-by-capability lookup. |

---

## Verification and Confidence

Results move through `ResultEnvelope` with confidence, provenance, claims, warnings, constraints, and metadata. The verification layer checks structural output, expected keys/files, command status, provenance, confidence thresholds, claim support, and hallucination indicators.

The cognition layer exposes four confidence classes:

- `ConfidentValue` â€” high-quality evidence, no significant uncertainty.
- `ConvergeValue` â€” multiple signals converging on a stable answer.
- `ProvisionalValue` â€” plausible but requires validation.
- `ExploreValue` â€” speculative; treat as a hypothesis.

Confidence uses product-rule composition: multiple uncertain signals cannot combine into false certainty.

---

## Release Validation & Eval Suites

Before publishing or tagging a release, run the full gate:

```bash
ruff check .
python -m pytest -q
python scripts/validate_release.py
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python -m ghostchimera.evals run --suite workspace
python -m ghostchimera.evals run --suite competitive
python -m ghostchimera.evals run --suite superiority
python -m ghostchimera.evals run --suite coverage
python -m ghostchimera.evals run --suite redteam
python -m ghostchimera.evals run --suite track2
python -m ghostchimera.evals run --suite track3
python -m ghostchimera.evals run --suite track4
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
ghostchimera capabilities --format json
ghostchimera superiority score --format json
python scripts/run_operator_workbench_e2e.py --no-screenshot
ghostchimera review-pr --base HEAD --head HEAD
```

**Eval suite summary:**

| Suite | Coverage |
|---|---|
| `smoke` | Core compile/schedule/execute/verify pipeline. |
| `safety` | Policy gating, DPI scanning, Python execution denial, SSRF. |
| `autonomy` | Profile-aware job planning, fallback routing, approval gates. |
| `user-journey` | End-to-end workspace evidence â†’ CWR retrieval â†’ task context injection. |
| `workspace` | Workspace context injection, freshness scoring, citation quality, count(). |
| `competitive` | Capability matrix score, console route, and CLI report against Codex/Claude/LangGraph/CrewAI/Hermes/OpenClaw-style benchmarks. |
| `superiority` | Operator Workbench, scorecard CLI/API, platform breadth, autonomy-depth proof, and browser-facing E2E contract. |
| `github-connected` | GitHub auth detection, issue planning, console routes, and policy simulation. |
| `path-synthesis` | Role profiles, path synthesis, active path console route, path CLI, and source licensing policy. |
| `coverage` | SSRF policy, approval token, material policy, error classifier, MoA scoring, context compressor, autonomy queue, checkpoint save/restore, telemetry export. |
| `redteam` | Prompt injection blocking, credential-leak blocking, PII detection, exfiltration blocking, intent-mismatch flagging, benign-prompt pass-through, LobsterTrap enforcement, SecurityMonitor aggregation. |
| `track2` | Gemini provider integration (8 cases). |
| `track3` | Simulation / robotics backend (6 cases). |
| `track4` | Analytics and data-pipeline backend (9 cases). |

The full test suite (`python -m pytest tests/ -q`) covers 54 test modules and 1100+ tests.

---

## Development

```bash
ruff check .                          # lint (line-length=120, target=py311)
python -m pytest tests/ -v           # full test suite
python -m compileall ghostchimera tests  # compile check
python scripts/validate_release.py   # release gate
```

### Optional IBM Bob Developer Tools

The IBM Bob materials are optional hackathon and developer-experience tooling. They are not required to run Ghost Chimera, import the package, deploy Ghost Console, or use the production CLIs. Check repository health and get personalized onboarding guidance with the explicit Bob scripts:

```bash
python scripts/bob_accelerator.py              # comprehensive report
python scripts/bob_accelerator.py --format json  # machine-readable
python scripts/coverage_report.py              # test coverage analysis
```

See [`docs/BOB_OPTIONAL_TOOLING.md`](docs/BOB_OPTIONAL_TOOLING.md) for the runtime boundary and [`docs/IBM_BOB_WORKFLOW.md`](docs/IBM_BOB_WORKFLOW.md) for the complete Bob workflow.

The CI workflow runs the release gate and package build across Ubuntu, Windows, and macOS for Python 3.11, 3.12, and 3.13.

Install dev tools:

```bash
python -m pip install -e ".[dev,gateway,mcp]"
```

The full test suite requires `.[gateway]` (croniter) and `.[mcp]` (mcp) to be installed.

---

## Documentation

- `docs/USER_TUTORIAL.md` â€” first-run product tutorial for new users.
- `docs/quick-start.md` â€” fastest install and launch path.
- `CHIMERA_PILOT.md` â€” focused Chimera Pilot usage and backend notes.
- `SECURITY.md` â€” supported status, high-risk capabilities, and hardening guidance.
- `CHANGELOG.md` â€” detailed per-version change log.
- `docs/PERSONAL_MINIMIND_PRIVACY.md` â€” Personal MiniMind consent scopes, whole-machine/email crawling behavior, local storage, and local runtime guidance.
- `docs/ARCHITECTURE.md` â€” layered architecture and runtime convergence.
- `docs/AGENT_LOOP.md` â€” multi-turn `AIAgent` loop design.
- `docs/GATEWAY_SERVER.md` â€” gateway server HTTP route registry and WebSocket protocol.
- `docs/CRON_SCHEDULER.md` â€” cron scheduler design and safe defaults.
- `docs/MIXTURE_OF_AGENTS.md` â€” MoA scoring and Jaccard strategy selection.
- `docs/SUBAGENT_DELEGATION.md` â€” subagent pool and depth-limited tree spawning.
- `docs/CREDENTIAL_POOL.md` â€” credential pool and external auth provider contracts.
- `docs/DESKTOP_CONTROL_HANDOFF.md` â€” desktop control policy and handoff notes.
- `docs/BOB_OPTIONAL_TOOLING.md` â€” IBM Bob optional tooling boundary and opt-out guidance.
- `docs/IBM_BOB_WORKFLOW.md` â€” optional IBM Bob developer accelerator workflow and tools.
- `docs/adr/` â€” Architecture Decision Records documenting key design choices.
- `docs/PRODUCTION_ISOLATION.md` â€” production guardrail requirements.
- `docs/MISSING_IMPLEMENTATIONS.md` â€” beta wiring audit.
- `docs/RELEASE_CHECKLIST.md` â€” manual release verification checklist.
- `docs/RUNNING.md` â€” step-by-step Docker and local Python run guide.
- `docs/AUTONOMY_CAPABILITY_EXTRACTION.md` â€” extraction notes from AETHER, WRAITH, EVO, OpenChimera_v1, and appforge.
- `docs/CLEAN_ROOM.md` â€” clean-room implementation boundary.
- `docs/VULTR_HACKATHON_DEPLOYMENT.md` â€” Vultr VM public-demo deployment runbook.
- `docs/HACKATHON_SUBMISSION_GUIDE.md` â€” challenge track, submission framing, and demo script.
- `docs/IBM_BOB_HACKATHON_WORKFLOW.md` â€” Bob analysis evidence and Bob-to-Ghost delivery package.
- `streamlit-demo/` â€” optional safe judge landing app when a form requires Streamlit/Replit/Vercel.

---

## Appropriate Uses

- User-supervised automation and assistance for real work (planning + execution) in local-first mode.
- Desktop workflows via the desktop backend (dry-run by default; live mode requires explicit enablement).
- Governed repository change workflows: evidence retrieval â†’ plan â†’ policy checks â†’ PR-ready output.
- Building user-specific context via Operator Workspace evidence/reflections synced into local CWR memory.
- Production automation inside externally isolated, reviewed deployments that pass `ghostchimera doctor --production`.
- Batch orchestration and subagent workflow development.
- MCP gateway and credential-pool integration work.
- Tool/connector integration via MCP (email, calendar, CRM) through explicit, policy-gated tool surfaces.
- Extending Ghost Chimera with new backends, skills, and connectors.
- Analytics and data pipeline tasks (CSV aggregation, trend forecasting, anomaly detection).
- Simulation and robotics policy testing via the digital-twin simulation backend.

## Non-Goals And Boundaries

- Untrusted prompts, repositories, or code must run inside external isolation, not directly on a host machine.
- Ghost Chimera does not claim AGI, subjective consciousness, or fully autonomous operation.
- Commercial and enterprise deployments are expected to pass production guardrails and add organization-specific controls.
- Optional simulator support is not access to a proprietary quantum operating system.

---

## License

MIT â€” see `LICENSE`. Third-party attribution in `NOTICE`.

