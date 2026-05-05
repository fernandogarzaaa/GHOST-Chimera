# Ghost Chimera

Ghost Chimera is a local-first agent orchestration project. It provides a small modular agent stack plus **Chimera Pilot**, a control-plane layer for compiling objectives into task IR, scheduling backends, calibrating backend health, executing with fallback, validating results, and recording telemetry.

This repository is release-ready as a **beta release**. It is not marketed as AGI, an autonomous production agent, or a replacement for licensed quantum operating systems.

## What is included

- `agent_core` — planning, execution, memory, and skill dispatch with confidence-aware results.
- `model_layer` — provider abstraction for model calls and local model profiles.
- `tool_layer` — filesystem, browser, and shell wrappers.
- `skill_layer` — domain skills built on tools and models.
- `safety_layer` — approval gating, MaterialRegistry policy patterns, and PolicyEnforcer.
- `chimera_pilot` — task IR, resource registry, scheduler, calibration, executor, verifier, telemetry, agent loop, context compression, credential pool, toolset management, checkpoint system, cron scheduling, MCP gateway, batch orchestration, mixture-of-agents, and optional quantum-simulator bridge.
- `cognition_layer` — confidence type system, claim extraction, hallucination detection, and conscious workspace primitives.
- `memory_layer` — SQLite memory store and persistent namespace store.

## Install from source

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Optional quantum simulator support:

```bash
python -m pip install -e '.[quantum]'
```

## Validate the release

```bash
python scripts/validate_release.py
python -m pytest tests/
ruff check .
```

## CLI quickstart

Configure Ghost Chimera:

```bash
ghostchimera setup          # Interactive wizard: provider, model, gateway, safety
ghostchimera doctor         # Health check: Python, config, providers, safety
ghostchimera model          # Interactive model picker
```

Show Chimera Pilot status:

```bash
chimera-pilot status --include-deterministic-backend
```

Compile an objective without executing it:

```bash
chimera-pilot compile "retrieve memory about project"
```

Run a safe deterministic fallback task:

```bash
chimera-pilot run "retrieve memory about project" --include-deterministic-backend
```

Add and retrieve local CWR memory:

```bash
chimera-pilot memory-add --memory-db .ghostchimera-memory.sqlite3 --source project-goals --content "Ghost Chimera should use real local memory retrieval."
chimera-pilot memory-search --memory-db .ghostchimera-memory.sqlite3 "local memory retrieval"
chimera-pilot run "retrieve local memory retrieval" --memory-db .ghostchimera-memory.sqlite3 --include-deterministic-backend
```

Local Python execution is disabled by default. Enable it only for trusted code:

```bash
chimera-pilot run "python: print(2 + 3)" --allow-python
```

The main control-plane CLI exposes Chimera Pilot as well:

```bash
ghostchimera --config-show
ghostchimera --pilot-status
ghostchimera --pilot-run "python: print(2 + 3)" --allow-python
```

## Safety and policy enforcement

Ghost Chimera uses a multi-layer safety system:

### ExecutionPolicy (binary gating)

- network-requiring tasks are blocked unless explicitly allowed
- local Python and test execution are blocked unless explicitly allowed
- Python execution uses restricted environment, isolated interpreter, bounded timeout, and AST-level rejection of high-risk calls

### MaterialRegistry (policy patterns)

Seven inline policy patterns derived from OWASP MCP Top-10 and guardrails research:

| Pattern | Purpose |
|---------|---------|
| `strict_factual` | Require strong confidence and evidence-backed claims |
| `brainstorm` | Allow exploratory output with hedge/abstention tagging |
| `medical_cautious` | Conservative with strong source requirements |
| `code_review` | Balanced review policy with constrained confidence |
| `mcp_security` | Hardened against token theft, scope creep, tool poisoning |
| `prompt_injection_hardened` | Treats contextual metadata as potentially tainted |
| `research_factcheck` | Evidence-first with contradiction checks and abstention |

### PolicyEnforcer (unified gate)

Combines MaterialRegistry checks with PilotPolicy validation, returning a combined enforcement result with material scan data, pilot check status, and security warnings.

### Security defaults

- dangerous execution surfaces are documented in `SECURITY.md`
- These protections reduce accidental risk but are not a substitute for container or VM isolation

## Confidence type system

Ghost Chimera tracks confidence through the Chimera Pilot pipeline:

- **ConfidentValue** — confidence >= 0.95, no hallucination allowed
- **ConvergeValue** — confidence >= 0.6, requires multi-branch consensus
- **ProvisionalValue** — confidence >= 0.3, revocable until contradicted
- **ExploreValue** — confidence < 0.3, explicitly allows hallucination

Confidence combines via the product rule: independent uncertainties compound (`p * q`), preventing spurious high confidence from multiple moderate signals.

## Result transport

Results flow through `ResultEnvelope` with:

- **confidence** — numerical confidence (0.0-1.0)
- **provenance** — step-by-step trace of backends and scores
- **claims** — extracted claims with verification status
- **warnings** — security and confidence warnings
- **metadata** — task metadata, attempt counts, verification results

Multi-agent results merge via `merge_envelopes()` with weighted confidence combination.

## Mixture of agents

Ghost Chimera includes a parallel reasoning system:

```python
from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents, MoAConfig

moa = MixtureOfAgents(config=MoAConfig(num_agents=3))
result = moa.vote("What is the best approach to X?")
print(f"Consensus: {result.consensus_answer} ({result.consensus_pct:.1f}%)")
```

Each agent reasons independently from different perspectives; outputs are scored, contradictions are detected, and consensus is found via Jaccard similarity.

## Semantic verification

`SemanticVerifier` extends structural verification with:

- **confidence threshold** — results below min_confidence are rejected
- **provenance checks** — verifies every result has a backend trace
- **claim verification** — checks claims against material registry gold data
- **hallucination detection** — scans for confidence anomalies and attack patterns

`ClaimExtractor` parses freeform text into structured claims:

```python
from ghostchimera.chimera_pilot.claim_extractor import ClaimExtractor

extractor = ClaimExtractor()
result = extractor.extract_and_verify("Paris is the capital of France.")
# {claims: [...], claim_count: 1, factual_count: 1, security: {...}}
```

## Hallucination detection

`HallucinationDetector` scans for four hallucination indicators:

- **Branch divergence** — gate branches produce wildly different results
- **Confidence anomalies** — unexplained confidence spikes
- **Promotion violations** — Explore -> Confident without gate consensus
- **Source trace gaps** — values lacking provenance

## Local model profiles

The local model layer exposes explicit small-model profiles for constrained hardware:

- `tiny` - Qwen2.5 0.5B instruct GGUF, q4, designed for the 4 GB RAM target.
- `balanced` - SmolLM2 1.7B instruct GGUF, q4, still lightweight.
- `stronger` - Phi-3.5 mini instruct, q4, for machines with more available memory.

Set `GHOSTCHIMERA_MODEL_PROVIDER=minimind` and `MINIMIND_MODEL_PROFILE=tiny` to use the minimind-compatible provider once a matching runtime is installed.

For GGUF models, use the optional llama.cpp-compatible runtime:

```bash
chimera-pilot model-profiles
chimera-pilot status --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
chimera-pilot run "explain the current project" --local-model-path C:\models\qwen2.5-0.5b-instruct-q4.gguf --local-model-profile tiny
```

The base package does not install heavy local inference dependencies. Install a compatible `llama_cpp` runtime separately before using `--local-model-path`.

## Conscious workspace

Ghost Chimera includes inspectable consciousness-inspired state primitives:

- `SelfModel` for identity, capabilities, limits, and active goals.
- `WorkingMemory` for task evidence and reflections.
- `AttentionController` for relevance/trust/recency ranking.
- `ReflectionEngine` for post-action learning records.

These are engineering surfaces for agent state and evaluation. They are not claims of subjective experience.

## Clean-room boundary

Chimera Pilot is inspired by public systems architecture patterns from resource orchestration and quantum/classical scheduling. It does not copy proprietary Origin Pilot code, binaries, private APIs, private endpoints, UI assets, or licensed files. See `docs/CLEAN_ROOM.md`.

## Project status

Current release status: **beta**.

Appropriate uses:

- local experimentation;
- backend scheduling research;
- agent runtime prototyping;
- testable extension work;
- parallel batch orchestration;
- mixture-of-agents reasoning;
- MCP gateway and credential pooling;
- optional quantum simulator integration;
- confidence-aware result validation;
- policy-pattern security scanning.

Not appropriate yet:

- unattended production automation;
- executing untrusted code without external sandboxing;
- claims of AGI or fully autonomous operation;
- commercial/enterprise deployment without additional security review.

## Development

Run the built-in suite:

```bash
python -m unittest tests.test_chimera_pilot tests.test_release_package -v
```

Run the expanded test suite (all components):

```bash
python -m pytest tests/ -v
```

Run lint checks:

```bash
ruff check .
```

Run compile checks:

```bash
python -m compileall ghostchimera tests
```

Run the release gate:

```bash
python scripts/validate_release.py
```

Run built-in eval suites:

```bash
python -m ghostchimera.evals run --suite smoke
python -m ghostchimera.evals run --suite safety
```
