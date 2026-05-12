# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ghost Chimera is a local-first agent orchestration prototype (v0.3.0-beta). It provides a layered agent runtime with **Chimera Pilot** as the control-plane: a resource orchestrator that compiles natural-language objectives into a task IR, schedules them across registered backends using weighted scoring, enforces safety policy, executes with fallback, and records telemetry. Beta-stage — designed for local experimentation, not production.

Python 3.11–3.13. MIT licensed.

## Quick Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'              # dev deps (ruff, pytest, build)
pip install -e '.[gateway]'          # WebSocket gateway + cron
pip install -e '.[mcp]'             # MCP support
pip install -e '.[local]'           # llama.cpp local inference
pip install -e '.[minimind]'        # MiniMind PyTorch adapter
pip install -e '.[all]'             # all optional features

# Lint (ruff, line-length=120, target py311)
ruff check .

# Compile check
python -m compileall ghostchimera tests

# Tests (stdlib unittest / pytest)
python -m pytest tests/
python -m pytest tests/ -v           # verbose
python -m pytest tests/test_chimera_pilot.py -v  # single file

# Release validation
python scripts/validate_release.py

# Eval suites
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey

# Package build
python -m build

# Smoke installed wheel
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway

# CLI
ghostchimera setup
ghostchimera doctor
ghostchimera --config-show
ghostchimera --pilot-status
ghostchimera --pilot-run "objective"
chimera-pilot status --include-deterministic-backend
chimera-pilot compile "objective"
chimera-pilot run "objective" --include-deterministic-backend
chimera-pilot autonomy-profiles
ghostchimera autonomy show
ghostchimera minimind architectures
```

## Architecture

```
ghostchimera/
  agent_core/       Legacy planner/skill executor + AgentCore facade (Chimera Pilot handoff)
  chimera_pilot/    Control-plane: compiler, scheduler, policy, executor, verifier, telemetry
    backends/       Runtime backends (deterministic, python, cwr, llamacpp, pyqpanda3, desktop, mcp)
  cognition_layer/  CWR state primitives (SelfModel, WorkingMemory, AttentionController, ReflectionEngine)
  control_plane/    CLI entry points (chimera-pilot, ghostchimera, gateway console)
  evals/            Smoke and safety evaluation suites
  memory_layer/     SQLite FTS5 local memory store with namespace support
  model_layer/      LLM provider abstraction, router, local model profiles, MiniMind adapters, llama.cpp runtime
  safety_layer/     ExecutionPolicy gating, approval gates, audit records, SSRF policy, rate limiting, production mode
  skill_layer/      Domain skills (code_search, tech_support, to_issues, software_engineer, browser_operator)
  tool_layer/       Policy-gated filesystem, shell, and browser wrappers
mcp/                 Lightweight JSON-RPC MCP server/client surfaces
```

### Key design patterns

**Two execution paths:** `AgentCore.handle_request()` tries Chimera Pilot first (structured task IR + backend scheduling). If no registered backend can handle the task, it falls back to the legacy planner/skill executor with the same `ExecutionPolicy`.

**Chimera Pilot pipeline:** Objective -> `RuleBasedTaskCompiler` -> `TaskSpec` list -> `ChimeraScheduler` (weighted scoring) -> best backend -> `ChimeraPilotExecutor` (with fallback) -> `Verifier` -> telemetry.

**Backend contract:** Every backend exposes `id`, `name`, `capabilities`, `probe()`, `can_run(task)`, `estimate(task)`, `execute()`. This unifies local runtimes, cloud models, MCP connectors, and quantum simulators behind one scheduling interface.

**Safety boundary:** Scheduler decides *where* to run; policy decides *whether* it's allowed. Two separate layers (`PilotPolicy` for Chimera Pilot tasks, `ExecutionPolicy` for tool-layer operations). Network access denied by default, Python/test execution denied by default.

**Conservative defaults:** Production mode (`GHOSTCHIMERA_DEPLOYMENT_MODE=production`) blocks shell execution, file writes, and live desktop control unless deployment declares required guardrails.

**Autonomy profiles:** `assist` (single-backend, small budgets), `supervised` (default, fallback routing + approvals), `autonomous` (larger budgets, bounded parallel), `generalist` (highest, MoA-style strategy selection). Set via `GHOSTCHIMERA_AUTONOMY_LEVEL`.

### Core files

| Area | Key file(s) |
|------|------|
| Entry point | `ghostchimera/control_plane/cli.py` |
| Agent facade | `ghostchimera/agent_core/core.py` (AgentCore) |
| Pilot kernel | `ghostchimera/chimera_pilot/kernel.py` (ChimeraPilotKernel) |
| Task IR | `ghostchimera/chimera_pilot/task_ir.py` (TaskSpec, TaskKind) |
| Compiler | `ghostchimera/chimera_pilot/compiler.py` (RuleBasedTaskCompiler) |
| Scheduler | `ghostchimera/chimera_pilot/scheduler.py` (weighted scoring) |
| Pilot policy | `ghostchimera/chimera_pilot/policy.py` (PilotPolicy) |
| Tool policy | `ghostchimera/safety_layer/gating.py` (ExecutionPolicy) |
| Config | `ghostchimera/config.py` (GhostChimeraConfig) |
| LLM layer | `ghostchimera/model_layer/llm.py` + `providers.py` + `router.py` |
| Memory store | `ghostchimera/memory_layer/store.py` |
| CWR primitives | `ghostchimera/cognition_layer/workspace.py` |
| Evals | `ghostchimera/evals/runner.py` |
| Release validator | `scripts/validate_release.py` |
| CI | `.github/workflows/ci.yml` |

### New runtime components (v0.3.0)

| Component | File |
|------|------|
| AIAgent (multi-turn loop) | `chimera_pilot/agent_loop.py` |
| ContextCompressor | `chimera_pilot/context_compressor.py` |
| MCPWrapper | `chimera_pilot/mcp_wrapper.py` |
| CredentialPool | `chimera_pilot/credential_pool.py` |
| ErrorClassifier | `chimera_pilot/error_classifier.py` |
| CheckpointManager | `chimera_pilot/checkpoint.py` |
| ToolsetManager | `chimera_pilot/toolsets.py` |
| SubagentPool | `chimera_pilot/subagent.py` |
| MixtureOfAgents | `chimera_pilot/mixture_of_agents.py` |
| BatchRunner | `chimera_pilot/batch_runner.py` |
| CronScheduler | `chimera_pilot/cron_scheduler.py` |
| GatewayServer | `chimera_pilot/gateway_server.py` |

### Extension surfaces

- `HookRegistry` with `before_tool_call`, `after_tool_call`, `llm_input`, `llm_output` events
- `ToolMiddlewareChain` for normalizing/wrapping tool results
- `PluginManifest` + `PluginLoader` for declaring plugin capabilities
- `BackgroundService` + `ServiceRegistry` for long-running components
- `ApprovalHandler` + `ApprovalPolicy` for human-reviewable tool calls
- `SSRFPolicy` + `NetworkDispatcher` for fail-closed network
- `AuthProfile` + `OAuthCredential` + `ExternalAuthProvider` for credentials
- `ModelCatalogEntry` for model pricing/context metadata

## Environment Variables

| Variable | Purpose |
|------|------|
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI provider |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Anthropic provider |
| `GOOGLE_API_KEY` / `GEMINI_MODEL` | Google Gemini provider |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq LPU inference (default model: `llama-3.3-70b-versatile`) |
| `XAI_API_KEY` / `XAI_MODEL` | xAI / Grok provider (default model: `grok-3-mini`) |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | Mistral AI provider (default model: `mistral-small-latest`) |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | DeepSeek provider (default model: `deepseek-chat`) |
| `TOGETHER_API_KEY` / `TOGETHER_MODEL` | Together AI open-model hosting (default: `meta-llama/Llama-3-70b-chat-hf`) |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | OpenRouter gateway — 100+ models (default: `openai/gpt-4o-mini`) |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local Ollama server (default URL: `http://localhost:11434`, model: `llama3.2`) |
| `COHERE_API_KEY` / `COHERE_MODEL` | Cohere provider (default model: `command-r-plus`) |
| `PERPLEXITY_API_KEY` / `PERPLEXITY_MODEL` | Perplexity AI — search-augmented models (default: `llama-3.1-sonar-small-128k-online`) |
| `FIREWORKS_API_KEY` / `FIREWORKS_MODEL` | Fireworks AI fast inference (default: `accounts/fireworks/models/llama-v3p1-70b-instruct`) |
| `CEREBRAS_API_KEY` / `CEREBRAS_MODEL` | Cerebras ultra-fast inference (default model: `llama3.1-70b`) |
| `AI21_API_KEY` / `AI21_MODEL` | AI21 Labs Jamba models (default model: `jamba-1.5-mini`) |
| `HF_TOKEN` / `HUGGINGFACE_MODEL` | Hugging Face Inference API (default: `meta-llama/Llama-3.3-70B-Instruct`) |
| `NVIDIA_API_KEY` / `NVIDIA_MODEL` | NVIDIA NIM GPU inference (default: `meta/llama-3.1-70b-instruct`) |
| `MOONSHOT_API_KEY` / `MOONSHOT_MODEL` | Moonshot AI / Kimi (default: `moonshot-v1-8k`) |
| `DEEPINFRA_API_KEY` / `DEEPINFRA_MODEL` | DeepInfra affordable inference (default: `meta-llama/Meta-Llama-3.1-70B-Instruct`) |
| `DASHSCOPE_API_KEY` / `QWEN_MODEL` | Alibaba DashScope / Qwen (default: `qwen-turbo`) |
| `ARK_API_KEY` / `VOLCENGINE_MODEL` | Volcengine / ByteDance Doubao (default: `doubao-pro-4k`) |
| `STEPFUN_API_KEY` / `STEPFUN_MODEL` | StepFun AI (default: `step-1-8k`) |
| `ZHIPUAI_API_KEY` / `GLM_MODEL` | ZhipuAI GLM-4 (default: `glm-4-flash`) |
| `VENICE_API_KEY` / `VENICE_MODEL` | Venice AI privacy-preserving inference (default: `llama-3.3-70b`) |
| `LMSTUDIO_BASE_URL` / `LMSTUDIO_MODEL` | Local LM Studio server (default URL: `http://localhost:1234`) |
| `GHOSTCHIMERA_MODEL_PROVIDER` | Default provider (e.g. `groq`, `mistral`, `ollama`) |
| `GHOSTCHIMERA_STATE_DIR` | State directory (default `~/.ghostchimera`) |
| `GHOSTCHIMERA_MEMORY_DB` | CWR SQLite path |
| `GHOSTCHIMERA_AUTONOMY_LEVEL` | Default autonomy profile |
| `GHOSTCHIMERA_DEPLOYMENT_MODE` | Set `production` for high-impact guardrails |
| `GHOSTCHIMERA_EXTERNAL_ISOLATION` | Isolation declaration: `container`, `vm`, `service-account`, `sandboxed` |
| `MINIMIND_MODEL_PATH` | Path to MiniMind model weights |
| `MINIMIND_ROOT` | Upstream MiniMind workspace (optional) |

## Release Validation

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
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
```

## Docs

- `CHIMERA_PILOT.md` - focused Chimera Pilot usage and backend notes
- `docs/ARCHITECTURE.md` - layered architecture and runtime convergence
- `docs/RELEASE_CHECKLIST.md` - release checks
- `docs/MISSING_IMPLEMENTATIONS.md` - beta wiring audit
- `SECURITY.md` - supported status and hardening guidance
