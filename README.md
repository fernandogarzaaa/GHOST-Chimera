# Ghost Chimera

Ghost Chimera is a local-first beta agent orchestration runtime. It combines a modular agent stack with Chimera Pilot, a resource-control layer that compiles objectives into task specs, chooses an execution backend, enforces policy, verifies results, and records telemetry.

For hackathon positioning, Ghost Chimera is packaged as a single product: **Governed Enterprise Change Agent**. The product workflow is: repo + docs intake -> evidence retrieval -> governed plan -> policy/security checks -> PR-ready package with audit trail.

This is a developer beta for local experimentation, runtime research, and extension work. It is not AGI, not a secure sandbox for untrusted code by itself, and not a replacement for licensed quantum operating systems.

## Current Status

- Release phase: beta
- Package version: `0.3.0-beta`
- Python: 3.11 through 3.13
- License: MIT
- Runtime posture: local-first, conservative-by-default, optional integrations
- Validation gate: release script, test suite, build, smoke/safety/autonomy/user-journey evals, installed-wheel smokes

## What Is Wired

| Layer | Purpose |
| --- | --- |
| `agent_core` | Planner, task linearization, memory, skill dispatch, and Chimera Pilot handoff. |
| `chimera_pilot` | Task IR, compiler, backend registry, scheduler, policy gate, fallback executor, verifier, telemetry, checkpointing, batch orchestration, subagents, credential pool, gateway server, cron scheduling, toolsets, lifecycle hooks, tool-result middleware, plugin manifests, and service registry. |
| `cognition_layer` | Confidence values, hallucination flags, task ordering, self-model, working memory, attention, reflection primitives, and durable operator workspace state. |
| `control_plane` | User-facing CLIs for setup, diagnostics, model selection, policy management, parallel runs, and Pilot execution. |
| `evals` | Built-in release smoke and safety evaluation suites. |
| `mcp` | Lightweight JSON-RPC style MCP server/client surfaces and Chimera Pilot MCP backend. |
| `memory_layer` | SQLite-backed memory retrieval and namespace persistence. |
| `model_layer` | Provider abstraction, provider routing, auth profiles, model catalog, media-provider interfaces, Ghost-native MiniMind architecture/runtime adapters, runtime specialization, and optional llama.cpp/GGUF runtime. |
| `safety_layer` | Execution policy, approval gates, MaterialRegistry policy patterns, audit records, policy enforcement, SSRF/network dispatch, and rate limiting. |
| `skill_layer` | Built-in skills for browser fetches, code search, software tasks, tech support, issue conversion, and dynamic skill registry support. |
| `tool_layer` | Policy-aware filesystem, shell, and browser tools. |

## Quick Start (no install required)

Build and run the browser console with the included Docker artifacts:

```bash
docker compose up --build
```

Then open **http://localhost:8766/** in your browser. The console provides a point-and-click UI for running objectives, viewing autonomy jobs, managing schedules, inspecting the security monitor, and controlling the operator workspace — no terminal required after startup.

For a step-by-step Docker and local Python guide, see [`docs/RUNNING.md`](docs/RUNNING.md).

For public demo URL runbooks and judge-ready packaging, see `docs/HACKATHON_ALL_IN_ONE.md` and `docs/hackathons/DEPLOYMENT_RUNBOOK.md`.

## Developer Install

From a clean checkout (Python 3.11–3.13 required):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Optional extras:

```bash
python -m pip install -e ".[gateway]"  # WebSocket gateway and cron scheduling
python -m pip install -e ".[mcp]"      # MCP package integration
python -m pip install -e ".[local]"    # llama.cpp-compatible local model runtime
python -m pip install -e ".[minimind]" # optional MiniMind Transformers/PyTorch inference adapter
python -m pip install -e ".[cute]"     # optional NVIDIA CuTe DSL package on supported Linux/Python 3.12 systems
python -m pip install -e ".[quantum]"  # optional pyqpanda3 simulator backend
python -m pip install -e ".[dev]"      # build and lint tools
```

Heavy runtimes such as `llama-cpp-python`, MiniMind's PyTorch/Transformers path, `nvidia-cutlass-dsl`, and `pyqpanda3` are optional. The base package stays lightweight and stdlib-first.

## CLI Quickstart

Run the setup and diagnostics flow:

```bash
ghostchimera setup
ghostchimera doctor
ghostchimera model
ghostchimera --config-show
```

Open the local browser console when you do not want to drive Ghost Chimera through command flags:

```bash
python -m pip install -e ".[gateway]"
ghostchimera console
ghostchimera console --no-open
ghostchimera console --state-dir .ghost-console-state
```

To enable bearer token authentication on all API routes (recommended when the console is reachable beyond localhost):

```bash
ghostchimera console --auth-token mysecrettoken
```

The token is printed to the terminal on startup and entered in the browser prompt the first time.

The console runs on localhost by default and exposes status, autonomy profile controls, safe objective runs, a durable autonomy job center, recurring schedules, a live security monitor (DPI / LobsterTrap events + HMAC audit chain), a browser workspace tab, release-readiness checks, and optional `agent-browser` workspace controls through the gateway-backed UI. Install the `gateway` extra for WebSocket and cron scheduling dependencies. The browser workspace is optional; when `agent-browser` is not installed, the console reports a degraded browser-workspace state while core controls continue to work.

Inspect the local operator workspace state:

```bash
ghostchimera workspace show
ghostchimera workspace add-evidence --source release-audit --content "release gate passed" --confidence 0.92
ghostchimera workspace reflect --reflection-action "ran beta gate" --outcome "operator workspace stayed inspectable" --confidence 0.9
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
```

The workspace state is persisted under the Ghost Chimera state directory and is also available through `/api/console/workspace`. It exposes the self model, working memory, attention ranking, goals, and uncertainty for local operators. `sync-memory` promotes high-confidence evidence and reflections into the local CWR memory store with provenance metadata, filters low-confidence records, marks stale or conflicting records for review, and skips duplicates on repeat runs. It is not a claim of subjective consciousness, AGI, SGI, or fully autonomous production operation.

Inspect Chimera Pilot:

```bash
chimera-pilot status --include-deterministic-backend
chimera-pilot compile "retrieve memory about project"
chimera-pilot calibrate --include-deterministic-backend
```

Run a deterministic local task:

```bash
chimera-pilot run "retrieve memory about project" --include-deterministic-backend
```

Use the same Pilot path through the main control-plane CLI:

```bash
ghostchimera --pilot-status
ghostchimera --pilot-run "retrieve memory about project"
```

## Local Memory

Ghost Chimera includes Conscious Workspace Retrieval through a local SQLite FTS store:

```bash
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source project-note --content "Ghost Chimera stores local project memory."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "project memory"
chimera-pilot run "retrieve project memory" --memory-db .ghostchimera-memory.sqlite3 --include-deterministic-backend
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
```

## Execution Safety

Potentially dangerous execution surfaces are denied unless explicitly enabled.

Python execution is blocked by default:

```bash
chimera-pilot run "python: print(2 + 3)"
```

Trusted local Python can be enabled per run:

```bash
chimera-pilot run "python: print(2 + 3)" --allow-python
```

Desktop control is opt-in and dry-run oriented by default:

```bash
chimera-pilot run "click submit button" --enable-desktop-backend --allow-desktop-control --ghost-mode possess
```

Live desktop mutation requires the live backend flag, possess mode, explicit caller/runtime constraints, and bounded session limits:

```bash
chimera-pilot run "live desktop: click submit button" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess
```

Desktop actions are classified as `read_only`, `mutating`, or `destructive`. The default policy allows `read_only` and `mutating` only; destructive live desktop actions require an explicit action-class allowlist and confirmation token:

```bash
chimera-pilot run "live desktop: click delete project" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess --desktop-action-class read_only --desktop-action-class mutating --desktop-action-class destructive --desktop-confirm-token confirm-destructive-desktop
```

Multi-step desktop plans are supported with `then` or `->` chaining:

```bash
chimera-pilot run "live desktop: click app=chrome window=Docs then type hello world then press ctrl+s" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess --desktop-allow-app chrome --desktop-allow-window Docs
```

Desktop policy can now enforce app/window allowlists and denylists:

```bash
chimera-pilot status --enable-desktop-backend --allow-desktop-control --ghost-mode possess --desktop-allow-app chrome --desktop-deny-window Admin
```

Allowlist flags are opt-in: if no allowlist values are provided, targets are permitted unless denied.

Create the configured desktop kill switch from another terminal to stop live actions before the next backend action:

```bash
chimera-pilot desktop-stop --desktop-kill-switch-path .ghost/DESKTOP_STOP
```

For replayable live sessions, provide both an action log and screenshot directory. The backend captures best-effort before/after screenshots for each live action and includes those artifact paths in action logs, result metrics, and replay bundles:

```bash
chimera-pilot run "live desktop: click submit button" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess --desktop-action-log-path .ghost/desktop-actions.jsonl --desktop-screenshot-dir .ghost/desktop-screens
```

For unattended or high-impact use, run Ghost Chimera inside an external sandbox such as a container, VM, or locked-down service account. See `SECURITY.md`.

## Production Mode

Ghost Chimera now has an explicit production-readiness contract for high-impact execution. Set `GHOSTCHIMERA_DEPLOYMENT_MODE=production` and run:

```bash
ghostchimera doctor --production
```

Production mode blocks shell execution, local Python/test execution, file writes, network execution, and live desktop control unless the deployment declares all required guardrails:

```bash
GHOSTCHIMERA_EXTERNAL_ISOLATION=container
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
```

Accepted isolation declarations are `container`, `vm`, `service-account`, and `sandboxed`. Host execution also remains trusted-inputs-only by default; setting `GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=1` makes the production gate fail for high-impact local execution.

## Chimera Pilot Backends

Built-in backends currently include:

- `DeterministicBackend` for CI, smoke checks, and fallback testing.
- `PythonRuntimeBackend` for explicitly allowed local Python and unittest execution.
- `CWRBackend` for SQLite-backed local memory retrieval.
- `MCPBackend` for MCP-style tool execution.
- `LlamaCppBackend` for optional GGUF reasoning through a local model path.
- `PyQPanda3Backend` for optional pyqpanda3 simulator tasks.
- `DesktopRuntimeBackend` for dry-run desktop control and gated live desktop control.

The backend contract is intentionally small: every backend advertises capabilities, probes health, estimates fit, and executes a normalized `TaskSpec`.

## Extension Surfaces

The `0.3.0-beta` line closes the main OpenClaw parity gaps with concrete extension contracts:

- `HookRegistry` with `before_tool_call`, `after_tool_call`, `llm_input`, and `llm_output` lifecycle events.
- `ToolMiddlewareChain` for normalizing, truncating, and wrapping tool results before they enter agent context.
- `PluginManifest` and `PluginLoader` for declaring plugin capabilities, activation rules, and contracts.
- `BackgroundService` and `ServiceRegistry` for long-running components with `start`, `stop`, `probe`, and `status`.
- `ApprovalHandler` and `ApprovalPolicy` for human-reviewable tool calls.
- `SSRFPolicy` and `NetworkDispatcher` for fail-closed outbound network requests.
- `AuthProfile`, `OAuthCredential`, and `ExternalAuthProvider` for provider credential assembly.
- Media provider interfaces for image generation, speech, web search, web fetch, media understanding, and document extraction.
- `ModelCatalogEntry` for known model pricing/context metadata used by scheduling and routing.

## Confidence, Verification, And Results

Results move through `ResultEnvelope` with confidence, provenance, claims, warnings, constraints, and metadata. The verification layer checks structural output, expected keys/files, command status, provenance, confidence thresholds, claim support, and hallucination indicators.

The cognition layer exposes confidence classes:

- `ConfidentValue`
- `ConvergeValue`
- `ProvisionalValue`
- `ExploreValue`

Confidence uses product-rule composition so multiple uncertain signals do not become falsely certain.

## Local Model Profiles

Small local model profiles are exposed for constrained hardware:

```bash
chimera-pilot model-profiles
```

Profiles include `tiny`, `balanced`, and `stronger`. GGUF execution requires a compatible `llama_cpp` runtime and an explicit model path:

```bash
chimera-pilot status --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
chimera-pilot run "explain the current project" --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
```

## Ghost MiniMind

Ghost Chimera includes a Ghost-native MiniMind compatibility layer so open-source checkouts are not tied to a developer's local `MINIMIND_ROOT`. The base package embeds MiniMind architecture contracts for `minimind-3`, `minimind-3-moe`, `minimind2-small`, `minimind2-moe`, and `minimind2`, plus runtime inspection that distinguishes architecture availability from real local inference.

```bash
ghostchimera minimind architectures
ghostchimera minimind status
```

The integration is derived from the public Apache-2.0 MiniMind project and attributed in `NOTICE`. Ghost Chimera does not bundle MiniMind weights. To run MiniMind inference, install the optional adapter and point Ghost Chimera at a local Transformers-format model directory:

```bash
python -m pip install -e ".[minimind]"
export MINIMIND_MODEL_PATH=/models/minimind-3
ghostchimera minimind status
```

`MINIMIND_ROOT` remains optional for users who keep an upstream MiniMind workspace nearby. It is not required for status, architecture planning, dataset export, low-confidence logging, or release validation.

## Runtime Specialization

Ghost Chimera includes a CuTeDSL-inspired local runtime specialization planner for MiniMind/llama.cpp execution. It classifies each prompt as `prefill`, `decode`, or `hybrid`, derives vector/load-width, warp, grid-barrier, and `llama_cpp` batch hints, and exposes the selected plan in backend health and execution metrics.

Inspect a plan without loading a model:

```bash
chimera-pilot runtime-specialization "short prompt" --local-model-profile tiny --local-model-gpu-layers 12 --gpu-architecture sm100 --gpu-sm-count 160 --estimated-output-tokens 2
```

Precompute the built-in decode, hybrid, and prefill plans for one or more profiles before serving:

```bash
chimera-pilot runtime-warmup --runtime-specialization-cache-dir .ghost/runtime-specialization --local-model-profile tiny --local-model-profile balanced
ghostchimera runtime-warmup --runtime-specialization-cache-dir .ghost/runtime-specialization --local-model-profile stronger
```

When a GGUF model is enabled, the same planner feeds the local runtime's `n_batch` load parameter and can persist replayable manifests:

```bash
chimera-pilot run "explain the current project" --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --runtime-specialization-cache-dir .ghost/runtime-specialization
```

Installing `.[cute]` enables detection of NVIDIA's `nvidia-cutlass-dsl` package on supported Linux/Python 3.12 systems. Ghost Chimera does not claim to compile custom CuTeDSL kernels unless that runtime exists in the deployment; the beta path currently uses the specialization plan to tune and report local model execution.

## Adjustable Autonomy

Ghost Chimera exposes autonomy as an operator-adjustable profile, not as a claim of AGI or consciousness:

```bash
chimera-pilot autonomy-profiles
ghostchimera autonomy jobs
ghostchimera autonomy run repair-preview
ghostchimera minimind architectures
ghostchimera minimind status
chimera-pilot status --autonomy-level supervised --include-deterministic-backend
chimera-pilot run "retrieve project memory" --autonomy-level autonomous --memory-db .ghostchimera-memory.sqlite3 --include-deterministic-backend
```

Profiles:

- `assist` keeps execution single-backend with small tool-loop budgets.
- `supervised` is the default beta posture with fallback routing and approval requirements.
- `autonomous` enables larger tool-loop budgets, scheduler adaptation, and bounded parallel task execution when the caller has already opted into the underlying execution permissions.
- `generalist` is the highest local-first beta profile with MoA-style strategy selection and preview-only self-improvement posture.

`GHOSTCHIMERA_AUTONOMY_LEVEL` sets the default profile. The aliases `agi` and `sgi` are accepted as operator shorthand for `generalist`, but Ghost Chimera still does not claim AGI, subjective consciousness, or fully autonomous operation.

The main control-plane CLI can persist operator defaults in `~/.ghostchimera/config.json`:

```bash
ghostchimera autonomy show
ghostchimera autonomy set --level autonomous --local-model-profile stronger
```

Profile-aware jobs include `self-audit`, `dependency-scan`, `test-regression`, `memory-refresh`, `model-health-check`, and `repair-preview`. Conservative profiles return preview plans for high-impact jobs. `autonomous` and `generalist` may run bounded checks when the caller passes `--execute`, but source mutation, training, network access, Python execution, shell execution, and desktop control still require their existing policy opt-ins and production guardrails.

The browser console adds a local job center for the same profile-aware jobs. It records durable history in the Ghost Chimera state directory, supports queued preview runs, exposes run-now for operator-approved jobs, and creates disabled recurring schedules that reuse the same profile and policy checks before execution.

MiniMind helpers provide embedded architecture status, optional runtime inspection, dataset generation, and low-confidence logging:

```bash
ghostchimera minimind dataset --prompt "Summarize this finding" --response "..."
ghostchimera minimind log-failure --prompt "..." --response "..." --confidence 0.2
```

## Release Validation

Before publishing or tagging a release, run:

```bash
python -m ruff check .
python -m pytest -q
python scripts/validate_release.py
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
```

For package validation, install the built wheel into a fresh virtual environment and smoke the console and workspace entry points:

```bash
python -m ghostchimera.control_plane.cli --help
python -m ghostchimera.control_plane.cli console --help
python -m ghostchimera.control_plane.cli workspace show
python -m ghostchimera.chimera_pilot.cli --help
python -m ghostchimera.evals run --suite safety
```

## Documentation

- `CHIMERA_PILOT.md` - focused Chimera Pilot usage and backend notes.
- `docs/ARCHITECTURE.md` - layered architecture and runtime convergence.
- `docs/AUTONOMY_CAPABILITY_EXTRACTION.md` - extraction notes from AETHER, WRAITH, EVO, OpenChimera_v1, and appforge.
- `docs/CLEAN_ROOM.md` - clean-room implementation boundary.
- `docs/DESKTOP_CONTROL_HANDOFF.md` - desktop control policy and handoff notes.
- `docs/MISSING_IMPLEMENTATIONS.md` - beta wiring audit.
- `docs/RELEASE_CHECKLIST.md` - release checks and manual verification.
- `SECURITY.md` - supported status, high-risk capabilities, and hardening guidance.
- `docs/HACKATHON_ALL_IN_ONE.md` - single-product framing and four-track mapping.
- `docs/hackathons/SUBMISSION_KIT.md` - short/long descriptions, tags, and judging-mapped bullets.
- `docs/hackathons/DEMO_SCRIPTS.md` - one shared demo flow plus four track narratives.
- `docs/hackathons/TRUST_STORY.md` - judge-facing trust, policy, and evidence checklist.
- `docs/hackathons/IBM_BOB_TRACK_PACK.md` - IBM Bob workflow + required Bob artifact guidance.
- `docs/hackathons/DEPLOYMENT_RUNBOOK.md` - public demo URL deployment runbook.

## Appropriate Uses

- Local agent-runtime experimentation.
- Backend scheduling and fallback research.
- Safety-gated tool/runtime prototyping.
- Production automation inside externally isolated, reviewed deployments that pass `ghostchimera doctor --production`.
- Local memory and model-profile experiments.
- Batch orchestration and subagent workflow development.
- MCP gateway and credential-pool integration work.
- Release-gated extension development.

## Non-Goals And Boundaries

- Untrusted prompts, repositories, or code should run only inside external isolation, not directly on a host machine.
- Ghost Chimera does not claim AGI, subjective consciousness, or fully autonomous operation.
- Commercial and enterprise deployments are expected to pass production guardrails and add organization-specific controls.
- Optional simulator support is not access to a proprietary quantum operating system.

## Development

```bash
python -m pytest tests/ -v
ruff check .
python -m compileall ghostchimera tests
python scripts/validate_release.py
```

The CI workflow runs the release gate and package build across Ubuntu, Windows, and macOS for Python 3.11, 3.12, and 3.13.
