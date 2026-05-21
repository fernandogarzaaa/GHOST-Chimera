# Capability Admission

Capability Admission is Ghost Chimera's local review gate for anything that can
change the operator's effective power: models, MCP servers, skills, RAG sources,
config changes, and built-in or external tools.

The goal is simple: discovery can recommend, but activation requires review.

## What It Does

- Records proposed capabilities with provenance, risk level, requested
  permissions, and redacted metadata.
- Keeps raw tokens and credential-like values out of API responses and saved
  records.
- Enforces a small lifecycle so records cannot jump straight from discovery to
  active execution.
- Feeds Operator Home and Trust Runtime production readiness.
- Works entirely from the configured Ghost state directory.

## Lifecycle

The normal path is:

```text
discovered -> inspected -> review_required -> approved -> active
```

An operator can revoke or quarantine records from safe states. Revoked records
are terminal. Quarantined records can only be revoked in this phase.

## CLI

```bash
ghostchimera capability-admission list
ghostchimera capability-admission inspect --kind model --name openrouter/demo --source openrouter --risk medium
ghostchimera capability-admission approve <record_id>
ghostchimera capability-admission activate <record_id>
ghostchimera capability-admission revoke <record_id>
ghostchimera capability-admission quarantine <record_id>
```

Use `--permission` repeatedly to document what a candidate needs:

```bash
ghostchimera capability-admission inspect --kind mcp --name docs-search --source local --risk high --permission read_docs --permission network
```

## Console

Open **Trust Runtime** in Ghost Console. The **Capability Admission** panel lets
operators add records, approve them, activate them, revoke them, or quarantine
them without editing `.env` or code.

The panel is intentionally a review surface, not an auto-enable mechanism.

Model Discovery, MCP trust, and Self-Evolution use the same gate:

- Selecting a discovered model queues a model admission record first. The model
  is saved only after that record is approved and activated.
- Approving an MCP server creates and activates the matching MCP admission
  record; revoking MCP trust revokes that record.
- Promoting a Self-Evolution candidate requires an active admission record for
  the candidate. The first promotion attempt queues review if no active record
  exists.

## Production Rules

Production readiness should remain in review when any high or critical record is
unapproved, active without review, or quarantined. This is a guardrail for
Self-Evolution, model discovery, MCP enablement, and skill intake.

Capability Admission complements MCP trust. MCP trust says whether a server is
trusted to expose tools. Capability Admission says whether a proposed capability
from any source has been reviewed and accepted.
