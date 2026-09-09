# Nango Integration for Ghost Chimera

Nango provides 1-click OAuth and proxied API actions so Ghost connectors
never store third-party tokens or implement refresh logic. Ghost's Python
runtime mirrors the standard Nango architecture below.

## 1. Frontend (dashboard / Ghost Console)

Install the SDK:

```bash
npm install @nangohq/frontend
```

Trigger the connection modal when the user clicks "Connect":

```javascript
import Nango from '@nangohq/frontend';

const nango = new Nango({ publicKey: process.env.NEXT_PUBLIC_NANGO_PUBLIC_KEY });

async function connectIntegration(providerConfigKey, userConnectionId) {
  try {
    // Opens the native OAuth popup for Gmail, Slack, Zendesk, etc.
    await nango.auth(providerConfigKey, userConnectionId);
    console.log('Successfully connected!');
    // Update UI status to "Connected"
  } catch (error) {
    console.error('Connection failed:', error);
  }
}

// Example usage:
// <button onClick={() => connectIntegration('google-mail', 'va_user_123')}>Connect Gmail</button>
// <button onClick={() => connectIntegration('slack', 'va_user_123')}>Connect Slack</button>
```

Against a running Ghost Console, fetch the public session bundle first
(no secrets involved — the secret key never leaves the backend):

```javascript
const res = await fetch('/api/connectors/nango/session', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ providerConfigKey: 'slack', connectionId: 'va_user_123' })
});
const { session } = await res.json();
const nango = new Nango({ publicKey: session.publicKey });
await nango.auth(session.providerConfigKey, session.connectionId);
```

## 2. Backend action trigger (Ghost Python runtime)

No npm needed — use `ghostchimera.connectors.NangoClient`:

```python
from ghostchimera.connectors import NangoClient, NangoAction

client = NangoClient()  # reads NANGO_SECRET_KEY / NANGO_BASE_URL from env

# Triggered by a Stealth worker: email on behalf of a VA connection.
client.proxy(
    method="POST",
    endpoint="/users/me/messages/send",
    provider_config_key="google-mail",
    connection_id="va_user_123",
    data={"raw": "...base64 mime..."},
)

# Or as a reusable action (pairs with the stealth agent JSON output):
action = NangoAction(provider="slack", endpoint="/chat.postMessage",
                     payload={"channel": "#ops", "text": "Update sent."})
action.execute(client, connection_id="va_user_123")
```

Connections management: `get_connection()`, `list_connections()`,
`delete_connection()`. Webhooks: point Nango at
`POST /api/connectors/nango/webhook` — deliveries are normalized and
appended to a redacted JSONL inbox (`GET /api/connectors/nango/inbox`).

## Provider catalog

| Category | Provider keys |
|---|---|
| Comms | `google-mail`, `slack` |
| Support desks | `zendesk`, `freshdesk`, `gorgias` |
| CRM | `hubspot`, `salesforce` |
| Productivity | `notion`, `airtable` |
| Workforce | `hubstaff`, `time-doctor` |
| Dev / social | `github`, `linkedin` |

Full catalog with docs links: `GET /api/connectors/providers`.
Native (non-Nango) OAuth presets for the same providers live in
`ghostchimera/connectors/oauth.py` with `TokenVault` storage for
local-first deployments that prefer direct OAuth.

## Environment

```bash
NANGO_SECRET_KEY=...     # backend only, never shipped to browsers
NANGO_PUBLIC_KEY=...     # frontend bundle via /api/connectors/nango/session
NANGO_BASE_URL=https://api.nango.dev  # default; override for self-hosted Nango
```
