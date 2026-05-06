# Autonomy Capability Extraction

This note captures the reusable patterns extracted from adjacent Fernando Garza repositories on 2026-05-06. The goal is not to vendor those projects into Ghost Chimera; it is to preserve the concrete capabilities that should influence the beta autonomy layer.

## Reference Snapshot

| Repository | Commit | Useful Signals | Do Not Copy Blindly |
| --- | --- | --- | --- |
| `Project-AETHER` | `302bf09` | Local-first model routing, health checks, swarm checkpointing, local RAG, skill/config audit loops, lightweight constitutional validation. | Hardcoded paths and credentials, duplicated classes, broad research notes, root-level experiments. |
| `Project-WRAITH` | `a3ecf41` | Circadian scheduler pattern, background process supervision, data-to-training-pair pipeline shape, symbolic protocol parser. | Browser decoy/scraping behavior, absolute `D:\Project Wraith` paths, Unsloth fine-tuning stub. |
| `Project-EVO` | `ef85273` | Audit -> architect -> adversary -> coder -> tester loop, loop/circuit breakers, checkpointing, PR-first governance, dynamic test detection. | Placeholder planner rewards, simulated code edits, direct branch mutation without Ghost Chimera policy gates. |
| `OpenChimera_v1` | `9ba3230` | Autonomy job specs, operator diagnostics, MiniMind lifecycle service, preview-only self-repair, self-evolution loop guard, multi-agent consensus metrics. | AGI completion claims and heavy runtime assumptions should be reframed as beta capability profiles. |
| `appforge` | `65fc80b` | Observability -> reasoning -> action -> verification cycle, swarm CLI scripts, provider registry, dashboard/onboarding concepts, CI regression gates. | Large vendored artifacts, generated reports, long-path model caches, production claims that exceed current Ghost Chimera guarantees. |

## Extracted Capability Set

1. **Adjustable autonomy profiles**: a user-visible contract should tune budgets and orchestration posture without granting unsafe permissions.
2. **Fallback and MoA strategy ceilings**: stronger profiles can allow fallback chains, parallel task execution, and MoA-style selection; conservative profiles cap these back to single-backend execution.
3. **MiniMind/local-model posture**: profiles should select an appropriate local model profile (`tiny`, `balanced`, `stronger`) but still require explicit model/runtime availability.
4. **Preview-only self-improvement**: self-audit and repair planning can be automated before code mutation. Training and self-modification stay off by default.
5. **Governance before mutation**: high-impact actions keep human approval, production guardrails, trusted-input checks, and external isolation requirements.
6. **Verification as a loop boundary**: every autonomous run should preserve verification results, confidence, telemetry, and replay metadata before follow-on action.

## Ghost Chimera Mapping

The first implementation slice lives in `ghostchimera.chimera_pilot.autonomy` and wires into:

- `GhostChimeraConfig` via `GHOSTCHIMERA_AUTONOMY_LEVEL`.
- `PilotPolicy.to_dict()` and `ChimeraPilotKernel.status()`.
- `chimera-pilot autonomy-profiles`.
- `--autonomy-level` on Pilot status, run, and calibrate flows.
- `AIAgent` tool-loop budgets.
- Scheduler strategy ceilings.
- Kernel parallel execution when the selected profile explicitly permits it.

The profile names are:

- `assist`
- `supervised`
- `autonomous`
- `generalist`

Aliases such as `agi` and `sgi` resolve to `generalist` for operator convenience, but the profile metadata explicitly describes this as a capability profile, not AGI, consciousness, or superior intelligence.
