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
    operator_outcomes: tuple[str, ...] = ()
    personalization_sources: tuple[str, ...] = ()
    tool_domains: tuple[str, ...] = ()
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
            "operator_outcomes": list(self.operator_outcomes),
            "personalization_sources": list(self.personalization_sources),
            "tool_domains": list(self.tool_domains),
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
        operator_outcomes=("tested code changes", "pull requests", "release-gate reports"),
        personalization_sources=("local_repository", "project_docs", "engineering_preferences"),
        tool_domains=("code_execution", "github", "review", "release_validation"),
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
        operator_outcomes=("engineering proxy work", "code reviews", "agent workflow implementation"),
        personalization_sources=("local_machine", "email", "private_repositories", "public_repositories"),
        tool_domains=("code_execution", "github", "mcp", "desktop", "review"),
        requires_disclosure=True,
    ),
    "manager-operator": RoleProfile(
        id="manager-operator",
        name="Manager Operator",
        description="Coordinates decisions, follow-ups, summaries, plans, and team operations from approved work context.",
        source_scopes=("local_documents", "email", "calendar_exports", "approved_integrations", "policy_docs"),
        learning_modes=("rag", "workflow_memory", "dataset_generation"),
        dashboard_tabs=("path", "minimind", "autonomy", "audit", "memory"),
        eval_suites=("personal-context", "safety", "redteam"),
        operator_outcomes=("meeting briefs", "follow-up plans", "status summaries", "decision logs"),
        personalization_sources=("email", "calendar_exports", "team_docs", "meeting_notes", "management_preferences"),
        tool_domains=("team_coordination", "planning", "communication", "task_followup"),
    ),
    "marketing-specialist": RoleProfile(
        id="marketing-specialist",
        name="Marketing Specialist",
        description="Learns brand, audience, campaigns, and approved assets to draft, review, and coordinate marketing work.",
        source_scopes=("local_documents", "campaign_assets", "approved_public_sources", "approved_integrations"),
        learning_modes=("rag", "workflow_memory", "dataset_generation"),
        dashboard_tabs=("path", "minimind", "memory", "browser", "audit"),
        eval_suites=("personal-context", "safety"),
        operator_outcomes=("campaign briefs", "content drafts", "audience research", "brand-consistent reviews"),
        personalization_sources=("campaign_assets", "brand_guidelines", "audience_research", "content_history"),
        tool_domains=("content_operations", "research", "asset_review", "publishing_workflow"),
    ),
    "virtual-assistant": RoleProfile(
        id="virtual-assistant",
        name="Virtual Assistant",
        description="Handles consented admin, scheduling, inbox triage, reminders, and personal operations workflows.",
        source_scopes=("local_machine", "email", "calendar_exports", "approved_integrations"),
        learning_modes=("rag", "workflow_memory", "dataset_generation"),
        dashboard_tabs=("path", "minimind", "autonomy", "audit", "memory"),
        eval_suites=("personal-context", "safety", "redteam"),
        operator_outcomes=("inbox triage", "schedule prep", "reminders", "personal task execution"),
        personalization_sources=("email", "schedule_exports", "local_documents", "assistant_preferences"),
        tool_domains=("personal_admin", "calendar", "communication", "local_file_workflows"),
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
        operator_outcomes=("personal task discovery", "consented workflow execution", "local context summaries"),
        personalization_sources=("local_machine", "email", "calendar_exports", "personal_preferences"),
        tool_domains=("personal_admin", "local_file_workflows", "communication", "scheduling"),
    ),
    "research-analyst": RoleProfile(
        id="research-analyst",
        name="Research Analyst",
        description="Builds sourced research briefs from approved repositories, documents, and public sources.",
        source_scopes=("approved_public_sources", "github_public_repositories", "local_documents"),
        learning_modes=("rag", "dataset_generation"),
        dashboard_tabs=("path", "browser", "memory", "audit"),
        eval_suites=("smoke", "safety"),
        operator_outcomes=("sourced briefs", "evidence maps", "research summaries"),
        personalization_sources=("local_documents", "approved_public_sources", "research_preferences"),
        tool_domains=("research", "browser", "citation_review"),
    ),
    "enterprise-operator": RoleProfile(
        id="enterprise-operator",
        name="Enterprise Operator",
        description="Runs governed automations with RBAC, policy simulation, audit trails, and approval workflows.",
        source_scopes=("organization_repositories", "approved_integrations", "policy_docs"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("policy", "github", "audit", "autonomy", "capabilities"),
        eval_suites=("safety", "redteam", "github-connected"),
        operator_outcomes=("governed automations", "approval workflows", "audit-ready operations"),
        personalization_sources=("policy_docs", "organization_repositories", "approved_integrations"),
        tool_domains=("governance", "github", "policy_simulation", "audit"),
    ),
    "custom": RoleProfile(
        id="custom",
        name="Custom Ghost",
        description="Lets the operator combine source, learning, tool, and policy controls manually.",
        source_scopes=("operator_selected",),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("path", "autonomy", "memory", "audit"),
        eval_suites=("safety",),
        operator_outcomes=("operator-defined work",),
        personalization_sources=("operator_selected",),
        tool_domains=("operator_selected",),
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
