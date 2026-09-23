# Running Ghost Chimera for $0 — Free-Model Guide

Ghost can run entirely on free model tiers. No card required anywhere
below. Quotas reset daily; the router fails over automatically when one
tier is exhausted or errors.

## The chain (in order, automatic failover)

| # | Tier | What to do | Daily quota | Trains on your prompts? |
|---|---|---|---|---|
| 1 | Gemini 2.5 Flash-Lite | Free key at `ai.google.dev` → `GOOGLE_API_KEY` | ~1,500 req | **Yes — keep secrets out** |
| 2 | Gemini 2.5 Flash | Same key (better quality, smaller pool) | ~500 req | **Yes — keep secrets out** |
| 3 | Groq `gpt-oss-20b` | Free key at `console.groq.com` → `GROQ_API_KEY` | ~1,000 req | No |
| 4 | Groq `qwen3.6-27b` | Same key (second pool stacks quota) | ~1,000 req | No |
| 5 | OpenRouter free pool | Free key at `openrouter.ai` → `OPENROUTER_API_KEY` | 50 req (strictly $0) | **Yes — keep secrets out** |
| 6 | Cloudflare Workers AI | Free account: `CF_ACCOUNT_ID` + `CF_API_TOKEN` | ~neuron allowance | No |
| 7 | Pollinations keyless | Nothing — works with zero setup | ~96 req | **Yes — emergency only** |

Model IDs and limits rotate; re-check the linked consoles monthly.
Totals assume one identity per provider — never farm accounts to dodge
quotas (ban risk everywhere).

## Setup (pick one)

**Wizard (recommended):** `ghostchimera setup` → choose
`Free tiers` first in the list. Paste the free keys you have (Enter
skips any); the router uses whatever is present.

**Console:** paste each key in Stored Keys as a `byok` entry, or set the
env vars (`GOOGLE_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`,
`CF_ACCOUNT_ID` + `CF_API_TOKEN`).

**No keys at all:** Ghost still works — Pollinations keyless answers as
the last resort. Expect slowness and small models.

## Privacy rule (enforced, not advised)

Tiers marked **trains on data** never receive content the sensitivity
guard flags (passwords, keys, IDs, codes, reset links). Such calls skip
to a non-logging tier or fail with a clear error instead of leaking.
This is automatic in `FreeRouter.chat()` — see `quota_status()` for
per-tier privacy flags shown in the Console Usage tab.

## What stays free, what doesn't

- Background Ghost (learning, triggers, approvals, automations): **$0
  always** — no model calls involved.
- Chat and summaries: **$0** while free quotas last. Heavy days can
  exhaust the 50/day OpenRouter pool; Gemini Lite's 1,500/day is the
  workhorse.
- If every tier is exhausted, Ghost says so explicitly (per-tier
  diagnostics) instead of silently degrading.
