# OAuth Setup (localhost + LAN, local-only registration)

Ghost connects to Google/Gmail, GitHub, Slack, and more via self-hosted
OAuth2. **No credentials ever leave your machine**: tokens are
Fernet-encrypted in the local state dir, the console only reports
connected/expiry status, and client secrets stay in environment variables.

## Paste keys in the console (no terminal needed)

Connections tab → **Provider Logins** section. Every provider shows its
supported flows, whether its client ID/secret is set (and from where:
environment or saved), and the exact callback URL to register. Per
provider you can:

- paste the **client ID** and, for confidential clients (Notion, HubSpot),
  the **client secret**, then Save keys (secrets are stored in the local
  config file with owner-only permissions and are never displayed back);
- **Device login**: shows a code + verification link, opens the provider
  page, and completes automatically when you approve (works over LAN,
  no redirect setup);
- **Browser login**: opens the provider approval in a new tab;
- **Disconnect**: revokes the stored connection;
- **Clear saved keys**: removes locally saved credentials for that provider.

The same operations exist as API routes (`POST /api/auth/client-id`,
`/api/auth/device/start`, `/api/auth/device/poll`,
`GET /api/auth/login-options`). Environment variables always win over
saved values, so containers and production can keep using env-only config.

Two login flows exist per provider. The Integrations tab
(`GET /api/auth/login-options`) tells you which each provider supports.

## Flow 1 — Device login (recommended, works over LAN)
No redirect URI, no browser on the server machine. The console shows a
`user_code` (e.g. `ABCD-1234`) and a verification URL; you open the URL on
**any** device, enter the code, approve, and the console polls until done.

Supported today: **GitHub** (more providers as they gain device flows).

### GitHub (one-time registration, ~3 min)

1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
   - Application name: `Ghost Chimera (local)`; Homepage URL: anything.
   - **Authorization callback URL**: any placeholder (device flow ignores it).
2. Copy the **Client ID** (no secret needed for device flow).
3. In the app's settings, check **Enable Device Flow**.
4. Give Ghost the ID (pick one, first wins):
   - env: `GHOSTCHIMERA_GITHUB_CLIENT_ID=<id>`, or
   - Console → Integrations tab → paste into the GitHub client-ID field.
5. Integrations tab → GitHub → Device login → enter the code at
   https://github.com/login/device → approve.

## Flow 2 — Browser login (redirect flow)

For providers without device flow (Google/Gmail, Slack, …). The console
builds an authorize URL, you approve in your browser, the provider
redirects back to the console callback with a code.

### The redirect-URI rule (read this once)

Providers match the redirect URI **exactly**. Two cases:

- **Same-machine browser** (console + browser on one PC): use a
  **Desktop/native app** client type (Google "Desktop app", Slack PKCE
  public client). Redirects go to `http://127.0.0.1:<any-port>/callback`
  and need no per-port pre-registration.
- **LAN browser** (console on a server, browser on another device):
  register the exact LAN callback in the provider app, e.g.
  `http://192.168.1.50:8766/api/auth/callback`, and **pin the console
  port** so it never changes (see below). Find your exact callback at
  any time via `GET /api/auth/login-options` → `callback_url`.

### Pinning the console address

```powershell
$env:GHOSTCHIMERA_HTTP_PORT = "8766"   # stable port, survives restarts
$env:GHOSTCHIMERA_OAUTH_CALLBACK = "http://192.168.1.50:8766/api/auth/callback"
```

Or save `"console": {"http_port": 8766}` in the Ghost config file. On
startup Ghost warns if the bound address doesn't match the registered
callback (`redirect_uri_mismatch` is a startup warning now, not a login
mystery later). Override per-launch with the `http_port=` argument.

### Google / Gmail (one-time registration, ~5 min)

1. Google Cloud Console → new project → APIs & Services → Credentials →
   Create Credentials → OAuth client ID → **Desktop app**.
2. Enable the **Gmail API** for the project (APIs & Services → Library).
3. Copy the Client ID → `GOOGLE_OAUTH_CLIENT_ID` env (or Integrations tab).
   No secret needed for the Desktop/PKCE path.
4. Integrations → Gmail → Browser login → approve. First consent asks for
   `gmail.readonly` (extra scopes are requested incrementally later).
5. Notes: Google shows an "unverified app" screen until the project is
   verified (fine for personal use — click through). Past ~100 users,
   Restricted scopes (Gmail) require verification + possibly a security
   assessment. **Device flow cannot do Gmail** (Google forbids Gmail
   scopes on it) — use the browser flow.

### Slack (one-time registration, ~5 min)

1. api.slack.com/apps → Create New App → From scratch.
2. Enable **PKCE** (makes it a public client — no secret needed).
3. Add redirect `http://127.0.0.1:<port>/callback` (same-machine) and/or
   your LAN callback.
4. Copy the Client ID → `SLACK_CLIENT_ID` env (or Integrations tab).
5. Ghost requests **user (xoxp) scopes** (`channels:history`,
   `channels:read`, `groups:history`, `groups:read`, `users:read`).
   PKCE/desktop installs **cannot** request bot scopes — if you need a bot
   token, register a classic confidential app and set `SLACK_CLIENT_SECRET`
   instead (Ghost omits the secret automatically when it is empty).

### Salesforce

Standard browser flow. If your org uses a sandbox or My Domain, set the
login host (no code change needed):

```powershell
$env:SALESFORCE_LOGIN_HOST = "example.my.salesforce.com"  # or test.salesforce.com
```

### Per-provider environment reference

| Provider | Client ID env | Secret env (confidential only) | Notes |
|---|---|---|---|
| GitHub | `GHOSTCHIMERA_GITHUB_CLIENT_ID` | — | enable Device Flow on the app |
| Google/Gmail | `GOOGLE_OAUTH_CLIENT_ID` | — | Desktop app type; Gmail API on |
| Slack | `SLACK_CLIENT_ID` | `SLACK_CLIENT_SECRET` | PKCE public client needs no secret |
| Salesforce | `SALESFORCE_CLIENT_ID` | `SALESFORCE_CLIENT_SECRET` | `SALESFORCE_LOGIN_HOST` for sandboxes |
| Notion | `NOTION_CLIENT_ID` | `NOTION_CLIENT_SECRET` | confidential: secret required |
| HubSpot | `HUBSPOT_CLIENT_ID` | `HUBSPOT_CLIENT_SECRET` | confidential: secret required |
| Airtable | `AIRTABLE_CLIENT_ID` | — | PKCE, secret optional |
| LinkedIn | `LINKEDIN_CLIENT_ID` | `LINKEDIN_CLIENT_SECRET` | native PKCE gated by LinkedIn |

## Security notes

- Client IDs are public identifiers — safe in the local config file.
  **Secrets and tokens are never committed**: keep them in env vars.
- `SHIPPED_CLIENT_IDS` in `auth_engine.py` is intentionally empty in the
  public repo. Do not paste your private client IDs there — use env or
  the Integrations tab.
- Device login handles (`device-{...}.json`) hold single-use device codes
  server-side and are deleted on completion, denial, or expiry.
- Disconnect actually revokes: Integrations → Revoke, or
  `POST /api/auth/revoke`.

## Zero-friction logins (no registration at all)

### GitHub CLI import

If `gh` is logged in on the same machine, Ghost reuses it — no OAuth app,
no browser clicks. Connections → Provider Logins shows a "GitHub CLI login
detected" banner automatically; one click imports the token into Ghost's
vault (source labeled `github-cli`, inheriting `gh`'s scopes). If the token
goes stale (`gh auth logout`, revocation), status shows `NEEDS_REAUTH` with
the same one-click re-import. API: `POST /api/auth/gh/status`,
`POST /api/auth/gh/import`.

### Stored keys (API keys + mail app passwords)

Connections → Stored Keys. Paste any key once (OpenAI/Anthropic/xAI keys,
Gmail/Outlook/Yahoo **app passwords** — the 12–64 char provider-issued
codes, never account passwords), label it, and Ghost stores it
Fernet-encrypted. Listings show labels only; values are never displayed,
logged, or returned by any route. API: `/api/auth/keys/save|list|delete`.

App passwords become usable mail through `POST /api/auth/mail/fetch`
(key ID or label, max 50 messages, IMAP UNSEEN by default): read-only,
consent-gated (Personal MiniMind email-crawl consent required), headers +
OTP-scrubbed snippets only. Attach the email address as the key's hint
when saving so Ghost knows which inbox to open.

### Browser password import (CSV or direct)

Connections → Import Browser Passwords. Two paths, same per-row mapping UI
(save as API key / app password / skip):

- **CSV**: export from Chrome/Brave Settings → Passwords → Export, paste
  the text, preview, commit. Delete the CSV after (Ghost offers guidance).
- **Direct**: tick the consent checkbox to read this machine's Chromium
  login store (Chrome/Brave/Edge, Windows-only v1, DPAPI). Nothing leaves
  the computer; the temp DB copy is shredded after reading. Firefox and
  non-Windows: use CSV.

Google rows in a CSV hold *account* passwords, which Google rejects over
IMAP/SMTP — Ghost suggests skipping them and points at OAuth or a fresh
app password instead. Mail-provider rows suggest the app-password kind.
