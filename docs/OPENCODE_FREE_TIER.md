# OpenCode Free-Tier Routing

Ghost Chimera can route model calls through OpenCode's free-tier models
(`opencode/*`) without any API key of its own. This page explains how the
routing works, why it is built the way it is, and how to set it up.

## How it works

The provider is `ghostchimera/model_layer/opencode_cli_provider.py`
(`OpenCodeCliProvider`, registered as `opencode_cli`). For each chat turn it:

1. Builds a prompt from the system and user messages.
2. Spawns the genuine `opencode run --format json --model <model>` CLI
   subprocess in an empty temporary working directory (so the delegated
   model cannot see or touch the operator's files).
3. Parses the newline-delimited JSON event stream and returns the assistant
   text parts.

Ghost Chimera never talks to OpenCode's inference endpoints directly.

## Why the CLI subprocess, not direct HTTPS

Zen's free-tier models intentionally reject direct HTTPS calls from
non-OpenCode clients (HTTP 403 client gate). There is no supported way to
call the free tier over raw HTTP, and Ghost Chimera does not try to bypass
that gate: no spoofed `User-Agent`, no forged session headers.

The legitimate free-tier route is delegating to the user's own authenticated
`opencode` CLI, which OpenCode maintains and authorizes. Ghost Chimera keeps
a strict boundary here:

- OpenCode owns its auth lifecycle. Ghost Chimera only **presence-checks**
  the auth file (exists and non-empty); it never reads or copies OpenCode's
  private credentials.
- If the CLI is missing or not logged in, the provider reports that plainly
  and refuses to run. It never silently falls back to a paid provider.

## Setup

1. Install the OpenCode CLI (https://opencode.ai) so `opencode` is on your PATH.
   Override the command name with `GHOSTCHIMERA_OPENCODE_COMMAND` if needed.
2. Log in: `opencode auth login`
3. In Ghost Chimera, run `ghostchimera setup` (or the model picker) and choose
   **OpenCode CLI**. The wizard prints setup guidance automatically if the CLI
   is missing or not logged in.

Useful environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `GHOSTCHIMERA_OPENCODE_COMMAND` | CLI command to invoke | `opencode` |
| `GHOSTCHIMERA_OPENCODE_MODEL` | Model override | `opencode/mimo-v2.5-free` |
| `GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS` | Per-turn subprocess timeout | `180` |

## Free-model rotation

Free-tier model names rotate on OpenCode's side. The provider keeps an ordered
preference list (`KNOWN_FREE_MODELS` in the provider module):

- The configured model is always tried first.
- If the configured model is itself a known free-tier model and OpenCode
  reports it as retired/unknown, the provider automatically tries the next
  known free model instead of failing hard. The model that served the answer
  is recorded on `provider.last_model_used` and in `to_dict()`.
- If you explicitly configure a model outside the known free list, it is used
  exactly as configured: it is never silently swapped. If it becomes
  unavailable you get an error telling you to update it.

To change the model at any time: `GHOSTCHIMERA_OPENCODE_MODEL=opencode/<name>-free`
or re-run the setup wizard / model picker.

## Data-use warning

Free-tier `opencode/*` models may use your prompts to improve their service,
and some free models are trial/evaluation-only. **Do not send confidential,
personal, or secret data through this provider** unless you have reviewed the
model host's terms. The setup wizard and model picker print this notice every
time the provider is selected, and it is also present in the provider's
`to_dict()` output under `data_use_notice`.

## Troubleshooting

- `OpenCode CLI was not found on PATH` — install the CLI and ensure
  `opencode` resolves via `which opencode`.
- `OpenCode CLI is not logged in. Run: opencode auth login` — complete the
  official login flow, then retry.
- `timed out after 180s` — free-tier models can be slow or rate-limited;
  raise `GHOSTCHIMERA_OPENCODE_TIMEOUT_SECONDS` or retry later.
- `the configured free model appears to be retired or unknown` — the free
  lineup rotated; set `GHOSTCHIMERA_OPENCODE_MODEL` to a current free model.
