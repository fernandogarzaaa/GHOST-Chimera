# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ghost Chimera is a local-first agent orchestration project (alpha, v0.1.0). It provides a layered agent runtime with **Chimera Pilot** as the control-plane: a resource orchestrator that compiles natural-language objectives into a task IR, schedules them across registered backends using weighted scoring, enforces safety policy, executes with fallback, and records telemetry.

## Quick Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
python -m pip install -e '.[dev]'

# Lint (ruff)
ruff check ghostchimera tests

# Compile check
python -m compileall ghostchimera tests

# Tests (stdlib unittest)
python -m unittest tests.test_chimera_pilot tests.test_release_package -v

# Release validation (checks imports, metadata, policy defaults, test suite)
python scripts/validate_release.py

# Eval suites
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety

# CLI
chimera-pilot status --include-deterministic-backend
chimera-pilot compile "objective"
chimera-pilot run "objective" --include-deterministic-backend
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
  model_layer/      LLM provider abstraction (OpenAI, minimind, llama.cpp)
  safety_layer/     ExecutionPolicy gating and audit records
  skill_layer/      Domain skills (code_search, tech_support, to_issues, software_engineer, browser_operator)
  tool_layer/       Policy-gated filesystem, shell, and browser wrappers
```

### Key design patterns

**Two execution paths:** `AgentCore.handle_request()` tries Chimera Pilot first (structured task IR + backend scheduling). If no registered backend can handle the task, it falls back to the legacy planner/skill executor with the same `ExecutionPolicy`.

**Chimera Pilot pipeline:** Objective → `RuleBasedTaskCompiler` → `TaskSpec` list → `ChimeraScheduler` (weighted scoring) → best backend → `ChimeraPilotExecutor` (with fallback) → `Verifier` → telemetry.

**Backend contract:** Every backend exposes `id`, `name`, `capabilities`, `probe()`, `can_run(task)`, `estimate(task)`, `execute(task)`. This unifies local runtimes, cloud models, MCP connectors, and quantum simulators behind one scheduling interface.

**Safety boundary:** Scheduler decides *where* to run; policy decides *whether* it's allowed. Two separate layers (`PilotPolicy` for Chimera Pilot tasks, `ExecutionPolicy` for tool-layer operations).

**Conservative defaults:** Network access denied, Python/test execution denied, Python runs with bounded timeout, minimal env, isolated interpreter, temporary cwd, AST-level rejection of high-risk calls (`os.system`, `subprocess`, `eval`, `exec`, etc.). Denied fragments hardcoded in `chimera_pilot/policy.py`.

### Core files

| Area | Key file(s) |
|------|-------------|
| Entry point | `ghostchimera/control_plane/cli.py` |
| Agent facade | `ghostchimera/agent_core/core.py` (AgentCore) |
| Pilot kernel | `ghostchimera/chimera_pilot/kernel.py` (ChimeraPilotKernel) |
| Task IR | `ghostchimera/chimera_pilot/task_ir.py` (TaskSpec, TaskKind) |
| Compiler | `ghostchimera/chimera_pilot/compiler.py` (RuleBasedTaskCompiler) |
| Scheduler | `ghostchimera/chimera_pilot/scheduler.py` (weighted scoring) |
| Pilot policy | `ghostchimera/chimera_pilot/policy.py` (PilotPolicy) |
| Tool policy | `ghostchimera/safety_layer/gating.py` (ExecutionPolicy) |
| Config | `ghostchimera/config.py` (GhostChimeraConfig) |
| LLM layer | `ghostchimera/model_layer/llm.py` + `providers.py` |
| Memory store | `ghostchimera/memory_layer/store.py` |
| CWR primitives | `ghostchimera/cognition_layer/workspace.py` |
| Evals | `ghostchimera/evals/runner.py` |
| Release validator | `scripts/validate_release.py` |
| CI | `.github/workflows/ci.yml` |

## Contributing

Follow rules in `CONTRIBUTING.md`: small PRs, no unrelated refactors, add tests, keep local execution opt-in, maintain clean-room boundaries. Run the full test gate before PRs.
