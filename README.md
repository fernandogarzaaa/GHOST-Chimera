# Ghost Chimera

Ghost Chimera is a local-first beta agent orchestration runtime. It combines a modular agent stack with Chimera Pilot, a resource-control layer that compiles objectives into task specs, chooses an execution backend, enforces policy, verifies results, and records telemetry.

This is a developer beta for local experimentation, runtime research, and extension work. It is not AGI, not a secure sandbox for untrusted code by itself, and not a replacement for licensed quantum operating systems.

## Current Status

- Release phase: beta
- Package version: `0.3.0-beta`
- Python: 3.11 through 3.13
- License: MIT
- Runtime posture: local-first, conservative-by-default, optional integrations
- Validation gate: release script, test suite, build, smoke evals, safety evals

## What Is Wired

| Layer | Purpose |
| --- | --- |
| `agent_core` | Planner, task linearization, memory, skill dispatch, and Chimera Pilot handoff. |
| `chimera_pilot` | Task IR, compiler, backend registry, scheduler, policy gate, fallback executor, verifier, telemetry, checkpointing, batch orchestration, subagents, credential pool, gateway server, cron scheduling, toolsets, lifecycle hooks, tool-result middleware, plugin manifests, and service registry. |
| `cognition_layer` | Confidence values, hallucination flags, task ordering, self-model, working memory, attention, and reflection primitives. |
| `control_plane` | User-facing CLIs for setup, diagnostics, model selection, policy management, parallel runs, and Pilot execution. |
| `evals` | Built-in release smoke and safety evaluation suites. |
| `mcp` | Lightweight JSON-RPC style MCP server/client surfaces and Chimera Pilot MCP backend. |
| `memory_layer` | SQLite-backed memory retrieval and namespace persistence. |
| `model_layer` | Provider abstraction, provider routing, auth profiles, model catalog, media-provider interfaces, minimind-compatible profiles, and optional llama.cpp/GGUF runtime. |
| `safety_layer` | Execution policy, approval gates, MaterialRegistry policy patterns, audit records, policy enforcement, SSRF/network dispatch, and rate limiting. |
| `skill_layer` | Built-in skills for browser fetches, code search, software tasks, tech support, issue conversion, and dynamic skill registry support. |
| `tool_layer` | Policy-aware filesystem, shell, and browser tools. |

## Install

From a clean checkout:

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
python -m pip install -e ".[cute]"     # optional NVIDIA CuTe DSL package on supported Linux/Python 3.12 systems
python -m pip install -e ".[quantum]"  # optional pyqpanda3 simulator backend
python -m pip install -e ".[dev]"      # build and lint tools
```

Heavy runtimes such as `llama-cpp-python`, `nvidia-cutlass-dsl`, and `pyqpanda3` are optional. The base package stays lightweight and stdlib-first.

## CLI Quickstart

Run the setup and diagnostics flow:

```bash
ghostchimera setup
ghostchimera doctor
ghostchimera model
ghostchimera --config-show
```

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

## Runtime Specialization

Ghost Chimera includes a CuTeDSL-inspired local runtime specialization planner for MiniMind/llama.cpp execution. It classifies each prompt as `prefill`, `decode`, or `hybrid`, derives vector/load-width, warp, grid-barrier, and `llama_cpp` batch hints, and exposes the selected plan in backend health and execution metrics.

Inspect a plan without loading a model:

```bash
chimera-pilot runtime-specialization "short prompt" --local-model-profile tiny --local-model-gpu-layers 12 --gpu-architecture sm100 --gpu-sm-count 160 --estimated-output-tokens 2
```

When a GGUF model is enabled, the same planner feeds the local runtime's `n_batch` load parameter and can persist replayable warmup manifests:

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

MiniMind helpers provide lightweight local runtime status, dataset generation, and low-confidence logging:

```bash
ghostchimera minimind dataset --prompt "Summarize this finding" --response "..."
ghostchimera minimind log-failure --prompt "..." --response "..." --confidence 0.2
```

## Release Validation

Before publishing or tagging a release, run:

```bash
python scripts/validate_release.py
python -m pytest -q
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
```

For package validation, install the built wheel into a fresh virtual environment and smoke the console entry points:

```bash
python -m ghostchimera.control_plane.cli --help
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
