# Release Checklist

Use this before publishing a public release.

## Required checks

```bash
python -m ruff check .
python -m pytest -q
python scripts/validate_release.py
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
python -m ghostchimera.evals run --suite autonomy
python -m ghostchimera.evals run --suite user-journey
python -m ghostchimera.evals run --suite workspace
python -m ghostchimera.evals run --suite competitive
python -m ghostchimera.evals run --suite github-connected
python -m ghostchimera.evals run --suite path-synthesis
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
ghostchimera capabilities --format json
ghostchimera local-model inventory
ghostchimera local-model resolve --source Qwen/Qwen2.5-7B-Instruct
ghostchimera cognition guard --confidence 0.9 --variance 0.01
ghostchimera context compress --text "latency latency matters" --focus latency
ghostchimera capability-pack list
ghostchimera sandbox journey
ghostchimera remote status
ghostchimera trust status
ghostchimera trust eval baseline
ghostchimera trust eval-cases list
ghostchimera trust trace export latest
ghostchimera mcp trust list
ghostchimera capability-admission list
ghostchimera capability-admission inspect --kind model --name release-review-demo --source local --risk low
ghostchimera github status
ghostchimera path list
ghostchimera path set --profile ai-engineer-proxy --training-mode rag-first --approval-level supervised
ghostchimera path show
ghostchimera review-pr --base HEAD --head HEAD
ghostchimera workspace show
ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30
ghostchimera minimind personal-status
ghostchimera minimind personal-consent --admin-controls --allow-system-specs --allow-files --allow-training --file-path README.md
ghostchimera minimind personal-consent --admin-controls --allow-machine-crawl --allow-email-crawl --allow-training --crawl-root . --exclude-path .git
ghostchimera minimind personal-bootstrap --include-system-specs
ghostchimera minimind personal-handoff --objective "Summarize pending beta release work"
GHOSTCHIMERA_DEPLOYMENT_MODE=production GHOSTCHIMERA_EXTERNAL_ISOLATION=container GHOSTCHIMERA_SECURITY_REVIEWED=1 GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 ghostchimera doctor --production
```

The release gate, package build, built-in eval suites, and installed-wheel
smokes must pass before tagging or pushing a beta release branch to `main`.

The browser console also exposes `/api/console/readiness` as a local runbook view
of these commands. It is intentionally a checklist surface, not an unattended
production deployment workflow.

## Optional Bob developer tooling checks

These checks validate the optional IBM Bob developer-tooling layer. They are not
required to run Ghost Chimera, but they must keep passing when release notes or
developer-tooling claims mention the Bob roadmap.

```bash
python scripts/bob_accelerator.py
python scripts/audit_dependencies.py --format markdown
python scripts/bob_delivery_package.py --output docs/bob_delivery_package.md
python scripts/generate_api_reference.py
python scripts/generate_sbom.py
python scripts/dependency_graph.py
python scripts/analyze_logs.py --demo
python scripts/dev_env.py
python -m pytest tests/integration/test_bob_toolchain.py -q
python -m pytest tests/performance/test_bob_tool_performance.py -q
```

Run the installed-wheel smoke once without extras to verify the base package
does not require optional dependencies. Run it again with gateway extras to
verify console scheduling and the local operator user journey in a clean virtual
environment.

## Manual checks

- [ ] `python -m ghostchimera.evals run --suite workspace` passes.
- [ ] `python -m ghostchimera.evals run --suite competitive` passes.
- [ ] `python -m ghostchimera.evals run --suite github-connected` passes.
- [ ] `python -m ghostchimera.evals run --suite path-synthesis` passes.
- [ ] `ghostchimera capabilities --format json` reports `ok: true`, `score_ratio: 1.0`, and no `top_gaps`.
- [ ] `ghostchimera github status` reports a usable auth mode (`token` or `gh-cli`).
- [ ] `ghostchimera path set ...` persists an active Ghost Path and `ghostchimera path show` returns the same profile.
- [ ] Console Path tab can synthesize and save the active Ghost Path through `/api/console/paths/active`.
- [ ] `ghostchimera review-pr --base origin/main --head HEAD` reports no blocking P0/P1 findings before merge or push.
- [ ] `docs/COMPETITIVE_CAPABILITY_MATRIX.md` is current for Codex, Claude Code, LangGraph, CrewAI, Hermes-style, and OpenClaw-style benchmarks.
- [ ] `ghostchimera local-model check` reports system readiness and llama-cpp install state.
- [ ] `ghostchimera local-model profiles` lists tiny, balanced, and stronger profiles.
- [ ] `ghostchimera local-model inventory` scans only local model roots and remains preview-only.
- [ ] `ghostchimera local-model resolve --source Qwen/Qwen2.5-7B-Instruct` classifies model sources without downloading anything.
- [ ] `ghostchimera cognition guard --confidence 0.9 --variance 0.01` reports a passing confidence/variance guard.
- [ ] `ghostchimera context compress --text "latency latency matters" --focus latency` returns deterministic compressed text.
- [ ] `ghostchimera capability-pack list` reports built-in tools without requiring an external MCP server.
- [ ] `ghostchimera sandbox journey` emits a local operator journey report and preserves findings.
- [ ] `ghostchimera remote status` reports disabled-by-default remote control state, no paired peers unless intentionally configured, and no raw channel secrets.
- [ ] `ghostchimera trust status` reports durable journal readiness, pending approvals, MCP trust posture, trace health, and eval baseline status without raw secrets.
- [ ] `ghostchimera trust eval baseline` creates a fresh local trust baseline before production deployment.
- [ ] `ghostchimera trust eval-cases list` lists promoted regression cases or returns an empty local-first case list without failing.
- [ ] `ghostchimera trust trace export latest` exports redacted local JSON when a run exists, or fails closed when no runs exist.
- [ ] `ghostchimera mcp trust list` shows approved/revoked/reviewed MCP servers and no unreviewed high-risk server is enabled for production.
- [ ] `ghostchimera capability-admission list` reports reviewed capability records and does not expose raw secrets.
- [ ] Console Trust Runtime tab can add a capability record, approve it, activate it, revoke it, and quarantine it through `/api/console/capability-admission`.
- [ ] `ghostchimera local-model guide --profile balanced` prints install steps.
- [ ] Optional hackathon/developer tooling, including IBM Bob files, remains outside the `ghostchimera/` runtime package and is documented in `docs/BOB_OPTIONAL_TOOLING.md`.
- [ ] README quickstart works from a clean virtual environment.
- [ ] CI installs `.[gateway,dev]` for full source validation and separately smokes the base wheel with no extras.
- [ ] `ghostchimera --config-show` prints JSON with expected state paths and policy defaults.
- [ ] `ghostchimera workspace show` prints the local operator workspace state with truthful capability limits.
- [ ] `ghostchimera workspace sync-memory --memory-db .ghostchimera-memory.sqlite3 --min-confidence 0.8 --stale-after-days 30` promotes high-confidence workspace evidence/reflections into CWR memory with provenance, filters low-confidence records, flags stale/conflicting records for review, and skips duplicates on repeat runs.
- [ ] With `.[gateway]` installed, `ghostchimera console --state-dir .ghost-console-smoke --no-open` starts and prints a localhost URL.
- [ ] Console `/api/console/workspace` reports self-model, working memory, attention, and uncertainty.
- [ ] Console `/api/console/autonomy/jobs` lists profile-aware jobs and records a preview run.
- [ ] Console `/api/console/autonomy/schedules` can create a disabled recurring autonomy job.
- [ ] Console browser workspace status remains useful when optional `agent-browser` is not installed.
- [ ] `python -m ghostchimera.evals run --suite user-journey` passes in a gateway-enabled clean environment.
- [ ] `ghostchimera --pilot-status` prints JSON.
- [ ] `chimera-pilot status --include-deterministic-backend` prints JSON.
- [ ] `chimera-pilot model-profiles` lists the constrained local model profiles.
- [ ] `ghostchimera minimind architectures` lists embedded MiniMind architecture contracts without optional dependencies.
- [ ] `ghostchimera minimind status` distinguishes embedded architecture availability from real MiniMind inference availability.
- [ ] `ghostchimera minimind personal-status` reports consent, memory, dataset, and RAG handoff readiness.
- [ ] `ghostchimera minimind personal-consent --admin-controls ...` persists explicit Personal MiniMind admin consent and approved source scopes.
- [ ] `ghostchimera minimind personal-bootstrap --include-system-specs` ingests only consented sources and writes local dataset records when training is allowed.
- [ ] Whole-machine crawl toggle discovers only readable supported files under configured roots, respects default/custom exclusions, and honors `--max-files` / `--max-emails`.
- [ ] Console MiniMind tab can save/revoke consent, toggle whole-machine/email crawling, bootstrap approved sources, and build a primary-model handoff prompt.
- [ ] `docs/PERSONAL_MINIMIND_PRIVACY.md` is current for consent scopes, local storage, email artifact crawling, and local MiniMind runtime behavior.
- [ ] `chimera-pilot run "retrieve memory about project" --include-deterministic-backend` succeeds.
- [ ] CWR memory add/search/run works with a local `--memory-db`.
- [ ] `chimera-pilot run "python: print(2 + 3)"` is denied by default.
- [ ] `chimera-pilot run "python: print(2 + 3)" --allow-python` succeeds for trusted code.
- [ ] `SECURITY.md` reflects the current execution surfaces.
- [ ] `CHANGELOG.md` includes the release date and scope.
- [ ] No secrets are committed.
- [ ] Optional quantum dependency remains optional.
- [ ] Optional local inference dependencies, including MiniMind and llama.cpp, remain optional.

## Release positioning

Use beta language while still being explicit that the project has not undergone external security review or production deployment testing.

Recommended wording:

> Ghost Chimera is a beta local-first agent orchestration runtime with a resource scheduling and policy layer called Chimera Pilot.

Avoid:

> Production AGI OS, autonomous enterprise agent, quantum OS clone, or secure sandbox for untrusted code.
