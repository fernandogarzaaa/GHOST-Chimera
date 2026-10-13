# Ghost Chimera

[![CI](https://github.com/fernandogarzaaa/GHOST-Chimera/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/fernandogarzaaa/GHOST-Chimera/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ghostchimera?include_prereleases&label=pypi)](https://pypi.org/project/ghostchimera/)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Ghost Chimera is local-first background AI for your workflow.** Its Stealth Loop
watches events (issues, files, agent prompts), learns how you work, and quietly
prepares context for whichever AI agent you use, consulting **NVIDIA Nemotron on
Nebius Token Factory** when it needs deeper reasoning.

## Try it in one minute

```bash
pipx install ghostchimera      # or: pip install ghostchimera
ghost demo                     # replays a Nemotron session offline: no keys, no network
```

> `ghost demo` is new after 0.4.0b1 on PyPI. Until the next release, install from GitHub:
> `pipx install git+https://github.com/fernandogarzaaa/GHOST-Chimera`

`ghost demo` runs the real Stealth Loop and Nemotron reasoner against a session
recorded live on Nebius Token Factory and bundled with the package (UNDERSTAND
with Nemotron 3 Nano, PREDICT with Nemotron 3 Super); the replies are the
models' raw output, unedited. To go live, set `NEBIUS_API_KEY`
([console.nebius.com](https://console.nebius.com), Token Factory → API keys) and
record your own session with `ghost demo --record session.json`.

**Demo video:** _coming soon_ <!-- DEMO_VIDEO_URL: replace with the YouTube/Loom link -->

## Learn more

- **[Full overview](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/OVERVIEW.md)**: how the
  Stealth Loop works, Nemotron/Tavily/LangSmith setup, the one-line installers, runtime specs, and capabilities.
- [Quick start](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/quick-start.md) ·
  [Install matrix](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/INSTALL.md) ·
  [Architecture](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/ARCHITECTURE.md) ·
  [Usage guide](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/USAGE_GUIDE.md)
- [Experimental features](https://github.com/fernandogarzaaa/GHOST-Chimera/blob/main/docs/experimental/README.md)
  (superiority scorecard, SaaS, quantum, MiniMind): shipped but early, and not part of the hackathon submission.

**Python is canonical for the hackathon.** This package is what judges install and
what `ghost demo` runs. [ghost-chimera-rs](https://github.com/fernandogarzaaa/ghost-chimera-rs)
is the lean long-term core.

Beta software for user-supervised, local-first work. Not AGI, and not a sandbox for
untrusted code on its own.

## License

MIT, see [`LICENSE`](LICENSE). Third-party attribution in [`NOTICE`](NOTICE).
