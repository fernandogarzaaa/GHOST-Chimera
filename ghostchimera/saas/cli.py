"""CLI entrypoints for Ghost Chimera SaaS public-launch primitives."""

from __future__ import annotations

import json
import os
from argparse import Namespace

from .models import Role
from .oidc import OIDCSettings, validate_oidc_settings
from .store import POSTGRES_SCHEMA_TABLES, InMemorySaasStore, build_postgres_schema_sql
from .worker import WorkerQueue


def run_saas_cli(args: Namespace) -> int:
    action = getattr(args, "saas_action", "status")
    if action == "status":
        print(json.dumps(saas_status_from_env(), indent=2, sort_keys=True))
        return 0
    if action == "init-db":
        payload = {
            "ok": True,
            "database_url_configured": bool(os.environ.get("GHOSTCHIMERA_DATABASE_URL")),
            "tables": list(POSTGRES_SCHEMA_TABLES),
            "sql": build_postgres_schema_sql() if getattr(args, "print_sql", False) else "",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if action == "create-admin":
        email = str(getattr(args, "email", "") or "").strip()
        if not email or "@" not in email:
            print(json.dumps({"ok": False, "error": "--email is required for create-admin"}, indent=2, sort_keys=True))
            return 2
        store = InMemorySaasStore()
        org = store.create_organization(str(getattr(args, "org", "") or "Ghost Chimera"))
        user = store.create_user(email=email, display_name=email.split("@", 1)[0], oidc_subject=email)
        membership = store.add_member(org.org_id, user.user_id, Role.OWNER)
        print(
            json.dumps(
                {"ok": True, "organization": org.to_dict(), "user": user.to_dict(), "membership": membership.to_dict()},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(json.dumps({"ok": False, "error": f"unknown saas action {action}"}, indent=2, sort_keys=True))
    return 2


def run_worker_cli(args: Namespace) -> int:
    action = getattr(args, "worker_action", "status")
    store = InMemorySaasStore()
    queue = WorkerQueue(store)
    if action == "status":
        print(json.dumps(queue.status(), indent=2, sort_keys=True))
        return 0
    if action == "start":
        print(
            json.dumps(
                {
                    "ok": True,
                    "worker_id": getattr(args, "worker_id", "") or "local-worker",
                    "mode": "dry-run",
                    "message": "Worker queue primitives are ready. Production workers require SaaS Postgres configuration.",
                    "queue": queue.status(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(json.dumps({"ok": False, "error": f"unknown worker action {action}"}, indent=2, sort_keys=True))
    return 2


def saas_status_from_env() -> dict[str, object]:
    target = os.environ.get("GHOSTCHIMERA_DEPLOYMENT_TARGET", "local")
    settings = OIDCSettings(
        issuer=os.environ.get("GHOSTCHIMERA_OIDC_ISSUER", ""),
        client_id=os.environ.get("GHOSTCHIMERA_OIDC_CLIENT_ID", ""),
        client_secret=os.environ.get("GHOSTCHIMERA_OIDC_CLIENT_SECRET", ""),
        redirect_uri=os.environ.get("GHOSTCHIMERA_OIDC_REDIRECT_URI", ""),
        allowed_domains=tuple(
            item.strip()
            for item in os.environ.get("GHOSTCHIMERA_OIDC_ALLOWED_DOMAINS", "").split(",")
            if item.strip()
        ),
        admin_bootstrap_email=os.environ.get("GHOSTCHIMERA_ADMIN_BOOTSTRAP_EMAIL", ""),
    )
    oidc = validate_oidc_settings(settings)
    required = {
        "GHOSTCHIMERA_DATABASE_URL": bool(os.environ.get("GHOSTCHIMERA_DATABASE_URL")),
        "GHOSTCHIMERA_SESSION_SECRET": bool(os.environ.get("GHOSTCHIMERA_SESSION_SECRET")),
        "GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY": bool(os.environ.get("GHOSTCHIMERA_SECRETS_ENCRYPTION_KEY")),
        "GHOSTCHIMERA_WORKER_TOKEN": bool(os.environ.get("GHOSTCHIMERA_WORKER_TOKEN")),
    }
    errors = []
    if target == "saas":
        errors.extend(key for key, configured in required.items() if not configured)
        if not oidc["ok"]:
            errors.extend(str(error) for error in oidc["errors"])
    return {
        "ok": not errors,
        "deployment_target": target,
        "database_url_configured": required["GHOSTCHIMERA_DATABASE_URL"],
        "required": required,
        "oidc": oidc,
        "errors": errors,
    }
