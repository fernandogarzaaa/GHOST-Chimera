"""Synthesize Ghost Chimera configuration from a user-selected path."""

from __future__ import annotations

from typing import Any

from .role_profiles import get_role_profile


def synthesize_path(profile_id: str, preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve role, source, learning, dashboard, and proxy policy for a Ghost path."""

    preferences = preferences or {}
    profile = get_role_profile(profile_id)
    training_mode = str(preferences.get("training_mode") or "rag-first")
    approval_level = str(preferences.get("approval_level") or "supervised")
    external_training = training_mode in {"dataset_generation", "local_fine_tuning"}
    uses_public_github = "github_public_repositories" in profile.source_scopes
    return {
        "role": profile.to_dict(),
        "dashboard_tabs": list(profile.dashboard_tabs),
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
            "admin_controls_required": profile.id in {"ai-engineer-proxy", "enterprise-operator"},
        },
        "proxy_policy": {
            "disclosure_required": profile.requires_disclosure,
            "allowed_claim": "authorized Ghost Chimera operator proxy",
            "blocked_claim": "undisclosed human impersonation",
        },
        "eval_suites": list(profile.eval_suites),
    }
