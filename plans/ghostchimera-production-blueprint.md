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

1. **Release hardening**
   - Keep CI aligned with the release gates above on Windows, Linux, and macOS.
   - Add regression fixtures when a direct-to-main fix reveals a missed
     operator path.
   - Keep `docs/RELEASE_CHECKLIST.md`, `docs/MISSING_IMPLEMENTATIONS.md`, and
     `/api/console/readiness` synchronized with the real gate.

2. **Conscious workspace feedback loop**
   - Feed persisted reflection records and high-confidence workspace evidence
     into future retrieval and planning paths with explicit provenance.
   - Add eval cases for stale, conflicting, and low-confidence workspace
     evidence without inventing hidden subjective experience.

3. **Local model bootstrap**
   - Add operator-friendly model profile checks, install guidance, benchmark
     output, and fallback explanations for the low-resource target envelope.
   - Keep optional local inference dependencies out of the base install.

4. **Memory and retrieval depth**
   - Extend CWR beyond FTS with ingestion workflows, source freshness signals,
     reflection memory, and citation-quality evals.
   - Add failure cases for empty indexes, stale context, and conflicting
     evidence.

5. **Production isolation guidance**
   - Document container/VM isolation, state backup/restore, audit retention,
     secret handling, and rollback procedures.
   - Keep unattended production automation explicitly out of scope until
     external isolation and review are proven.

## Completion Scorecard

| Area | Weight | Current | Target |
|---|---:|---:|---:|
| Safety and policy | 20 | 80% | 100% |
| Runtime convergence | 15 | 75% | 100% |
| Real memory/retrieval | 15 | 55% | 100% |
| Local model runtime | 15 | 50% | 100% |
| Conscious workspace | 15 | 60% | 100% |
| Evaluation harness | 10 | 70% | 100% |
| Production packaging | 10 | 70% | 100% |

Estimated beta readiness now: 70-80%, assuming the current release gate passes
in a clean local environment and CI.

## Plan Mutation Protocol

- Update this file whenever a milestone moves from planned to wired.
- Do not reintroduce AGI, SGI, consciousness, quantum OS, or unattended
  production claims as public release criteria.
- Any new execution surface must land behind policy, audit, tests, docs, and a
  user-facing operator path.
- Any new optional dependency must have a degraded base-install behavior and a
  clean installed-wheel smoke path.
