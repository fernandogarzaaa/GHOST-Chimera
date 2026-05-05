# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ghost Chimera is a local-first agent orchestration prototype (v0.2.0-beta). It provides a layered agent runtime with **Chimera Pilot** as the control-plane: a resource orchestrator that compiles natural-language objectives into a task IR, schedules them across registered backends using weighted scoring, enforces safety policy, executes with fallback, and records telemetry. Alpha-stage — designed for local experimentation, not production.

## Quick Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'                    # dev deps (ruff, build)
pip install -e '.[quantum]'               # optional quantum simulator
pip install -e '.[local]'                 # optional local inference (llama-cpp)

# Lint (ruff, line-length=120, target py311)
ruff check ghostchimera tests

# Compile check
python -m compileall ghostchimera tests

# Tests (stdlib unittest / pytest)
python -m pytest tests/
python -m unittest tests.test_chimera_pilot tests.test_release_package tests.test_safety_policy -v

# Release validation
python scripts/validate_release.py

# Eval suites
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety

# CLI
ghostchimera status
ghostchimera compile <goal>
ghostchimera calibrate
ghostchimera run <goal> --include-deterministic-backend
chimera-pilot status
chimera-pilot memory-add <sqlite_path> <item>
chimera-pilot memory-search <sqlite_path> <query>
chimera-pilot model-profiles
ghostchimera --config-show
```

## Architecture

```
ghostchimera/
  agent_core/       Legacy planner/skill executor + AgentCore facade
  chimera_pilot/    Control-plane: compiler, scheduler, policy, executor, verifier, telemetry
    backends/       Runtime backends (deterministic, python, cwr, llamacpp, pyqpanda3)
  cognition_layer/  CWR state primitives (SelfModel, WorkingMemory, AttentionController, ReflectionEngine)
  control_plane/    CLI entry points (chimera-pilot, ghostchimera)
  evals/            Smoke and safety evaluation suites
  memory_layer/     SQLite FTS5 local memory store
  model_layer/      LLM provider abstraction + router, local model profiles
  safety_layer/     ExecutionPolicy gating and audit records
  skill_layer/      Domain skills (code_search, tech_support, to_issues, software_engineer, browser_operator)
  tool_layer/       Policy-gated filesystem, shell, and browser wrappers
```

### Key design patterns

**Two execution paths:** `AgentCore.handle_request()` tries Chimera Pilot first (structured task IR + backend scheduling). If no registered backend can handle the task, it falls back to the legacy planner/skill executor with the same `ExecutionPolicy`.

**Chimera Pilot pipeline:** Objective -> `RuleBasedTaskCompiler` -> `TaskSpec` list -> `ChimeraScheduler` (weighted scoring) -> best backend -> `ChimeraPilotExecutor` (with fallback) -> `Verifier` -> telemetry.

**Backend contract:** Every backend exposes `id`, `name`, `capabilities`, `probe()`, `can_run(task)`, `estimate(task)`, `execute()`. This unifies local runtimes, cloud models, MCP connectors, and quantum simulators behind one scheduling interface.

**Safety boundary:** Scheduler decides *where* to run; policy decides *whether* it's allowed. Two separate layers (`PilotPolicy` for Chimera Pilot tasks, `ExecutionPolicy` for tool-layer operations).

**Conservative defaults:** Network access denied, Python/test execution denied. Python runs with bounded timeout, minimal env, isolated interpreter, temp cwd, AST-level rejection of high-risk calls. Denied fragments hardcoded in `chimera_pilot/policy.py`.

**Local model profiles:** Three built-in profiles configured via environment variables (see `.env.example`): `tiny` (fastest/lightest), `balanced`, `stronger` (best quality). GGUF support requires an external inference runtime.

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

## MCP Integration

This project is configured with the **ChimeraLang MCP server** (44 tools for probabilistic types, confidence gating, hallucination detection, and provenance tracking). Configuration lives in `.claude/settings.json`.

### Setup

```bash
# Install the MCP server (comes from the chimeralang-mcp package)
pip install chimeralang-mcp
# or for development:
pip install -e /path/to/chimeralang-mcp
```

The server is configured in `.claude/settings.json` to transport via stdio. Verify it is running:

```bash
python3 -m chimeralang_mcp.server --transport stdio
```

### Available Tool Categories

| Category | Tools | Use case |
|----------|-------|----------|
| **Core language** | `chimera_run`, `chimera_typecheck`, `chimera_prove` | Execute/type-check ChimeraLang programs with integrity proofs |
| **Confidence gating** | `chimera_confident`, `chimera_explore`, `chimera_gate` | Assert confidence >= threshold, wrap uncertain values, consensus collapse |
| **Safety** | `chimera_detect`, `chimera_safety_check`, `chimera_constrain` | Hallucination detection, policy validation, constraint middleware |
| **Reasoning** | `chimera_plan_goals`, `chimera_causal`, `chimera_deliberate`, `chimera_quantum_vote` | Multi-path deliberation, causal graphs, consensus voting |
| **Knowledge** | `chimera_world_model`, `chimera_knowledge`, `chimera_memory` | Persistent namespace-scoped state carried across sessions |
| **Provenance** | `chimera_claims`, `chimera_verify`, `chimera_provenance_merge`, `chimera_trace` | Evidence-backed verification, claim extraction, FEVER-style verdicts |
| **Token budget** | `chimera_compress`, `chimera_optimize`, `chimera_budget`, `chimera_cost_estimate` | Query-aware text compression with quantum-inspired salience scoring |

All stateful tools persist to `~/.chimeralang_mcp` (configurable via `CHIMERA_MCP_DATA_DIR`).

### Hook Configuration

ChimeraLang ships with lifecycle hooks for session telemetry. Add to `.claude/settings.json` hooks:

```jsonc
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "pip install -e . -q 2>/dev/null || true" },
                  { "type": "command", "command": "python -m chimeralang_mcp.cli hook --event session-start" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python -m chimeralang_mcp.cli hook --event user-prompt" }] }
    ],
    "PreToolUse": [
      { "hooks": [{ "type": "command", "command": "python -m chimeralang_mcp.cli hook --event pre-tool-use" }] }
    ],
    "PostToolUse": [
      { "hooks": [{ "type": "command", "command": "python -m chimeralang_mcp.cli hook --event post-tool-use" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "python -m chimeralang_mcp.cli hook --event stop" }] }
    ]
  }
}
```

### Usage Examples

**Gate a value before acting:**
Use `chimera_confident` to verify data confidence >= 0.95 before submitting results.

**Consensus across reasoning paths:**
Run `chimera_quantum_vote` to collapse multiple candidate answers into the most reliable one via contradiction detection.

**Hallucination scan on output:**
Run `chimera_detect` with `strategy="semantic"` on tool results to flag absolute-certainty markers or out-of-range values.

**Evidence-backed fact-checking:**
Use `chimera_claims` to extract atomic claims, then `chimera_verify` against source text, then `chimera_policy` with `strict_factual` to enforce rigor.

**Cost tracking during long sessions:**
Use `chimera_cost_track` before and after compression operations, check `chimera_budget` for token usage against a cap, and use `chimera_dashboard` for a session-level summary.

### Materials Pack

The MCP package ships with a curated core material pack. Inspect it with `chimera_materials` or use the CLI:

```bash
chimeralang-mcp status
chimeralang-mcp licenses
chimeralang-mcp sync          # fetch upstream metadata snapshots
chimeralang-mcp build         # write normalized JSON manifests to disk
```

## Hermes-Agent Migration (v0.3.0)

Ghost Chimera has been enhanced with the full Hermes-Agent (Nous Research) architecture — agent loop, multi-provider credentials, subagent delegation, parallel reasoning, cron scheduling, and WebSocket gateway.

### New runtime components

| Component | File | Purpose |
|------|------|------|
| **AIAgent** | `chimera_pilot/agent_loop.py` | Multi-turn agent with tool-calling loop, error recovery, model fallback |
| **ContextCompressor** | `chimera_pilot/context_compressor.py` | Lossy conversation compression, ContextEngine base for pluggable engines |
| **MCPWrapper** | `chimera_pilot/mcp_wrapper.py` | MCPClient, MCPRegistry, universal MCP tool bridge |
| **CredentialPool** | `chimera_pilot/credential_pool.py` | Multi-provider auth, key rotation, quota tracking, health monitoring |
| **ErrorClassifier** | `chimera_pilot/error_classifier.py` | 13 error categories, auto-recovery plans, severity scoring, regex + predicate rules |
| **CheckpointManager** | `chimera_pilot/checkpoint.py` | Shadow git repo snapshots, CRUD, diff, pruning |
| **ToolsetManager** | `chimera_pilot/toolsets.py` | Composable tool groups with progressive disclosure (coding, research, safety, devops) |
| **SubagentPool** | `chimera_pilot/subagent.py` | Isolated child agents, spawn/spawn_parallel/spawn_tree, depth limiting, delegation tool |
| **MixtureOfAgents** | `chimera_pilot/mixture_of_agents.py` | Parallel reasoning, quality scoring, contradiction detection, consensus voting, multi-round revote |
| **BatchRunner** | `chimera_pilot/batch_runner.py` | Multiprocessing batch execution, result aggregation, JSONL output |
| **CronScheduler** | `chimera_pilot/cron_scheduler.py` | Cron expressions, persistent state, periodic execution |
| **GatewayServer** | `chimera_pilot/gateway_server.py` | WebSocket persistent sessions, real-time tool streaming, remote agent management |

### Quick start (new features)

```bash
# Agent loop
from ghostchimera.chimera_pilot.agent_loop import AIAgent
agent = AIAgent(model_name="claude-sonnet-4-20250514")
agent.start_session("my-session")
response = agent.run("Write a Python function to sort a list")

# Credential pool
from ghostchimera.chimera_pilot.credential_pool import get_pool
pool = get_pool()
pool.add_credential("openai", api_key="sk-...")
best = pool.select_best_provider()

# Subagent delegation
from ghostchimera.chimera_pilot.subagent import SubagentPool
pool = SubagentPool("Analyze these repos", max_workers=3)
result = pool.spawn_parallel(["review auth", "review tests", "review deps"])
print(result.to_dict())

# Mixture of agents
from ghostchimera.chimera_pilot.mixture_of_agents import get_moa
moa = get_moa(num_agents=5)
result = moa.vote("What is the best architecture for a 10k LOC codebase?")
print(f"Consensus: {result.consensus_answer[:200]}")
print(f"Agreement: {result.consensus_pct}%")

# Batch execution
from ghostchimera.chimera_pilot.batch_runner import BatchRunner, BatchJob
jobs = [BatchJob(objective=obj) for obj in objectives]
runner = BatchRunner(jobs, workers=4, output_dir="batch_output")
summary = runner.run()
print(summary.to_dict())

# Cron scheduler
from ghostchimera.chimera_pilot.cron_scheduler import get_scheduler
sched = get_scheduler()
sched.add_job("daily-review", "0 9 * * 1-5", "Review pending PRs")
sched.start()

# Gateway server
from ghostchimera.chimera_pilot.gateway_server import get_server
server = get_server()
server.start()  # listens on ws://127.0.0.1:8765 by default
```

### New dependencies

```bash
pip install -e '.[mcp]'     # MCP client/server support
pip install -e '.[gateway]' # WebSocket gateway + cron scheduler
pip install -e '.[all]'     # all optional features
```
