# Architecture

Ghost Chimera is organized as a layered local-first agent runtime.

```text
ghostchimera/
  agent_core/       planning, Chimera Pilot handoff, execution, skill dispatch
  chimera_pilot/    task IR, policy, scheduling, execution, verification
  cognition_layer/  self-model, working memory, attention, reflection primitives
  control_plane/    user-facing CLI entry points
  evals/            smoke and safety evaluation suites
  memory_layer/     SQLite FTS local retrieval store
  model_layer/      OpenAI, minimind-compatible, llama.cpp, and runtime specialization adapters
  safety_layer/     execution policy and audit records
  skill_layer/      higher-level skills
  tool_layer/       policy-gated filesystem, shell, and browser wrappers
```

## Chimera Pilot

Chimera Pilot is the most production-shaped subsystem in this beta release.
It provides:

1. **Task IR** - `TaskSpec` and `TaskKind` normalize objectives.
2. **Compiler** - a deterministic rule-based compiler maps common objectives into task specs.
3. **Resource registry** - runtime backends register capabilities.
4. **Scheduler** - deterministic scoring chooses backends by reliability, latency, cost, privacy, context fit, GPU, and network fit.
5. **Policy** - blocks network and local code execution unless explicitly allowed.
6. **Executor** - executes the best backend and falls back to lower-ranked candidates.
7. **Verifier** - validates JSON, output keys, command success, and expected files.
8. **Calibration** - probes backend health and stores reliability history.
9. **Telemetry** - records execution attempts and summary metrics.

## Backend contract

Every Chimera Pilot backend exposes:

```text
id
name
capabilities
probe()
can_run(task)
estimate(task)
execute(task)
```

This keeps local runtimes, cloud models, MCP connectors, vector stores, browser tools, and quantum simulators behind the same scheduling interface.

## Runtime convergence

`AgentCore` tries Chimera Pilot first for task kinds that have registered backends. Unsupported requests fall back to the legacy planner/skill executor, but that path now carries the same `ExecutionPolicy` into shell, filesystem, and browser tools. This keeps public CLI behavior, pilot scheduling, and direct agent execution behind one safety boundary.

## Local memory and models

The CWR backend uses `memory_layer.MemoryStore`, a local SQLite FTS5 index, for retrieval-augmented task execution without external services. The local model path is explicit: minimind-compatible runtimes consume named profiles, while optional GGUF execution goes through the llama.cpp backend when `--local-model-path` is provided.

Local model execution also has a runtime-specialization planner inspired by CuTeDSL-style serving systems. It does three concrete things in the current beta:

1. Classifies a local reasoning request as `prefill`, `decode`, or `hybrid` from prompt/output shape.
2. Derives accelerator-aware hints such as vector width, load width, recommended warps, grid-barrier eligibility, and a `llama_cpp` `n_batch` value.
3. Emits a stable cache key, JSON plan manifests, and a warmup index so deployment/replay tooling can see which specialization was selected.

The planner is wired into `LlamaCppRuntime`, `LlamaCppBackend`, Chimera Pilot status, `chimera-pilot runtime-specialization`, `chimera-pilot runtime-warmup`, and `ghostchimera runtime-warmup`. It detects the optional `nvidia-cutlass-dsl` package when installed, but the default beta path remains llama.cpp execution with specialization metadata rather than unverified custom GPU kernel compilation.

## Safety boundary

The scheduler decides where a task should run. The policy decides whether it is allowed to run. These are intentionally separate so future deployments can plug in stricter enterprise, local-only, or supervised policies without rewriting the scheduler.
