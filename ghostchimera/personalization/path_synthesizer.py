"""Synthesize Ghost Chimera configuration from a user-selected path."""

from __future__ import annotations

from typing import Any

from .role_profiles import get_role_profile

_SENSITIVE_SOURCE_SCOPES = {
    "local_machine",
    "email",
    "calendar_exports",
    "approved_integrations",
    "organization_repositories",
    "campaign_assets",
}

_OPEN_SOURCE_SCOPES = {
    "github_public_repositories",
    "approved_public_sources",
    "license_allowed_external_sources",
}


def _training_pipeline(training_mode: str) -> list[str]:
    pipeline = ["local memory RAG", "operator preference capture"]
    if training_mode == "dataset_generation":
        pipeline.append("MiniMind dataset generation")
    elif training_mode == "local_fine_tuning":
        pipeline.extend(["MiniMind dataset generation", "local fine-tuning handoff"])
    return pipeline


def synthesize_path(profile_id: str, preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve role, source, learning, dashboard, and proxy policy for a Ghost path."""

    preferences = preferences or {}
    profile = get_role_profile(profile_id)
    training_mode = str(preferences.get("training_mode") or "rag-first")
    approval_level = str(preferences.get("approval_level") or "supervised")
    external_training = training_mode in {"dataset_generation", "local_fine_tuning"}
    uses_public_github = "github_public_repositories" in profile.source_scopes
    uses_sensitive_sources = bool(set(profile.source_scopes) & _SENSITIVE_SOURCE_SCOPES)
    uses_open_source_scopes = bool(set(profile.source_scopes) & _OPEN_SOURCE_SCOPES)
    dataset_mode_selected = training_mode in {"dataset_generation", "local_fine_tuning"}
    rag_mode_selected = training_mode == "rag-first"
    will_scrape_open_source_materials = uses_open_source_scopes and (rag_mode_selected or dataset_mode_selected)
    can_generate_dataset = "dataset_generation" in set(profile.learning_modes)
    will_generate_open_source_dataset = uses_open_source_scopes and dataset_mode_selected and can_generate_dataset
    confirmation = (
        "Selected path can use approved open-source materials and convert them into MiniMind datasets."
        if will_generate_open_source_dataset
        else (
            "Selected path can read approved open-source materials via RAG, but dataset generation mode is not enabled."
            if uses_open_source_scopes
            else "Selected path does not include open-source scraping scopes by default."
        )
    )
    return {
        "role": profile.to_dict(),
        "dashboard_tabs": list(profile.dashboard_tabs),
        "ghost_blueprint": {
            "concept": "personalized AI operator proxy",
            "role": profile.name,
            "becomes": profile.description,
            "operator_outcomes": list(profile.operator_outcomes),
            "learns_from": list(profile.personalization_sources),
            "can_operate": list(profile.tool_domains),
            "training_pipeline": _training_pipeline(training_mode),
            "handoff_contract": "act only through approved tools, consented sources, and configured autonomy policy",
        },
        "learning_strategy": {
            "default_mode": training_mode,
            "allowed_modes": list(profile.learning_modes),
            "external_training_requires_license_metadata": uses_public_github or external_training,
            "rag_first": training_mode == "rag-first",
        },
        "source_policy": {
            "scopes": list(profile.source_scopes),
            "license_check_required": uses_public_github,
            "record_commit_sha": uses_public_github,
            "rag_allowed_before_fine_tuning": True,
            "unknown_license_training_allowed": False,
        },
        "tool_policy": {
            "approval_level": approval_level,
            "push_requires_approval": True,
            "destructive_actions_require_approval": True,
            "admin_controls_required": profile.id in {"ai-engineer-proxy", "enterprise-operator"}
            or uses_sensitive_sources,
        },
        "proxy_policy": {
            "disclosure_required": profile.requires_disclosure,
            "allowed_claim": "authorized Ghost Chimera operator proxy",
            "blocked_claim": "undisclosed human impersonation",
        },
        "minimind_intake": {
            "open_source_scopes_enabled": uses_open_source_scopes,
            "dataset_mode_selected": dataset_mode_selected,
            "dataset_generation_supported": can_generate_dataset,
            "will_scrape_open_source_materials": will_scrape_open_source_materials,
            "will_generate_open_source_dataset": will_generate_open_source_dataset,
            "confirmation": confirmation,
        },
        "eval_suites": list(profile.eval_suites),
    }
