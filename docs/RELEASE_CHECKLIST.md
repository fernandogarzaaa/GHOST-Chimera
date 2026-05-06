# Release Checklist

Use this before publishing a public release.

## Required checks

```bash
python scripts/validate_release.py
python -m build
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
GHOSTCHIMERA_DEPLOYMENT_MODE=production GHOSTCHIMERA_EXTERNAL_ISOLATION=container GHOSTCHIMERA_SECURITY_REVIEWED=1 GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1 ghostchimera doctor --production
```

The release gate, package build, and built-in eval suites must pass before tagging.

The browser console also exposes `/api/console/readiness` as a local runbook view
of these commands. It is intentionally a checklist surface, not an unattended
production deployment workflow.

## Manual checks

- [ ] README quickstart works from a clean virtual environment.
- [ ] `ghostchimera --config-show` prints JSON with expected state paths and policy defaults.
- [ ] With `.[gateway]` installed, `ghostchimera console --state-dir .ghost-console-smoke --no-open` starts and prints a localhost URL.
- [ ] Console `/api/console/autonomy/jobs` lists profile-aware jobs and records a preview run.
- [ ] Console `/api/console/autonomy/schedules` can create a disabled recurring autonomy job.
- [ ] Console browser workspace status remains useful when optional `agent-browser` is not installed.
- [ ] `ghostchimera --pilot-status` prints JSON.
- [ ] `chimera-pilot status --include-deterministic-backend` prints JSON.
- [ ] `chimera-pilot model-profiles` lists the constrained local model profiles.
- [ ] `chimera-pilot run "retrieve memory about project" --include-deterministic-backend` succeeds.
- [ ] CWR memory add/search/run works with a local `--memory-db`.
- [ ] `chimera-pilot run "python: print(2 + 3)"` is denied by default.
- [ ] `chimera-pilot run "python: print(2 + 3)" --allow-python` succeeds for trusted code.
- [ ] `SECURITY.md` reflects the current execution surfaces.
- [ ] `CHANGELOG.md` includes the release date and scope.
- [ ] No secrets are committed.
- [ ] Optional quantum dependency remains optional.
- [ ] Optional local inference dependency remains optional.

## Release positioning

Use beta language while still being explicit that the project has not undergone external security review or production deployment testing.

Recommended wording:

> Ghost Chimera is a beta local-first agent orchestration runtime with a resource scheduling and policy layer called Chimera Pilot.

Avoid:

> Production AGI OS, autonomous enterprise agent, quantum OS clone, or secure sandbox for untrusted code.
