# Deep Audit — Console user workflow (sandbox + EVE QA)

Date: 2026-09-17. Method: isolated sandbox
(`scripts/sandbox_user_workflow.py`) drives the real console HTTP API through
a fresh first-run journey; EVE 0.5.0 (playwright persona `first-time-user`)
attacks the same live console. This is the first audit that exercises the
*browser-facing* journey end to end rather than unit surfaces.

## What the sandbox covers (9 steps)

landing page → status → provider selection → autonomy read → objective run →
workspace snapshot → thinking trace → capabilities → readiness.

## Fixed during this audit

### 1. Console config is not isolated by `state_dir` (real bug)
`run_console(state_dir=tmp)` isolated memory/audit/trust but **not config**:
the browser config always read/wrote `~/.ghostchimera/config.json`. A
sandbox run silently overwrote the user's real provider. `register_console_routes`
already accepted `config_path`; `run_console` did not wire it.
Fix: `run_console` passes `config_path=state_dir/config.json`.

### 2. Objective runs ignore the console's own config (real bug)
`_default_run_objective` read the *global* `load_config()` for autonomy and
`GhostChimeraConfig.from_env()` for the model, so even an isolated console
ran with the user's global provider/key. A sandbox run used the real
OpenRouter key instead of the sandbox's Ollama setting.
Fix: when `config_path` is provided, `_apply_saved_config_env(config_path,
overwrite=True)` and read autonomy from that config file.

### 3. Run failures are silent (real bug)
`POST /api/console/run` returned `{"ok": false, "error": null}` with the
real error buried in `executions[].error`. A user clicking Run sees a
silent failure with no path forward.
Fix: surface the first execution error at the top level.

All three fixed with the sandbox verifying the behavior; `73 passed` across
console + gateway suites, real `~/.ghostchimera/config.json` untouched.

## Verified gaps still open (from EVE QA)

### 4. Dead controls — no visible feedback on action
EVE (12 major usability findings): clicking **Config**, **Save GitHub
Client**, **Enable remote control**, standing-order forms shows **no
perceivable response**. First-time users click again and blame themselves.
(Not reproduced as an HTTP error — the endpoints return 200 — so this is a
front-end feedback gap, not a backend failure.)

### 5. First-run provider UX: no keyless option in the browser
The browser config endpoint only offers real providers (29). A first-time
user with no API key has no "skip / local-first / deterministic" path; the
CLI supports `skip`, the browser does not. Sandbox falls back to Ollama.

### 6. EVE noise vs signal (instrumentation, not product)
EVE reports ~70 major findings, but most are detector false positives on
this dark theme: checkbox-label pairs read as "overlapping elements",
input placeholders read as "text only eyes can reach", hidden tab panels
report as "controls missing from screen". These should be **filtered or
ignored** in any automated EVE CI gate, otherwise the signal (real findings
#4/#5) drowns.

## Prioritized recommendations

1. **P1 — Action feedback (finding 4):** every console action button
   (Save/Enable/Submit) must render a toast/spinner/result. This is the
   single highest-impact EVE finding and is pure front-end.
2. **P1 — Keyless first-run (finding 5):** expose a `skip`/deterministic
   (and local) option in the browser config endpoint so a no-key user can
   complete onboarding.
3. **P2 — EVE noise filter (finding 6):** add an EVE-ignore list (or a
   post-process filter) for the known false-positive detector classes so
   the QA gate reports only real findings.
4. **P3 — Sandbox into CI:** run `sandbox_user_workflow.py` in CI (it needs
   no model/key — the run step warns, not fails, when the provider is
   unreachable).

## Files touched

- `ghostchimera/control_plane/console.py` — config isolation, run isolation,
  error surfacing.
- `scripts/sandbox_user_workflow.py` — new sandbox (9-step journey, EVE hold).
- `scripts/hold_console_for_eve.py` — new EVE QA hold launcher.