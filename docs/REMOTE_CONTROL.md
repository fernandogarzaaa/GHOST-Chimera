# Ghost Chimera Remote Control

Ghost Chimera includes a native remote-control layer inspired by OpenClaw and Hermes-Agent messaging patterns. It does not require either project at runtime.

Remote control is built around pairing, explicit policy, and auditability:

- Unknown senders receive a pairing challenge and no command is processed.
- Paired peers can run safe slash commands such as `/status`, `/readiness`, `/paths`, `/jobs`, `/help`, and `/stop`.
- `/run <objective>` creates a pending approval by default.
- The dashboard can enable global direct execution and then enable direct execution for specific paired admin peers.
- Direct execution is never enabled by default.
- Provider adapters for Telegram, Discord, Slack, WhatsApp, Signal, SMS, and email remain optional. The built-in webhook/test channel works without external services.

## Console Flow

1. Start Ghost Console:

   ```bash
   ghostchimera console
   ```

2. Open `http://localhost:8766/` and select **Remote Control**.

3. Create a pairing code for the sender, or use **Simulate Inbound Message** with an unknown peer to generate a pairing challenge.

4. Approve the pairing in the dashboard.

5. Run `/status` or `/readiness` from the paired peer.

6. To allow direct `/run` execution:
   - Enable **Allow paired admins to enable direct execution** in Remote Policy.
   - Enable direct execution on the specific paired peer.

7. To prepare real provider adapters, use **Adapter Configuration**:
   - Choose the channel.
   - Paste the bot/API token, webhook URL, phone number ID, or signing secret.
   - Save the channel.
   - Ghost only reports `configured`, `secret_fields_configured`, and `send_enabled`; raw values are never returned.
   - Outbound sending remains disabled until **Enable outbound sending for this channel** is checked.
   - If a `signing_secret` is configured, provider webhook endpoints require a matching HMAC SHA-256 signature in `X-Ghost-Signature`, `X-Hub-Signature-256`, or `X-Signature`.

## CLI Flow

Preview remote status:

```bash
ghostchimera remote status
```

Create a pairing code:

```bash
ghostchimera remote pair-code --channel telegram --peer admin-chat --display-name "Admin phone"
```

Simulate an inbound message:

```bash
ghostchimera remote simulate --channel webhook --peer admin-chat --text "/status"
```

Provider-shaped webhook payloads can also be posted to:

```text
POST /api/console/remote/webhook/telegram
POST /api/console/remote/webhook/discord
POST /api/console/remote/webhook/slack
POST /api/console/remote/webhook/whatsapp
POST /api/console/remote/webhook/signal
POST /api/console/remote/webhook/webhook
```

Those endpoints normalize each provider payload into the same paired command path used by the dashboard simulation. A Telegram `message.text`, Discord `content`, Slack `event.text`, WhatsApp Cloud API text message, Signal envelope message, or generic `{ "peer_id": "...", "text": "/status" }` body all become a `RemoteInboundMessage`.

Webhook signatures are optional until a channel has a saved signing secret. After that, the provider endpoint fails closed unless the raw request body matches `sha256=<hmac>` using the stored secret. The local **Simulate Inbound Message** dashboard action is intentionally unsigned so operators can test pairing and command flow without provider setup.

Every inbound response also includes a `reply_preview` object. This is a provider-shaped outbound payload preview, not a network send. It includes the method, endpoint hint, body, and whether auth is required. Raw provider tokens are never returned.

Example Telegram preview:

```json
{
  "channel": "telegram",
  "method": "POST",
  "endpoint_hint": "https://api.telegram.org/bot<TOKEN>/sendMessage",
  "auth_required": true,
  "body": {
    "chat_id": "123",
    "text": "Ghost Chimera is reachable."
  }
}
```

Enable or disable the global direct-execution policy:

```bash
ghostchimera remote policy --direct-execution
ghostchimera remote policy --no-direct-execution
```

## Safety Model

The remote layer stores local state under the Ghost Chimera state directory in `remote_control_state.json`. API responses redact secret-like fields, and command activity is written to `remote_control_events.jsonl` plus the operator timeline.

Provider credentials are stored separately in `remote_control_secrets.json`. They are write-only through the Console API:

- Leaving a field blank keeps the existing value.
- **Clear Channel Secrets** removes stored secrets for that channel.
- Status responses show only configured field names, never token values.
- Enabling outbound sending requires stored credentials and a separate channel-level toggle.
- **Send Test Reply** performs an actual outbound POST only when the channel is configured and `send_enabled` is true. Provider failures are returned as redacted status/error data.
- Provider webhook signatures are enforced only when a signing secret is stored for that channel. This keeps the default local flow low-friction while letting production adapters fail closed.

Direct execution has two gates:

1. Global policy must allow direct execution.
2. The specific paired admin peer must allow direct execution.

If either gate is closed, `/run <objective>` becomes a pending approval instead of executing.
