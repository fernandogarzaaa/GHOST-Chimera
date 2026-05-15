# ADR-001: Chimera Pilot Scheduling Architecture

**Date:** 2026-05-15  
**Status:** Accepted

## Context

Ghost Chimera needed a unified way to orchestrate execution across heterogeneous backends:
- Local Python runtimes
- 27+ model providers (OpenAI, Anthropic, Gemini, etc.)
- Memory retrieval systems (SQLite FTS5)
- Browser/search tools
- MCP-style tool servers
- Optional quantum simulators

Without a scheduling layer, each backend would require custom integration logic, making the system brittle and hard to extend.

## Decision

Implement Chimera Pilot as a resource orchestration layer with:

1. **Task IR**: Neutral `TaskSpec` and `TaskKind` representation
2. **Rule-based compiler**: Deterministic objective to TaskSpec mapping
3. **Backend registry**: Uniform interface (`probe`, `can_run`, `estimate`, `execute`)
4. **Weighted scheduler**: Score backends by reliability, latency, cost, privacy, context fit
5. **Policy gate**: Separate "where to run" (scheduler) from "allowed to run" (policy)
6. **Fallback executor**: Automatic retry with lower-ranked backends
7. **Verifier**: Validate outputs meet expectations
8. **Telemetry**: Record all execution attempts

## Consequences

### Positive

- New backends integrate via standard interface (5 methods)
- Scheduling logic is testable and deterministic
- Policy enforcement is centralized and auditable
- Fallback provides resilience without manual retry logic
- Telemetry enables observability and debugging

### Negative

- Additional abstraction layer adds complexity
- Scheduler scoring requires tuning and calibration
- Task IR may not capture all backend-specific nuances
- Performance overhead from scoring and verification

### Neutral

- Backends must implement standard interface (migration cost for existing code)
- Compiler rules need maintenance as new patterns emerge

## Alternatives Considered

### Alternative 1: Direct Backend Selection

Let callers choose backends explicitly (e.g., `run_with_openai()`, `run_with_local()`).

**Rejected because:**
- No automatic fallback
- Duplicated policy enforcement across backends
- Hard to add new backends without changing call sites

### Alternative 2: LangChain-style Chains

Use sequential chains with manual fallback configuration.

**Rejected because:**
- Less flexible for parallel/MoA strategies
- Harder to inject policy gates
- Telemetry would be fragmented

### Alternative 3: Kubernetes-style Pod Scheduling

Full resource manager with node affinity, taints, tolerations.

**Rejected because:**
- Over-engineered for local-first use case
- Adds operational complexity
- Doesn't fit single-machine deployment model

## References

- `docs/ARCHITECTURE.md` - Layer architecture
- `docs/CHIMERA_PILOT.md` - Pilot usage guide
- `ghostchimera/chimera_pilot/scheduler.py` - Implementation
- `tests/test_chimera_pilot.py` - Test coverage
