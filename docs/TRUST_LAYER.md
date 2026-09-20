# Trust Layer: Approvals + Audit

The agent proposes, you dispose. Connector **reads** (GET) always work
once connected. Connector **writes** (POST/PUT/DELETE/…) can require your
one-time approval via the opt-in gate.

## Single-use scoped approvals

Requesting approval binds it to **exactly one action**:
`sha256(provider + method + url + canonical body + scope)`. The approval:

- authorizes that action **once** — replay burns (second use fails);
- expires (default 10 minutes);
- fails closed on any byte difference: different destination, different
  payload, different account, expired, denied, or unknown ID.

Request: `POST /api/auth/approvals/request`
`{entity_id, provider, method, url, data, scope?, summary?}` →
`{id, digest}`. Decide (human, console UI):
`POST /api/auth/approvals/decide` `{id, approved}`. Pending:
`POST /api/auth/approvals/pending`. The executing call passes
`approval_id` to the proxy, which verifies + burns it atomically.

## Write gate (opt-in, default off)

Connections → Trust & Approvals → tick **Require approval for connector
writes**, or set `GHOSTCHIMERA_REQUIRE_WRITE_APPROVAL=1`. When on, every
non-GET proxy call without a matching unconsumed approval raises
`NeedsApproval` and is audit-logged as `proxy.write_denied`. Reads are
never gated. X stays fully blocked regardless (login-only).

## Audit trail (append-only, redacted)

`{state_dir}/audit/connector-audit.jsonl` — one JSON object per line:
`approval.requested/approved/denied/consumed`, `token.stored/refreshed/
revoked/imported`, `proxy.call`, `proxy.write_denied`. Proxy entries log
the host and action digest only — never bodies, tokens, or secrets
(redaction is structural, in `audit_trail._redact`). View the tail in
Connections → Trust & Approvals → View Audit Trail
(`POST /api/auth/audit/recent`).

## What this does not do (yet)

- OTP/reset-link filtering for mail fetch — shipped in `mail_basic`.
- Automations with run-history threads (scheduled triggers) — planned.

## Takeover mode (shipped)

Connections → Trust & Approvals → **Take over**: Ghost pauses the
stealth loop policy, blocks all live browser/desktop agent actions, and
captures nothing while you log in manually in your own browser or desktop
app. Passwords, 2FA codes, and session cookies never pass through Ghost
code — the executors themselves refuse with `TakeoverActive`, and the
loop resumes (restoring its prior enabled state) only on Release or TTL
expiry (10 minutes). Session-only: the only records are
`takeover.start/release` audit events with your stated purpose.
API: `/api/auth/takeover/start|release|status`.
