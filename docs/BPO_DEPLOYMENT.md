# BPO Production Deployment (no-funds edition)

Everything in the production architecture runs **local-first, free, offline**
except the model calls themselves. Mapping spec → implementation:

| Spec asks | Ghost implementation | Cost |
|---|---|---|
| Postgres: va_users, oauth_connections, browser_profiles, audit logs | `stealth/bpo_store.py` (SQLite/WAL, same column contract) | $0 |
| Fernet-encrypted auth.json blobs | `BpoStore.save/load_browser_profile` (machine-local key, 0600 file) | $0 |
| FastAPI webhook normalizer + queue | `connectors/webhooks.py` (gmail/slack/zendesk) + `POST /api/webhooks/{source}/{va_id}` + `BackgroundRuntime` | $0 |
| E2B/Playwright MicroVM runner | `browser_profiles` storage + hydration contract; execution reuses `tool_layer` browser workspace | $0 local; E2B only if you outgrow local |
| Ghost-writer Chrome extension | `extensions/ghost-writer/` + `POST /api/stealth/ghost-write` (model-backed, silent without one) | $0 until inference |
| Audit trail with mode + pathway | `ghost_audit_logs` + `StealthStore` outcomes | $0 |

## What still costs money (and the free alternative)

- **Model inference** (completions, ghost-writer, cleanup passes): OpenRouter
  free-tier endpoints (`:free` suffix) work today — see the live free-model
  test. Paid models need credits.
- **E2B sandboxes / Browserbase**: only if local Playwright stops being
  enough. The profile store is backend-agnostic by design.

## Environment

```bash
GHOSTCHIMERA_VAULT_SECRET=...   # optional: pins browser-profile encryption
                                 # (default: generated machine-local 0600 key)
NANGO_SECRET_KEY=...             # only for Nango-proxied actions
OPENROUTER_API_KEY=...           # only for model-backed routes (ghost-write)
```
