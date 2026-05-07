# Subagent Delegation

## Architecture

Subagent delegation lives in `ghostchimera/chimera_pilot/subagent.py` and `ghostchimera/chimera_pilot/agent_pool.py`.

### SubagentPool

The `SubagentPool` manages a collection of parallel subagents that are delegated to handle independent sub-tasks. Key behaviors:

- **Spawn patterns**: Supports `parallel` (all subagents run simultaneously), `sequential` (subagents run one after another), and `fan-out/fan-in` (spawn N agents, merge results)
- **Task splitting**: The parent agent splits a complex objective into N independent sub-objectives using a split strategy (default: divide by topic keywords)
- **Result merging**: Uses `merge_envelopes()` from `result_envelope.py` to combine subagent results into a single `ResultEnvelope`

### Subagent Lifecycle

1. `pool.spawn(objective, task_kind)` — creates a new `AIAgent` with a sub-objective derived from the parent's objective
2. `pool.execute()` — runs all spawned subagents, collecting `ResultEnvelope` objects
3. `pool.merge()` — merges results using `merge_envelopes()`, applies consensus voting
4. `pool.shutdown()` — cleans up agent sessions

### Subagent Constraints

Subagents inherit the parent's safety policy (production mode, SSRF policy, etc.) but have their own:

- Context budget (default: 500 tokens, half of parent's budget)
- Max tool rounds (default: 6, half of parent's max)
- Timeout (default: 60s)

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/subagent.py` | SubagentPool, spawn patterns |
| `ghostchimera/chimera_pilot/agent_pool.py` | AIAgentPool, agent lifecycle |
| `ghostchimera/chimera_pilot/result_envelope.py` | merge_envelopes(), ResultEnvelope |
