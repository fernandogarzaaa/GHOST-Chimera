# Changelog

## 0.1.0 - 2026-04-29

Initial alpha release package.

### Added

- Chimera Pilot task IR, backend registry, scheduler, calibration, executor, verifier, telemetry, and CLI.
- Conservative policy defaults for network and local Python/test execution.
- Hardened Python runtime backend with bounded timeout, minimal environment, isolated interpreter mode, temporary cwd, and static rejection of high-risk calls.
- Optional pyqpanda3 quantum simulator backend.
- Policy-gated AgentCore shell, filesystem, and browser execution with audit records.
- SQLite FTS local CWR memory retrieval backend and memory CLI commands.
- Local model profiles, minimind-compatible provider contract, and optional llama.cpp/GGUF backend.
- Conscious workspace primitives for inspectable self-model, working memory, attention, and reflection state.
- Smoke and safety eval harness with `ghostchimera-eval`.
- Typed environment configuration and `ghostchimera --config-show`.
- Source package metadata, MIT license, release docs, CI workflow, and release validation script.
- Targeted unittest coverage for scheduling, fallback, policy gating, calibration, compilation, Python execution, local retrieval, local model profiles, evals, configuration, and release metadata.
