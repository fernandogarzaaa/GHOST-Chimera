# Custom Auth Engine (self-hosted OAuth, no Nango)

Ghost Chimera runs its own OAuth2 engine. No third-party auth cloud, no
per-seat auth fees, no `NANGO_SECRET_KEY`. Provider credentials are plain
OAuth app client IDs that you create once per provider.

## Concepts

- **Entity**: who connected — a VA/agent/tenant id (e.g. `va-1`, `console-user`).
- **Connection**: one `(entity_id, provider)` row holding Fernet-encrypted
  `access_token` + `refresh_token`, expiry, scopes, and status
  (`ACTIVE` / `NEEDS_REAUTH`). SQLite locally
  (`auth.sqlite3`); `migrations/0001_integration_auth_tokens.sql` is the
  identical Postgres contract.
- **Master secret**: `GHOSTCHIMERA_VAULT_SECRET` pins encryption. Without it
  a generated machine-local 0600 key is used (same machine decrypts).

## Console flow (Integrations tab)

1. Click **Connect** → `POST /api/auth/authorize {provider, entity_id,
   redirect_uri}` returns `{authorize_url, state}` and opens the provider
   login. `entity_id` + provider ride inside signed `state` (+ PKCE).
2. Provider redirects to `/api/auth/callback` (wire it to call
   `CustomAuthEngine.handle_callback`) → code exchanged, tokens encrypted
   and stored → `{ok, expires_at, scopes}`.
3. Refresh Status → `GET /api/auth/status` (redacted: no tokens, ever).
4. Every API call goes through `get_valid_token()`: decrypt, 5-minute
   skew, single-flight auto-refresh, `invalid_grant` demotes the row to
   `NEEDS_REAUTH` instead of deleting it.

## Backend use (stealth workers, approvals)

```python
from ghostchimera.connectors import CustomAuthEngine, EngineAction

engine = CustomAuthEngine(state_dir)
try:
    action = EngineAction(
        provider="slack",
        url="https://slack.com/api/chat.postMessage",
        payload={"channel": "#ops", "text": "Update sent."},
    )
    action.execute(engine, "va-1")  # Bearer header, fresh token, no middleman
finally:
    engine.close()
```

Approval drafts (`approve_draft(..., connections={"slack": "va-1"})`)
deliver through the same path; without a grant they stay
approved-but-not-sent with copy-paste text — never claimed as sent.

## Provider setup (one client ID each)

| Provider | Env | Notes |
|---|---|---|
| Slack | `SLACK_CLIENT_ID` (+ `_CLIENT_SECRET`) | api.slack.com app, bot scopes |
| Google/Gmail | `GOOGLE_OAUTH_CLIENT_ID` | console.cloud.google.com, Gmail API |
| GitHub | `GHOSTCHIMERA_GITHUB_CLIENT_ID` | OAuth App, device flow also available |
| Notion | `NOTION_CLIENT_ID` | notion.so integrations |
| LinkedIn | `LINKEDIN_CLIENT_ID` | developer.linkedin.com, r_liteprofile |
| HubSpot | `HUBSPOT_CLIENT_ID` | private app or OAuth |
| Salesforce | `SALESFORCE_CLIENT_ID` | connected app |
| Zendesk/Freshdesk/Gorgias | `*_CLIENT_ID` | subdomain apps; pass absolute API URLs |
| Airtable | `AIRTABLE_CLIENT_ID` | airtable.com/oauth2 |
| Hubstaff/Time Doctor | `*_CLIENT_ID` | workforce scopes |

Full preset URLs/scopes: `ghostchimera/connectors/oauth.py` (`OAUTH_PRESETS`).

## Migrating off Nango

There is nothing to migrate *from*: the previous integration used Nango
Cloud as a proxy, so existing grants live in Nango, not here. Reconnect
each provider once through the Integrations tab; the old `NANGO_*`
environment variables are ignored and can be deleted. `docs/NANGO.md`
has been removed; this file replaces it.

## Shared project logins (why users don't all register apps)

OAuth always needs *an* app registration — the only question is who owns
it. Platforms with 1-click login (Nango, Zapier) operate **one shared,
verified app per provider** and proxy every user through it. Ghost does
the same thing without the proxy company:

1. The maintainer registers **one OAuth app per provider** (Desktop/native
   type, PKCE, no secret to leak) and drops its public client ID into
   `SHIPPED_CLIENT_IDS` in `connectors/auth_engine.py`.
2. Every user then gets 1-click login: the engine resolves client IDs as
   environment → console-saved → shipped default, and the UI can show
   which source is active via `client_id_source()`.

Per-provider reality check:

| Provider | Shared login friction |
|---|---|
| GitHub, Slack | none — register the app, embed the ID, done |
| Notion | public integration needs Notion approval for distribution |
| Google (Gmail) | **sensitive scopes**: brand verification + privacy policy + review (weeks); 100 test-user cap until verified |
| LinkedIn, HubSpot, Salesforce | developer program signup each; verify per product |

Public clients (PKCE, no secret) vs confidential clients: the engine reads
`<PRESET>_CLIENT_SECRET` from the environment at token-exchange time and omits
it when empty. Providers whose preset sets `use_pkce` (`oauth.py`) work with a
public Desktop/native client and no secret:

GitHub, Slack, Notion, LinkedIn, Google, Zendesk, Gorgias, HubSpot,
Salesforce, Airtable, Time Doctor.

These two require a confidential client **plus** its secret in the
environment — a public client alone cannot complete login:

| Provider | Secret env var |
|---|---|
| Freshdesk | `FRESHDESK_CLIENT_SECRET` |
| Hubstaff | `HUBSTAFF_CLIENT_SECRET` |

Until a shared ID ships for a provider, users paste their own client ID
once in the Integrations tab (bring-your-own, same UX, their quota).
