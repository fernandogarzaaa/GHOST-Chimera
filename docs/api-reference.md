# API Reference

Generated from source using AST. Modules are not imported.

## `ghostchimera.agent_core.core`

### Classes

- `AgentCore`
  - Entry point for performing natural language requests.
  - `__init__(self, llm, memory_manager, skill_manager, pilot_kernel, execution_policy, logger, skill_registry)`
  - `handle_request(self, request)`

## `ghostchimera.agent_core.executor`

### Classes

- `Executor`
  - Executes planned tasks using available skills.
  - `__init__(self, skills, memory, logger, policy)`
  - `execute(self, tasks)`

## `ghostchimera.agent_core.memory`

### Classes

- `MemoryManager`
  - Thread?safe persistent memory store.
  - `__init__(self, file_path)`
  - `add_event(self, event)`
  - `get_events(self)`
  - `search(self, query)`

## `ghostchimera.agent_core.planner`

### Classes

- `Planner`
  - Convert free text requests into structured task lists.
  - `__init__(self, llm)`
  - `plan(self, request)`

## `ghostchimera.agent_core.skill_manager`

### Classes

- `SkillManager`
  - Discover and register available skills.
  - `__init__(self, package, logger)`
  - `register(self, skill)`
  - `get_skill_for_action(self, action)`
  - `list_skills(self)`

## `ghostchimera.chimera_pilot.agent_loop`

### Classes

- `Message`
  - `to_dict(self)`
- `SessionState`
  - Persistent session carrying message history and token state.
  - `turn_count(self)`
  - `message_dicts(self)`
  - `recent_confidence(self, n)`
- `ToolCall`
  - Represents a tool invocation requested by the agent.
- `Classification`
- `ErrorClassifier`
  - Classify LLM/provider errors and recommend recovery strategies.
  - `classify(cls, error_msg, error_type)`
- `AIAgent`
  - Multi-turn agent with tool-calling loop, error recovery, and model fallback.
  - `__init__(self, kernel, model_name, max_tool_rounds, fallback_chain, system_prompt, max_tokens, router, config, session, autonomy_profile)`
  - `session(self)`
  - `active_session_id(self)`
  - `start_session(self, session_id, system_prompt)`
  - `switch_session(self, session_id)`
  - `end_session(self, reason)`
  - `run(self, user_message, tools)`
  - `run_async(self, user_message, tools)`
  - `create_task(self, kind, objective, inputs)`
  - `format_with_confidence(self, result)`
  - `status(self)`

## `ghostchimera.chimera_pilot.agent_pool`

### Classes

- `BatchResult`
  - Result of a single batch task.
  - `to_dict(self)`
- `BatchSummary`
  - Summary of a batch run.
  - `to_dict(self)`
- `BatchAgent`
  - Run multiple objectives in parallel using worker threads.
  - `__init__(self, objectives, workers, output_dir, checkpoint_interval, metadata)`
  - `run(self)`
- `ParallelAgent`
  - Lightweight parallel agent that reads objectives from a JSONL file.
  - `__init__(self, jsonl_file, workers, output_dir)`
  - `run(self)`

## `ghostchimera.chimera_pilot.autonomy`

### Functions

- `get_autonomy_profile(name)`
- `get_autonomy_profile_from_env()`
- `list_autonomy_profiles()`

### Classes

- `AutonomyProfile`
  - Runtime contract for how much initiative Ghost Chimera may take.
  - `to_dict(self)`
  - `cap_strategy(self, strategy)`

## `ghostchimera.chimera_pilot.autonomy_jobs`

### Classes

- `AutonomyJobSpec`
  - `to_dict(self)`
- `AutonomyJobResult`
  - `ok(self)`
  - `finish(self)`
  - `to_dict(self)`
- `AutonomyJobRunner`
  - Runs bounded, profile-aware autonomy jobs.
  - `__init__(self, profile, state_dir, kernel)`
  - `list_jobs()`
  - `run(self, job_name, execute)`

## `ghostchimera.chimera_pilot.autonomy_queue`

### Classes

- `AutonomyJobQueue`
  - Persist and run bounded autonomy jobs through the existing runner.
  - `__init__(self, state_dir, runner_factory)`
  - `available_jobs()`
  - `list_jobs(self)`
  - `get(self, job_id)`
  - `validate_request(self, job_name, profile, execute)`
  - `enqueue(self, job_name, profile, execute, run_now, source, schedule_id)`
  - `run(self, job_id)`
  - `run_next(self)`
  - `cancel(self, job_id)`

## `ghostchimera.chimera_pilot.backend_registry`

### Functions

- `discover_builtin_backends(backend_dir)`
  - Discover, import, and register all self-registering backend modules.
- `invalidate_check_fn_cache()`
  - Drop all cached ``check_fn`` results.

### Classes

- `BackendEntry`
  - Metadata for a single registered backend.
  - `to_dict(self)`
- `BackendRegistry`
  - Singleton registry that collects backend classes from self-registering modules.
  - `register(self, backend_class, check_fn, description)`
  - `deregister(self, backend_id)`
  - `get_all_classes(self)`
  - `is_available(self, backend_id)`
  - `get_registered_ids(self)`
  - `get_check_fns(self)`
  - `generation(self)`

## `ghostchimera.chimera_pilot.backends.__init__`

### Functions

- `discover_builtin_backends()`
  - Discover and register all self-registering backends.

## `ghostchimera.chimera_pilot.backends.analytics`

### Classes

- `AnalyticsBackend`
  - Zero-dependency analytics backend for Chimera Pilot.
  - `__init__(self)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.base`

### Classes

- `BackendCapabilities`
  - Static capabilities advertised by a backend.
  - `supports(self, task)`
- `BackendHealth`
  - Dynamic backend health and cost estimate.
- `ExecutionResult`
  - Result returned by a backend after executing one task.
- `ChimeraBackend`
  - Runtime backend protocol.
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.cwr`

### Classes

- `CWRBackend`
  - SQLite-backed retrieval backend for RAG queries.
  - `__init__(self, store)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.desktop_runtime`

### Classes

- `DesktopRuntimeBackend`
  - Executes Desktop Control tasks.
  - `__init__(self, dry_run, kill_switch_path, action_log_path, screenshot_dir, max_live_actions, max_session_seconds, clock)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.deterministic`

### Classes

- `DeterministicBackend`
  - A real backend with deterministic, configured behavior.
  - `__init__(self, backend_id, kinds, output, fail, reliability, latency_ms, supports_offline, estimated_cost_usd)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.gemini`

### Classes

- `GeminiBackend`
  - Chimera Pilot backend powered by Google Gemini.
  - `__init__(self)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.llamacpp`

### Classes

- `LlamaCppBackend`
  - Run reasoning tasks through a local GGUF model when configured.
  - `__init__(self, model_path, profile_name, n_gpu_layers, runtime_specialization, specialization_cache_dir)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.mcp`

### Classes

- `MCPBackend`
  - Execute tasks through an MCP server.
  - `__init__(self, host, port)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.pyqpanda3_backend`

### Classes

- `PyQPanda3Backend`
  - Run small local quantum simulations through pyqpanda3 when installed.
  - `is_available(cls)`
  - `__init__(self)`
  - `is_available()`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.python_runtime`

### Classes

- `PythonRuntimeBackend`
  - Execute local Python snippets and unittest discovery commands.
  - `__init__(self, default_timeout_seconds, cwd, allowed_roots, allow_imports, safe_imports)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.backends.simulation`

### Classes

- `Vec3`
  - `distance_to(self, other)`
  - `to_list(self)`
  - `from_list(cls, data)`
- `RobotState`
  - `to_dict(self)`
- `SensorReading`
  - `to_dict(self)`
- `SimulationBackend`
  - Deterministic robotics / simulation backend for Chimera Pilot.
  - `__init__(self)`
  - `probe(self)`
  - `can_run(self, task)`
  - `estimate(self, task)`
  - `execute(self, task)`

## `ghostchimera.chimera_pilot.batch_runner`

### Functions

- `run_batch(objectives, workers, output_dir, timeout)`
  - Quick batch run of multiple objectives.

### Classes

- `BatchJob`
  - A single job in a batch run.
- `BatchJobResult`
  - Result from a single batch job.
  - `to_dict(self)`
- `BatchSummary`
  - Summary of a batch run.
  - `to_dict(self)`
- `BatchRunner`
  - Multiprocessing-based batch execution of objectives.
  - `__init__(self, jobs, workers, output_dir, timeout, checkpoint_interval, config)`
  - `run(self)`
  - `run_with_checkpoints(self, output_dir)`
  - `classify_batch_errors(self, results)`

## `ghostchimera.chimera_pilot.calibration`

### Classes

- `CalibrationRecord`
- `CalibrationStore`
  - Bounded in-memory calibration history.
  - `__init__(self, max_records_per_backend)`
  - `add(self, backend_id, health)`
  - `recent(self, backend_id, window)`
  - `reliability(self, backend_id, window)`
  - `summary(self)`
- `ChimeraCalibrator`
  - Probe all registered backends and record their health.
  - `__init__(self, backends, store)`
  - `run_once(self)`

## `ghostchimera.chimera_pilot.calibration_async`

### Functions

- `calibrate_backends_parallel(backends, store, max_workers)`
  - Probe all backends concurrently and record their health.
