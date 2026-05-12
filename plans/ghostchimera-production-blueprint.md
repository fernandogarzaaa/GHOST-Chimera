# Ghost Chimera Production Blueprint

Objective: evolve Ghost Chimera from a beta local-first agent orchestration
runtime into a release-grade local operator system with measurable safety,
retrieval, local-model, and autonomy behavior.

Important boundary: this blueprint does not claim proven consciousness, AGI,
SGI, or fully autonomous production operation. The "singularity track" is an
internal research/evaluation theme for self-model, working-memory, reflection,
goal-state, uncertainty, and safe local autonomy behavior under reproducible
tests.

## Current Beta Baseline

- Safety and policy are wired through Chimera Pilot, AgentCore fallback
  execution, shell/filesystem/browser tool wrappers, production guardrails, and
  audit records.
- Runtime convergence is live: AgentCore tries Chimera Pilot first and falls
  back to the legacy planner only when Pilot has no route for the request.
- CWR memory is backed by local SQLite FTS retrieval with cited results.
- Local model support is profile-driven with optional llama.cpp/GGUF execution,
  runtime specialization warmup manifests, and deterministic fallback behavior.
- Conscious workspace primitives now have an operator-facing state store:
  `ghostchimera workspace show` and `/api/console/workspace` expose self model,
  working memory, attention ranking, reflection, goal state, and uncertainty.
- High-confidence workspace evidence and reflections can now sync into the CWR
  memory store through CLI and console routes with explicit provenance and
  duplicate-safe persistence.
- Workspace sync now emits quality metadata for low-confidence, stale, and
  conflicting records before workspace-derived context enters retrieval.
- The local operator console exposes status, autonomy profiles, safe objective
  runs, durable autonomy jobs, recurring schedules, degraded-friendly optional
  browser workspace status, and release-readiness runbook output.
- Release validation now includes source tests, release validator, package
  build, smoke/safety/autonomy/user-journey eval suites, production doctor, and
  clean installed-wheel smokes with and without gateway extras.

## Release Gates

Ghost Chimera is release-ready for a beta tag only when these gates pass:

```powershell
python -m ruff check .
python -m pytest -q
python scripts\validate_release.py
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python scripts\smoke_installed_wheel.py
python scripts\smoke_installed_wheel.py --extras gateway
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
$env:GHOSTCHIMERA_DEPLOYMENT_MODE="production"
$env:GHOSTCHIMERA_EXTERNAL_ISOLATION="container"
$env:GHOSTCHIMERA_SECURITY_REVIEWED="1"
$env:GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED="1"
ghostchimera doctor --production
```

The installed-wheel smoke without extras must prove the base package imports and
top-level CLI dispatch work without optional gateway, browser, quantum, MCP, or
local inference dependencies. The gateway smoke must prove console scheduling
and the user-journey eval work in a clean environment with gateway extras.

## Remaining Milestones

All five blueprint milestones are now wired and gated. The remaining work before
a v1.0 stable release is:

1. **External security audit** — the production guardrails and DPI layer need
   review by an external security practitioner before any high-stakes deployment.
2. **CI coverage on Windows and macOS** — path-safety and desktop-control tests
   should be confirmed on all three OS targets in CI.
3. **User documentation** — operator guide, API reference, and quickstart for
   non-developer operators.
4. **Long-form retrieval benchmarks** — real-world recall@k and citation-quality
   benchmarks against public corpora to validate the FTS + freshness stack.

## Completion Scorecard

| Area | Weight | Current | Target |
|---|---:|---:|---:|
| Safety and policy | 20 | 95% | 100% |
| Runtime convergence | 15 | 90% | 100% |
| Real memory/retrieval | 15 | 95% | 100% |
| Local model runtime | 15 | 90% | 100% |
| Conscious workspace | 15 | 95% | 100% |
| Evaluation harness | 10 | 100% | 100% |
| Production packaging | 10 | 95% | 100% |

Estimated beta readiness: **93–96%**. All release gates pass. Remaining gap is
external security audit (Safety/policy → 100%), Windows/macOS CI path verification
(Runtime convergence → 100%), and user documentation (Production packaging → 100%).

**What was completed in this session (v0.3.0-beta final):**

- All five production blueprint milestones confirmed wired and passing.
- CHANGELOG expanded to cover v0.1.0, v0.2.0, v0.2.1, and v0.3.0-beta.
- `docs/MISSING_IMPLEMENTATIONS.md` updated with all newly wired surfaces.
- `docs/RELEASE_CHECKLIST.md` updated with workspace eval suite and local-model
  CLI gates.
- `SECURITY.md` updated to mention desktop control backend, SSRF policy, and DPI
  engine.
- All release gates confirmed green in this session:
  - `ruff check .` — clean
  - `pytest` — 933 passed
  - `validate_release.py` — ok
  - `python -m build` — wheel and sdist produced
  - eval suites: smoke ✓, safety ✓, autonomy ✓, user-journey ✓, workspace ✓
  - `smoke_installed_wheel.py` — ok
  - `smoke_installed_wheel.py --extras gateway` — ok

## Plan Mutation Protocol

- Update this file whenever a milestone moves from planned to wired.
- Do not reintroduce AGI, SGI, consciousness, quantum OS, or unattended
  production claims as public release criteria.
- Any new execution surface must land behind policy, audit, tests, docs, and a
  user-facing operator path.
- Any new optional dependency must have a degraded base-install behavior and a
  clean installed-wheel smoke path.
