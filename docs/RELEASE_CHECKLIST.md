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
python scripts/smoke_installed_wheel.py
python scripts/smoke_installed_wheel.py --extras gateway
ghostchimera workspace show
GHOSTCHIMERA_DEPLOYMENT_MODE=production GHOSTCHIMERA_EXTERNAL_ISOLATION=container GHOSTCHIMERA_SECURITY_REVIEWED=1 GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 ghostchimera doctor --production
```

The release gate, package build, built-in eval suites, and installed-wheel
smokes must pass before tagging or pushing a beta release branch to `main`.

The browser console also exposes `/api/console/readiness` as a local runbook view
of these commands. It is intentionally a checklist surface, not an unattended
production deployment workflow.

Run the installed-wheel smoke once without extras to verify the base package
does not require optional dependencies. Run it again with gateway extras to
verify console scheduling and the local operator user journey in a clean virtual
environment.

## Manual checks

- [ ] README quickstart works from a clean virtual environment.
- [ ] CI installs `.[gateway,dev]` for full source validation and separately smokes the base wheel with no extras.
- [ ] `ghostchimera --config-show` prints JSON with expected state paths and policy defaults.
- [ ] `ghostchimera workspace show` prints the local operator workspace state with truthful capability limits.
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
