# Chimera Pilot

Chimera Pilot is Ghost Chimera's resource orchestration layer. It turns high-level objectives into neutral `TaskSpec` objects, chooses a backend, enforces policy, executes with fallback, verifies output, and records telemetry.

## Why it exists

The subsystem re-iterates quantum/classical resource-orchestration ideas for practical everyday agent infrastructure:

- local Python runtimes;
- model providers;
- retrieval systems;
- browser/search tools;
- MCP-style tool servers;
- optional quantum simulators.

It does not require a quantum computer.

## Governed Enterprise Change Agent Workflow

When used as the product control plane, Chimera Pilot drives one enterprise change loop:

1. Ingest repo/document objective context.
2. Compile objective to normalized `TaskSpec` units.
3. Schedule and execute with fallback/parallel strategy ceilings based on autonomy profile.
4. Enforce policy and production guardrails.
5. Verify and emit confidence-bearing, audit-ready outputs for change review.

This shared flow is reused across Agentic Olympics, enterprise/security, IBM Bob, and AI GENESIS hackathon demos with track-specific framing.

## Commands

```bash
chimera-pilot status --include-deterministic-backend
chimera-pilot compile "retrieve memory about project"
chimera-pilot calibrate --include-deterministic-backend
chimera-pilot run "retrieve memory about project" --include-deterministic-backend
chimera-pilot model-profiles
```

Use the local Conscious Workspace Retrieval store:

```bash
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source project-note --content "Ghost Chimera stores local project memory."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "project memory"
chimera-pilot run "retrieve project memory" --memory-db .ghostchimera-memory.sqlite3 --include-deterministic-backend
```

Python execution is denied by default:

```bash
chimera-pilot run "python: print(2 + 3)"
```

For trusted local code only:

```bash
chimera-pilot run "python: print(2 + 3)" --allow-python
```

Desktop control is denied by default:

```bash
chimera-pilot run "click submit button" --enable-desktop-backend
```

For explicit desktop-control opt-in and possess mode:

```bash
chimera-pilot run "click submit button" --enable-desktop-backend --allow-desktop-control --ghost-mode possess
```

Compiler shorthand prefixes are supported for desktop intent strength:

```bash
chimera-pilot run "dryrun desktop: click submit button" --enable-desktop-backend --allow-desktop-control --ghost-mode possess
chimera-pilot run "live desktop: click submit button" --enable-desktop-backend --enable-live-desktop --allow-desktop-control --ghost-mode possess
```

## Built-in task kinds

- `reasoning`
- `code_edit`
- `test_run`
- `web_research`
- `file_analysis`
- `rag_query`
- `tool_call`
- `python`
- `quantum_sim`
- `desktop_control`

## Built-in backends

- `DeterministicBackend` for CI, smoke checks, and fallback tests.
- `PythonRuntimeBackend` for trusted local Python/test execution.
- `PyQPanda3Backend` for optional pyqpanda3 quantum simulation when installed.
- `CWRBackend` for SQLite-backed local memory retrieval.
- `LlamaCppBackend` for optional GGUF reasoning when a local model path is provided.
- `DesktopRuntimeBackend` for dry-run desktop control (with explicit live constraints for real UI mutation).

## Security

Local execution is policy-gated. See `SECURITY.md` before enabling Python, shell, filesystem mutation, or network tasks.
