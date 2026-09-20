# Automations: Describe Once, Run on Trigger

Connections → Automations. Each automation has one trigger and one action.

## Triggers

- **Schedule (cron)**: standard 5-field cron (`0 8 * * *` = 08:00 daily).
  Next run is computed at creation and after every firing.
- **Inbound email**: vault app-password key + optional sender/subject
  substring filters. The poller checks UNSEEN mail (throttled to 5-minute
  gaps per automation), fires once per message UID, and remembers seen
  UIDs so nothing double-fires.

## Actions

- **Log**: record the trigger event + instruction (detection value —
  "boss mailed about deploy at 08:12").
- **Webhook**: POST `{automation, instruction, trigger, run_id}` as JSON
  to any URL (Home Assistant, n8n, …). 20 s timeout; failures mark the
  run failed, never silently.
- **Connector write**: the run requests a single-use action approval and
  parks as `awaiting-approval`. You approve in Trust & Approvals, then
  **Execute approved** consumes it and completes the run as a child
  thread of the parked one. No approval, no execution — the trust layer
  guarantees it.

## Run history threads

Every firing appends to `automations_runs.jsonl`: trigger context,
status (`complete` / `failed` / `awaiting-approval`), summary, optional
parent link. **Continue** starts a child run carrying your note.
**Run now** fires manually regardless of schedule.

## Notifications

The `notify` preference (`console` / `audit` / `both` / `neither`) is
recorded per automation; every run writes an `automation.ran` audit
entry. Push/email delivery is a later phase.

## Operations

One daemon poll thread per state dir (starts on first automations call,
idles at 60 s). Pause/resume/delete per automation; cron next-runs
recompute on resume. Email polling needs the mailbox key present —
missing keys fail quiet (no run, no spam) until you save one.
