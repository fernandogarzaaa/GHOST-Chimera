# GHOST Chimera — SOTA Research & Improvement Report
*Generated: 2026-06-16 | Sources: 28 | Confidence: High (corroborated across multiple 2026 sources)*

## Executive Summary

GHOST Chimera's founding bets — a tiny local model (MiniMind), a "beyond-RAG" memory, gated autonomy, and a Chimera Pilot kernel that compiles objectives into tasks — are *exactly* the four areas where 2026 research has moved fastest. The good news: the architecture's instincts are correct and now have strong literature backing. The actionable news: each pillar has a concrete, published technique that is more capable than what a from-scratch implementation would produce.

The five highest-leverage moves:
1. **Serving:** standardize the local model path on **llama.cpp + GGUF Q4_K_M with 8-bit KV cache** — the documented sweet spot for 8 GB VRAM — instead of a bespoke MiniMind loader. ([TinyWeights](https://tinyweights.dev/posts/run-local-llms-low-vram-windows-gpu/), [Presenc AI](https://presenc.ai/research/local-llm-quantization-quality-benchmarks-2026))
2. **Reasoning:** adopt **test-time compute on a small reasoning model** (Qwen3-1.7B-Thinking / MobileLLM-R1) so a 1.7B model that "thinks longer" beats an 8B that answers immediately — directly serves the 4 GB/8 GB goal. ([Meta on-device 2026](https://v-chandra.github.io/on-device-llms/), [Qualcomm](https://qualcomm-ai-research.github.io/llm-reasoning-on-edge/))
3. **Memory (the "beyond-RAG" idea):** implement a **bi-temporal knowledge-graph memory with decouple-before-aggregate retrieval and sleep-time consolidation** (Zep/Graphiti + xMemory + MemoryOS patterns) on top of the existing CWR SQLite store. ([Zep](https://arxiv.org/html/2501.13956), [xMemory](https://arxiv.org/pdf/2602.02007), [Zylos](https://zylos.ai/research/2026-04-20-memory-consolidation-ai-agents))
4. **Safety:** formalize the safety layer as a **deterministic, fail-closed pre-action authorization hook** at the framework level (not prompt-based), with default-deny escalation tied to action reversibility. ([Pre-Action Authorization](https://arxiv.org/pdf/2603.20953), [NOFire](https://www.nofire.ai/guides/NOFire-Runtime-Policy-Patterns-2026.pdf), [permission-protocol](https://github.com/permission-protocol/governance-framework))
5. **Orchestration:** evolve Chimera Pilot's compiler into a **typed DAG with precondition/effect edges and locality-bounded repair** (GraSP/TDP/GraphBit) so a failed task only re-plans its descendants, not the whole objective. ([GraSP](https://arxiv.org/pdf/2604.17870), [TDP](https://arxiv.org/pdf/2601.07577), [GraphBit](https://arxiv.org/html/2605.13848))

---

## 1. Small/Edge LLM Serving & Quantization → `model_layer/providers.py`, MiniMind

**State of the art (2026):**
- **8 GB VRAM is the sweet spot** for the 7–8B class at Q4; 4–6 GB lands you in the 3–4B range. The first knob when OOMing is context length, the second is KV-cache quantization. ([TinyWeights](https://tinyweights.dev/posts/run-local-llms-low-vram-windows-gpu/))
- **Q4_K_M is the default for a reason** — 1–3% perplexity loss vs FP16, ~4× memory savings; Q5/Q6 give <1% recovery at real memory cost. Never go below Q3 for reasoning. ([Presenc AI](https://presenc.ai/research/local-llm-quantization-quality-benchmarks-2026), [Chaos and Order](https://www.youngju.dev/blog/llm/2026-03-06-llm-quantization-gptq-awq-gguf-comparison.en))
- **Format follows runtime, not the reverse.** GGUF = llama.cpp/Ollama (CPU+consumer GPU, single file, every backend). AWQ+Marlin = vLLM on NVIDIA for multi-user serving. Mixing ecosystems (e.g. GGUF in vLLM = 93 t/s, 958 ms TTFT) is the canonical "don't do this." ([The AI Engineer](https://theaiengineer.substack.com/p/quantization-in-practice-gptq-vs), [RunLocalAI](https://www.runlocalai.co/systems/quantization-formats))
- **KV-cache quantization is the highest-impact single flag** for tight VRAM: `--cache-type-k q8_0 --cache-type-v q8_0` halves cache with negligible quality loss. INT4 cache cuts 75%. TurboQuant (ICLR 2026, Hadamard+QJL) reaches 3-bit cache with near-zero loss → 128K context on consumer cards. ([MortalApps](https://mortalapps.com/blog/kv-cache-explained/))

**Recommendations (mapped):**
- **[P0]** Make the **default local provider a llama.cpp/GGUF backend** behind the existing `ModelProvider` interface. Ship a Q4_K_M default with `n_gpu_layers=999`, `ctx_size=4096–8192`, and **8-bit KV cache on by default**. This is a concrete contract (model loading, quantization, device policy, context budget, streaming, fallback) — the exact gap flagged in the genesis review for the MiniMind provider.
- **[P1]** Keep MiniMind as a *specialization* (personal fine-tune / draft model), not the serving substrate. Treat the 4 GB target as "3–4B-class GGUF Q4_K_M + 2K–4K context"; reserve 7–8B for the 8 GB tier.
- **[P2]** Add a VRAM-aware auto-tuner: detect free VRAM, then pick {model size, quant level, ctx, KV-cache bits} from a lookup table rather than failing on OOM.

## 2. Agent Memory & Retrieval "Beyond RAG" → `memory_layer` (CWR SQLite), `compiler.py` RAG_QUERY

This is GHOST's signature "something more powerful than RAG" goal — and it's the most mature research area of the five.

**State of the art (2026):**
- **Graph-based memory is the 2025–2026 frontier**: move from a passive log/vector store to a *structured topological model of experience* that encodes relations, hierarchy, and causal/temporal dependencies. Plain memory is just a degenerate graph. ([Graph Agent Memory survey](https://arxiv.org/pdf/2602.05665))
- **Bi-temporal knowledge graph (Zep/Graphiti):** every fact is an edge with four timestamps (created/expired, valid/invalid), so "I started my job two weeks ago" is handled without rewriting history. Three tiers: episodes → semantic entities → communities (GraphRAG-style). This is the production-proven design. ([Zep](https://arxiv.org/html/2501.13956))
- **Decouple-before-aggregate (xMemory):** decompose logs into atomic evidence units first, then aggregate into revisable groups; retrieve coarse→fine, expanding to raw messages only when needed. ([xMemory](https://arxiv.org/pdf/2602.02007))
- **Unifying theory:** every hierarchical memory system = three operators **(α extraction, C coarsening, τ traversal)**; representatives sit on a self-sufficiency spectrum that dictates retrieval strategy. A clean blueprint to build against rather than ad-hoc. ([Hierarchical Memory Theory](https://www.arxiv.org/pdf/2603.21564))
- **Consolidation = "sleep":** significance-gated reflection (Generative Agents), heat-score promotion across hot/warm/cold tiers (MemoryOS: +49% F1 over flat storage on LoCoMo), and async sleep-time compute (Letta) all outperform flat append. ([Zylos](https://zylos.ai/research/2026-04-20-memory-consolidation-ai-agents))
- **Active retrieval:** the newest work treats retrieval as *reconstruction* — reasoning over intermediate evidence rather than fixed top-k. ([Memory is Reconstructed](https://arxiv.org/html/2606.06036v1))

**Recommendations (mapped):**
- **[P0]** Replace "RAG is only a task label" by wiring `TaskKind.RAG_QUERY` to a real retriever over the CWR store. Minimum viable: episodic buffer → semantic entities, recency+importance+relevance scoring (the workspace already promotes "high-confidence evidence" — extend it).
- **[P1]** Add a **bi-temporal layer** to CWR: store `valid_from/valid_to` + `recorded_at/expired_at` per fact so Ghost's beliefs about the user can change over time without losing provenance. This *is* the "beyond-RAG" differentiator and pairs naturally with capability-admission audit trails.
- **[P1]** Implement **sleep-time consolidation** as a scheduled CronScheduler job (GHOST already has one): cluster recent evidence, synthesize reflections, promote by heat score, expire stale edges. This reuses existing autonomy-job infra.
- **[P2]** Adopt **coarse→fine (decouple-before-aggregate) retrieval** under a token budget — critical because small local models suffer "context rot" badly (effective reasoning <10K for a 1.7B model).

## 3. Autonomous Agent Safety & Capability Gating → `safety_layer`, `capability_admission.py`, trust runtime

GHOST's "earn capabilities via eval gates / profile-gated autonomy" maps almost 1:1 onto 2026's strongest safety consensus.

**State of the art (2026):**
- **Prompt guardrails fail ~26.7% under adversarial conditions; runtime fail-closed policy fails 0%.** Enforcement must be a *structural boundary*, not an instruction. ([NOFire](https://www.nofire.ai/guides/NOFire-Runtime-Policy-Patterns-2026.pdf))
- **Pre-action authorization** = a blocking hook before *every* tool call, at the framework level so prompt injection can't bypass it. Four complementary layers: alignment → pre-action auth → sandbox (blast radius) → post-hoc eval. ([Pre-Action Authorization](https://arxiv.org/pdf/2603.20953))
- **Progressive autonomy** (AI-SDLC, CSA Agentic Trust, Knight-Columbia): agents *start at Level 0–1* and are promoted only on quantitative criteria (min task count, metric thresholds, min duration, approvals). Least-Autonomy = Least-Privilege extended. ([AI-SDLC](https://ai-sdlc.io/docs/spec/autonomy))
- **Approval mechanics:** default-deny on timeout; escalation chains; kill switch; emergency override; escalation must be faster than the action's *reversibility window* or you must block instead. ([permission-protocol](https://github.com/permission-protocol/governance-framework), [SARC](https://arxiv.org/html/2605.07728v1))
- **Capability *awareness* scoping:** "an agent cannot misuse a tool it does not know exists" — dynamically inject only the minimal tool set per task (AgentWarden Layer 1; learned via RL in Layer 2). ([AgentWarden](https://arxiv.org/pdf/2604.11839))
- Reference implementations to port from: [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) (covers OWASP Agentic Top 10; privilege rings, kill switch, Merkle audit).

**Recommendations (mapped):**
- **[P0]** Resolve the genesis P1 finding structurally: route **all** AgentCore tool calls (shell, filesystem, browser) through the same pre-action policy hook Chimera Pilot already uses — no path bypasses the safety layer. Fail-closed by default.
- **[P0]** Bind capability_admission to **reversibility**: irreversible/high-blast actions (data deletion, external comms, `shell=True`) require human approval or a passed eval; default-deny on timeout.
- **[P1]** Implement **least-capability-awareness**: the compiler injects only the tools a given objective needs into the executor's action space (cuts attack surface and small-model confusion at once).
- **[P1]** Add a **kill switch + signed/Merkle audit log** of every gated decision (the docs already aspire to an "operator-facing audit layer" — make it tamper-evident).
- **[P2]** Map gates to OWASP Agentic Top 10 / NIST AI RMF for a credible "production isolation" story.

## 4. Agent Orchestration & Planning → `chimera_pilot/compiler.py`, kernel, backends

GHOST already "compiles objectives → TaskSpecs," which is precisely the direction the field has converged on.

**State of the art (2026):**
- **Typed DAGs beat prompt-embedded plans.** Decompose into a dependency DAG; the *engine* governs transitions/state while LLMs are invoked only for narrowly-scoped, schema-validated judgment calls. Deterministic, auditable, reproducible despite stochastic LLM output. ([GraphBit](https://arxiv.org/html/2605.13848), [Runtime-Structured Decomposition](https://arxiv.org/html/2605.15425v1))
- **Locality-bounded repair** is the key efficiency win: a failure only invalidates its topological descendants — replanning drops from O(N) to O(d^h) (GraSP), and replanning stays inside one node without propagating (TDP). ([GraSP](https://arxiv.org/pdf/2604.17870), [TDP](https://arxiv.org/pdf/2601.07577))
- **Typed precondition/effect edges** on skills (GraSP) turn a flat skill set into an executable plan with causal ordering — directly applicable to GHOST's `skill_layer` + `TaskKind`.
- **Topology matters more than model choice** as models converge: route task DAGs to parallel/sequential/hierarchical/hybrid in O(|V|+|E|) (AdaptOrch, +12–23% with identical models). ([AdaptOrch](https://arxiv.org/pdf/2602.16873))
- **A small model can be the orchestrator** (ParaManager): decouple planning from solving, delegate subtasks in parallel — ideal for a local-first system. ([Agent-as-Tool](https://arxiv.org/pdf/2604.17009))
- **Search-based tool planning** (ToolTree MCTS with pre/post-execution scoring) recovers from early missteps within a call budget. ([ToolTree](https://arxiv.org/pdf/2603.12740))

**Recommendations (mapped):**
- **[P0]** Evolve the compiler output from a TaskSpec list into a **typed DAG** with explicit precondition/effect edges; execute by topological order; validate each node's output against a schema before dependents run.
- **[P1]** Add **locality-bounded repair**: on a node failure, re-plan only that node + descendants, reusing the node-scoped context (TDP's "strict locality") — huge for a small local model with a tight context budget.
- **[P1]** Make the executor a **small-model orchestrator** that delegates to typed backends (deterministic/analytics/gemini/desktop) as "tools," keeping each backend's reasoning isolated.
- **[P2]** Add topology routing (parallel vs sequential) keyed on DAG width/critical-path depth.

## 5. On-Device Reasoning → the 4 GB/8 GB AGI-aspiration core

**State of the art (2026):**
- **Test-time compute lets small models punch up:** Llama-3.2-1B with Diverse Verifier Tree Search beats the 8B; 3B beats 70B. "A 1B model that thinks longer can beat a 7B that answers immediately." This is the single most important finding for GHOST's hardware thesis. ([Meta on-device 2026](https://v-chandra.github.io/on-device-llms/))
- **Distilled reasoning models** are the practical substrate: DeepSeek-R1 distillation (1.5B–70B), **Qwen3-1.7B-Thinking-Distil** (dual Thinking/Non-Thinking in one weight set, 32K ctx, GQA, runs in 1.5–2 GB RAM on phones / <4 GB VRAM on entry GPUs), MobileLLM-R1 (sub-1B, 2–5× better reasoning than 2× larger models on mobile CPU), Phi-4-mini. ([Qwen3-1.7B](https://tokenmix.ai/blog/qwen3-1-7b-tiny-model-benchmarks-mobile-2026), [HF distil](https://huggingface.co/reaperdoesntknow/Qwen3-1.7B-Thinking-Distil))
- **On-device reasoning recipe (Qualcomm):** LoRA reasoning adapters + RL "budget forcing" to cap chain length + **parallel decoding with on-device verification** (generation-verification head reusing the KV cache) + **dynamic adapter switching** (reason only when needed). ([Qualcomm](https://qualcomm-ai-research.github.io/llm-reasoning-on-edge/))
- **Speculative decoding** is "free" on-device since you already have a small draft model — EAGLE-3, Medusa, DART (~2× on Qwen3, +30–65% over EAGLE3 on code). ([Meta](https://v-chandra.github.io/on-device-llms/), [DART](https://wiki.charleschen.ai/Coding/inference/dart-spec-dec-qwen3-14b-mcqueen))
- **Honest limits:** MoE on edge is unsolved (must store all experts); on-device fine-tuning / test-time training is immature; the reasoning ceiling forces explicit local↔cloud routing. ([Medium 2026](https://medium.com/@humourinquotes/local-llms-at-the-edge-what-actually-runs-and-what-still-doesnt-2026-b5317d92f0db))

**Recommendations (mapped):**
- **[P0]** Adopt **Qwen3-1.7B-Thinking (GGUF Q4_K_M)** as the default reasoning model for the 4 GB tier; expose a `reasoning_effort`/`thinking_budget` knob in the model layer (dual-mode weight set makes this one model).
- **[P1]** Implement **test-time compute** in the executor: best-of-N / self-consistency / verifier-scored sampling for high-value or low-confidence tasks — gate it on a confidence threshold so cheap tasks stay cheap (ties into ChimeraLang's confidence tooling).
- **[P1]** Add **speculative decoding** (draft = a smaller/quantized sibling) once on llama.cpp — near-free latency win.
- **[P2]** Build an explicit **local↔cloud router**: small local model first; escalate to a cloud model only when the on-device verifier's confidence is low. Honors local-first while respecting the small-model reasoning ceiling.

---

## Key Takeaways (prioritized backlog)

| Pri | Area | Action | Maps to |
|-----|------|--------|---------|
| P0 | Serving | llama.cpp/GGUF Q4_K_M default + 8-bit KV cache | `model_layer/providers.py` |
| P0 | Reasoning | Qwen3-1.7B-Thinking default + thinking-budget knob | `model_layer` |
| P0 | Memory | Wire `RAG_QUERY` to a real CWR retriever (scored) | `compiler.py`, `memory_layer` |
| P0 | Safety | All tool calls through one fail-closed pre-action hook | `safety_layer`, `agent_core/executor.py` |
| P0 | Orchestration | TaskSpec list → typed DAG w/ schema-validated nodes | `chimera_pilot/compiler.py` |
| P1 | Memory | Bi-temporal facts + sleep-time consolidation job | CWR + CronScheduler |
| P1 | Safety | Reversibility-gated approval + kill switch + signed audit | `capability_admission.py` |
| P1 | Orchestration | Locality-bounded repair (re-plan descendants only) | kernel |
| P1 | Reasoning | Test-time compute gated on confidence; spec decoding | executor |
| P2 | Serving | VRAM-aware auto-tuner (size/quant/ctx/KV) | model layer |
| P2 | Safety | Least-capability-awareness tool injection; OWASP/NIST map | compiler→executor |
| P2 | Reasoning | Explicit local↔cloud confidence router | model layer |

## Methodology
Searched 5 sub-questions (edge serving/quantization; memory beyond RAG; safety/capability gating; orchestration/planning; on-device reasoning) via Exa neural search, ~30 sources, prioritizing 2026 arXiv papers, official docs, and reputable practitioner benchmarks. Recommendations were mapped onto GHOST Chimera's known modules (`model_layer`, `memory_layer`/CWR, `safety_layer`, `capability_admission`, `chimera_pilot/compiler.py`, `agent_core`). Single-source claims are attributed inline; cross-corroborated claims (Q4_K_M sweet spot, graph memory frontier, fail-closed > prompt guardrails, typed-DAG orchestration, test-time compute for small models) appear in 2+ independent sources.

## Sources
1. [Unified llama.cpp Quantization Evaluation (arXiv 2601.14277)](https://arxiv.org/pdf/2601.14277)
2. [Running Local LLMs on 6–8GB GPUs 2026 — TinyWeights](https://tinyweights.dev/posts/run-local-llms-low-vram-windows-gpu/)
3. [Local LLM Quantization Quality Benchmarks 2026 — Presenc AI](https://presenc.ai/research/local-llm-quantization-quality-benchmarks-2026)
4. [KV Cache Explained — MortalApps](https://mortalapps.com/blog/kv-cache-explained/)
5. [GPTQ vs AWQ vs GGUF 2026 — The AI Engineer](https://theaiengineer.substack.com/p/quantization-in-practice-gptq-vs)
6. [Quantization formats for local AI — RunLocalAI](https://www.runlocalai.co/systems/quantization-formats)
7. [GGUF/AWQ/GPTQ practical guide — Chaos and Order](https://www.youngju.dev/blog/llm/2026-03-06-llm-quantization-gptq-awq-gguf-comparison.en)
8. [Graph-based Agent Memory survey (arXiv 2602.05665)](https://arxiv.org/pdf/2602.05665)
9. [GAM: Hierarchical Graph-based Agentic Memory (arXiv 2604.12285)](https://arxiv.org/html/2604.12285v1)
10. [Beyond RAG for Agent Memory: xMemory (arXiv 2602.02007)](https://arxiv.org/pdf/2602.02007)
11. [Memory Consolidation in Long-Running Agents — Zylos](https://zylos.ai/research/2026-04-20-memory-consolidation-ai-agents)
12. [Theory of Hierarchical Memory (arXiv 2603.21564)](https://www.arxiv.org/pdf/2603.21564)
13. [Zep: Temporal Knowledge Graph for Agent Memory (arXiv 2501.13956)](https://arxiv.org/html/2501.13956)
14. [Kumiho: Graph-Native Cognitive Memory (arXiv 2603.17244)](https://www.arxiv.org/pdf/2603.17244)
15. [Memory is Reconstructed, Not Retrieved (arXiv 2606.06036)](https://arxiv.org/html/2606.06036v1)
16. [Pre-Action Authorization for Agents (arXiv 2603.20953)](https://arxiv.org/pdf/2603.20953)
17. [microsoft/agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit)
18. [OpenAI: Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
19. [AgentWarden: Learned Capability Governance (arXiv 2604.11839)](https://arxiv.org/pdf/2604.11839)
20. [SARC: Governance-by-Architecture (arXiv 2605.07728)](https://arxiv.org/html/2605.07728v1)
21. [AI-SDLC Progressive Autonomy Spec](https://ai-sdlc.io/docs/spec/autonomy)
22. [permission-protocol/governance-framework](https://github.com/permission-protocol/governance-framework)
23. [NOFire Runtime Policy Patterns 2026](https://www.nofire.ai/guides/NOFire-Runtime-Policy-Patterns-2026.pdf)
24. [AdaptOrch: Task-Adaptive Multi-Agent Orchestration (arXiv 2602.16873)](https://arxiv.org/pdf/2602.16873)
25. [Runtime-Structured Task Decomposition (arXiv 2605.15425)](https://arxiv.org/html/2605.15425v1)
26. [Task-Decoupled Planning / TDP (arXiv 2601.07577)](https://arxiv.org/pdf/2601.07577)
27. [Agent-as-Tool / ParaManager (arXiv 2604.17009)](https://arxiv.org/pdf/2604.17009)
28. [GraSP: Graph-Structured Skill Compositions (arXiv 2604.17870)](https://arxiv.org/pdf/2604.17870)
29. [ToolTree: MCTS Tool Planning (arXiv 2603.12740)](https://arxiv.org/pdf/2603.12740)
30. [GraphBit: Non-Linear Agent Orchestration (arXiv 2605.13848)](https://arxiv.org/html/2605.13848)
31. [On-Device LLMs: State of the Union 2026 — Meta/Vikas Chandra](https://v-chandra.github.io/on-device-llms/)
32. [Efficient Reasoning on the Edge — Qualcomm AI Research](https://qualcomm-ai-research.github.io/llm-reasoning-on-edge/)
33. [Local LLMs at the Edge 2026 — Medium](https://medium.com/@humourinquotes/local-llms-at-the-edge-what-actually-runs-and-what-still-doesnt-2026-b5317d92f0db)
34. [Qwen3-1.7B benchmarks & mobile — TokenMix](https://tokenmix.ai/blog/qwen3-1-7b-tiny-model-benchmarks-mobile-2026)
35. [Qwen3-1.7B-Thinking-Distil — Hugging Face](https://huggingface.co/reaperdoesntknow/Qwen3-1.7B-Thinking-Distil)
