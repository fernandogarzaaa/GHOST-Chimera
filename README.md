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

> `ghost demo` is included in 0.4.0b2 on PyPI. Install from PyPI with the command above.

`ghost demo` runs the real Stealth Loop and Nemotron reasoner against a session
recorded live on Nebius Token Factory and bundled with the package (UNDERSTAND
with Nemotron 3 Nano, PREDICT with Nemotron 3 Super); the replies are the
models' raw output, unedited. To go live, set `NEBIUS_API_KEY`
([console.nebius.com](https://console.nebius.com), Token Factory → API keys) and
record your own session with `ghost demo --record session.json`.

### Environment variables

Setting `NEBIUS_API_KEY` alone is enough: with `GHOSTCHIMERA_MODEL_PROVIDER` unset,
`ghost ask`, `ghost --pilot-run`, `ghost doctor` and the Stealth Loop auto-select Nebius
(Nemotron). An explicit `GHOSTCHIMERA_MODEL_PROVIDER` always wins.

| Variable | Default | What it does |
|---|---|---|
| `NEBIUS_API_KEY` | unset | Turns on Nemotron (auto-selects the `nebius` provider). |
| `NEBIUS_MODEL` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | Model for `ask`/pilot and Stealth Loop UNDERSTAND. |
| `NEBIUS_FALLBACK_MODELS` | unset | Comma list tried when the primary errors, e.g. `nvidia/Nemotron-3_5-Lightning`. |
| `GHOSTCHIMERA_NEMOTRON_MODE` | `async` | `async`: Nemotron runs off the `emit()` hot path; `sync`: inline. |
| `GHOSTCHIMERA_NEMOTRON_TIMEOUT_S` | `20` | Per-call timeout for Stealth Loop Nemotron calls. |
| `GHOSTCHIMERA_NEMOTRON_CALLS_PER_MIN` | `30` | Cloud call budget per minute (0 = unlimited). |
| `GHOSTCHIMERA_NEMOTRON_TOKENS_PER_HOUR` | `100000` | Token budget (reasoning tokens included); calls stop when spent. |
| `GHOSTCHIMERA_NEMOTRON_UNDERSTAND_THINKING` | `0` | `1` turns Nemotron's reasoning trace back on for UNDERSTAND (slower). |
| `GHOSTCHIMERA_PROVIDER_RETRIES` | `2` | Retries on 429/5xx, honouring `Retry-After`. |
| `GHOSTCHIMERA_BUS_LOG_MAX` | `5000` | Events kept in the in-memory replay log. |

**Demo video:** [Watch the 3-minute demo on YouTube](https://youtu.be/m1jGOAfMZsg): real Linux screen capture showing `ghost demo`, a live Nemotron Stealth Loop pass on Nebius, and the console.

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
