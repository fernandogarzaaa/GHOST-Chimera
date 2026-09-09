"""Ghost Console routes for connectors (OAuth + Nango + status).

Additive: register via register_connector_routes(server, state_dir).
Handlers follow the console ctx-dict convention and return redacted
JSON — raw tokens and secret keys never leave these routes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _body(ctx: dict[str, Any]) -> dict[str, Any]:
    raw = str(ctx.get("body") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _inbox_path(state_dir: Path) -> Path:
    return Path(state_dir) / "connector_oauth" / "nango_webhooks.jsonl"


def first_run_status(state_dir: str | Path) -> dict[str, Any]:
    """Guided first-run checklist: model -> readiness -> integrations.

    model_configured is True when a saved model provider exists with a
    usable key (saved config or environment). Never returns key material.
    """
    import os

    from .oauth import oauth_status

    base = Path(state_dir)
    try:
        from ..control_plane.config import load_config

        saved = load_config()
    except Exception:
        saved = {}
    model = saved.get("model") if isinstance(saved.get("model"), dict) else {}
    provider = str(model.get("provider") or os.environ.get("GHOSTCHIMERA_MODEL_PROVIDER") or "")
    key_envs = [f"{provider.upper()}_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]
    model_configured = bool(provider) and any(os.environ.get(k) for k in key_envs)
    native = oauth_status(base)
    integrations_connected = sum(1 for s in native.values() if s.get("connected"))
    steps = [
        {"id": "model", "title": "Connect a model provider",
         "detail": "Config tab, or set PROVIDER_API_KEY in the environment.",
         "done": model_configured, "tab": "config"},
        {"id": "readiness", "title": "Run the readiness check",
         "detail": "Operator Workbench → Run Readiness Check.",
         "done": False, "tab": "operator"},
        {"id": "integrations", "title": "Connect Slack, Notion, GitHub…",
         "detail": "Integrations tab, or 1-click via Nango.",
         "done": integrations_connected > 0, "tab": "integrations"},
    ]
    done = sum(1 for s in steps if s["done"])
    return {"ok": True, "steps": steps, "done_count": done, "total": len(steps),
            "first_run": not model_configured}


def register_connector_routes(server: Any, state_dir: str | Path, *,
                              auth: str = "open", token: str = "") -> None:
    """Register /api/connectors/* routes on a GatewayServer."""
    from .nango import NANGO_CATALOG, NangoClient, NangoError
    from .oauth import oauth_status

    base = Path(state_dir)

    def providers(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .nango import nango_secret_key

        items = []
        statuses = oauth_status(base)
        for key, provider in NANGO_CATALOG.items():
            items.append({
                "key": key, "display": provider.display, "category": provider.category,
                "docs": provider.docs,
                "native_oauth": statuses.get(key, {"connected": False}),
            })
        return {"ok": True, "providers": items,
                "nango_configured": bool(nango_secret_key())}

    def status(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .nango import nango_secret_key

        return {"ok": True, "native": oauth_status(base),
                "nango_configured": bool(nango_secret_key())}

    def nango_session(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        provider_config_key = str(data.get("providerConfigKey", ""))
        connection_id = str(data.get("connectionId", ""))
        if not provider_config_key or not connection_id:
            return {"ok": False, "error": "providerConfigKey and connectionId are required"}
        try:
            client = NangoClient()
        except NangoError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            return {"ok": True, "session": client.frontend_session(
                provider_config_key=provider_config_key, connection_id=connection_id)}
        except NangoError as exc:
            return {"ok": False, "error": str(exc)}

    def nango_webhook(ctx: dict[str, Any]) -> dict[str, Any]:
        from .nango import NangoClient

        record = NangoClient.normalize_webhook(_body(ctx))
        try:
            path = _inbox_path(base)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            return {"ok": False, "error": f"inbox write failed: {exc}"}
        return {"ok": True, "record": record}

    def webhook_inbox(_ctx: dict[str, Any]) -> dict[str, Any]:
        path = _inbox_path(base)
        records: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-50:]
        except OSError:
            lines = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return {"ok": True, "records": records}

    server.routes.register("/api/connectors/providers", providers, method="GET",
                           auth=auth, token=token, description="Connector catalog + redacted status")
    server.routes.register("/api/connectors/status", status, method="GET",
                           auth=auth, token=token, description="Connector connection status")
    server.routes.register("/api/connectors/nango/session", nango_session, method="POST",
                           auth=auth, token=token, description="Nango frontend session bundle")
    server.routes.register("/api/connectors/nango/webhook", nango_webhook, method="POST",
                           auth="open", description="Nango webhook inbox (redacted)")
    server.routes.register("/api/connectors/nango/inbox", webhook_inbox, method="GET",
                           auth=auth, token=token, description="Recent Nango webhook records")
    server.routes.register("/api/connectors/first-run",
                           lambda _ctx: first_run_status(base), method="GET",
                           auth=auth, token=token, description="Guided first-run checklist")

    # -- Stealth activity monitor + pre-fill drafts (STE-checked) ----------
    def stealth_activity(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop, ste_prefill

        loop = get_service_loop(base)
        interventions = []
        for item in list(loop.interventions.values())[-25:]:
            interventions.append({
                "id": item.id, "workflow": item.workflow,
                "state": str(item.state), "outcome": str(item.outcome),
                "confidence": item.confidence, "reason": item.reason,
                "drafts": len(draft_actions(item)),
                "approval": (item.provenance or {}).get("approval"),
            })
        recent = []
        if loop.store is not None:
            try:
                for event in loop.store.recent_events(limit=25):
                    recent.append({"event_id": event["event_id"],
                                   "event_type": event["event_type"],
                                   "actor": event["actor"], "source": event["source"],
                                   "timestamp": event["timestamp"]})
            except Exception:
                pass
        return {"ok": True, "events_processed": loop.bus.processed,
                "recent_events": recent,
                "interventions": interventions,
                "workflows": [h.to_dict() for h in loop.learner.hypotheses()[:8]],
                "autonomy": loop.policy.autonomy.name, "enabled": loop.policy.enabled}

    def stealth_drafts(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop, ste_prefill

        loop = get_service_loop(base)
        drafts = []
        for item in loop.interventions.values():
            actions = draft_actions(item)
            if not actions:
                continue
            drafts.append({
                "id": item.id, "workflow": item.workflow, "state": str(item.state),
                "summary": (item.provenance or {}).get("event_summary", ""),
                "approval": (item.provenance or {}).get("approval"),
                "actions": [ste_prefill(a) for a in actions],
            })
        return {"ok": True, "drafts": drafts}

    def stealth_approve(ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import approve_draft, get_service_loop

        data = _body(ctx)
        iid = str(ctx.get("path", "")).rsplit("/", 2)[-2]
        return approve_draft(get_service_loop(base), iid,
                             final_text=str(data.get("text", "")),
                             connections=data.get("connections") if isinstance(
                                 data.get("connections"), dict) else None)

    def stealth_edit(ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop
        from ..stealth.ste import simplify

        data = _body(ctx)
        iid = str(ctx.get("path", "")).rsplit("/", 2)[-2]
        loop = get_service_loop(base)
        item = loop.interventions.get(iid)
        if item is None:
            return {"ok": False, "error": "unknown intervention"}
        actions = draft_actions(item)
        index = int(data.get("action_index", 0))
        if not (0 <= index < len(actions)):
            return {"ok": False, "error": "action_index out of range"}
        payload = actions[index].setdefault("payload", {})
        if not isinstance(payload, dict):
            return {"ok": False, "error": "action payload is not editable"}
        from .stealth_service import extract_draft_text

        before = extract_draft_text(actions[index])
        payload["body"] = str(data.get("text", before))
        # Re-run STE on the edited text so the stored draft stays compliant.
        checked = simplify(payload["body"])
        payload["body"] = checked.text or payload["body"]
        if loop.store is not None:
            try:
                loop.store.record_intervention(item)
            except Exception:
                pass
        return {"ok": True, "ste_text": payload["body"],
                "ste_rules": checked.rules_applied, "ste_warnings": checked.warnings}

    def stealth_emit(ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import get_service_loop
        from ..stealth.events import Event

        data = _body(ctx)
        loop = get_service_loop(base)
        try:
            event = Event.from_dict(data.get("event") if "event" in data else data)
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "error": f"bad event: {exc}"}
        delivered = loop.emit(event)
        result = loop.last_result
        return {"ok": True, "delivered": delivered,
                "decision": str(result.decision) if result else "none",
                "intervention_id": result.intervention_id if result else ""}

    def stealth_simplify(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..stealth.ste import simplify

        result = simplify(str(_body(ctx).get("text", "")))
        return {"ok": True, "ste_text": result.text,
                "ste_rules": result.rules_applied, "ste_warnings": result.warnings}

    def stealth_draft_action(ctx: dict[str, Any]) -> dict[str, Any]:
        """POST /api/stealth/drafts/{id}/approve|edit — suffix-dispatched."""
        path = str(ctx.get("path", "")).rstrip("/")
        if path.endswith("/approve"):
            return stealth_approve(ctx)
        if path.endswith("/edit"):
            return stealth_edit(ctx)
        return {"ok": False, "error": "unknown draft action (use approve|edit)"}

    server.routes.register("/api/stealth/activity", stealth_activity, method="GET",
                           auth=auth, token=token, description="Stealth loop activity feed")
    server.routes.register("/api/stealth/drafts", stealth_drafts, method="GET",
                           auth=auth, token=token, description="STE pre-fill drafts")
    server.routes.register("/api/stealth/drafts/", stealth_draft_action, method="POST", prefix=True,
                           auth=auth, token=token, description="Draft approve/edit by id suffix")
    server.routes.register("/api/stealth/emit", stealth_emit, method="POST",
                           auth=auth, token=token, description="Emit event into the Stealth loop")
    server.routes.register("/api/stealth/simplify", stealth_simplify, method="POST",
                           auth=auth, token=token, description="STE-check arbitrary text")


__all__ = ["register_connector_routes"]
