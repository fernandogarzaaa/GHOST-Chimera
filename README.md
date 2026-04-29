# Ghost Chimera

Ghost Chimera is a local-first agent orchestration project. It provides a small modular agent stack plus **Chimera Pilot**, a control-plane layer for compiling objectives into task IR, scheduling backends, calibrating backend health, executing with fallback, validating results, and recording telemetry.

This repository is release-ready as an **alpha developer release**. It is not marketed as AGI, an autonomous production agent, or a replacement for licensed quantum operating systems.

## What is included

- `agent_core` - planning, execution, memory, and skill dispatch.
- `model_layer` - provider abstraction for model calls.
- `tool_layer` - filesystem, browser, and shell wrappers.
- `skill_layer` - domain skills built on tools and models.
- `safety_layer` - approval gating and audit helpers.
- `chimera_pilot` - task IR, resource registry, scheduler, calibration, executor, verifier, telemetry, and optional quantum-simulator bridge.

## Install from source

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Optional quantum simulator support:

```bash
python -m pip install -e '.[quantum]'
```

## Validate the release

```bash
python scripts/validate_release.py
```

The validator checks required release files, imports, compileability, package metadata, policy defaults, and the unittest suite.

## CLI quickstart

Show Chimera Pilot status:

```bash
chimera-pilot status --include-deterministic-backend
```

Compile an objective without executing it:

```bash
chimera-pilot compile "retrieve memory about project"
```

Run a safe deterministic fallback task:

```bash
chimera-pilot run "retrieve memory about project" --include-deterministic-backend
```

Add and retrieve local CWR memory:

```bash
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source project-goals --content "Ghost Chimera should use real local memory retrieval."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "local memory retrieval"
chimera-pilot run "retrieve local memory retrieval" --memory-db .ghostchimera-memory.sqlite3 --include-deterministic-backend
```

Local Python execution is disabled by default. Enable it only for trusted code:

```bash
chimera-pilot run "python: print(2 + 3)" --allow-python
```

The main control-plane CLI exposes Chimera Pilot as well:

```bash
ghostchimera --config-show
ghostchimera --pilot-status
ghostchimera --pilot-run "python: print(2 + 3)" --allow-python
```

## Security posture

Ghost Chimera defaults to conservative execution:

- network-requiring tasks are blocked unless explicitly allowed;
- local Python and test execution are blocked unless explicitly allowed;
- Python execution uses a restricted environment, temporary cwd by default, bytecode disabled, isolated interpreter mode, bounded timeout, and AST-level rejection of high-risk calls;
- dangerous execution surfaces are documented in `SECURITY.md`.

These protections reduce accidental risk, but they are not a substitute for container or VM isolation when running untrusted code.

## Local model profiles

The local model layer exposes explicit small-model profiles for constrained hardware:

- `tiny` - Qwen2.5 0.5B instruct GGUF, q4, designed for the 4 GB RAM target.
- `balanced` - SmolLM2 1.7B instruct GGUF, q4, still lightweight.
- `stronger` - Phi-3.5 mini instruct, q4, for machines with more available memory.

Set `GHOSTCHIMERA_MODEL_PROVIDER=minimind` and `MINIMIND_MODEL_PROFILE=tiny` to use the minimind-compatible provider once a matching runtime is installed.

For GGUF models, use the optional llama.cpp-compatible runtime:

```bash
chimera-pilot model-profiles
chimera-pilot status --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
chimera-pilot run "explain the current project" --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
```

The base package does not install heavy local inference dependencies. Install a compatible `llama_cpp` runtime separately before using `--local-model-path`.

## Conscious workspace

Ghost Chimera includes inspectable consciousness-inspired state primitives:

- `SelfModel` for identity, capabilities, limits, and active goals.
- `WorkingMemory` for task evidence and reflections.
- `AttentionController` for relevance/trust/recency ranking.
- `ReflectionEngine` for post-action learning records.

These are engineering surfaces for agent state and evaluation. They are not claims of subjective experience.

## Clean-room boundary

Chimera Pilot is inspired by public systems architecture patterns from resource orchestration and quantum/classical scheduling. It does not copy proprietary Origin Pilot code, binaries, private APIs, private endpoints, UI assets, or licensed files. See `docs/CLEAN_ROOM.md`.

## Project status

Current release status: **alpha**.

Appropriate uses:

- local experimentation;
- backend scheduling research;
- agent runtime prototyping;
- testable extension work;
- optional quantum simulator integration.

Not appropriate yet:

- unattended production automation;
- executing untrusted code without external sandboxing;
- claims of AGI or fully autonomous operation;
- commercial/enterprise deployment without additional security review.

## Development

Run the built-in suite:

```bash
python -m unittest tests.test_chimera_pilot tests.test_release_package -v
```

Run compile checks:

```bash
python -m compileall ghostchimera tests
```

Run the release gate:

```bash
python scripts/validate_release.py
```

Run built-in eval suites:

```bash
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
```
