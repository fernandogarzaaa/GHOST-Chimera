# Unrestricted Host Execution

Ghost Chimera defaults to sandboxed execution. Unrestricted Host Execution is an explicit admin mode for trusted local operators who want Ghost to run host commands and apply source patches from the Console.

This mode is intentionally separate from the normal runtime:

- It is off by default.
- It requires the exact confirmation phrase `I ACCEPT HOST EXECUTION RISK`.
- It writes local audit artifacts for command runs and self-edits.
- Self-edits write requested, applied, and revert patches.
- It only mutates files under the configured allowed root.
- API responses redact confirmation phrases and secret-like fields.

Use this mode only on machines and repositories where you can review diffs and revert changes. Keep it disabled for shared machines, untrusted prompts, or production hosts without isolation.

Remote outbound messaging is separate. Configure a Remote Control channel, write-only credentials, and a default reply target before expecting Ghost to send messages. Without a configured target, Ghost should record local message intent instead of claiming that a real message was sent.

This feature exists to make self-evolution real and auditable: Ghost can apply a concrete patch through its own Console API instead of relying on an operator to edit files manually.
