"""Ghost Console routes for connectors (OAuth + Custom Auth Engine + status).

Additive: register via register_connector_routes(server, state_dir).
Handlers follow the console ctx-dict convention and return redacted
JSON — raw tokens and secret keys never leave these routes.
"""

from __future__ import annotations

import json
from contextlib import suppress
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
         "detail": "Integrations tab with built-in OAuth.",
         "done": integrations_connected > 0, "tab": "integrations"},
    ]
    done = sum(1 for s in steps if s["done"])
    return {"ok": True, "steps": steps, "done_count": done, "total": len(steps),
            "first_run": not model_configured}


def register_connector_routes(server: Any, state_dir: str | Path, *,
                              auth: str = "open", token: str = "") -> None:
    """Register /api/connectors/* and /api/auth/* routes on a GatewayServer."""
    from .auth_engine import PROVIDERS, AuthEngineError, CustomAuthEngine
    from .oauth import oauth_status

    base = Path(state_dir)

    def _engine() -> Any:
        return CustomAuthEngine(base)

    def providers(_ctx: dict[str, Any]) -> dict[str, Any]:
        items = []
        statuses = oauth_status(base)
        for key, provider in PROVIDERS.items():
            items.append({
                "key": key, "display": provider.display, "category": provider.category,
                "api_base": provider.api_base,
                "native_oauth": statuses.get(key, {"connected": False}),
            })
        return {"ok": True, "providers": items, "auth_engine": "custom"}

    def status(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "native": oauth_status(base), "auth_engine": "custom"}

    def auth_authorize(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        provider = str(data.get("provider", ""))
        entity_id = str(data.get("entity_id", ""))
        redirect_uri = str(data.get("redirect_uri", ""))
        if not provider or not entity_id or not redirect_uri:
            return {"ok": False,
                    "error": "provider, entity_id, and redirect_uri are required"}
        engine = _engine()
        try:
            result = engine.authorize_url(
                provider, entity_id, redirect_uri,
                scopes=data.get("scopes") if isinstance(data.get("scopes"), list) else None)
            return {"ok": True, **result}
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_callback(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        engine = _engine()
        try:
            return engine.handle_callback(
                str(data.get("provider", "")), str(data.get("code", "")),
                str(data.get("state", "")), str(data.get("redirect_uri", "")))
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_status(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        query = ctx.get("query") if isinstance(ctx.get("query"), dict) else {}
        entity_id = str(data.get("entity_id", "") or (query or {}).get("entity_id", ""))
        if not entity_id:
            return {"ok": False, "error": "entity_id is required"}
        engine = _engine()
        try:
            return {"ok": True, **engine.status(entity_id)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_revoke(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        engine = _engine()
        try:
            revoked = engine.revoke(str(data.get("entity_id", "")),
                                    str(data.get("provider", "")))
            return {"ok": True, "revoked": revoked}
        finally:
            with suppress(Exception):
                engine.close()

    server.routes.register("/api/connectors/providers", providers, method="GET",
                           auth=auth, token=token, description="Connector catalog + redacted status")
    server.routes.register("/api/connectors/status", status, method="GET",
                           auth=auth, token=token, description="Connector connection status")
    server.routes.register("/api/auth/authorize", auth_authorize, method="POST",
                           auth=auth, token=token, description="OAuth authorize URL + state")
    server.routes.register("/api/auth/callback", auth_callback, method="POST",
                           auth=auth, token=token, description="OAuth callback + token exchange")
    server.routes.register("/api/auth/status", auth_status, method="POST",
                           auth=auth, token=token, description="Redacted connection status")
    server.routes.register("/api/auth/revoke", auth_revoke, method="POST",
                           auth=auth, token=token, description="Revoke a connection")
    server.routes.register("/api/connectors/first-run",
                           lambda _ctx: first_run_status(base), method="GET",
                           auth=auth, token=token, description="Guided first-run checklist")

    # -- Stealth activity monitor + pre-fill drafts (STE-checked) ----------
    def stealth_activity(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop

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
        from ..stealth.ste import simplify
        from .stealth_service import draft_actions, get_service_loop

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
            with suppress(Exception):
                loop.store.record_intervention(item)
        return {"ok": True, "ste_text": payload["body"],
                "ste_rules": checked.rules_applied, "ste_warnings": checked.warnings}

    def stealth_emit(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..stealth.events import Event
        from .stealth_service import get_service_loop

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

    # -- Ghost-writer: gray completions for VA text fields ------------------
    def ghost_write(ctx: dict[str, Any]) -> dict[str, Any]:
        """POST /api/stealth/ghost-write {prompt_context, url?}.

        Model-backed when a provider is configured; otherwise an honest
        no-model response (the extension then stays silent — it never
        hallucinates completions locally).
        """
        data = _body(ctx)
        context = str(data.get("prompt_context", ""))[:4000]
        if len(context.strip()) < 5:
            return {"ok": False, "error": "prompt_context too short"}
        try:
            from ..model_layer.llm import LLM

            llm = LLM()
            if not llm.available:
                raise RuntimeError("no model provider available")
            suggestion = llm.chat(
                "You are a ghost-writer for support agents. Continue the draft below with "
                "the next 1-2 sentences only: plain, human, concise. No preamble.",
                context)
            return {"ok": True, "ghost_suggestion": str(suggestion)[:500],
                    "provider": llm.provider_name}
        except Exception as exc:
            return {"ok": False, "error": f"no completion available: {type(exc).__name__}"}

    server.routes.register("/api/stealth/ghost-write", ghost_write, method="POST",
                           auth=auth, token=token, description="Ghost-writer completions")
    def inbound_webhook(ctx: dict[str, Any]) -> dict[str, Any]:
        import time as _time
        import uuid as _uuid

        from .stealth_service import get_service_loop
        from .webhooks import NORMALIZERS, normalize_webhook

        parts = str(ctx.get("path", "")).strip("/").split("/")
        # ["api", "webhooks", source, va_id]
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "webhooks":
            return {"ok": False, "error": "use POST /api/webhooks/{source}/{va_id}"}
        source, va_id = parts[2], parts[3]
        if source not in NORMALIZERS:
            return {"ok": False, "error": f"unknown source '{source}'"}
        delivery_id = str(ctx.get("headers", {}).get("x-delivery-id", "")
                          or _uuid.uuid4().hex[:12])
        event = normalize_webhook(source, delivery_id, va_id, _body(ctx))
        if event is None:
            # Verification pings, bot echoes, empty payloads: ack, don't learn.
            return {"ok": True, "queued": False, "reason": "ignored (ping/echo/empty)"}
        loop = get_service_loop(base)
        delivered = loop.emit(event)
        result = loop.last_result
        return {"ok": True, "queued": True, "event_id": event.event_id,
                "delivered": delivered,
                "decision": str(result.decision) if result else "none",
                "intervention_id": result.intervention_id if result else "",
                "received_at": _time.time()}

    server.routes.register("/api/webhooks/", inbound_webhook, method="POST", prefix=True,
                           auth="open", description="Unified inbound webhooks per VA")


__all__ = ["register_connector_routes"]
