# Dependency Graph

Package: `ghostchimera`
Modules: 158

## `ghostchimera.__init__`
- No internal imports

## `ghostchimera.__main__`
- `.control_plane.cli`

## `ghostchimera.agent_core.__init__`
- `.core`

## `ghostchimera.agent_core.core`
- `..chimera_pilot`
- `..cognition_layer.reasoning`
- `..cognition_layer.workspace`
- `..model_layer.llm`
- `..safety_layer.gating`
- `..skill_layer.registry`
- `.executor`
- `.memory`
- `.planner`
- `.skill_manager`

## `ghostchimera.agent_core.executor`
- `..safety_layer.audit`
- `..safety_layer.gating`
- `.memory`
- `.skill_manager`

## `ghostchimera.agent_core.memory`
- No internal imports

## `ghostchimera.agent_core.planner`
- `..model_layer.llm`

## `ghostchimera.agent_core.skill_manager`
- `..skill_layer.base`

## `ghostchimera.chimera_pilot.__init__`
- `.agent_pool`
- `.autonomy`
- `.backend_registry`
- `.calibration_async`
- `.claim_extractor`
- `.compiler`
- `.executor`
- `.executor_async`
- `.executor_parallel`
- `.hooks`
- `.kernel`
- `.plugin_manifest`
- `.policy`
- `.resource_registry`
- `.result_envelope`
- `.scheduler`
- `.semantic_verifier`
- `.service_registry`
- `.task_ir`
- `.tool_middleware`

## `ghostchimera.chimera_pilot.agent_loop`
- `..cognition_layer.confidence`
- `..cognition_layer.workspace`
- `..config`
- `..logging_config`
- `..model_layer.router`
- `..safety_layer.approval`
- `.autonomy`
- `.hooks`
- `.kernel`
- `.result_envelope`
- `.task_ir`
- `.telemetry`
- `.tool_middleware`

## `ghostchimera.chimera_pilot.agent_pool`
- `..agent_core.core`

## `ghostchimera.chimera_pilot.autonomy`
- No internal imports

## `ghostchimera.chimera_pilot.autonomy_jobs`
- `..model_layer.minimind_lifecycle`
- `.autonomy`
- `.kernel`

## `ghostchimera.chimera_pilot.autonomy_queue`
- `..config`
- `.autonomy`
- `.autonomy_jobs`

## `ghostchimera.chimera_pilot.backend_registry`
- `ghostchimera.chimera_pilot.backend_registry`

## `ghostchimera.chimera_pilot.backends.__init__`
- `.analytics`
- `.base`
- `.cwr`
- `.desktop_runtime`
- `.deterministic`
- `.gemini`
- `.llamacpp`
- `.mcp`
- `.pyqpanda3_backend`
- `.python_runtime`
- `.simulation`
- `ghostchimera.chimera_pilot.backend_registry`

## `ghostchimera.chimera_pilot.backends.analytics`
- `...logging_config`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.base`
- `..task_ir`

## `ghostchimera.chimera_pilot.backends.cwr`
- `...logging_config`
- `...memory_layer.store`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.desktop_runtime`
- `..desktop_adapter`
- `..desktop_policy`
- `..desktop_targeting`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.deterministic`
- `...logging_config`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.gemini`
- `...logging_config`
- `...model_layer.gemini_provider`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.llamacpp`
- `...logging_config`
- `...model_layer.llamacpp_runtime`
- `...model_layer.local_profiles`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.mcp`
- `..backends.base`
- `..task_ir`
- `ghostchimera.mcp.client`

## `ghostchimera.chimera_pilot.backends.pyqpanda3_backend`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.python_runtime`
- `...logging_config`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.backends.simulation`
- `...logging_config`
- `..task_ir`
- `.base`

## `ghostchimera.chimera_pilot.batch_runner`
- `..agent_core.core`
- `..chimera_pilot.error_classifier`
- `..chimera_pilot.task_ir`
- `..config`
- `..logging_config`

## `ghostchimera.chimera_pilot.calibration`
- `.backends.base`

## `ghostchimera.chimera_pilot.calibration_async`
- `.backends.base`
- `.calibration`

## `ghostchimera.chimera_pilot.capability_intelligence`
- No internal imports

## `ghostchimera.chimera_pilot.checkpoint`
- `..agent_core.core`
- `..config`
- `..logging_config`

## `ghostchimera.chimera_pilot.claim_extractor`
- `..safety_layer.material_policy`

## `ghostchimera.chimera_pilot.cli`
- `..memory_layer.store`
- `..model_layer.local_profiles`
- `..model_layer.runtime_specialization`
- `.autonomy`
- `.desktop_policy`
- `.kernel`

## `ghostchimera.chimera_pilot.compiler`
- `.desktop_policy`
- `.desktop_targeting`
- `.schema`
- `.task_ir`

## `ghostchimera.chimera_pilot.context_compressor`
- `..logging_config`
- `.telemetry`

## `ghostchimera.chimera_pilot.credential_pool`
- `..config`
- `..logging_config`
- `..model_layer.auth_profiles`
- `..model_layer.providers`

## `ghostchimera.chimera_pilot.cron_scheduler`
- `..agent_core.core`
- `..chimera_pilot.task_ir`
- `..config`
- `..logging_config`
- `.service_registry`

## `ghostchimera.chimera_pilot.desktop_adapter`
- No internal imports

## `ghostchimera.chimera_pilot.desktop_policy`
- No internal imports

## `ghostchimera.chimera_pilot.desktop_targeting`
- No internal imports

## `ghostchimera.chimera_pilot.error_classifier`
- `..logging_config`

## `ghostchimera.chimera_pilot.executor`
- `..logging_config`
- `.backends.base`
- `.hooks`
- `.policy`
- `.result_envelope`
- `.scheduler`
- `.schema`
- `.semantic_verifier`
- `.task_ir`
- `.telemetry`
- `.verifier`

## `ghostchimera.chimera_pilot.executor_async`
- `.executor`
- `.policy`
- `.scheduler`
- `.task_ir`
- `.telemetry`

## `ghostchimera.chimera_pilot.executor_parallel`
- `.backends.base`
- `.executor`
- `.policy`
- `.scheduler`
- `.task_ir`
- `.telemetry`

## `ghostchimera.chimera_pilot.gateway_server`
- `..chimera_pilot.agent_loop`
- `..chimera_pilot.checkpoint`
- `..chimera_pilot.credential_pool`
- `..chimera_pilot.toolsets`
- `..config`
- `..logging_config`
- `.service_registry`

## `ghostchimera.chimera_pilot.hooks`
- `..logging_config`

## `ghostchimera.chimera_pilot.kernel`
- `..cognition_layer.workspace_state`
- `..logging_config`
- `..memory_layer.store`
- `..personalization.context_provider`
- `..safety_layer.material_policy`
- `..safety_layer.production`
- `.autonomy`
- `.backends.cwr`
- `.backends.desktop_runtime`
- `.backends.deterministic`
- `.backends.llamacpp`
- `.backends.pyqpanda3_backend`
- `.backends.python_runtime`
- `.calibration`
- `.compiler`
- `.executor`
- `.executor_parallel`
- `.hooks`
- `.policy`
- `.resource_registry`
- `.scheduler`
- `.task_ir`
- `.telemetry`

## `ghostchimera.chimera_pilot.mcp_wrapper`
- `..logging_config`

## `ghostchimera.chimera_pilot.mixture_of_agents`
- `..config`
- `..logging_config`
- `..model_layer.router`
- `.agent_loop`
- `.context_compressor`
- `.credential_pool`
- `.error_classifier`
- `.result_envelope`

## `ghostchimera.chimera_pilot.plugin_manifest`
- `..logging_config`

## `ghostchimera.chimera_pilot.policy`
- `..safety_layer.production`
- `..safety_layer.ssrf`
- `.autonomy`
- `.desktop_policy`
- `.desktop_targeting`
- `.task_ir`

## `ghostchimera.chimera_pilot.pr_review`
- No internal imports

## `ghostchimera.chimera_pilot.resource_registry`
- `.backends.base`

## `ghostchimera.chimera_pilot.result_envelope`
- No internal imports

## `ghostchimera.chimera_pilot.scheduler`
- `..model_layer.model_catalog`
- `..safety_layer.material_policy`
- `.autonomy`
- `.backends.base`
- `.task_ir`

## `ghostchimera.chimera_pilot.schema`
- `.desktop_policy`
- `.task_ir`

## `ghostchimera.chimera_pilot.semantic_verifier`
- `..cognition_layer.hallucination`
- `..safety_layer.material_policy`
- `.backends.base`
- `.result_envelope`
- `.task_ir`

## `ghostchimera.chimera_pilot.service_registry`
- `..logging_config`

## `ghostchimera.chimera_pilot.subagent`
- `..config`
- `..logging_config`
- `.agent_loop`
- `.checkpoint`
- `.credential_pool`
- `.error_classifier`

## `ghostchimera.chimera_pilot.task_ir`
- No internal imports

## `ghostchimera.chimera_pilot.telemetry`
- No internal imports

## `ghostchimera.chimera_pilot.tool_middleware`
- `..logging_config`

## `ghostchimera.chimera_pilot.toolsets`
- `..agent_core.skill_manager`
- `..logging_config`
- `.mcp_wrapper`
- `.tool_middleware`

## `ghostchimera.chimera_pilot.verifier`
- `.backends.base`
- `.task_ir`

## `ghostchimera.cognition_layer.__init__`
- `.confidence`
- `.hallucination`
- `.reasoning`
- `.workspace`
- `.workspace_state`

## `ghostchimera.cognition_layer.confidence`
- No internal imports

## `ghostchimera.cognition_layer.hallucination`
- `.confidence`

## `ghostchimera.cognition_layer.reasoning`
- No internal imports

## `ghostchimera.cognition_layer.workspace`
- No internal imports

## `ghostchimera.cognition_layer.workspace_state`
- `..config`
- `..memory_layer.store`
- `.workspace`

## `ghostchimera.config`
- `.safety_layer.gating`

## `ghostchimera.control_plane.__init__`
- `.cli`

## `ghostchimera.control_plane.cli`
- `..agent_core.core`
- `..chimera_pilot`
- `..chimera_pilot.autonomy`
- `..chimera_pilot.autonomy_jobs`
- `..chimera_pilot.capability_intelligence`
- `..chimera_pilot.desktop_policy`
- `..chimera_pilot.pr_review`
- `..cognition_layer.workspace_state`
- `..config`
- `..integrations.github_client`
- `..integrations.github_tasks`
- `..logging_config`
- `..model_layer.minimind_beta_orchestrator`
- `..model_layer.minimind_lifecycle`
- `..model_layer.minimind_personal_agent`
- `..model_layer.minimind_runtime`
- `..model_layer.runtime_specialization`
- `..personalization.path_state`
- `..personalization.role_profiles`
- `.cli_policy`
- `.config`
- `.console`
- `.doctor`
- `.local_model_cli`
- `.model_picker`
- `.parallel_cli`
- `.setup_wizard`

## `ghostchimera.control_plane.cli_policy`
- `..safety_layer.material_policy`

## `ghostchimera.control_plane.colors`
- No internal imports

## `ghostchimera.control_plane.config`
- No internal imports

## `ghostchimera.control_plane.console`
- `..chimera_pilot`
- `..chimera_pilot.autonomy`
- `..chimera_pilot.autonomy_jobs`
- `..chimera_pilot.autonomy_queue`
- `..chimera_pilot.capability_intelligence`
- `..chimera_pilot.cron_scheduler`
- `..chimera_pilot.desktop_policy`
- `..chimera_pilot.gateway_server`
- `..chimera_pilot.pr_review`
- `..cognition_layer.workspace_state`
- `..config`
- `..integrations.github_client`
- `..integrations.github_policy`
- `..integrations.github_tasks`
- `..memory_layer.store`
- `..model_layer.minimind_lifecycle`
- `..model_layer.minimind_personal_agent`
- `..personalization.document_ingester`
- `..personalization.email_ingester`
- `..personalization.path_state`
- `..personalization.path_synthesizer`
- `..personalization.role_profiles`
- `..safety_layer.audit`
- `..safety_layer.security_monitor`
- `..skill_layer.registry`
- `..tool_layer.browser`
- `..tool_layer.browser_workspace`
- `.config`

## `ghostchimera.control_plane.doctor`
- `..safety_layer.production`
- `.colors`
- `.config`
- `ghostchimera.chimera_pilot.autonomy`
- `ghostchimera.model_layer.minimind_lifecycle`
- `ghostchimera.skill_layer.registry`

## `ghostchimera.control_plane.local_model_cli`
- `..model_layer.local_profiles`

## `ghostchimera.control_plane.model_picker`
- `.colors`
- `.config`

## `ghostchimera.control_plane.parallel_cli`
- `..chimera_pilot`
- `..chimera_pilot.agent_pool`
- `..config`
- `..logging_config`
- `.cli`

## `ghostchimera.control_plane.setup_wizard`
- `.colors`
- `.config`

## `ghostchimera.evals.__init__`
- `.runner`

## `ghostchimera.evals.__main__`
- `.runner`

## `ghostchimera.evals.runner`
- `ghostchimera.agent_core.executor`
- `ghostchimera.agent_core.memory`
- `ghostchimera.agent_core.skill_manager`
- `ghostchimera.chimera_pilot`
- `ghostchimera.chimera_pilot.autonomy`
- `ghostchimera.chimera_pilot.autonomy_jobs`
- `ghostchimera.chimera_pilot.autonomy_queue`
- `ghostchimera.chimera_pilot.backends`
- `ghostchimera.chimera_pilot.backends.analytics`
- `ghostchimera.chimera_pilot.backends.gemini`
- `ghostchimera.chimera_pilot.backends.simulation`
- `ghostchimera.chimera_pilot.capability_intelligence`
- `ghostchimera.chimera_pilot.checkpoint`
- `ghostchimera.chimera_pilot.compiler`
- `ghostchimera.chimera_pilot.context_compressor`
- `ghostchimera.chimera_pilot.error_classifier`
- `ghostchimera.chimera_pilot.gateway_server`
- `ghostchimera.chimera_pilot.mixture_of_agents`
- `ghostchimera.chimera_pilot.scheduler`
- `ghostchimera.chimera_pilot.task_ir`
- `ghostchimera.chimera_pilot.telemetry`
- `ghostchimera.cognition_layer.workspace_state`
- `ghostchimera.control_plane.console`
- `ghostchimera.integrations.source_discovery`
- `ghostchimera.memory_layer.document_ingester`
- `ghostchimera.memory_layer.store`
- `ghostchimera.model_layer.gemini_provider`
- `ghostchimera.model_layer.lobster_trap_provider`
- `ghostchimera.model_layer.model_catalog`
- `ghostchimera.model_layer.providers`
- `ghostchimera.personalization.path_synthesizer`
- `ghostchimera.personalization.role_profiles`
- `ghostchimera.safety_layer.approval`
- `ghostchimera.safety_layer.gating`
- `ghostchimera.safety_layer.lobster_trap`
- `ghostchimera.safety_layer.material_policy`
- `ghostchimera.safety_layer.production`
- `ghostchimera.safety_layer.security_monitor`
- `ghostchimera.safety_layer.ssrf`
- `ghostchimera.tool_layer.browser_workspace`

## `ghostchimera.harness.__init__`
- `.case`
- `.runner`

## `ghostchimera.harness.__main__`
- `.case`
- `.runner`

## `ghostchimera.harness.case`
- No internal imports

## `ghostchimera.harness.runner`
- `..chimera_pilot.hooks`
- `..chimera_pilot.kernel`
- `..memory_layer.store`
- `.case`

## `ghostchimera.integrations.__init__`
- No internal imports

## `ghostchimera.integrations.github_audit`
- No internal imports

## `ghostchimera.integrations.github_ci`
- No internal imports

## `ghostchimera.integrations.github_client`
- No internal imports

## `ghostchimera.integrations.github_discovery`
- No internal imports

## `ghostchimera.integrations.github_policy`
- No internal imports

## `ghostchimera.integrations.github_review`
- `ghostchimera.chimera_pilot.pr_review`

## `ghostchimera.integrations.github_tasks`
- No internal imports

## `ghostchimera.integrations.github_worktree`
- No internal imports

## `ghostchimera.integrations.source_discovery`
- No internal imports

## `ghostchimera.logging_config`
- No internal imports

## `ghostchimera.mcp.__init__`
- No internal imports

## `ghostchimera.mcp.client`
- No internal imports

## `ghostchimera.mcp.server`
- No internal imports

## `ghostchimera.memory_layer.__init__`
- `.namespace_store`
- `.store`

## `ghostchimera.memory_layer.document_ingester`
- `.store`

## `ghostchimera.memory_layer.namespace_store`
- No internal imports

## `ghostchimera.memory_layer.store`
- No internal imports

## `ghostchimera.model_layer.__init__`
- `.auth_profiles`
- `.llm`
- `.media_providers`
- `.model_catalog`

## `ghostchimera.model_layer.auth_profiles`
- No internal imports

## `ghostchimera.model_layer.base_provider`
- No internal imports

## `ghostchimera.model_layer.gemini_provider`
- `..logging_config`
- `.auth_profiles`

## `ghostchimera.model_layer.llamacpp_runtime`
- `.local_profiles`
- `.runtime_specialization`

## `ghostchimera.model_layer.llm`
- `..logging_config`
- `.auth_profiles`
- `.providers`

## `ghostchimera.model_layer.lobster_trap_provider`
- `..logging_config`
- `..safety_layer.lobster_trap`
- `.providers`

## `ghostchimera.model_layer.local_profiles`
- No internal imports

## `ghostchimera.model_layer.media_providers`
- `..logging_config`
- `.auth_profiles`

## `ghostchimera.model_layer.minimind_beta_orchestrator`
- `..chimera_pilot.autonomy_queue`
- `..memory_layer.store`
- `.minimind_lifecycle`

## `ghostchimera.model_layer.minimind_lifecycle`
- `..memory_layer.store`
- `..personalization.document_ingester`
- `..personalization.email_ingester`
- `.local_profiles`
- `.minimind_runtime`

## `ghostchimera.model_layer.minimind_personal_agent`
- `..memory_layer.store`
- `..personalization.context_provider`
- `..personalization.document_ingester`
- `..personalization.path_state`
- `.minimind_beta_orchestrator`
- `.minimind_lifecycle`

## `ghostchimera.model_layer.minimind_runtime`
- No internal imports

## `ghostchimera.model_layer.model_catalog`
- No internal imports

## `ghostchimera.model_layer.openai_compatible_providers`
- `..logging_config`
- `.auth_profiles`
- `.base_provider`

## `ghostchimera.model_layer.providers`
- `..logging_config`
- `.auth_profiles`
- `.base_provider`
- `.gemini_provider`
- `.llamacpp_runtime`
- `.local_profiles`
- `.minimind_runtime`
- `.openai_compatible_providers`

## `ghostchimera.model_layer.router`
- `.providers`

## `ghostchimera.model_layer.runtime_specialization`
- `.local_profiles`

## `ghostchimera.personalization.__init__`
- `.context_provider`
- `.document_ingester`
- `.email_ingester`

## `ghostchimera.personalization.context_provider`
- `..logging_config`
- `..memory_layer.store`
- `..model_layer.minimind_runtime`

## `ghostchimera.personalization.document_ingester`
- `..memory_layer.store`

## `ghostchimera.personalization.email_ingester`
- `..memory_layer.store`

## `ghostchimera.personalization.path_state`
- `..control_plane.config`
- `.path_synthesizer`

## `ghostchimera.personalization.path_synthesizer`
- `.role_profiles`

## `ghostchimera.personalization.role_profiles`
- No internal imports

## `ghostchimera.safety_layer.__init__`
- `.approval`
- `.audit`
- `.gating`
- `.lobster_trap`
- `.material_policy`
- `.policy_enforcement`
- `.production`
- `.security_monitor`
- `.ssrf`

## `ghostchimera.safety_layer.approval`
- `..logging_config`

## `ghostchimera.safety_layer.audit`
- No internal imports

## `ghostchimera.safety_layer.gating`
- `.production`

## `ghostchimera.safety_layer.lobster_trap`
- `..logging_config`
- `.security_monitor`

## `ghostchimera.safety_layer.material_policy`
- No internal imports

## `ghostchimera.safety_layer.policy_enforcement`
- `..chimera_pilot.policy`
- `..chimera_pilot.task_ir`
- `.material_policy`

## `ghostchimera.safety_layer.production`
- No internal imports

## `ghostchimera.safety_layer.rate_limiter`
- No internal imports

## `ghostchimera.safety_layer.security_monitor`
- `..logging_config`

## `ghostchimera.safety_layer.ssrf`
- `..logging_config`

## `ghostchimera.sdk`
- `.chimera_pilot.executor`
- `.chimera_pilot.kernel`
- `.memory_layer.store`
- `.model_layer.minimind_lifecycle`
- `.model_layer.minimind_personal_agent`
- `.personalization.context_provider`
- `.personalization.document_ingester`
- `.personalization.email_ingester`

## `ghostchimera.skill_layer.__init__`
- `.base`
- `.browser_operator`
- `.registry`
- `.software_engineer`
- `.tech_support`

## `ghostchimera.skill_layer.base`
- No internal imports

## `ghostchimera.skill_layer.browser_operator`
- `..tool_layer.browser`
- `.base`

## `ghostchimera.skill_layer.code_search`
- `.base`

## `ghostchimera.skill_layer.registry`
- `.base`

## `ghostchimera.skill_layer.software_engineer`
- `..tool_layer.file_system`
- `..tool_layer.shell`
- `.base`

## `ghostchimera.skill_layer.tech_support`
- `..model_layer.llm`
- `.base`

## `ghostchimera.skill_layer.to_issues`
- `.base`

## `ghostchimera.tool_layer.__init__`
- `.browser`
- `.file_system`
- `.shell`

## `ghostchimera.tool_layer.browser`
- `..logging_config`
- `..safety_layer.gating`

## `ghostchimera.tool_layer.browser_workspace`
- `..logging_config`

## `ghostchimera.tool_layer.file_system`
- `..safety_layer.gating`

## `ghostchimera.tool_layer.shell`
- `..safety_layer.gating`
