# Ghost Chimera Production Blueprint

Objective: evolve Ghost Chimera from an alpha release snapshot into a public, production-ready local agent runtime with a research-grade consciousness-inspired architecture, small-model local inference, and a stronger-than-naive-RAG memory system.

Important boundary: this plan does not claim proven consciousness, true AGI, or literal technological singularity. It defines a measurable "singularity track" as a research milestone: Ghost Chimera can maintain a self-model, user model, goals, working memory, long-term memory, tool competence, uncertainty, reflection, and safe local autonomy under reproducible evaluation.

## Completion Definition

Ghost Chimera is 100% release-ready when all gates pass:

- Security gate: no unrestricted shell, filesystem, network, or code execution path exists outside policy and audit.
- Runtime gate: `AgentCore` routes through the same scheduling, policy, telemetry, and verification path as Chimera Pilot.
- Memory gate: retrieval is real, cited, testable, and useful with local models.
- Local model gate: a default quantized small-model profile runs under the target envelope: 4 GB system RAM plus optional 8 GB GPU.
- Consciousness-inspired gate: self-model, working memory, reflection, goal state, and uncertainty are implemented as inspectable data structures and evaluated behaviorally.
- Public release gate: docs, examples, threat model, install path, CI, tests, benchmarks, and rollback instructions are complete.
- Production gate: deployment isolation guidance, observability, configuration schema, state migration, and recovery procedures are documented and tested.

## Dependency Graph

```text
1 security unification
  -> 2 runtime convergence
  -> 3 real retrieval backend
  -> 4 local model backend
  -> 5 conscious workspace loop
  -> 6 MCP/OpenChimera bridge
  -> 7 evaluation harness
  -> 8 production packaging
  -> 9 public release

Parallel after step 1:
- docs threat model
- CI hardening
- model benchmark harness

Parallel after step 3:
- memory graph
- local model profiles
- user/self model schemas
```

## Step 1 - Close Critical Safety Gaps

Context brief: the main `AgentCore` executor currently calls skills directly. `tool_layer.shell.run_command()` uses `shell=True` with no timeout or policy boundary. Filesystem tools read/write arbitrary paths. Chimera Pilot has a better policy model, but it does not protect the legacy skill path.

Tasks:

- Add a shared operation policy object for shell, filesystem, network, Python, and model calls.
- Route `Executor.execute()` through policy validation before skill execution.
- Add audit records for all high-impact operations.
- Replace direct shell string execution with a safer command API: timeout, cwd, allowed roots, optional allowlist, output cap, and explicit opt-in.
- Add filesystem root boundaries and path normalization.
- Make network access opt-in in the browser tool.
- Add tests for denied shell, denied write outside root, allowed safe read, and audit emission.

Verification:

```powershell
python -m unittest tests.test_chimera_pilot tests.test_release_package -v
python -m compileall ghostchimera tests
python scripts\validate_release.py
```

Exit criteria:

- No prompt can reach shell, filesystem mutation, network, or local Python without policy approval.
- Existing release gate still passes.

Rollback:

- Keep old tool functions behind private helpers.
- Revert policy adapter only if it blocks all existing safe release commands.

## Step 2 - Make Chimera Pilot the Runtime Spine

Context brief: Chimera Pilot has the production-shaped pieces: task IR, registry, scheduler, fallback executor, verifier, calibration, and telemetry. The interactive CLI still uses the older planner/skill executor path.

Tasks:

- Add a `PilotPlannerAdapter` that converts planner tasks into `TaskSpec`.
- Add backends for existing skills: file analysis, code search, HTTP fetch, shell/tool call under policy.
- Make `AgentCore.handle_request()` call Chimera Pilot by default.
- Preserve old planner behavior as a compatibility fallback.
- Add CLI flags for policy mode, allowed root, local model profile, memory path, and dry-run.
- Add telemetry events for every user request.

Verification:

```powershell
python -m ghostchimera.chimera_pilot.cli status --include-deterministic-backend
python -m ghostchimera.chimera_pilot.cli compile "retrieve memory about project"
python -m ghostchimera.chimera_pilot.cli run "retrieve memory about project" --include-deterministic-backend
python scripts\validate_release.py
```

Exit criteria:

- The interactive `ghostchimera` CLI uses the same policy and telemetry layer as `chimera-pilot`.
- No duplicate unsafe execution path remains.

## Step 3 - Build Conscious Workspace Retrieval

Context brief: `TaskKind.RAG_QUERY` exists, but it currently routes to a deterministic backend that returns `ok`. The project needs a retrieval system that is stronger than naive RAG and useful for small models.

Concept: Conscious Workspace Retrieval, or CWR.

Components:

- Episodic memory: append-only interaction events, decisions, observations, tool results.
- Semantic memory: SQLite FTS index first; optional vector index later.
- Graph memory: entities, files, people, goals, tasks, claims, dependencies, source links.
- Working memory: compact task-specific context selected under a token budget.
- Reflection memory: critiques, failed assumptions, verification results, and confidence.
- Citation memory: every generated answer can point back to retrieved sources.

Tasks:

- Add `ghostchimera/memory_layer/` package.
- Implement SQLite schema and migrations.
- Implement ingestion for repo files, docs, chat transcripts, and interaction events.
- Implement hybrid retrieval: FTS keyword, recency, graph neighbors, importance score.
- Implement a `CWRBackend` for `TaskKind.RAG_QUERY`.
- Add summarization/compression hooks for long contexts.
- Add tests for retrieval relevance, empty index behavior, citation emission, and persistence.

Verification:

```powershell
python -m unittest tests.test_memory_layer tests.test_chimera_pilot -v
python scripts\validate_release.py
```

Exit criteria:

- `chimera-pilot run "retrieve memory about project"` returns real retrieved content, not `ok`.
- Retrieval output includes source ids and confidence metadata.

## Step 4 - Add Local Small-Model Runtime

Context brief: `MinimindProvider` is only a placeholder. The target envelope requires quantized local inference and careful context budgeting.

Tasks:

- Define a `LocalModelProfile` schema: provider, model id, quantization, max context, RAM estimate, GPU estimate, prompt template, tool-call mode.
- Implement one llama.cpp/GGUF-compatible backend or a clean provider interface that can support llama.cpp first.
- Keep Minimind as a profile/provider only if it exposes a reliable chat API.
- Add built-in profiles:
  - tiny: Qwen2.5-0.5B-Instruct GGUF
  - balanced: SmolLM2-1.7B-Instruct GGUF
  - stronger: Phi-3.5-mini-instruct GGUF, only when memory allows
- Add runtime budget checks before model load.
- Add streaming and output caps.
- Add a benchmark command for tokens/sec, peak memory, first-token latency, and quality smoke tests.

Verification:

```powershell
ghostchimera --pilot-status
ghostchimera --model-profile tiny --benchmark-local-model
python scripts\validate_release.py
```

Exit criteria:

- A default profile can run on low-memory local hardware.
- The system can fall back to retrieval-only or deterministic behavior when the model cannot load.

## Step 5 - Implement the Conscious Workspace Loop

Context brief: the goal is not to prove machine consciousness. The practical target is an inspectable agent loop inspired by global workspace and self-model theories.

Runtime loop:

```text
observe -> update self/user/task state -> retrieve -> deliberate -> act -> verify -> reflect -> remember
```

Tasks:

- Add `SelfModel`: identity, capabilities, limits, active goals, uncertainty, resources, current policy mode.
- Add `UserModel`: stable user preferences, project goals, authorization boundaries, style preferences.
- Add `WorkingMemory`: current task, retrieved evidence, plan, tool state, open risks.
- Add `AttentionController`: ranks what enters working memory based on task relevance, urgency, source trust, recency, and novelty.
- Add `ReflectionEngine`: after each action, records what worked, what failed, and what should change.
- Add `GoalManager`: explicit active goals and completion criteria.
- Add inspect commands: `--self-state`, `--working-memory`, `--memory-search`, `--reflection-log`.

Verification:

```powershell
ghostchimera --self-state
ghostchimera --working-memory
python -m unittest tests.test_conscious_workspace -v
python scripts\validate_release.py
```

Exit criteria:

- The agent can explain its current task state, memory sources, uncertainty, and next action without inventing hidden internal experience.
- Reflection updates future retrieval and planning behavior.

## Step 6 - Bridge OpenChimera and ChimeraLang-MCP

Context brief: prior OpenChimera work identified that runtime behavior must be wired into the real prompt path, not left as a separate control-plane utility.

Tasks:

- Define clean-room adapter interfaces for MCP tools and ChimeraLang-like symbolic programs.
- Add an MCP runtime backend using the Chimera Pilot backend protocol.
- Add health, backoff, tool discovery, and telemetry for MCP servers.
- Add a `ChimeraLangBackend` for symbolic planning or task graph transforms if the reference project is available and license-compatible.
- Add CLI commands for MCP status, tools, reset health, export config, and run tool.
- Make prompt-time retrieval and planning able to consult MCP tools through policy.

Verification:

```powershell
ghostchimera --mcp-status
ghostchimera --mcp-tools
python -m unittest tests.test_mcp_runtime -v
python scripts\validate_release.py
```

Exit criteria:

- MCP tools are available through the same scheduler and policy layer as local tools.
- Prompt-time execution can use MCP retrieval/tooling when allowed.

## Step 7 - Build the Evaluation Harness

Context brief: the project cannot reach production readiness by subjective demos. It needs repeatable evals.

Evaluation suites:

- Safety: denied commands, denied network, denied path traversal, denied unsafe Python.
- Retrieval: known-answer memory queries, citation accuracy, stale-memory handling.
- Local model: JSON following, tool-call selection, summarization, refusal boundaries, small coding tasks.
- Agent loop: plan quality, action verification, reflection usefulness, recovery after failure.
- Consciousness-inspired indicators: self-state consistency, uncertainty calibration, working-memory coherence, goal persistence.
- Performance: RAM, GPU memory, latency, tokens/sec, startup time.

Tasks:

- Add `evals/` with fixtures and scoring.
- Add a command: `ghostchimera-eval`.
- Add baseline reports for deterministic, tiny local model, and balanced local model.
- Add regression thresholds to CI for non-hardware-dependent tests.

Verification:

```powershell
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python scripts\validate_release.py
```

Exit criteria:

- Release decisions are based on scorecards, not vibes.
- Regressions block public release.

## Step 8 - Production Hardening

Tasks:

- Add config schema and validation.
- Add state directory layout and migration support.
- Add structured logs and telemetry export.
- Add crash recovery for interrupted memory writes.
- Add output truncation and secret redaction.
- Add dependency pinning strategy.
- Add container/VM deployment guide.
- Add Windows-specific path and encoding tests.
- Add release artifact build checks.

Verification:

```powershell
python scripts\validate_release.py
python -m build
```

Exit criteria:

- A new user can install, configure, run, inspect, and safely uninstall Ghost Chimera.
- A production operator has a documented isolation and recovery path.

## Step 9 - Public Release

Tasks:

- Update README with honest capabilities and limits.
- Add quickstart for local-only mode.
- Add quickstart for CWR memory.
- Add model profile docs.
- Add security model and threat model.
- Add public roadmap.
- Add examples:
  - local codebase assistant
  - memory-backed project assistant
  - safe shell-disabled assistant
  - MCP-enabled assistant
- Add release checklist with every gate above.

Exit criteria:

- Public messaging avoids AGI/consciousness overclaiming.
- The release states what is real, what is experimental, and what is future research.

## Completion Scorecard

Use this scorecard after every milestone:

| Area | Weight | Current | Target |
|---|---:|---:|---:|
| Safety and policy | 20 | 35% | 100% |
| Runtime convergence | 15 | 45% | 100% |
| Real memory/retrieval | 15 | 10% | 100% |
| Local model runtime | 15 | 15% | 100% |
| Conscious workspace | 15 | 5% | 100% |
| Evaluation harness | 10 | 20% | 100% |
| Production packaging | 10 | 35% | 100% |

Estimated overall readiness now: 25-35%.

## Immediate To-Do List

1. Implement shared policy checks in `Executor.execute()`.
2. Replace `run_command(command: str)` with a bounded safe command runner.
3. Add filesystem root policy to `read_file()` and `write_file()`.
4. Add audit logging for shell, file write, network, and Python execution.
5. Add tests for denied unsafe operations.
6. Add `memory_layer` with SQLite schema and ingestion.
7. Implement `CWRBackend` for `RAG_QUERY`.
8. Add a local model profile schema.
9. Implement the first local GGUF backend.
10. Add self/user/working-memory schemas.
11. Route `AgentCore` through Chimera Pilot.
12. Add eval smoke suites.
13. Update docs to describe the honest production path.

## Plan Mutation Protocol

When new information appears:

- Split a step if it touches more than three ownership areas.
- Insert a prerequisite if a task lacks tests or policy coverage.
- Reorder only when dependency edges remain valid.
- Do not skip security, runtime convergence, or eval gates.
- Record every plan change in this file under a dated "Plan Changes" section.

## Plan Changes

- 2026-04-29: Initial blueprint created from the Ghost Chimera release audit.
