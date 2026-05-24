"""SaaS store contracts and dependency-free in-memory implementation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import (
    AuditEvent,
    GhostProfile,
    Membership,
    Organization,
    Role,
    SaasApproval,
    SaasRun,
    TenantSecretRef,
    UserAccount,
    Workspace,
)
from .rbac import require_permission

POSTGRES_SCHEMA_TABLES = (
    "organizations",
    "user_accounts",
    "memberships",
    "workspaces",
    "ghost_profiles",
    "tenant_secret_refs",
    "saas_runs",
    "saas_approvals",
    "audit_events",
    "worker_leases",
    "eval_baselines",
)


def build_postgres_schema_sql() -> str:
    """Return the initial Postgres schema for SaaS mode."""

    return """
CREATE TABLE IF NOT EXISTS organizations (
  org_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS user_accounts (
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  oidc_subject TEXT NOT NULL DEFAULT '',
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  membership_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  user_id TEXT NOT NULL REFERENCES user_accounts(user_id),
  role TEXT NOT NULL CHECK (role IN ('viewer','operator','admin','owner')),
  created_at DOUBLE PRECISION NOT NULL,
  UNIQUE(org_id, user_id)
);
CREATE TABLE IF NOT EXISTS workspaces (
  workspace_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  name TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS ghost_profiles (
  ghost_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  name TEXT NOT NULL,
  path_profile TEXT NOT NULL,
  approval_level TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_secret_refs (
  secret_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  provider TEXT NOT NULL,
  label TEXT NOT NULL,
  configured BOOLEAN NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS saas_runs (
  run_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  actor_user_id TEXT NOT NULL REFERENCES user_accounts(user_id),
  objective TEXT NOT NULL,
  status TEXT NOT NULL,
  approval_required BOOLEAN NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS saas_approvals (
  approval_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  run_id TEXT NOT NULL REFERENCES saas_runs(run_id),
  requested_by TEXT NOT NULL REFERENCES user_accounts(user_id),
  risk_level TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  actor_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_id TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_leases (
  lease_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  run_id TEXT NOT NULL REFERENCES saas_runs(run_id),
  worker_id TEXT NOT NULL,
  lease_until DOUBLE PRECISION NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_baselines (
  baseline_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES organizations(org_id),
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id),
  score_json TEXT NOT NULL,
  created_at DOUBLE PRECISION NOT NULL
);
""".strip()


class InMemorySaasStore:
    """Small tenant-aware store used by tests, local demos, and CLI smoke checks."""

    def __init__(self) -> None:
        self.organizations: dict[str, Organization] = {}
        self.users: dict[str, UserAccount] = {}
        self.memberships: dict[str, Membership] = {}
        self.workspaces: dict[str, Workspace] = {}
        self.ghost_profiles: dict[str, GhostProfile] = {}
        self.secret_refs: dict[str, TenantSecretRef] = {}
        self.runs: dict[str, SaasRun] = {}
        self.approvals: dict[str, SaasApproval] = {}
        self.audit_events: list[AuditEvent] = []
        self._members_by_org: dict[str, set[str]] = defaultdict(set)

    def create_organization(self, name: str) -> Organization:
        org = Organization(name=name)
        self.organizations[org.org_id] = org
        return org

    def create_user(self, email: str, display_name: str = "", oidc_subject: str = "") -> UserAccount:
        user = UserAccount(email=email, display_name=display_name, oidc_subject=oidc_subject)
        self.users[user.user_id] = user
        return user

    def add_member(self, org_id: str, user_id: str, role: Role) -> Membership:
        if org_id not in self.organizations:
            raise KeyError(f"unknown organization {org_id}")
        if user_id not in self.users:
            raise KeyError(f"unknown user {user_id}")
        membership = Membership(org_id=org_id, user_id=user_id, role=role)
        self.memberships[membership.membership_id] = membership
        self._members_by_org[org_id].add(membership.membership_id)
        return membership

    def role_for(self, org_id: str, user_id: str) -> Role:
        for membership_id in self._members_by_org.get(org_id, set()):
            membership = self.memberships[membership_id]
            if membership.user_id == user_id:
                return membership.role
        raise PermissionError(f"user {user_id} is not a member of {org_id}")

    def create_workspace(self, org_id: str, actor_user_id: str, name: str) -> Workspace:
        require_permission(self.role_for(org_id, actor_user_id), "worker:manage")
        workspace = Workspace(org_id=org_id, name=name)
        self.workspaces[workspace.workspace_id] = workspace
        self.record_audit(org_id, actor_user_id, "workspace.created", workspace.workspace_id)
        return workspace

    def create_ghost_profile(
        self, org_id: str, workspace_id: str, actor_user_id: str, name: str, path_profile: str
    ) -> GhostProfile:
        require_permission(self.role_for(org_id, actor_user_id), "run:create")
        ghost = GhostProfile(org_id=org_id, workspace_id=workspace_id, name=name, path_profile=path_profile)
        self.ghost_profiles[ghost.ghost_id] = ghost
        self.record_audit(org_id, actor_user_id, "ghost.created", ghost.ghost_id)
        return ghost

    def add_secret_ref(
        self, org_id: str, workspace_id: str, actor_user_id: str, provider: str, label: str
    ) -> TenantSecretRef:
        require_permission(self.role_for(org_id, actor_user_id), "secret:manage")
        ref = TenantSecretRef(org_id=org_id, workspace_id=workspace_id, provider=provider, label=label)
        self.secret_refs[ref.secret_id] = ref
        self.record_audit(org_id, actor_user_id, "secret.configured", ref.secret_id, {"provider": provider})
        return ref

    def create_run(self, org_id: str, workspace_id: str, actor_user_id: str, objective: str) -> SaasRun:
        require_permission(self.role_for(org_id, actor_user_id), "run:create")
        run = SaasRun(org_id=org_id, workspace_id=workspace_id, actor_user_id=actor_user_id, objective=objective)
        self.runs[run.run_id] = run
        self.record_audit(org_id, actor_user_id, "run.queued", run.run_id)
        approval = SaasApproval(
            org_id=org_id,
            workspace_id=workspace_id,
            run_id=run.run_id,
            requested_by=actor_user_id,
            risk_level="medium",
            reason="Approval-first SaaS mode requires review before execution.",
        )
        self.approvals[approval.approval_id] = approval
        return run

    def list_org_runs(self, org_id: str, actor_user_id: str) -> list[SaasRun]:
        require_permission(self.role_for(org_id, actor_user_id), "workspace:read")
        return [run for run in self.runs.values() if run.org_id == org_id]

    def record_audit(
        self, org_id: str, actor_user_id: str, action: str, target_id: str = "", metadata: dict[str, Any] | None = None
    ) -> AuditEvent:
        event = AuditEvent(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            target_id=target_id,
            metadata=metadata or {},
        )
        self.audit_events.append(event)
        return event
