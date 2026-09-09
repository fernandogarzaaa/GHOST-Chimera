# Install Ghost Chimera

Two doors, one runtime. Pick the one that matches your machine.

> **npm (`npm install -g ghostchimera`) is paused**: the npmjs account needs
> 2FA recovery first (npmjs.com → Sign In → account recovery via email).
> The wrapper in `npm/` is finished and tested — publishing is a single
> `npm publish --access public` once access is restored.

## pip (Python, recommended for developers)

Full install first — everything included:

```bash
pip install "ghostchimera[all]"   # every backend: desktop, local models, MCP, voice, quantum
ghostchimera doctor               # reports exactly which backends are live
```

Lean alternative (servers, containers, minimal footprint):

```bash
pip install ghostchimera            # headless core: console, pilot, stealth loop
pip install "ghostchimera[desktop]" # add just live desktop control (pulls pyautogui)
```

Requires Python ≥ 3.11. The core has exactly 4 required packages
(certifi, croniter, jsonschema, websockets); everything else is optional
and lazy-loaded, so missing extras degrade — never crash.

## npm — paused

`npm install -g ghostchimera` is on hold until the npmjs account 2FA is
recovered. The finished wrapper lives in `npm/`; publishing is one command
(`cd npm && npm publish --access public`) once access is restored.

## Homebrew (macOS / Linux)

```bash
brew tap fernandogarzaaa/ghostchimera
brew install --HEAD ghostchimera   # stable `brew install` after the v0.4.0 tag
ghostchimera doctor
```

The formula (`homebrew/ghostchimera.rb`) installs into an isolated venv
with Python 3.12. See `homebrew/README.tap.md` for tap setup.

## After install

```bash
ghostchimera start     # Ghost Console at http://127.0.0.1:8766/
ghostchimera doctor    # health checks: providers, models, gateway, skills
```

First run? The Console's Operator Workbench shows a 3-step checklist:
connect a model provider → run the readiness check → connect integrations
(Slack, Notion, GitHub…) from the **Integrations** tab or 1-click via Nango
(see `docs/NANGO.md`).

## Local voice (Wispr-style dictation + Ghost speech)

```bash
pip install "ghostchimera[voice]"   # faster-whisper, vosk, pocketsphinx
```

Then point Ghost at a model (fully offline after first download):

```bash
# Example: faster-whisper tiny model (~75 MB)
# download once, then:
set GHOSTCHIMERA_LOCAL_STT_MODEL=C:\models\faster-whisper-tiny   # Windows
export GHOSTCHIMERA_LOCAL_STT_MODEL=~/.ghostchimera/models/fw-tiny  # macOS/Linux
```

Provider chain is automatic: faster-whisper → vosk → pocketsphinx, with
per-provider status at `/api/console/conversation/local-voice/status`.
In the Console, hold **Hold 🎙** to dictate (transcribed, Wispr-formatted,
and dropped into the message box), and use the voice-speed slider + Test
voice for Ghost's spoken replies. No audio ever leaves the machine.

## Publishing a release (maintainers)

```bash
# 1. Tag and build
git tag v0.4.0 && git push origin v0.4.0
python -m build                    # dist/*.whl + *.tar.gz
twine check dist/*

# 2. PyPI  (needs a trusted-publisher or API token)
twine upload dist/*

# 3. npm  (PAUSED: needs npmjs 2FA recovery; name `ghostchimera` is free)
#    cd npm && npm publish --access public

# 4. Homebrew tap
#    - update url + sha256 in homebrew/ghostchimera.rb (shasum of the tag tarball)
#    - copy to homebrew-ghostchimera tap repo, `brew audit --new`, push
```

`tests/test_packaging.py` guards the whole matrix offline: npm manifest +
version sync, formula shape, PyPI metadata URLs, extras incl. `desktop`,
headless core free of GUI deps, and all four console entry points.
