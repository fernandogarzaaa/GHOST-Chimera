# Always-On Agents

## Architecture

The always-on runtime lives in `ghostchimera/chimera_pilot/always_on/`. It ports
the general-purpose always-on assistant pattern onto the `official` branch:
persistent agent identities that sleep, wake on triggers, do bounded work, and
go back to sleep, all operable from the browser Ghost Console.

### Lifecycle

Every agent has an explicit lifecycle state, persisted in
`<state_dir>/always_on/identities/<agent_id>.json`:

| State | Meaning |
|-------|---------|
| `sleeping` | Idle, waiting for a trigger. The steady state. |
| `queued` | A wake request is waiting to be processed. |
| `awake` | Actively executing a wake objective. |
| `completed` | The last wake finished; recorded on the durable session. |

After a wake completes, the agent settles back to `queued` (more work waits)
or `sleeping`. The console shows the current state plus recent wake history,
so `completed` work stays visible after the agent goes back to sleep.

### Components

| Module | Purpose |
|--------|---------|
| `daemon.py` | `AlwaysOnDaemon`: worker thread, durable wake queue, schedule firing, delegation, status |
| `identity.py` | `IdentityStore`: stable `ghost-<id>` identities, atomic JSON persistence |
| `sessions.py` | `SessionStore`: durable transcripts, wake history, compaction continuity |
| `compaction.py` | `AutoCompactor`: budget-driven automatic compaction via `ContextCompressor` |
| `approvals.py` | `ApprovalStore`, `QueuedApprovalHandler`: persistent approval tickets |
| `triggers.py` | `WebhookRegistry`: named webhooks, durable objective templates |

### Wake triggers

Wake requests are durably queued in `<state_dir>/always_on/wake_queue/` as JSON
files, so a wake enqueued by the CLI, the console, or another process is never
lost, even if the daemon is not running when it is created. The daemon drains
the directory on every loop iteration.

- **Manual / CLI**: `chimera-pilot always-on wake "objective" [--source cli]`
- **Console**: the Always-On tab, or `POST /api/console/always-on/wake`
- **Schedules**: `daemon.add_schedule(name, cron_expression, objective)`. A fired
  schedule wakes the agent with `source="schedule:<name>"`. Schedules share the
  `<state_dir>/cron_jobs.json` file with the rest of the system; the daemon
  reloads it every loop iteration, so schedules created from the console or CLI
  take effect without a restart.
- **Webhooks**: `daemon.register_webhook(name, objective_template=...)`, or
  `POST /api/console/always-on/webhooks`. `{placeholders}` in the template are
  filled from the trigger payload. Template webhooks are fully durable: the
  handler is rehydrated from the persisted template on every load.

### Durable sessions

Each wake appends the objective and the result to the agent's durable session
(`<state_dir>/always_on/sessions/`). Sessions survive daemon restarts: the next
wake resumes the same transcript, wake history, and compaction continuity
state. `AutoCompactor` compacts the transcript automatically once it crosses the
configured fraction of the model context window, and the iterative summary is
carried forward so nothing is lost across compactions or restarts.

### Approval gates

While the daemon runs, it installs `QueuedApprovalHandler` as the
process-default approval handler and restores the previous handler on clean
shutdown. Policy classification comes from `safety_layer/approval.py`:

- Trusted tools are approved immediately.
- Blocked tools are denied immediately.
- Tools that require approval park a persistent ticket
  (`<state_dir>/always_on/approvals/`) and the agent pauses until an operator
  approves or denies from the console (`POST
  /api/console/always-on/approvals/{id}/{approve|deny}`) or the ticket times
  out. Timeout denies and expires the ticket. There is no automatic approval
  path.

### Bounded delegation

`daemon.delegate(objective, goals, contract=...)` fans out through the existing
`SubagentPool` with `DelegationContract` bounds (max workers, timeouts, tool
restrictions) and collects `DelegationResult` with per-subagent outcomes.

### Running the daemon

```bash
# Foreground (SIGINT/SIGTERM shut down cleanly)
chimera-pilot always-on daemon --state-dir ~/.ghostchimera --profile supervised

# Enqueue a wake (works whether or not the daemon is running)
chimera-pilot always-on wake "check the inbox and summarize"

# Inspect agents and lifecycle states
chimera-pilot always-on status
```

### Console API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/console/always-on/agents` | Agents with lifecycle, session, wake history |
| POST | `/api/console/always-on/wake` | Enqueue a wake (`objective`, `source?`, `agent_id?`) |
| GET | `/api/console/always-on/webhooks` | List webhook definitions |
| POST | `/api/console/always-on/webhooks` | Register (`name`, `objective_template`, `description?`) |
| POST | `/api/console/always-on/webhooks/{name}/trigger` | Trigger with `payload` |
| POST | `/api/console/always-on/webhooks/{name}/delete` | Unregister |
| GET | `/api/console/always-on/schedules` | List wake schedules |
| POST | `/api/console/always-on/schedules` | Create (`name`, `cron_expression`, `objective`, `enabled?`) |
| POST | `/api/console/always-on/schedules/{id}/{enable,disable,delete,run-now}` | Manage |
| GET | `/api/console/always-on/approvals` | Pending and recent tickets |
| POST | `/api/console/always-on/approvals/{id}/{approve,deny}` | Decide (`decided_by?`) |

The browser Ghost Console has an **Always-On** tab (Operate group) with agent
states, a wake box, pending approvals with approve/deny buttons, wake
schedules, and webhooks.
