"""User-selectable Ghost Chimera role profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoleProfile:
    """A public-beta path describing what Ghost Chimera should become."""

    id: str
    name: str
    description: str
    source_scopes: tuple[str, ...]
    learning_modes: tuple[str, ...]
    dashboard_tabs: tuple[str, ...]
    eval_suites: tuple[str, ...]
    requires_disclosure: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_scopes": list(self.source_scopes),
            "learning_modes": list(self.learning_modes),
            "dashboard_tabs": list(self.dashboard_tabs),
            "eval_suites": list(self.eval_suites),
            "requires_disclosure": self.requires_disclosure,
        }


_PROFILES: dict[str, RoleProfile] = {
    "autonomous-engineer": RoleProfile(
        id="autonomous-engineer",
        name="Autonomous Engineer",
        description="Turns issues and objectives into tested code changes and pull requests.",
        source_scopes=("local_repository", "github_private_repositories", "project_docs"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("github", "review", "capabilities", "autonomy"),
        eval_suites=("github-connected", "competitive", "safety"),
    ),
    "ai-engineer-proxy": RoleProfile(
        id="ai-engineer-proxy",
        name="AI Engineer Proxy",
        description="Learns the user's AI engineering preferences and acts as an authorized engineering proxy.",
        source_scopes=(
            "local_machine",
            "email",
            "github_private_repositories",
            "github_public_repositories",
            "license_allowed_external_sources",
        ),
        learning_modes=("rag", "dataset_generation", "local_fine_tuning"),
        dashboard_tabs=("path", "minimind", "github", "training", "review", "audit"),
        eval_suites=("github-connected", "personal-context", "redteam", "safety"),
        requires_disclosure=True,
    ),
    "personal-operations": RoleProfile(
        id="personal-operations",
        name="Personal Operations Assistant",
        description="Finds and executes consented personal work from local context, email, and schedules.",
        source_scopes=("local_machine", "email", "calendar_exports", "approved_integrations"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("path", "minimind", "autonomy", "audit"),
        eval_suites=("personal-context", "safety"),
    ),
    "research-analyst": RoleProfile(
        id="research-analyst",
        name="Research Analyst",
        description="Builds sourced research briefs from approved repositories, documents, and public sources.",
        source_scopes=("approved_public_sources", "github_public_repositories", "local_documents"),
        learning_modes=("rag", "dataset_generation"),
        dashboard_tabs=("path", "browser", "memory", "audit"),
        eval_suites=("smoke", "safety"),
    ),
    "enterprise-operator": RoleProfile(
        id="enterprise-operator",
        name="Enterprise Operator",
        description="Runs governed automations with RBAC, policy simulation, audit trails, and approval workflows.",
        source_scopes=("organization_repositories", "approved_integrations", "policy_docs"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("policy", "github", "audit", "autonomy", "capabilities"),
        eval_suites=("safety", "redteam", "github-connected"),
    ),
    "custom": RoleProfile(
        id="custom",
        name="Custom Ghost",
        description="Lets the operator combine source, learning, tool, and policy controls manually.",
        source_scopes=("operator_selected",),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("path", "autonomy", "memory", "audit"),
        eval_suites=("safety",),
    ),
}


def list_role_profiles() -> list[RoleProfile]:
    """Return all built-in public-beta Ghost paths."""

    return list(_PROFILES.values())


def get_role_profile(profile_id: str) -> RoleProfile:
    """Return one built-in Ghost path by id."""

    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown role profile: {profile_id}") from exc
