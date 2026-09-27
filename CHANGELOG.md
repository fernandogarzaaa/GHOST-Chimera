# Changelog

## 0.4.0-beta - 2026-05-13

### Added

- Personal MiniMind service with persisted admin consent, system-spec capture, approved file/email bootstrap, local-memory dataset generation, and primary-model RAG handoff prompts.
- Whole-machine and email-artifact crawl consent scopes with configurable crawl roots, custom exclusions, default system/cache/dependency exclusions, and file/email limits.
- Ghost Console MiniMind tab for consent, source paths, crawl toggles, bootstrap, revocation, status, and handoff generation.
- Console API routes under `/api/console/minimind/personal/*`.
- SDK helpers: `enable_personal_minimind()`, `bootstrap_personal_minimind()`, `personal_minimind_status()`, `minimind_handoff()`, and `revoke_personal_minimind()`.
- CLI actions: `ghostchimera minimind personal-status`, `personal-consent`, `personal-bootstrap`, `personal-handoff`, and `personal-revoke`.
- Personal MiniMind privacy/operation documentation covering broad crawl behavior, email artifact discovery, local storage, and local quantized runtime options.
- Competitive capability intelligence layer with `ghostchimera capabilities`, `/api/console/capabilities`, a dashboard Capabilities tab, `docs/COMPETITIVE_CAPABILITY_MATRIX.md`, and a `competitive` eval suite.
- Automated PR/diff review with `ghostchimera review-pr`, `/api/console/review-pr`, a dashboard Review tab, deterministic security/release heuristics, Markdown/JSON output, and competitive eval coverage.

### Changed

- Bumped package metadata to `0.4.0-beta`.
- MiniMind personal bootstrap can generate training data from the full local memory corpus while preserving explicit consent gates.
- Release readiness now gates the competitive matrix against Codex, Claude Code, LangGraph, CrewAI, Hermes-style tool gateways, and OpenClaw-style local autonomy benchmarks.
- Competitive capability scoring now requires all tracked beta surfaces to be complete before the suite passes.

## 0.3.0-beta — 2026-05-12

### Added

- **Chimera Pilot v2 runtime components**: `AIAgent` multi-turn loop
  (`agent_loop.py`), `ContextCompressor` (token-budget context management),
  `MCPWrapper` (JSON-RPC MCP connector), `CredentialPool` + `ExternalAuthProvider`
  (OpenClaw-style credential injection), `ErrorClassifier` + `AutoRecoveryPlan`
  (typed recovery taxonomy), `CheckpointManager` (replay-safe run snapshots),
  `ToolsetManager` (named toolset composition), `SubagentPool`, `MixtureOfAgents`
  (MoA scoring + Jaccard strategy selection), `BatchRunner`, `CronScheduler`, and
  `GatewayServer` (WebSocket gateway with HTTP route registry).
- **Gemini / Google AI Studio integration**: `GeminiProvider` (chat, long-context,
  multi-agent history), `GeminiBackend` (REASONING + LONG_CONTEXT_DOC tasks), and
  `ModelCatalog` entries with 1 M-token context models.
- **Simulation backend** (`SimulationBackend`): kinematics trajectory planner,
  digital-twin sensor emulation, and policy-test episode runner with collision
  detection.
- **Analytics and data pipeline backend** (`AnalyticsBackend`): count/sum/avg
  group queries, simple linear-trend forecasting, z-score anomaly detection, CSV
  parsing, schema validation, and knowledge-graph triple extraction.
- **Document ingestion** (`DocumentIngester`): text chunking, CSV row ingestion,
  duplicate-safe insert via `add_document_once`.
- **DPI / LobsterTrap safety layer**: `BuiltinDPIEngine` (prompt injection,
  credential-leak, PII, exfiltration, and intent-mismatch scanning),
  `LobsterTrapProvider` wrapper, `LobsterTrapConfig.from_env()`, and
  `SecurityMonitor` with per-category event aggregation and threat summary.
- **OpenClaw modularity gaps closed** (all 10): `MediaProviders` (Gap 1),
  `ApprovalHandler` + new `HookName` entries (Gap 2), `ToolMiddlewareChain`
  (Gap 3), `Skill.check_requirements()` (Gap 4), `BackgroundService` +
  `ServiceRegistry` (Gap 5), `HttpRouteRegistry` in gateway (Gap 6),
  `PluginManifest` (Gap 7), `ExternalAuthProvider` in `CredentialPool`
  (Gap 8), `SSRFPolicy` + `PilotPolicy.allowed_hosts` (Gap 9),
  `TEXT_PROVIDERS` + `register_text_provider` (Gap 10).
- **Red-team eval suite** (`redteam`): 9 cases covering prompt injection blocking,
  credential-leak blocking, PII detection, exfiltration blocking, intent-mismatch
  flagging, benign-prompt pass-through, `LobsterTrapProvider` enforcement,
  `SecurityMonitor` aggregation, and `LobsterTrapConfig.from_env()`.
- **Track 2 eval suite** (`track2`): 8 Gemini integration cases.
- **Track 3 eval suite** (`track3`): 6 simulation/robotics cases.
- **Track 4 eval suite** (`track4`): 9 analytics and data-pipeline cases.
- **Coverage eval suite** (`coverage`): SSRF policy, approval token, material
  policy, error classifier, MoA scoring, context compressor, autonomy queue,
  checkpoint save/restore, and telemetry export format.
- **Workspace eval suite** (`workspace`): 6 cases covering workspace context
  injection into compiled tasks, no-injection on irrelevant objectives, freshness
  score and citation quality per search result, empty-index graceful degradation,
  `count()` tracking, and local-model profiles CLI.
- **Memory store depth**: `MemoryStore.search()` returns `freshness_score`
  (exponential decay from `created_at`, 30-day half-life), `citation_quality`
  (freshness × content-length heuristic), and `created_at` per result. New
  `stale_after_days` query-time filter and `count()` method.
- **Workspace feedback loop**: `OperatorWorkspaceStore.workspace_context_for_objective()`
  lightweight in-memory relevance retrieval. `ChimeraPilotKernel` accepts a
  `workspace_store` parameter and injects matching context into
  `TaskSpec.constraints["workspace_context"]` at compile time.
- **Local model bootstrap CLI**: `ghostchimera local-model` subcommand with
  `check`, `guide`, and `profiles` actions — reports system resources vs profile
  requirements, step-by-step download instructions, and fit analysis.
- **Production isolation guidance**: `docs/PRODUCTION_ISOLATION.md` — container
  and VM hardening, state backup/restore, audit log retention, secret handling,
  SSRF + network controls, and rollback runbooks.
- **Material policy** (`MaterialPolicyEngine` + `MaterialRegistry`): temporal and
  factual claim classification, adversarial prompt detection, and security-check
  trace IDs.
- **Runtime specialization warmup**: `detect_runtime_environment` and
  `warm_runtime_specialization_cache` for pre-computing llama.cpp launch manifests.
- **Async executor** (`executor_async.py`) and **parallel executor**
  (`executor_parallel.py`) with cooperative cancellation and structured
  failed-result return.
- **Calibration async** (`calibration_async.py`) with concurrent backend probing.
- New eval suites produce per-suite KPIs and release-gate summaries (all suites:
  smoke, safety, autonomy, user-journey, coverage, redteam, track2, track3,
  track4, workspace).

### Changed

- Scheduler strategy selection extended with `moa` strategy and `select_strategy`
  supporting historical success rate and uncertainty inputs.
- `PilotPolicy.autonomy_profile.cap_strategy` enforces per-profile ceilings on
  strategy selection.
- `MemoryStore.search()` signature now includes `stale_after_days` and
  `freshness_half_life_days` optional keyword arguments (backward-compatible).
- Blueprint scorecard updated: Real memory/retrieval 95%, Local model runtime 90%,
  Conscious workspace 95%, Evaluation harness 90%, Production packaging 90%.

---

## 0.2.1 — 2026-05-09

### Added

- **Workspace sync quality flags**: `ghostchimera workspace sync-memory` now
  reports low-confidence filtered records and marks stale (>30 days) and
  conflicting records with quality metadata before they enter retrieval.
- **Console operator routes**: browser console exposes evidence-add,
  reflection-add, goal-update, and workspace-sync-memory API routes in addition
  to workspace show.
- **Readiness runbook route**: `/api/console/readiness` exposes the full release
  gate checklist as a local operator runbook view.
- **Autonomy job center**: `/api/console/autonomy/jobs` records profile-gated
  preview runs; `/api/console/autonomy/schedules` manages disabled recurring
  autonomy jobs via `CronScheduler`.
- **User-journey eval suite** (`user-journey`): 6 cases covering top-level CLI
  dispatch, config/state reporting, console operator routes, workspace sync,
  workspace quality flags, and readiness runbook output.
- **Workspace sync CLI** (`ghostchimera workspace sync-memory`): promotes
  high-confidence evidence/reflections into the SQLite CWR store with provenance
  metadata and duplicate-safe inserts.
- **`ghostchimera doctor --production`**: production readiness report via
  `production_readiness_report()`.

### Fixed

- `OperatorWorkspaceStore.save()` now uses atomic rename to prevent partial writes
  on Windows.
- Desktop backend kill-switch check respects the configured stop-file path.

---

## 0.2.0 — 2026-05-06

### Added

- **Local operator console** (`ghostchimera console`): WebSocket-backed localhost
  UI for status, autonomy profile control, safe objective runs, optional browser
  workspace controls, and release-readiness checks. Supports `--host`, `--port`,
  `--http-port`, `--state-dir`, and `--no-open`.
- **Operator workspace UX**: `ghostchimera workspace show` exposes inspectable
  local self-model, working memory, attention ranking, goals, goal state, and
  uncertainty summary. `operator_workspace.json` persists under the state
  directory.
- **Conscious workspace feedback loop**: `ghostchimera workspace sync-memory`
  and `/api/console/workspace/sync-memory` promote high-confidence workspace
  evidence and reflections into the SQLite CWR store with provenance metadata
  and duplicate-safe inserts.
- **Desktop control backend** (`DesktopRuntimeBackend`): dry-run default,
  explicit live-mode opt-in, action-class filtering, kill-switch file, and
  screenshot/action-log telemetry. `ghostchimera desktop-stop` for immediate
  session halt.
- **Autonomy profiles**: `assist`, `supervised` (default), `autonomous`, and
  `generalist`. Configurable via `GHOSTCHIMERA_AUTONOMY_LEVEL` or
  `ghostchimera autonomy set`. Each profile caps strategy, budget, parallelism,
  and approval gates.
- **True autonomy desktop toggle** in Ghost Console: when enabled, default run
  uses possess-mode live desktop backend with expanded permissions.
- **Runtime state and checkpointing**: `run_id`, `attempt_id`, and `checkpoint_id`
  propagate through executor transitions; terminal-state checkpoint recording
  connected to telemetry and replay bundle generation.
- **Interrupt and cancellation**: cooperative cancellation for executor and
  parallel execution entry points; cancelled parallel runs return structured
  failed executions.
- **Adaptive scheduler learning loop**: score breakdowns, configurable weights,
  and bounded adaptation; outcome persistence wired through memory store;
  strategy selection supports `single`, `fallback_chain`, `parallel`, and `moa`.
- **Delegation and shared-state arbitration**: delegation contract primitives,
  file lease arbitration, and structured merge conflict reports in
  `ghostchimera.tool_layer.file_system`.
- **External skill discovery**: `SkillRegistry` discovers bundled + workspace
  skills from `~/.ghostchimera/skills/<name>/skill.py` (override via
  `GHOSTCHIMERA_SKILLS_DIR`). `AgentCore` accepts `skill_registry` param.
- **Production deployment mode** (`GHOSTCHIMERA_DEPLOYMENT_MODE=production`):
  blocks shell, file writes, and live desktop unless external isolation,
  security review, and human approval are all declared. `ProductionGuardrails`
  and `production_readiness_report()`.
- **Replayable observability**: replay bundles include run, decision, attempts,
  transitions, and trace hashes; telemetry exports JSON/CSV and replay-bundle
  files.
- **Ghost mode taxonomy**: `whisper`, `shadow`, `possess`, and `ghost` modes with
  per-mode policy implications.
- **CI workflow**: `.github/workflows/ci.yml` with lint, tests, build, and wheel
  smoke steps on push and pull request.
- **Dockerfile** for reproducible container deployments.

### Changed

- `AgentCore.handle_request()` now tries Chimera Pilot first, falling back to
  legacy planner/skill executor only when no backend can handle the task.
- `PilotPolicy` split from `ExecutionPolicy`: scheduler decides *where* to run,
  policy decides *whether* it is allowed — two separate boundary layers.
- `ghostchimera doctor` extended with `--production` flag for production
  readiness reporting.

---

## 0.1.0 — 2026-04-29

Initial alpha release package.

### Added

- Chimera Pilot task IR, backend registry, scheduler, calibration, executor, verifier, telemetry, and CLI.
- Conservative policy defaults for network and local Python/test execution.
- Hardened Python runtime backend with bounded timeout, minimal environment, isolated interpreter mode, temporary cwd, and static rejection of high-risk calls.
- Optional pyqpanda3 quantum simulator backend.
- Policy-gated AgentCore shell, filesystem, and browser execution with audit records.
- SQLite FTS local CWR memory retrieval backend and memory CLI commands.
- Local model profiles, minimind-compatible provider contract, and optional llama.cpp/GGUF backend.
- Ghost-native MiniMind architecture metadata, runtime inspection, attribution, and optional Transformers/PyTorch adapter.
- Conscious workspace primitives for inspectable self-model, working memory, attention, and reflection state.
- Smoke and safety eval harness with `ghostchimera-eval`.
- Typed environment configuration and `ghostchimera --config-show`.
- Source package metadata, MIT license, release docs, CI workflow, and release validation script.
- Targeted unittest coverage for scheduling, fallback, policy gating, calibration, compilation, Python execution, local retrieval, local model profiles, evals, configuration, and release metadata.
