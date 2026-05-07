# Mixture of Agents Strategy

## Architecture

The Mixture of Agents (MoA) strategy lives in `ghostchimera/chimera_pilot/mixture_of_agents.py`.

### Core Pipeline

1. **Prompt Diversification**: Generates N distinct reasoning prompts from the base query using `REASONING_PROMPTS` prefixes (analytical expert, creative problem-solver, pragmatist, skeptical reviewer, domain specialist)
2. **Parallel Execution**: Each prompt is assigned to an independent `AIAgent` and executed in parallel via `ThreadPoolExecutor`
3. **Quality Scoring**: Each output is scored by `score_output()` using four metrics:
   - **Specificity** (+20 pts): Number of numeric references (dates, counts, versions)
   - **Coherence** (+20 pts): Number of logical connectors (therefore, however, consequently)
   - **Completeness** (+20 pts): Word count / 20, capped
   - **Uncertainty penalty** (-3 pts): Each hedge word (might, perhaps, unclear) reduces score
4. **Consensus Detection**: `_find_consensus()` uses pairwise Jaccard similarity to find the output with the highest average similarity to all others, marking it as the consensus answer
5. **Contradiction Detection**: `_detect_contradictions_for_text()` identifies direct negation patterns between output pairs

### Configuration

`MoAConfig` controls the strategy:

| Field | Default | Purpose |
|-------|---------|---------|
| `num_agents` | 3 | Number of parallel agents |
| `temperature` | 0.7 | Model temperature |
| `min_consensus_pct` | 60.0 | Minimum consensus threshold to stop iterating |
| `timeout` | 120.0 | Per-agent timeout in seconds |
| `voting_strategy` | majority | How to pick winner: majority, weighted, highest_quality |

### MoAResult

The `MoAResult` dataclass contains:

- `consensus_answer`: The best-consensus output
- `consensus_pct`: Percentage of agents that agreed with consensus
- `num_agreeing`: Count of agents whose output matches consensus
- `contradictions`: List of detected contradictions between agents
- `confidence`: Merged envelope confidence
- `avg_tokens`, `avg_duration`: Agent performance metrics

## Key Files

| File | Purpose |
|------|---------|
| `ghostchimera/chimera_pilot/mixture_of_agents.py` | MixtureOfAgents, MoAConfig, MoAResult |
