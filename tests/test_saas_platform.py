from __future__ import annotations

import os

import pytest

from ghostchimera.saas import InMemorySaasStore, OIDCSettings, Role, WorkerQueue, build_postgres_schema_sql
from ghostchimera.saas.cli import saas_status_from_env
from ghostchimera.saas.models import AuditEvent, TenantSecretRef
from ghostchimera.saas.oidc import validate_oidc_settings
from ghostchimera.saas.rbac import require_permission


def test_postgres_schema_contains_required_saas_tables():
    schema = build_postgres_schema_sql()
    for table in [
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
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in schema


def test_rbac_blocks_viewer_from_run_creation():
    require_permission(Role.OPERATOR, "run:create")
    with pytest.raises(PermissionError):
        require_permission(Role.VIEWER, "run:create")


def test_store_enforces_tenant_roles_and_creates_approval_first_run():
    store = InMemorySaasStore()
    org = store.create_organization("Acme")
    owner = store.create_user("owner@example.com")
    viewer = store.create_user("viewer@example.com")
    store.add_member(org.org_id, owner.user_id, Role.OWNER)
    store.add_member(org.org_id, viewer.user_id, Role.VIEWER)

    workspace = store.create_workspace(org.org_id, owner.user_id, "Launch")
    with pytest.raises(PermissionError):
        store.create_run(org.org_id, workspace.workspace_id, viewer.user_id, "do high impact work")

    run = store.create_run(org.org_id, workspace.workspace_id, owner.user_id, "draft launch checklist")
    approvals = [approval for approval in store.approvals.values() if approval.run_id == run.run_id]
    assert run.approval_required is True
    assert run.status == "queued"
    assert approvals and approvals[0].status == "pending"


def test_secret_refs_and_audit_events_redact_sensitive_values():
    ref = TenantSecretRef(org_id="org_1", workspace_id="wsp_1", provider="openai", label="prod")
    assert ref.to_public_dict()["secret_value"] == "[redacted]"

    event = AuditEvent(
        org_id="org_1",
        actor_user_id="usr_1",
        action="secret.saved",
        metadata={"api_key": "sk-test", "safe": "visible"},
    )
    payload = event.to_dict()
    assert payload["metadata"]["api_key"] == "[redacted]"
    assert payload["metadata"]["safe"] == "visible"


def test_oidc_validation_requires_https_and_secret():
    bad = validate_oidc_settings(
        OIDCSettings(
            issuer="http://issuer.example.com",
            client_id="",
            client_secret="",
            redirect_uri="http://example.com/callback",
        )
    )
    assert bad["ok"] is False
    assert any("issuer" in error for error in bad["errors"])
    assert bad["settings"]["client_secret"] == ""

    good = validate_oidc_settings(
        OIDCSettings(
            issuer="https://issuer.example.com",
            client_id="client",
            client_secret="secret",
            redirect_uri="https://ghost.example.com/callback",
            allowed_domains=("example.com",),
            admin_bootstrap_email="owner@example.com",
        )
    )
    assert good["ok"] is True
    assert good["settings"]["client_secret"] == "[redacted]"


def test_worker_queue_claims_oldest_queued_run_once():
    store = InMemorySaasStore()
    org = store.create_organization("Acme")
    owner = store.create_user("owner@example.com")
    store.add_member(org.org_id, owner.user_id, Role.OWNER)
    workspace = store.create_workspace(org.org_id, owner.user_id, "Launch")
    run = store.create_run(org.org_id, workspace.workspace_id, owner.user_id, "ship")
    queue = WorkerQueue(store)

    lease = queue.claim_next("worker-1", lease_seconds=60)
    assert lease is not None
    assert lease.run_id == run.run_id
    assert queue.claim_next("worker-2") is None
    assert queue.release(lease.lease_id) is True


def test_saas_status_requires_env_only_in_saas_mode(monkeypatch):
    for key in list(os.environ):
        if key.startswith("GHOSTCHIMERA_OIDC_") or key in {
            "GHOSTCHIMERA_DEPLOYMENT_TARGET",
            "GHOSTCHIMERA_DATABASE_URL",
            "GHOSTCHIMERA_SESSION_SECRET",
            "GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY",
            "GHOSTCHIMERA_WORKER_TOKEN",
            "GHOSTCHIMERA_ADMIN_BOOTSTRAP_EMAIL",
        }:
            monkeypatch.delenv(key, raising=False)

    local = saas_status_from_env()
    assert local["deployment_target"] == "local"
    assert local["ok"] is True

    monkeypatch.setenv("GHOSTCHIMERA_DEPLOYMENT_TARGET", "saas")
    missing = saas_status_from_env()
    assert missing["ok"] is False
    assert "GHOSTCHIMERA_DATABASE_URL" in missing["errors"]

    monkeypatch.setenv("GHOSTCHIMERA_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("GHOSTCHIMERA_SESSION_SECRET", "session")
    monkeypatch.setenv("GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY", "secret-key")
    monkeypatch.setenv("GHOSTCHIMERA_WORKER_TOKEN", "worker")
    monkeypatch.setenv("GHOSTCHIMERA_OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("GHOSTCHIMERA_OIDC_CLIENT_ID", "client")
    monkeypatch.setenv("GHOSTCHIMERA_OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GHOSTCHIMERA_OIDC_REDIRECT_URI", "https://ghost.example.com/callback")
    ready = saas_status_from_env()
    assert ready["ok"] is True
