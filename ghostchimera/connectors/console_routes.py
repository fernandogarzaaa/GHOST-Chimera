"""Ghost Console routes for connectors (OAuth + Custom Auth Engine + status).

Additive: register via register_connector_routes(server, state_dir).
Handlers follow the console ctx-dict convention and return redacted
JSON — raw tokens and secret keys never leave these routes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# `gh` detection cache (module-level: a subprocess per page-load is wasteful).
_GH_STATUS_CACHE: dict[str, Any] = {}

# Automations engines by state dir (poller threads live with the process).
_AUTOMATIONS_ENGINES: dict[str, Any] = {}


def _vault_key_for(engine: Any, entity_id: str, key_id: str) -> dict[str, str] | None:
    """Reveal one custom key as {label, hint, secret} (internal use only)."""
    if not key_id:
        return None
    try:
        revealed = engine.reveal_custom_key(entity_id, key_id)
    except Exception:
        return None
    return {"label": revealed["label"], "hint": revealed.get("provider_hint", ""), "secret": revealed["secret"]}


def _selection_indices(selections: list[Any]) -> list[int]:
    """Row indices from import selections (malformed entries skipped)."""
    indices: list[int] = []
    for sel in selections:
        if isinstance(sel, dict):
            with suppress(TypeError, ValueError):
                indices.append(int(sel.get("index", -1)))
    return indices


# Honest setup cost per provider (engine key -> (cost, note)).
# "none" = works with zero registration (device flow, gh CLI, app password).
_SETUP_COST: dict[str, tuple[str, str]] = {
    "github": ("none", "Device login, gh CLI import, or any OAuth app — no registration needed for the first two."),
    "google-mail": (
        "one-time-free",
        "Register a free Desktop client once — or skip it entirely with a Gmail app password.",
    ),
    "google-gemini": (
        "one-time-free",
        "Same Google Desktop client; adds the Gemini API scope so chat bills your Google account, no API key.",
    ),
    "slack": ("one-time-free", "Create a free app with PKCE enabled, then paste its client ID."),
    "airtable": ("one-time-free", "Create a free OAuth integration, then paste its client ID."),
    "notion": ("one-time-free", "Create a public integration, then paste ID + secret."),
    "hubspot": ("one-time-free", "Create a developer app, then paste ID + secret."),
    "salesforce": ("one-time-free", "Create an External Client App, then paste its ID."),
    "linkedin": ("one-time-free", "Self-serve sign-in app; automation is banned by LinkedIn regardless."),
    "zendesk": ("one-time-free", "OAuth client per Zendesk subdomain."),
    "freshdesk": ("one-time-free", "OAuth client per Freshdesk domain."),
    "gorgias": ("one-time-free", "OAuth client per Gorgias domain."),
    "hubstaff": ("one-time-free", "OAuth client from Hubstaff."),
    "time-doctor": ("one-time-free", "OAuth client from Time Doctor."),
    "mastodon": (
        "none",
        "No registration: pick your instance (MASTODON_INSTANCE), paste its client ID — or get one auto-provisioned per instance.",
    ),
    "reddit": (
        "one-time-free",
        "Free personal script/web app at reddit.com/prefs/apps; secret authenticates via HTTP Basic automatically.",
    ),
    "discord": ("one-time-free", "Free app at discord.com/developers; user OAuth here, bot tokens go in Stored Keys."),
    "tiktok": ("one-time-free", "Free Login Kit app; basic scopes self-serve, publishing needs TikTok audit."),
    "facebook": ("one-time-free", "Free Meta app; basic login self-serve, deeper permissions need App Review."),
    "instagram": (
        "one-time-free",
        "Business/Creator account + linked Page required; own-account access needs no review.",
    ),
    "x": (
        "paid",
        "Login is free, but every X API call is billed pay-per-use: Ghost stores the token and refuses API calls until you approve spending.",
    ),
}


def _body(ctx: dict[str, Any]) -> dict[str, Any]:
    raw = str(ctx.get("body") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _provider_from_state(state: str) -> str | None:
    """Read the provider claim out of an authorize state blob (untrusted)."""
    import base64 as _b64

    try:
        padded = state + "=" * (-len(state) % 4)
        payload = json.loads(_b64.urlsafe_b64decode(padded).decode())
    except (ValueError, json.JSONDecodeError):
        return None
    provider = payload.get("provider") if isinstance(payload, dict) else None
    return str(provider) if provider else None


def _callback_html(ok: bool, title: str, detail: str) -> Any:
    """Minimal result page for the OAuth browser landing."""
    import html as _html

    from ..chimera_pilot.gateway_server import HttpResponse

    color = "#2bd587" if ok else "#fb7185"
    return HttpResponse(
        body=f"""<!doctype html><html><body style="background:#0a0c10;color:#eef2f7;
font:16px/1.5 system-ui,sans-serif;display:flex;min-height:90vh;
align-items:center;justify-content:center;margin:0">
<div style="border:1px solid #262d36;border-radius:12px;padding:32px;max-width:480px;text-align:center">
<div style="font-size:40px;color:{color}">{"✓" if ok else "✕"}</div>
<h2>{_html.escape(title)}</h2><p>{_html.escape(detail)}</p></div></body></html>""",
        content_type="text/html; charset=utf-8",
    )


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
    key_envs = [
        f"{provider.upper()}_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ]
    model_configured = bool(provider) and any(os.environ.get(k) for k in key_envs)
    native = oauth_status(base)
    integrations_connected = sum(1 for s in native.values() if s.get("connected"))
    readiness_done = False
    try:
        from ..control_plane.evolution import read_timeline

        readiness_done = any(
            event.get("event_type") == "readiness_check_run" for event in read_timeline(base, limit=200)
        )
    except Exception as exc:
        logger.warning("first-run readiness lookup failed: %s", exc)
        readiness_done = False
    steps = [
        {
            "id": "model",
            "title": "Connect a model provider",
            "detail": "Config tab, or set PROVIDER_API_KEY in the environment.",
            "done": model_configured,
            "tab": "config",
        },
        {
            "id": "readiness",
            "title": "Run the readiness check",
            "detail": "Activity tab → Run Readiness Check.",
            "done": readiness_done,
            "tab": "activity",
        },
        {
            "id": "integrations",
            "title": "Connect Slack, Notion, GitHub…",
            "detail": "Integrations tab with built-in OAuth.",
            "done": integrations_connected > 0,
            "tab": "integrations",
        },
    ]
    done = sum(1 for s in steps if s["done"])
    return {"ok": True, "steps": steps, "done_count": done, "total": len(steps), "first_run": not model_configured}


def _stealth_loop_with_authority(base: Path) -> Any:
    """Service loop whose queue is bridged to the process-local authority.

    The authority store is owned by the service layer (never closed), so —
    unlike a per-request engine store — the bridged queue never operates
    on a dead SQLite connection.
    """
    from .stealth_service import get_service_loop

    return get_service_loop(base)


def _stealth_pending_approvals(base: Path) -> list[dict[str, Any]]:
    """Stealth loop asks mapped onto the Trust item shape (source stealth)."""
    try:
        loop = _stealth_loop_with_authority(base)
    except Exception:
        return []
    queue = getattr(loop, "approvals", None)
    if queue is None:
        return []
    with suppress(Exception):
        queue.sync()
        out = []
        for item in queue.pending():
            data = item.to_dict() if hasattr(item, "to_dict") else {}
            out.append(
                {
                    "id": data.get("id", ""),
                    "provider": "stealth",
                    "method": "APPROVE",
                    "url": f"stealth://{data.get('source_kind', '')}/{data.get('source_id', '')}",
                    "scope": data.get("workflow", ""),
                    "summary": data.get("subject", ""),
                    "requested_by": data.get("requested_by", ""),
                    "created_at": data.get("created_at", 0),
                    "expires_at": data.get("expires_at", 0),
                    "source": "stealth",
                }
            )
        return out
    return []


def _decide_stealth_approval(base: Path, engine: Any, approval_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Decide a stealth ask through the loop queue (cascades to durable)."""
    try:
        loop = _stealth_loop_with_authority(base)
    except Exception as exc:
        return {"ok": False, "error": f"stealth loop unavailable: {type(exc).__name__}"}
    queue = getattr(loop, "approvals", None)
    if queue is None:
        return {"ok": False, "error": "no stealth approval queue"}
    actor = str(data.get("actor") or "console-user")
    try:
        done = queue.approve(approval_id, actor) if data.get("approved") else queue.deny(approval_id, actor)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not done:
        return {"ok": False, "error": "already resolved or expired"}
    with suppress(Exception):
        engine.audit.record(
            f"approval.{'approved' if data.get('approved') else 'denied'}",
            detail={"id": approval_id, "actor": actor, "source": "stealth"},
        )
    item = queue.get(approval_id)
    state = item.state.value if item is not None and hasattr(item.state, "value") else "resolved"
    return {"ok": True, "id": approval_id, "state": state, "source": "stealth"}


def register_connector_routes(server: Any, state_dir: str | Path, *, auth: str = "open", token: str = "") -> None:
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
            items.append(
                {
                    "key": key,
                    "display": provider.display,
                    "category": provider.category,
                    "api_base": provider.api_base,
                    "native_oauth": statuses.get(key, {"connected": False}),
                }
            )
        return {"ok": True, "providers": items, "auth_engine": "custom"}

    def status(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "native": oauth_status(base), "auth_engine": "custom"}

    def auth_authorize(ctx: dict[str, Any]) -> dict[str, Any]:
        """Create a provider authorization URL from a validated console request."""
        data = _body(ctx)
        provider = str(data.get("provider", ""))
        entity_id = str(data.get("entity_id", ""))
        redirect_uri = str(data.get("redirect_uri", ""))
        if not provider or not entity_id or not redirect_uri:
            return {"ok": False, "error": "provider, entity_id, and redirect_uri are required"}
        scopes = data.get("scopes") if isinstance(data.get("scopes"), list) else None
        if scopes is None and provider in ("google-mail",):
            # Gmail needs its API scope on top of the preset identity scopes.
            from .oauth import get_preset

            scopes = list(get_preset("google").scopes) + ["https://www.googleapis.com/auth/gmail.readonly"]
        if scopes is None and provider in ("google-gemini",):
            # Gemini API via user OAuth: generative-language scope.
            from .oauth import get_preset

            scopes = list(get_preset("google").scopes) + [
                "https://www.googleapis.com/auth/generative-language.retriever"
            ]
        engine = _engine()
        try:
            result = engine.authorize_url(provider, entity_id, redirect_uri, scopes=scopes)
            return {"ok": True, **result}
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_client_id(ctx: dict[str, Any]) -> dict[str, Any]:
        """Save (or clear) provider OAuth credentials from the console.

        Client IDs are public identifiers. Client secrets are accepted too
        (needed for confidential clients like Notion/HubSpot) and stored in
        the local config file with owner-only permissions. Values are
        write-only: responses confirm what is configured, never the values.
        Body: {provider, client_id?, client_secret?, clear?}
        """
        data = _body(ctx)
        provider = str(data.get("provider", "")).strip()
        client_id = str(data.get("client_id", "")).strip()
        client_secret = str(data.get("client_secret", "")).strip()
        clear = bool(data.get("clear"))
        if not provider:
            return {"ok": False, "error": "provider is required"}
        if not clear and not client_id and not client_secret:
            return {"ok": False, "error": "client_id, client_secret, or clear is required"}
        if len(client_id) > 200 or "/" in client_id or "\\" in client_id:
            return {"ok": False, "error": "that does not look like a client ID"}
        if len(client_secret) > 500:
            return {"ok": False, "error": "that does not look like a client secret"}
        try:
            from ..control_plane.config import load_config, save_config

            config = load_config()
            section = config.get("provider_oauth")
            if not isinstance(section, dict):
                section = {}
                config["provider_oauth"] = section
            # Map engine key -> oauth preset id for storage.
            from .auth_engine import _PRESET_FOR

            preset_id = _PRESET_FOR.get(provider, provider)
            if clear:
                section.pop(preset_id, None)
                save_config(config)
                return {"ok": True, "provider": provider, "cleared": True}
            entry = section.get(preset_id)
            if not isinstance(entry, dict):
                entry = {}
                section[preset_id] = entry
            if client_id:
                entry["client_id"] = client_id
            if client_secret:
                entry["client_secret"] = client_secret
            save_config(config)
            if client_secret:
                # Secrets at rest: owner-only permissions (best-effort).
                from ..control_plane.config import CONFIG_FILE

                with suppress(OSError):
                    os.chmod(CONFIG_FILE, 0o600)
            engine = _engine()
            try:
                source = engine.client_id_source(preset_id)
                secret_source = engine.client_secret_source(preset_id)
            finally:
                with suppress(Exception):
                    engine.close()
            return {
                "ok": True,
                "provider": provider,
                "saved": True,
                "client_id_configured": source != "none",
                "client_id_source": source,
                "client_secret_configured": secret_source != "none",
                "client_secret_source": secret_source,
            }
        except Exception as exc:
            return {"ok": False, "error": f"could not save: {type(exc).__name__}"}

    def auth_callback(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        engine = _engine()
        try:
            return engine.handle_callback(
                str(data.get("provider", "")),
                str(data.get("code", "")),
                str(data.get("state", "")),
                str(data.get("redirect_uri", "")),
            )
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
            revoked = engine.revoke(str(data.get("entity_id", "")), str(data.get("provider", "")))
            return {"ok": True, "revoked": revoked}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_callback_page(ctx: dict[str, Any]) -> Any:
        """Browser landing for provider redirects.

        GET /api/auth/callback?code=...&state=... — finishes the exchange
        and shows a plain result page. Open auth (providers can't hold our
        token); the single-use state nonce is the CSRF protection.
        """
        import html as _html

        query = ctx.get("query") if isinstance(ctx.get("query"), dict) else {}
        query = query or {}
        if query.get("error"):
            return _callback_html(False, "Login cancelled", str(query.get("error_description") or query.get("error")))
        code, state = str(query.get("code", "")), str(query.get("state", ""))
        if not code or not state:
            return _callback_html(
                False, "Incomplete login", "Missing code or state. Start over from the Integrations tab."
            )
        host = str((ctx.get("headers") or {}).get("host", "127.0.0.1:8766"))
        redirect_uri = os.environ.get("GHOSTCHIMERA_OAUTH_CALLBACK", f"http://{host}/api/auth/callback")
        provider = _provider_from_state(state)
        if provider is None:
            return _callback_html(False, "Bad login state", "Start over from the Integrations tab.")
        engine = _engine()
        try:
            result = engine.handle_callback(provider, code, state, redirect_uri)
            return _callback_html(
                True,
                f"Connected: {provider}",
                f"Account {result['entity_id']} connected. "
                f"Expires in {max(0, int(result['expires_at'] - time.time()))}s. "
                "You can close this tab and press Refresh Status in Ghost.",
            )
        except (AuthEngineError, ValueError) as exc:
            return _callback_html(False, "Login failed", _html.escape(str(exc))[:300])
        finally:
            with suppress(Exception):
                engine.close()

    def auth_gh_status(_ctx: dict[str, Any]) -> dict[str, Any]:
        """Detect a local `gh` login (no token touched). Cached 5 minutes.

        The cache is keyed on the GHOSTCHIMERA_GH_PATH override so tests
        (and gh installs appearing mid-process) never read a stale result.
        """
        import os as _os

        from .gh_cli import GH_PATH_ENV, gh_status

        cache_key = f"gh:{_os.environ.get(GH_PATH_ENV, '')}"
        now = time.time()
        cached = _GH_STATUS_CACHE.get(cache_key)
        if cached is not None and now - cached[0] < 300:
            return {"ok": True, **cached[1]}
        result = gh_status()
        _GH_STATUS_CACHE[cache_key] = (now, result)
        return {"ok": True, **result}

    def auth_gh_import(ctx: dict[str, Any]) -> dict[str, Any]:
        """One-click import of the user's own `gh` login (explicit consent)."""
        data = _body(ctx)
        entity_id = str(data.get("entity_id", ""))
        if not entity_id:
            return {"ok": False, "error": "entity_id is required"}
        engine = _engine()
        try:
            return engine.import_gh_cli(entity_id)
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_keys_save(ctx: dict[str, Any]) -> dict[str, Any]:
        """Store a pasted secret (BYOK key or mail app password). Write-only."""
        data = _body(ctx)
        engine = _engine()
        try:
            return engine.save_custom_key(
                str(data.get("entity_id") or "console-user"),
                str(data.get("kind") or ""),
                str(data.get("label") or ""),
                str(data.get("secret") or ""),
                provider_hint=str(data.get("provider_hint") or ""),
            )
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_keys_list(ctx: dict[str, Any]) -> dict[str, Any]:
        """Redacted key listing (labels only, never values)."""
        data = _body(ctx)
        engine = _engine()
        try:
            keys = engine.store.list_custom_keys(str(data.get("entity_id") or "console-user"))
            return {"ok": True, "keys": keys}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_keys_delete(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        key_id = str(data.get("id") or "")
        if not key_id:
            return {"ok": False, "error": "id is required"}
        engine = _engine()
        try:
            deleted = engine.store.delete_custom_key(str(data.get("entity_id") or "console-user"), key_id)
            return {"ok": True, "deleted": deleted}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_csv_preview(ctx: dict[str, Any]) -> dict[str, Any]:
        """Preview a browser CSV export (labels only, never passwords)."""
        from .credential_import import CredentialImportError, parse_browser_csv

        data = _body(ctx)
        try:
            rows = parse_browser_csv(str(data.get("csv_text") or ""))
            return {"ok": True, "rows": rows, "count": len(rows)}
        except CredentialImportError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_csv_commit(ctx: dict[str, Any]) -> dict[str, Any]:
        """Store selected CSV rows as vault keys. Response carries no passwords."""
        from .credential_import import extract_passwords

        data = _body(ctx)
        csv_text = str(data.get("csv_text") or "")
        selections = data.get("selections")
        if not isinstance(selections, list) or not selections:
            return {"ok": False, "error": "selections is required"}
        passwords = extract_passwords(csv_text)
        entity_id = str(data.get("entity_id") or "console-user")
        engine = _engine()
        try:
            saved: list[dict[str, Any]] = []
            for sel in selections:
                if not isinstance(sel, dict):
                    continue
                try:
                    index = int(sel.get("index", -1))
                except (TypeError, ValueError):
                    continue
                password = passwords.get(index, "")
                if not password:
                    saved.append({"index": index, "saved": False, "error": "no password in export for this row"})
                    continue
                try:
                    res = engine.save_custom_key(
                        entity_id,
                        str(sel.get("kind") or "byok"),
                        str(sel.get("label") or f"imported-{index}"),
                        password,
                        provider_hint=str(sel.get("provider_hint") or str(sel.get("url") or ""))[:80],
                    )
                    saved.append({"index": index, "saved": True, "id": res["id"], "label": res["label"]})
                except (AuthEngineError, ValueError) as exc:
                    saved.append({"index": index, "saved": False, "error": str(exc)})
            logger.info("csv import committed %d/%d rows", sum(1 for s in saved if s["saved"]), len(saved))
            return {"ok": True, "saved": saved}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_browser_preview(ctx: dict[str, Any]) -> dict[str, Any]:
        """List browser-saved-login labels after explicit consent (no passwords)."""
        from .browser_vault import BrowserVaultError, preview_chromium

        data = _body(ctx)
        if data.get("consent") is not True:
            return {"ok": False, "error": "explicit consent is required"}
        try:
            result = preview_chromium(str(data.get("browser") or "chrome"), consent=True)
            logger.info(
                "browser store preview: %s/%s %d entries",
                result["browser"],
                result["profile"],
                len(result["entries"]),
            )
            return {"ok": True, **result}
        except BrowserVaultError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_browser_import(ctx: dict[str, Any]) -> dict[str, Any]:
        """Decrypt selected browser entries straight into the vault."""
        from .browser_vault import BrowserVaultError, import_chromium

        data = _body(ctx)
        if data.get("consent") is not True:
            return {"ok": False, "error": "explicit consent is required"}
        selections = data.get("selections")
        if not isinstance(selections, list) or not selections:
            return {"ok": False, "error": "selections is required"}
        indices = _selection_indices(selections)
        engine = _engine()
        try:
            try:
                entries = import_chromium(str(data.get("browser") or "chrome"), consent=True, indices=indices)
            except BrowserVaultError as exc:
                return {"ok": False, "error": str(exc)}
            by_index = {}
            for sel in selections:
                if isinstance(sel, dict):
                    with suppress(TypeError, ValueError):
                        by_index[int(sel.get("index", -1))] = sel
            entity_id = str(data.get("entity_id") or "console-user")
            saved: list[dict[str, Any]] = []
            for entry in entries:
                sel = by_index.get(int(entry.get("index", -1)), {})
                try:
                    res = engine.save_custom_key(
                        entity_id,
                        str(sel.get("kind") or "byok"),
                        str(sel.get("label") or entry["url"] or f"browser-{entry['username']}")[:120],
                        entry["password"],
                        provider_hint=entry["url"][:80],
                    )
                    saved.append({"url": entry["url"], "saved": True, "id": res["id"], "label": res["label"]})
                except (AuthEngineError, ValueError) as exc:
                    saved.append({"url": entry["url"], "saved": False, "error": str(exc)})
            logger.info("browser import committed %d entries", sum(1 for s in saved if s["saved"]))
            return {"ok": True, "saved": saved}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_mail_fetch(ctx: dict[str, Any]) -> dict[str, Any]:
        """Read-only inbox fetch via a stored app password (consent-gated).

        Body: {key_id?, label?, max_messages?, query?}. Requires Personal
        MiniMind email-crawl consent, like the OAuth crawl. Returns headers
        + OTP-scrubbed snippets only — never full bodies, never secrets.
        """
        from ..integrations.mail_basic import fetch_inbox, resolve_app_password

        data = _body(ctx)
        entity_id = str(data.get("entity_id") or "console-user")
        try:
            from ..model_layer.minimind_personal_agent import MiniMindPersonalAgent

            consent = MiniMindPersonalAgent(state_dir=base).load_consent()
            if not consent.enabled or not consent.allow_email_crawl:
                return {
                    "ok": False,
                    "type": "consent_required",
                    "error": "Enable Personal MiniMind admin controls and email crawl consent before fetching mail.",
                }
        except Exception as exc:
            return {"ok": False, "error": f"consent check failed: {type(exc).__name__}"}
        engine = _engine()
        try:
            try:
                account = resolve_app_password(
                    engine, entity_id, key_id=str(data.get("key_id") or ""), label=str(data.get("label") or "")
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            try:
                max_messages = max(1, min(50, int(data.get("max_messages") or 10)))
            except (TypeError, ValueError):
                max_messages = 10
            try:
                result = fetch_inbox(
                    account["email"],
                    account["secret"],
                    max_messages=max_messages,
                    query=str(data.get("query") or "UNSEEN"),
                )
            except ValueError as exc:
                return {"ok": False, "error": str(exc)[:200]}
            result["account"] = account["label"]
            logger.info("app-password mail fetch for '%s': %d messages", account["label"], len(result["messages"]))
            return result
        finally:
            with suppress(Exception):
                engine.close()

    def auth_bluesky_post(ctx: dict[str, Any]) -> dict[str, Any]:
        """Publish a Bluesky post using a vault-stored app password.

        Login + post happen inside one call; session tokens never leave
        the request scope and are never stored. Body: {key_id, text}.
        """
        from ..integrations.bluesky_basic import BlueskyError, create_session, send_post

        data = _body(ctx)
        text = str(data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text is required"}
        engine = _engine()
        try:
            account = _vault_key_for(
                engine, str(data.get("entity_id") or "console-user"), str(data.get("key_id") or "")
            )
            if account is None:
                return {"ok": False, "error": "unknown key; save a Bluesky app password in Stored Keys first"}
            handle = (account["hint"] or account["label"]).strip()
            try:
                session = create_session(handle, account["secret"])
                result = send_post(session, text)
            except BlueskyError as exc:
                return {"ok": False, "error": str(exc)[:200]}
            return {"ok": True, "uri": result.get("uri", ""), "handle": handle}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_bluesky_timeline(ctx: dict[str, Any]) -> dict[str, Any]:
        """Read the Bluesky home timeline (text + authors only)."""
        from ..integrations.bluesky_basic import BlueskyError, create_session, get_timeline

        data = _body(ctx)
        engine = _engine()
        try:
            account = _vault_key_for(
                engine, str(data.get("entity_id") or "console-user"), str(data.get("key_id") or "")
            )
            if account is None:
                return {"ok": False, "error": "unknown key; save a Bluesky app password in Stored Keys first"}
            handle = (account["hint"] or account["label"]).strip()
            try:
                session = create_session(handle, account["secret"])
                try:
                    limit = max(1, min(25, int(data.get("limit") or 10)))
                except (TypeError, ValueError):
                    limit = 10
                feed = get_timeline(session, limit=limit)
            except BlueskyError as exc:
                return {"ok": False, "error": str(exc)[:200]}
            items = []
            for entry in (feed.get("feed") or [])[:limit]:
                post = entry.get("post") or {}
                author = post.get("author") or {}
                record = post.get("record") or {}
                items.append(
                    {
                        "author": author.get("handle", ""),
                        "text": str(record.get("text", ""))[:300],
                        "likes": (post.get("likeCount") or 0),
                    }
                )
            return {"ok": True, "handle": handle, "items": items}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_openrouter_start(ctx: dict[str, Any]) -> dict[str, Any]:
        """Begin Login with OpenRouter (yields a normal API key)."""
        data = _body(ctx)
        host = str((ctx.get("headers") or {}).get("host", "127.0.0.1:8766"))
        callback_base = str(data.get("callback_base") or "").strip() or f"http://{host}"
        engine = _engine()
        try:
            return engine.start_openrouter_login(str(data.get("entity_id") or "console-user"), callback_base)
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_openrouter_landing(ctx: dict[str, Any]) -> Any:
        """Browser landing for the OpenRouter redirect (?code=&setup=)."""
        query = ctx.get("query") if isinstance(ctx.get("query"), dict) else {}
        query = query or {}
        code, setup = str(query.get("code", "")), str(query.get("setup", ""))
        if not code or not setup:
            return _callback_html(False, "Incomplete login", "Missing code. Start over from Stored Keys.")
        engine = _engine()
        try:
            result = engine.finish_openrouter_login(code, setup)
            return _callback_html(
                True,
                "OpenRouter connected",
                f"Key '{result['label']}' saved to the vault. You can close this tab.",
            )
        except (AuthEngineError, ValueError) as exc:
            return _callback_html(False, "Login failed", str(exc)[:300])
        finally:
            with suppress(Exception):
                engine.close()

    def auth_keys_use_as_model(ctx: dict[str, Any]) -> dict[str, Any]:
        """Point the console model config at a vault key (no re-typing).

        Body: {key_id, provider, model?}. Mirrors the key value into the
        existing model.api_key path (existing ping/activation flows work
        unchanged) and records vault_key_id for the "used by model" badge.
        """
        data = _body(ctx)
        key_id = str(data.get("key_id") or "")
        provider = str(data.get("provider") or "").strip().lower()
        model = str(data.get("model") or "").strip()
        if not key_id or not provider:
            return {"ok": False, "error": "key_id and provider are required"}
        if len(provider) > 80 or len(model) > 300:
            return {"ok": False, "error": "provider/model is too long"}
        engine = _engine()
        try:
            try:
                revealed = engine.reveal_custom_key(str(data.get("entity_id") or "console-user"), key_id)
            except AuthEngineError as exc:
                return {"ok": False, "error": str(exc)}
            if revealed["kind"] != "byok":
                return {"ok": False, "error": "only API keys (byok) can back a model provider"}
        finally:
            with suppress(Exception):
                engine.close()
        try:
            from ..control_plane.config import CONFIG_FILE, load_config, save_config

            config = load_config()
            section = config.get("model")
            if not isinstance(section, dict):
                section = {}
                config["model"] = section
            section["provider"] = provider
            if model:
                section["model"] = model
            section["api_key"] = revealed["secret"]
            section["vault_key_id"] = revealed["id"]
            section["vault_label"] = revealed["label"]
            save_config(config)
            with suppress(OSError):
                os.chmod(CONFIG_FILE, 0o600)
            return {"ok": True, "provider": provider, "label": revealed["label"]}
        except Exception as exc:
            return {"ok": False, "error": f"could not save: {type(exc).__name__}"}

    def auth_keys_model_ref(_ctx: dict[str, Any]) -> dict[str, Any]:
        """Which vault key (if any) backs the console chat model. Labels only."""
        try:
            from ..control_plane.config import load_config

            model = load_config().get("model", {})
            if not isinstance(model, dict):
                return {"ok": True, "vault_key_id": "", "provider": ""}
            return {
                "ok": True,
                "vault_key_id": str(model.get("vault_key_id") or ""),
                "vault_label": str(model.get("vault_label") or ""),
                "provider": str(model.get("provider") or ""),
            }
        except Exception as exc:
            return {"ok": False, "error": f"could not read: {type(exc).__name__}"}

    def auth_approval_request(ctx: dict[str, Any]) -> dict[str, Any]:
        """Propose one connector write for human approval (agent proposes)."""
        from .action_approvals import ActionApprovalError

        data = _body(ctx)
        engine = _engine()
        try:
            return engine.request_action_approval(
                str(data.get("entity_id") or "console-user"),
                str(data.get("provider") or ""),
                str(data.get("method") or "POST"),
                str(data.get("url") or ""),
                data.get("data"),
                scope=str(data.get("scope") or ""),
                summary=str(data.get("summary") or ""),
                requested_by=str(data.get("requested_by") or "console"),
            )
        except (AuthEngineError, ValueError, ActionApprovalError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_approval_decide(ctx: dict[str, Any]) -> dict[str, Any]:
        """Human-only decision on a pending action approval.

        IDs starting with "apr-" are stealth loop asks: decided through the
        loop queue (which cascades to the durable record); everything else
        goes straight to the canonical authority.
        """
        data = _body(ctx)
        approval_id = str(data.get("id") or "")
        if not approval_id:
            return {"ok": False, "error": "id is required"}
        engine = _engine()
        try:
            if approval_id.startswith("apr-"):
                return _decide_stealth_approval(base, engine, approval_id, data)
            return engine.decide_action_approval(
                approval_id, approved=bool(data.get("approved")), actor=str(data.get("actor") or "console-user")
            )
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_approval_pending(ctx: dict[str, Any]) -> dict[str, Any]:
        """Pending approvals from the canonical store plus stealth asks.

        Connector items come from the durable authority; stealth loop items
        (source "stealth") are the loop queue mirrored there — one Trust
        surface for both, decided in one place. Mirrored stealth records
        (provider "stealth") are excluded from the connector list to avoid
        showing the same ask twice; for entity "stealth" the durable
        records are shown directly without queue mapping.
        """
        data = _body(ctx)
        entity_id = str(data.get("entity_id") or "console-user")
        engine = _engine()
        try:
            connector = engine.pending_action_approvals(entity_id)["approvals"]
            if entity_id == "stealth":
                for item in connector:
                    item["source"] = "connector"
                return {"ok": True, "approvals": connector}
            visible = [item for item in connector if item.get("provider") != "stealth"]
            for item in visible:
                item["source"] = "connector"
            stealth = _stealth_pending_approvals(base)
            return {"ok": True, "approvals": [*visible, *stealth]}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_audit_recent(ctx: dict[str, Any]) -> dict[str, Any]:
        """Recent trust-audit entries (redacted by construction)."""
        data = _body(ctx)
        engine = _engine()
        try:
            try:
                limit = max(1, min(200, int(data.get("limit") or 50)))
            except (TypeError, ValueError):
                limit = 50
            return {"ok": True, "entries": engine.audit.recent(limit=limit)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_write_gate(ctx: dict[str, Any]) -> dict[str, Any]:
        """Get or set the write-approval gate (opt-in; default off)."""
        data = _body(ctx)
        try:
            from ..control_plane.config import load_config, save_config

            if "enabled" in data:
                config = load_config()
                section = config.get("auth")
                if not isinstance(section, dict):
                    section = {}
                    config["auth"] = section
                section["require_write_approval"] = bool(data.get("enabled"))
                save_config(config)
                return {"ok": True, "enabled": bool(data.get("enabled"))}
            engine = _engine()
            try:
                return {"ok": True, "enabled": engine.write_approval_required()}
            finally:
                with suppress(Exception):
                    engine.close()
        except Exception as exc:
            return {"ok": False, "error": f"could not update: {type(exc).__name__}"}

    def _takeover_hooks() -> tuple[Any, Any]:
        """Pause/resume the stealth loop policy around a takeover."""
        from .stealth_service import get_service_loop

        def _pause() -> bool:
            loop = get_service_loop(base)
            was = bool(loop.policy.enabled)
            loop.policy.enabled = False
            return was

        def _resume() -> None:
            loop = get_service_loop(base)
            loop.policy.enabled = True

        return _pause, _resume

    def auth_takeover_start(ctx: dict[str, Any]) -> dict[str, Any]:
        """Hand the interactive surface to the operator (takeover mode).

        Pauses the stealth loop, blocks all live-executor agent actions,
        and stops capture. The operator logs in manually in their own
        browser/desktop; Ghost sees nothing typed. Body: {purpose?, url?}.
        """
        from ..stealth.takeover import TakeoverError, takeover_manager

        data = _body(ctx)
        manager = takeover_manager()
        pause, resume = _takeover_hooks()
        manager.set_loop_hooks(pause=pause, resume=resume)
        engine = _engine()
        try:
            try:
                state = manager.start(
                    purpose=str(data.get("purpose") or ""),
                    url=str(data.get("url") or ""),
                    actor=str(data.get("actor") or "console-user"),
                )
            except TakeoverError as exc:
                return {"ok": False, "error": str(exc)}
            engine.audit.record("takeover.start", detail={"purpose": state["purpose"], "url": state["url"] or None})
            return {"ok": True, **state}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_takeover_release(ctx: dict[str, Any]) -> dict[str, Any]:
        """Release takeover: resume the loop (restoring prior state)."""
        from ..stealth.takeover import takeover_manager

        data = _body(ctx)
        manager = takeover_manager()
        pause, resume = _takeover_hooks()
        manager.set_loop_hooks(pause=pause, resume=resume)
        engine = _engine()
        try:
            state = manager.release(actor=str(data.get("actor") or "console-user"))
            if state.get("released"):
                engine.audit.record("takeover.release", detail={"purpose": state.get("purpose")})
            return {"ok": True, **state}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_takeover_status(_ctx: dict[str, Any]) -> dict[str, Any]:
        from ..stealth.takeover import takeover_manager

        manager = takeover_manager()
        pause, resume = _takeover_hooks()
        manager.set_loop_hooks(pause=pause, resume=resume)
        return {"ok": True, **manager.status()}

    def _automations_engine() -> Any:
        from .automations import AutomationsEngine

        key = str(base)
        engine = _AUTOMATIONS_ENGINES.get(key)
        if engine is None:
            engine = AutomationsEngine(base)
            _AUTOMATIONS_ENGINES[key] = engine
        engine.ensure_running()
        return engine

    def auth_automations(ctx: dict[str, Any]) -> dict[str, Any]:
        """List automations + poller state."""
        try:
            engine = _automations_engine()
            return {"ok": True, "automations": engine.list(), "poller": "running"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def auth_automation_create(ctx: dict[str, Any]) -> dict[str, Any]:
        from .automations import AutomationError

        data = _body(ctx)
        try:
            engine = _automations_engine()
            created = engine.create(
                name=str(data.get("name") or ""),
                instruction=str(data.get("instruction") or ""),
                trigger=data.get("trigger") if isinstance(data.get("trigger"), dict) else {},
                action=data.get("action") if isinstance(data.get("action"), dict) else {"type": "log"},
                notify=str(data.get("notify") or "console"),
            )
            return {"ok": True, **created}
        except AutomationError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_automation_set(ctx: dict[str, Any]) -> dict[str, Any]:
        from .automations import AutomationError

        data = _body(ctx)
        automation_id = str(data.get("id") or "")
        if not automation_id:
            return {"ok": False, "error": "id is required"}
        try:
            engine = _automations_engine()
            if "enabled" in data:
                updated = engine.set_enabled(automation_id, enabled=bool(data.get("enabled")))
                return {"ok": True, **updated}
            if data.get("delete"):
                return {"ok": True, "deleted": engine.delete(automation_id)}
            return {"ok": False, "error": "enabled or delete is required"}
        except AutomationError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_automation_fire(ctx: dict[str, Any]) -> dict[str, Any]:
        """Run now (or continue with parent_run_id + note)."""
        from .automations import AutomationError

        data = _body(ctx)
        automation_id = str(data.get("id") or "")
        if not automation_id:
            return {"ok": False, "error": "id is required"}
        try:
            engine = _automations_engine()
            run = engine.fire(
                automation_id,
                trigger_context={"type": "manual"},
                parent_run_id=str(data.get("parent_run_id") or ""),
                note=str(data.get("note") or ""),
            )
            return {"ok": True, "run": run}
        except AutomationError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_automation_runs(ctx: dict[str, Any]) -> dict[str, Any]:
        data = _body(ctx)
        try:
            engine = _automations_engine()
            try:
                limit = max(1, min(200, int(data.get("limit") or 50)))
            except (TypeError, ValueError):
                limit = 50
            return {"ok": True, "runs": engine.runs(str(data.get("id") or ""), limit=limit)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def auth_automation_execute(ctx: dict[str, Any]) -> dict[str, Any]:
        """Complete an awaiting-approval run by consuming its approval."""
        from .automations import AutomationError

        data = _body(ctx)
        if not str(data.get("run_id") or "") or not str(data.get("approval_id") or ""):
            return {"ok": False, "error": "run_id and approval_id are required"}
        try:
            engine = _automations_engine()
            done = engine.execute_approved(str(data["run_id"]), str(data["approval_id"]))
            return {"ok": True, "run": done}
        except AutomationError as exc:
            return {"ok": False, "error": str(exc)}

    def auth_device_start(ctx: dict[str, Any]) -> dict[str, Any]:
        """Begin an RFC 8628 device login (no redirect URI — LAN-friendly).

        Returns user_code + verification_uri for display; the UI then polls
        /api/auth/device/poll until complete.
        """
        data = _body(ctx)
        provider = str(data.get("provider", ""))
        entity_id = str(data.get("entity_id", ""))
        if not provider or not entity_id:
            return {"ok": False, "error": "provider and entity_id are required"}
        scopes = data.get("scopes") if isinstance(data.get("scopes"), list) else None
        engine = _engine()
        try:
            return engine.start_device_login(provider, entity_id, scopes=scopes)
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_device_poll(ctx: dict[str, Any]) -> dict[str, Any]:
        """Single poll for a pending device login (UI calls repeatedly)."""
        data = _body(ctx)
        handle = str(data.get("handle", ""))
        if not handle:
            return {"ok": False, "error": "handle is required"}
        engine = _engine()
        try:
            return engine.poll_device_login(handle)
        except (AuthEngineError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            with suppress(Exception):
                engine.close()

    def auth_login_options(ctx: dict[str, Any]) -> dict[str, Any]:
        """Per-provider login capabilities for the Integrations tab.

        Tells the UI which flows each provider supports (device vs browser),
        where the effective client ID comes from, and the exact callback URL
        to register with the provider (for the redirect-URI mismatch check).
        """
        from .auth_engine import _PRESET_FOR
        from .oauth import get_preset

        host = str((ctx.get("headers") or {}).get("host", "127.0.0.1:8766"))
        callback_url = os.environ.get("GHOSTCHIMERA_OAUTH_CALLBACK", f"http://{host}/api/auth/callback")
        engine = _engine()
        try:
            options = []
            for key, provider in PROVIDERS.items():
                preset_id = _PRESET_FOR.get(key, key)
                try:
                    preset = get_preset(preset_id)
                except ValueError:
                    continue
                source = engine.client_id_source(preset_id)
                secret_source = engine.client_secret_source(preset_id)
                setup = _SETUP_COST.get(key, ("one-time-free", "Register a free OAuth client, then paste its ID."))
                options.append(
                    {
                        "key": key,
                        "display": provider.display,
                        "device_flow": preset.supports_device_flow,
                        "device_verification_url": preset.device_verification_url,
                        "browser_flow": True,
                        "client_id_source": source,
                        "client_id_configured": source != "none",
                        "client_secret_source": secret_source,
                        "client_secret_configured": secret_source != "none",
                        "setup_cost": setup[0],
                        "setup_note": setup[1],
                    }
                )
            return {"ok": True, "options": options, "callback_url": callback_url}
        finally:
            with suppress(Exception):
                engine.close()

    server.routes.register(
        "/api/connectors/providers",
        providers,
        method="GET",
        auth=auth,
        token=token,
        description="Connector catalog + redacted status",
    )
    server.routes.register(
        "/api/connectors/status",
        status,
        method="GET",
        auth=auth,
        token=token,
        description="Connector connection status",
    )
    server.routes.register(
        "/api/auth/authorize",
        auth_authorize,
        method="POST",
        auth=auth,
        token=token,
        description="OAuth authorize URL + state",
    )
    server.routes.register(
        "/api/auth/client-id",
        auth_client_id,
        method="POST",
        auth=auth,
        token=token,
        description="Save provider client ID",
    )
    server.routes.register(
        "/api/auth/callback",
        auth_callback,
        method="POST",
        auth=auth,
        token=token,
        description="OAuth callback + token exchange",
    )
    server.routes.register(
        "/api/auth/callback", auth_callback_page, method="GET", auth="open", description="OAuth browser landing page"
    )
    server.routes.register(
        "/api/auth/gh/status",
        auth_gh_status,
        method="POST",
        auth=auth,
        token=token,
        description="Detect a local GitHub CLI login",
    )
    server.routes.register(
        "/api/auth/gh/import",
        auth_gh_import,
        method="POST",
        auth=auth,
        token=token,
        description="Import the local GitHub CLI login",
    )
    server.routes.register(
        "/api/auth/keys/save",
        auth_keys_save,
        method="POST",
        auth=auth,
        token=token,
        description="Store a pasted key (write-only)",
    )
    server.routes.register(
        "/api/auth/keys/list",
        auth_keys_list,
        method="POST",
        auth=auth,
        token=token,
        description="Redacted key listing",
    )
    server.routes.register(
        "/api/auth/keys/delete",
        auth_keys_delete,
        method="POST",
        auth=auth,
        token=token,
        description="Delete a stored key",
    )
    server.routes.register(
        "/api/auth/import-csv/preview",
        auth_csv_preview,
        method="POST",
        auth=auth,
        token=token,
        description="Preview a browser CSV export",
    )
    server.routes.register(
        "/api/auth/import-csv/commit",
        auth_csv_commit,
        method="POST",
        auth=auth,
        token=token,
        description="Store selected CSV rows as keys",
    )
    server.routes.register(
        "/api/auth/browser/preview",
        auth_browser_preview,
        method="POST",
        auth=auth,
        token=token,
        description="Preview browser-saved logins (consent)",
    )
    server.routes.register(
        "/api/auth/browser/import",
        auth_browser_import,
        method="POST",
        auth=auth,
        token=token,
        description="Import selected browser logins (consent)",
    )
    server.routes.register(
        "/api/auth/mail/fetch",
        auth_mail_fetch,
        method="POST",
        auth=auth,
        token=token,
        description="App-password inbox fetch (consent-gated)",
    )
    server.routes.register(
        "/api/auth/bluesky/post",
        auth_bluesky_post,
        method="POST",
        auth=auth,
        token=token,
        description="Bluesky post via vault app password",
    )
    server.routes.register(
        "/api/auth/bluesky/timeline",
        auth_bluesky_timeline,
        method="POST",
        auth=auth,
        token=token,
        description="Bluesky timeline via vault app password",
    )
    server.routes.register(
        "/api/auth/openrouter/start",
        auth_openrouter_start,
        method="POST",
        auth=auth,
        token=token,
        description="Start Login with OpenRouter",
    )
    server.routes.register(
        "/api/auth/openrouter/landing",
        auth_openrouter_landing,
        method="GET",
        auth="open",
        description="OpenRouter browser landing page",
    )
    server.routes.register(
        "/api/auth/keys/use-as-model",
        auth_keys_use_as_model,
        method="POST",
        auth=auth,
        token=token,
        description="Point model config at a vault key",
    )
    server.routes.register(
        "/api/auth/keys/model-ref",
        auth_keys_model_ref,
        method="POST",
        auth=auth,
        token=token,
        description="Which vault key backs the chat model",
    )
    server.routes.register(
        "/api/auth/approvals/request",
        auth_approval_request,
        method="POST",
        auth=auth,
        token=token,
        description="Propose a connector write for approval",
    )
    server.routes.register(
        "/api/auth/approvals/decide",
        auth_approval_decide,
        method="POST",
        auth=auth,
        token=token,
        description="Approve or deny a pending action",
    )
    server.routes.register(
        "/api/auth/approvals/pending",
        auth_approval_pending,
        method="POST",
        auth=auth,
        token=token,
        description="List pending action approvals",
    )
    server.routes.register(
        "/api/auth/audit/recent",
        auth_audit_recent,
        method="POST",
        auth=auth,
        token=token,
        description="Recent trust-audit entries",
    )
    server.routes.register(
        "/api/auth/write-gate",
        auth_write_gate,
        method="POST",
        auth=auth,
        token=token,
        description="Get/set the write-approval gate",
    )
    server.routes.register(
        "/api/auth/takeover/start",
        auth_takeover_start,
        method="POST",
        auth=auth,
        token=token,
        description="Hand the browser/desktop to the operator",
    )
    server.routes.register(
        "/api/auth/takeover/release",
        auth_takeover_release,
        method="POST",
        auth=auth,
        token=token,
        description="Release takeover and resume",
    )
    server.routes.register(
        "/api/auth/takeover/status",
        auth_takeover_status,
        method="POST",
        auth=auth,
        token=token,
        description="Takeover state",
    )
    server.routes.register(
        "/api/auth/automations",
        auth_automations,
        method="POST",
        auth=auth,
        token=token,
        description="List automations",
    )
    server.routes.register(
        "/api/auth/automations/create",
        auth_automation_create,
        method="POST",
        auth=auth,
        token=token,
        description="Create an automation",
    )
    server.routes.register(
        "/api/auth/automations/set",
        auth_automation_set,
        method="POST",
        auth=auth,
        token=token,
        description="Pause/resume/delete an automation",
    )
    server.routes.register(
        "/api/auth/automations/fire",
        auth_automation_fire,
        method="POST",
        auth=auth,
        token=token,
        description="Run now or continue a run",
    )
    server.routes.register(
        "/api/auth/automations/runs",
        auth_automation_runs,
        method="POST",
        auth=auth,
        token=token,
        description="Run history",
    )
    server.routes.register(
        "/api/auth/automations/execute",
        auth_automation_execute,
        method="POST",
        auth=auth,
        token=token,
        description="Execute an approved run",
    )
    server.routes.register(
        "/api/auth/device/start",
        auth_device_start,
        method="POST",
        auth=auth,
        token=token,
        description="Start RFC 8628 device login",
    )
    server.routes.register(
        "/api/auth/device/poll",
        auth_device_poll,
        method="POST",
        auth=auth,
        token=token,
        description="Poll a pending device login",
    )
    server.routes.register(
        "/api/auth/login-options",
        auth_login_options,
        method="GET",
        auth=auth,
        token=token,
        description="Per-provider login capabilities + callback URL",
    )
    server.routes.register(
        "/api/auth/status", auth_status, method="POST", auth=auth, token=token, description="Redacted connection status"
    )
    server.routes.register(
        "/api/auth/revoke", auth_revoke, method="POST", auth=auth, token=token, description="Revoke a connection"
    )
    server.routes.register(
        "/api/connectors/first-run",
        lambda _ctx: first_run_status(base),
        method="GET",
        auth=auth,
        token=token,
        description="Guided first-run checklist",
    )

    # -- Stealth activity monitor + pre-fill drafts (STE-checked) ----------
    def stealth_activity(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop

        loop = get_service_loop(base)
        interventions = []
        for item in list(loop.interventions.values())[-25:]:
            interventions.append(
                {
                    "id": item.id,
                    "workflow": item.workflow,
                    "state": str(item.state),
                    "outcome": str(item.outcome),
                    "confidence": item.confidence,
                    "reason": item.reason,
                    "drafts": len(draft_actions(item)),
                    "approval": (item.provenance or {}).get("approval"),
                }
            )
        recent = []
        store_error = ""
        if loop.store is not None:
            try:
                for event in loop.store.recent_events(limit=25):
                    recent.append(
                        {
                            "event_id": event["event_id"],
                            "event_type": event["event_type"],
                            "actor": event["actor"],
                            "source": event["source"],
                            "timestamp": event["timestamp"],
                        }
                    )
            except Exception as exc:
                # Never present "no activity" as fact when the store failed.
                # Keep the detail server-side; the client only learns that
                # the timeline read failed (no paths, DSNs, or SQL leak).
                logger.warning("stealth recent-events read failed: %s", exc)
                store_error = "recent-events-unavailable"
        return {
            "ok": True,
            "events_processed": loop.bus.processed,
            "recent_events": recent,
            "recent_events_error": store_error,
            "interventions": interventions,
            "workflows": [h.to_dict() for h in loop.learner.hypotheses()[:8]],
            "autonomy": loop.policy.autonomy.name,
            "enabled": loop.policy.enabled,
        }

    def stealth_drafts(_ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import draft_actions, get_service_loop, ste_prefill

        loop = get_service_loop(base)
        drafts = []
        for item in loop.interventions.values():
            actions = draft_actions(item)
            if not actions:
                continue
            drafts.append(
                {
                    "id": item.id,
                    "workflow": item.workflow,
                    "state": str(item.state),
                    "summary": (item.provenance or {}).get("event_summary", ""),
                    "approval": (item.provenance or {}).get("approval"),
                    "actions": [ste_prefill(a) for a in actions],
                }
            )
        return {"ok": True, "drafts": drafts}

    def stealth_approve(ctx: dict[str, Any]) -> dict[str, Any]:
        from .stealth_service import approve_draft, get_service_loop

        data = _body(ctx)
        iid = str(ctx.get("path", "")).rsplit("/", 2)[-2]
        return approve_draft(
            get_service_loop(base),
            iid,
            final_text=str(data.get("text", "")),
            connections=data.get("connections") if isinstance(data.get("connections"), dict) else None,
        )

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
        return {
            "ok": True,
            "ste_text": payload["body"],
            "ste_rules": checked.rules_applied,
            "ste_warnings": checked.warnings,
        }

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
        return {
            "ok": True,
            "delivered": delivered,
            "decision": str(result.decision) if result else "none",
            "intervention_id": result.intervention_id if result else "",
        }

    def stealth_simplify(ctx: dict[str, Any]) -> dict[str, Any]:
        from ..stealth.ste import simplify

        result = simplify(str(_body(ctx).get("text", "")))
        return {"ok": True, "ste_text": result.text, "ste_rules": result.rules_applied, "ste_warnings": result.warnings}

    def stealth_draft_action(ctx: dict[str, Any]) -> dict[str, Any]:
        """POST /api/stealth/drafts/{id}/approve|edit — suffix-dispatched."""
        path = str(ctx.get("path", "")).rstrip("/")
        if path.endswith("/approve"):
            return stealth_approve(ctx)
        if path.endswith("/edit"):
            return stealth_edit(ctx)
        return {"ok": False, "error": "unknown draft action (use approve|edit)"}

    server.routes.register(
        "/api/stealth/activity",
        stealth_activity,
        method="GET",
        auth=auth,
        token=token,
        description="Stealth loop activity feed",
    )
    server.routes.register(
        "/api/stealth/drafts", stealth_drafts, method="GET", auth=auth, token=token, description="STE pre-fill drafts"
    )
    server.routes.register(
        "/api/stealth/drafts/",
        stealth_draft_action,
        method="POST",
        prefix=True,
        auth=auth,
        token=token,
        description="Draft approve/edit by id suffix",
    )
    server.routes.register(
        "/api/stealth/emit",
        stealth_emit,
        method="POST",
        auth=auth,
        token=token,
        description="Emit event into the Stealth loop",
    )
    server.routes.register(
        "/api/stealth/simplify",
        stealth_simplify,
        method="POST",
        auth=auth,
        token=token,
        description="STE-check arbitrary text",
    )

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
                context,
            )
            return {"ok": True, "ghost_suggestion": str(suggestion)[:500], "provider": llm.provider_name}
        except Exception as exc:
            return {"ok": False, "error": f"no completion available: {type(exc).__name__}"}

    server.routes.register(
        "/api/stealth/ghost-write",
        ghost_write,
        method="POST",
        auth=auth,
        token=token,
        description="Ghost-writer completions",
    )

    # -- Operator tools: CLI parity for the web console ----------------------
    # Thin dispatch over the same library functions the terminal CLIs call,
    # so CLI-only capabilities are also clickable in the console. Imports stay
    # lazy (inside each handler) so a heavy/optional dependency can never
    # break console startup. Handlers receive (args, base) and must return
    # JSON-serializable data or raise.

    def _tool_pilot_status(_args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.kernel import ChimeraPilotKernel

        return ChimeraPilotKernel.default().status()

    def _tool_pilot_calibrate(_args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.kernel import ChimeraPilotKernel

        return ChimeraPilotKernel.default().calibrate()

    def _tool_autonomy_profiles(_args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.autonomy import list_autonomy_profiles

        return {"profiles": [profile.to_dict() for profile in list_autonomy_profiles()]}

    def _tool_model_profiles(_args: dict[str, Any], _base: Path) -> Any:
        from ..model_layer.local_profiles import list_local_model_profiles

        return {"profiles": [profile.to_dict() for profile in list_local_model_profiles()]}

    def _tool_runtime_warmup(args: dict[str, Any], base_dir: Path) -> Any:
        from ..model_layer.runtime_specialization import (
            detect_runtime_environment,
            warm_runtime_specialization_cache,
        )

        cache_dir = str(args.get("cache_dir") or "").strip() or str(base_dir / "runtime-specialization")
        environment = detect_runtime_environment()
        return warm_runtime_specialization_cache(
            cache_dir=cache_dir,
            profile_names="tiny",
            environment=environment,
        )

    def _tool_desktop_stop(args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.desktop_policy import write_desktop_stop_file

        path = str(args.get("path") or "").strip() or None
        reason = str(args.get("reason") or "operator_stop").strip()[:120] or "operator_stop"
        target = write_desktop_stop_file(path, reason=reason)
        return {"ok": True, "path": str(target), "reason": reason}

    def _tool_ux_audit(_args: dict[str, Any], _base: Path) -> Any:
        from ..control_plane.cli import _ux_audit_payload

        return _ux_audit_payload()

    def _tool_saas_status(_args: dict[str, Any], _base: Path) -> Any:
        from ..saas.cli import saas_status_from_env

        return saas_status_from_env()

    def _tool_worker_status(_args: dict[str, Any], _base: Path) -> Any:
        from ..saas.store import InMemorySaasStore
        from ..saas.worker import WorkerQueue

        return WorkerQueue(InMemorySaasStore()).status()

    def _tool_evals_run(args: dict[str, Any], _base: Path) -> Any:
        from ..evals.runner import EVAL_SUITES, run_suite

        suite = str(args.get("suite") or "smoke").strip()
        if suite not in EVAL_SUITES:
            raise ValueError(f"Unknown eval suite: {suite!r}")
        return run_suite(suite)

    def _tool_production_gaps(_args: dict[str, Any], _base: Path) -> Any:
        from ..production_gaps import scan_production_gaps

        return scan_production_gaps(Path(__file__).resolve().parents[2])

    def _tool_context_compress(args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.context_compressor import compress_text_query_aware

        text = str(args.get("text") or "").strip()
        if not text:
            raise ValueError("Provide text to compress.")
        try:
            budget = int(args.get("budget_tokens") or 800)
        except (TypeError, ValueError):
            budget = 800
        budget = max(64, min(4000, budget))
        result = compress_text_query_aware(
            text,
            focus=str(args.get("focus") or ""),
            budget_tokens=budget,
        )
        return result.to_dict() if hasattr(result, "to_dict") else result

    def _tool_workspace_clear(_args: dict[str, Any], base: Path) -> Any:
        from ..cognition_layer.workspace_state import OperatorWorkspaceStore

        store = OperatorWorkspaceStore(state_dir=base)
        return store.clear()

    def _tool_minimind_architectures(_args: dict[str, Any], _base: Path) -> Any:
        from ..model_layer.minimind_runtime import list_minimind_architectures, minimind_source_metadata

        return {
            "architectures": [spec.to_dict() for spec in list_minimind_architectures()],
            "sources": minimind_source_metadata(),
        }

    def _tool_minimind_log_failure(args: dict[str, Any], base: Path) -> Any:
        from ..model_layer.minimind_lifecycle import MiniMindLifecycle

        prompt = str(args.get("prompt") or "").strip()
        response = str(args.get("response") or "").strip()
        if not prompt or not response:
            raise ValueError("Provide both prompt and response.")
        try:
            confidence = float(args.get("confidence") if args.get("confidence") not in (None, "") else 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        raw_threshold = str(args.get("threshold") or "").strip()
        try:
            threshold = float(raw_threshold) if raw_threshold else 0.5
        except (TypeError, ValueError):
            threshold = 0.5
        lifecycle = MiniMindLifecycle(state_dir=base)
        logged = lifecycle.log_low_confidence(
            prompt=prompt,
            response=response,
            confidence=confidence,
            threshold=threshold,
        )
        return {"ok": True, "logged": logged, "confidence": confidence, "threshold": threshold}

    def _tool_minimind_beta_vision(args: dict[str, Any], base: Path) -> Any:
        from ..model_layer.minimind_beta_orchestrator import BetaVisionConfig, run_beta_vision

        profile = str(args.get("profile") or "").strip() or None
        memory_db = str(args.get("memory_db") or "").strip() or ".ghostchimera-memory.sqlite3"
        run_jobs = str(args.get("run_autonomy_jobs") or "false").strip().lower() in {"1", "true", "yes"}
        config = BetaVisionConfig(
            memory_db=memory_db,
            file_paths=[],
            email_paths=[],
            run_autonomy_jobs=run_jobs,
            autonomy_profile="supervised",
            autonomy_jobs=["self-audit", "memory-refresh"],
        )
        return run_beta_vision(config=config, state_dir=base, profile_name=profile)

    def _tool_local_model_profiles(_args: dict[str, Any], _base: Path) -> Any:
        from ..control_plane.local_model_cli import local_model_profiles_payload

        return local_model_profiles_payload()

    def _tool_local_model_check(args: dict[str, Any], _base: Path) -> Any:
        from ..control_plane.local_model_cli import local_model_check_payload

        return local_model_check_payload(str(args.get("profile") or ""))

    def _tool_local_model_guide(args: dict[str, Any], _base: Path) -> Any:
        from ..control_plane.local_model_cli import local_model_guide_payload

        return local_model_guide_payload(str(args.get("profile") or ""))

    def _tool_cognition_handoff_verify(args: dict[str, Any], _base: Path) -> Any:
        from ..cognition_layer.trust import GhostHandoff, verify_handoff

        handoff_json = str(args.get("handoff_json") or "").strip()
        if not handoff_json:
            raise ValueError("Provide handoff JSON to verify.")
        result = verify_handoff(GhostHandoff.from_json(handoff_json))
        return {"ok": result.accepted, "result": result.to_dict()}

    def _tool_doctor(args: dict[str, Any], _base: Path) -> Any:
        from ..control_plane.doctor import doctor_checks

        production = str(args.get("production") or "false").strip().lower() in {"1", "true", "yes"}
        return doctor_checks(production=production)

    def _tool_eve_scan(args: dict[str, Any], _base: Path) -> Any:
        from ..stealth.project_scan import scan_project

        root = str(args.get("root") or "").strip() or str(Path(__file__).resolve().parents[2])
        strict = str(args.get("strict") or "true").strip().lower() not in {"0", "false", "no"}
        report = scan_project(root, strict=strict)
        return report.to_dict()

    def _tool_pilot_compile(args: dict[str, Any], _base: Path) -> Any:
        from ..chimera_pilot.kernel import ChimeraPilotKernel

        objective = str(args.get("objective") or "").strip()
        if not objective:
            raise ValueError("Provide an objective to compile.")
        kernel = ChimeraPilotKernel.default(include_deterministic_backend=True)
        return [
            {
                "id": task.id,
                "kind": task.kind.value,
                "objective": task.objective,
                "inputs": task.inputs,
                "constraints": task.constraints,
                "privacy_level": task.privacy_level,
                "requires_network": task.requires_network,
            }
            for task in kernel.compile(objective)
        ]

    def _tool_pilot_runtime_specialization(args: dict[str, Any], _base: Path) -> Any:
        from ..model_layer.local_profiles import get_local_model_profile
        from ..model_layer.runtime_specialization import (
            detect_runtime_environment,
            plan_runtime_specialization,
            workload_from_messages,
        )

        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Provide a prompt to plan runtime specialization for.")
        profile_name = str(args.get("profile") or "tiny").strip() or "tiny"
        profile = get_local_model_profile(profile_name)
        try:
            estimated_output_tokens = int(args.get("estimated_output_tokens") or 128)
        except (TypeError, ValueError):
            estimated_output_tokens = 128
        try:
            batch_size = int(args.get("batch_size") or 1)
        except (TypeError, ValueError):
            batch_size = 1
        workload = workload_from_messages(
            user_message=prompt,
            estimated_output_tokens=estimated_output_tokens,
            batch_size=batch_size,
            dtype=str(args.get("dtype") or "") or profile.quantization,
        )
        environment = detect_runtime_environment()
        plan = plan_runtime_specialization(profile=profile, workload=workload, environment=environment)
        return plan.to_dict()

    def _tool_parallel_run(args: dict[str, Any], base: Path) -> Any:
        from ..chimera_pilot.agent_pool import BatchAgent

        objectives = [line.strip() for line in str(args.get("objectives") or "").splitlines() if line.strip()]
        if not objectives:
            raise ValueError("Provide one objective per line.")
        try:
            workers = int(args.get("workers") or 1)
        except (TypeError, ValueError):
            workers = 1
        workers = max(1, min(16, workers))
        output_dir = str(args.get("output_dir") or "").strip() or str(base / "parallel_output")
        runner = BatchAgent(objectives=objectives, workers=workers, output_dir=output_dir)
        return runner.run().to_dict()

    def _tool_parallel_batch(args: dict[str, Any], base: Path) -> Any:
        from ..chimera_pilot.agent_pool import ParallelAgent

        jsonl_text = str(args.get("jsonl") or "").strip()
        if not jsonl_text:
            raise ValueError("Paste JSONL with one objective/prompt per line.")
        dataset_file = base / "parallel_batch_input.jsonl"
        dataset_file.write_text(jsonl_text, encoding="utf-8")
        try:
            workers = int(args.get("workers") or 4)
        except (TypeError, ValueError):
            workers = 4
        workers = max(1, min(16, workers))
        output_dir = str(args.get("output_dir") or "").strip() or str(base / "batch_output")
        runner = ParallelAgent(jsonl_file=str(dataset_file), workers=workers, output_dir=output_dir)
        return runner.run().to_dict()

    _TOOL_HANDLERS: dict[str, Any] = {
        "pilot-status": _tool_pilot_status,
        "pilot-calibrate": _tool_pilot_calibrate,
        "pilot-compile": _tool_pilot_compile,
        "pilot-runtime-specialization": _tool_pilot_runtime_specialization,
        "parallel-run": _tool_parallel_run,
        "parallel-batch": _tool_parallel_batch,
        "autonomy-profiles": _tool_autonomy_profiles,
        "model-profiles": _tool_model_profiles,
        "local-model-profiles": _tool_local_model_profiles,
        "local-model-check": _tool_local_model_check,
        "local-model-guide": _tool_local_model_guide,
        "minimind-architectures": _tool_minimind_architectures,
        "minimind-log-failure": _tool_minimind_log_failure,
        "minimind-beta-vision": _tool_minimind_beta_vision,
        "cognition-handoff-verify": _tool_cognition_handoff_verify,
        "doctor": _tool_doctor,
        "eve-scan": _tool_eve_scan,
        "workspace-clear": _tool_workspace_clear,
        "runtime-warmup": _tool_runtime_warmup,
        "desktop-stop": _tool_desktop_stop,
        "ux-audit": _tool_ux_audit,
        "saas-status": _tool_saas_status,
        "worker-status": _tool_worker_status,
        "evals-run": _tool_evals_run,
        "production-gaps": _tool_production_gaps,
        "context-compress": _tool_context_compress,
    }

    def _tools_catalog() -> list[dict[str, Any]]:
        try:
            from ..evals.runner import EVAL_SUITES

            suites = sorted(EVAL_SUITES)
        except Exception:
            suites = ["smoke"]
        return [
            {
                "id": "pilot-status",
                "title": "Pilot backend status",
                "description": "Health and telemetry of the Chimera Pilot kernel. Same as the pilot status command.",
                "inputs": [],
            },
            {
                "id": "pilot-calibrate",
                "title": "Calibrate backends",
                "description": "Probe every registered pilot backend once. Same as the pilot calibrate command. Can take a minute.",
                "inputs": [],
            },
            {
                "id": "autonomy-profiles",
                "title": "Autonomy profiles",
                "description": "List the built-in autonomy profiles. Same as the pilot autonomy-profiles command.",
                "inputs": [],
            },
            {
                "id": "model-profiles",
                "title": "Local model profiles",
                "description": "List the built-in local model profiles. Same as the pilot model-profiles command.",
                "inputs": [],
            },
            {
                "id": "runtime-warmup",
                "title": "Runtime warmup",
                "description": "Precompute local runtime specialization manifests into the console state dir. Same as the pilot runtime-warmup command. Can take a while.",
                "inputs": [],
            },
            {
                "id": "desktop-stop",
                "title": "Desktop kill-switch",
                "description": "Create the desktop kill-switch file immediately. Same as the pilot desktop-stop command.",
                "confirm": "Create the desktop kill-switch file now?",
                "inputs": [
                    {"name": "path", "label": "Kill-switch path (optional)", "placeholder": "default location"},
                    {"name": "reason", "label": "Reason", "placeholder": "operator_stop"},
                ],
            },
            {
                "id": "ux-audit",
                "title": "UX audit",
                "description": "UX strengths, gaps, and upgrade scorecard. Same as ghost ux-audit.",
                "inputs": [],
            },
            {
                "id": "saas-status",
                "title": "SaaS status",
                "description": "Enterprise SaaS launch-mode readiness. Same as ghost saas status.",
                "inputs": [],
            },
            {
                "id": "worker-status",
                "title": "Worker queue status",
                "description": "Inspect the SaaS worker queue. Same as ghost worker status.",
                "inputs": [],
            },
            {
                "id": "evals-run",
                "title": "Run eval suite",
                "description": "Run a Ghost Chimera evaluation suite. Same as evals run --suite. Can take a while.",
                "inputs": [
                    {"name": "suite", "label": "Suite", "type": "select", "options": suites},
                ],
            },
            {
                "id": "production-gaps",
                "title": "Production gaps",
                "description": "Scan the repo for production-readiness gaps. Same as ghost production-gaps.",
                "inputs": [],
            },
            {
                "id": "context-compress",
                "title": "Compress context",
                "description": "Query-aware deterministic compression preview. Same as ghost context.",
                "inputs": [
                    {"name": "text", "label": "Text", "type": "textarea", "placeholder": "Paste text to compress"},
                    {"name": "focus", "label": "Focus query (optional)", "placeholder": ""},
                    {"name": "budget_tokens", "label": "Token budget", "placeholder": "800"},
                ],
            },
            {
                "id": "pilot-compile",
                "title": "Compile objective (dry run)",
                "description": "Compile one objective into planned tasks without executing them. Same as the pilot compile command.",
                "inputs": [
                    {
                        "name": "objective",
                        "label": "Objective",
                        "type": "textarea",
                        "placeholder": "Objective to compile",
                    },
                ],
            },
            {
                "id": "pilot-runtime-specialization",
                "title": "Plan runtime specialization",
                "description": "Plan local runtime specialization for a prompt. Same as the pilot runtime-specialization command.",
                "inputs": [
                    {
                        "name": "prompt",
                        "label": "Prompt",
                        "type": "textarea",
                        "placeholder": "Prompt used to estimate workload shape",
                    },
                    {"name": "profile", "label": "Local model profile", "placeholder": "tiny"},
                    {"name": "estimated_output_tokens", "label": "Estimated output tokens", "placeholder": "128"},
                    {"name": "batch_size", "label": "Batch size", "placeholder": "1"},
                    {"name": "dtype", "label": "Dtype hint (optional)", "placeholder": ""},
                ],
            },
            {
                "id": "parallel-run",
                "title": "Run objectives in parallel",
                "description": "Run several objectives with a worker pool. Same as ghostchimera-parallel run. Executes work; can take a while.",
                "confirm": "Run these objectives in parallel? This executes real work.",
                "inputs": [
                    {
                        "name": "objectives",
                        "label": "Objectives (one per line)",
                        "type": "textarea",
                        "placeholder": "One objective per line",
                    },
                    {"name": "workers", "label": "Parallel workers", "placeholder": "1"},
                    {"name": "output_dir", "label": "Output dir (optional)", "placeholder": ""},
                ],
            },
            {
                "id": "parallel-batch",
                "title": "Batch run from JSONL",
                "description": "Run objectives from pasted JSONL lines in parallel. Same as ghostchimera-parallel batch. Executes work; can take a while.",
                "confirm": "Run this JSONL batch in parallel? This executes real work.",
                "inputs": [
                    {
                        "name": "jsonl",
                        "label": "JSONL (one objective/prompt per line)",
                        "type": "textarea",
                        "placeholder": '{"objective": "..."}',
                    },
                    {"name": "workers", "label": "Workers", "placeholder": "4"},
                    {"name": "output_dir", "label": "Output dir (optional)", "placeholder": ""},
                ],
            },
            {
                "id": "local-model-profiles",
                "title": "Local model profiles",
                "description": "List local model profiles with this machine's resource fit. Same as ghost local-model profiles.",
                "inputs": [],
            },
            {
                "id": "local-model-check",
                "title": "Check local model profile",
                "description": "Check whether a local model profile fits this machine. Same as ghost local-model check.",
                "inputs": [
                    {"name": "profile", "label": "Profile", "placeholder": "balanced"},
                ],
            },
            {
                "id": "local-model-guide",
                "title": "Local model install guide",
                "description": "Show install steps for a local model profile. Same as ghost local-model guide.",
                "inputs": [
                    {"name": "profile", "label": "Profile", "placeholder": "balanced"},
                ],
            },
            {
                "id": "minimind-architectures",
                "title": "MiniMind architectures",
                "description": "List the supported MiniMind model architectures. Same as ghost minimind architectures.",
                "inputs": [],
            },
            {
                "id": "minimind-log-failure",
                "title": "Log MiniMind low-confidence failure",
                "description": "Append a low-confidence record to the MiniMind failure log. Same as ghost minimind log-failure.",
                "inputs": [
                    {"name": "prompt", "label": "Prompt", "type": "textarea", "placeholder": "Prompt that failed"},
                    {
                        "name": "response",
                        "label": "Response",
                        "type": "textarea",
                        "placeholder": "Low-confidence response",
                    },
                    {"name": "confidence", "label": "Confidence (0-1)", "placeholder": "0.3"},
                    {"name": "threshold", "label": "Threshold (optional)", "placeholder": "0.5"},
                ],
            },
            {
                "id": "minimind-beta-vision",
                "title": "Run MiniMind beta vision",
                "description": "Bootstrap the personal MiniMind dataset and surface task hints. Same as ghost minimind beta-vision. Can take a while.",
                "inputs": [
                    {"name": "profile", "label": "Profile (optional)", "placeholder": ""},
                    {
                        "name": "memory_db",
                        "label": "Memory DB (optional)",
                        "placeholder": ".ghostchimera-memory.sqlite3",
                    },
                    {
                        "name": "run_autonomy_jobs",
                        "label": "Enqueue autonomy jobs",
                        "type": "select",
                        "options": ["false", "true"],
                    },
                ],
            },
            {
                "id": "cognition-handoff-verify",
                "title": "Verify cognition handoff",
                "description": "Verify a GhostHandoff payload's trust envelope. Same as ghost cognition handoff verify.",
                "inputs": [
                    {
                        "name": "handoff_json",
                        "label": "Handoff JSON",
                        "type": "textarea",
                        "placeholder": '{"handoff_id": "..."}',
                    },
                ],
            },
            {
                "id": "doctor",
                "title": "Doctor health checks",
                "description": "Run the Ghost Chimera health checks (Python, config, provider, safety, MiniMind, skills). Same as ghostchimera doctor.",
                "inputs": [
                    {
                        "name": "production",
                        "label": "Production mode",
                        "type": "select",
                        "options": ["false", "true"],
                    },
                ],
            },
            {
                "id": "eve-scan",
                "title": "EVE project scan",
                "description": "Run the strict EVE project scan for secrets and policy issues. Same as ghost-eve-scan.",
                "inputs": [
                    {"name": "root", "label": "Repo root (optional)", "placeholder": "defaults to this repo"},
                    {
                        "name": "strict",
                        "label": "Strict policy",
                        "type": "select",
                        "options": ["true", "false"],
                    },
                ],
            },
            {
                "id": "workspace-clear",
                "title": "Clear operator workspace",
                "description": "Clear the operator workspace state. Same as ghost workspace clear. Destructive and irreversible.",
                "confirm": "Clear the operator workspace? This permanently deletes workspace state.",
                "inputs": [],
            },
        ]

    def tools_catalog(_ctx: dict[str, Any]) -> dict[str, Any]:
        """GET /api/tools/catalog — operator tools available in this console."""
        return {"ok": True, "tools": _tools_catalog()}

    def tools_run(ctx: dict[str, Any]) -> dict[str, Any]:
        """POST /api/tools/run {tool, args?} — run one operator tool."""
        data = _body(ctx)
        name = str(data.get("tool") or "").strip()
        args = data.get("args")
        args = args if isinstance(args, dict) else {}
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {"ok": False, "error": f"Unknown tool: {name or '(empty)'}. See GET /api/tools/catalog."}
        try:
            result = handler(args, base)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "tool": name, "result": result}

    server.routes.register(
        "/api/tools/catalog",
        tools_catalog,
        method="GET",
        auth=auth,
        token=token,
        description="Operator tools catalog (CLI parity)",
    )
    server.routes.register(
        "/api/tools/run",
        tools_run,
        method="POST",
        auth=auth,
        token=token,
        description="Run one operator tool",
    )

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
        delivery_id = str(ctx.get("headers", {}).get("x-delivery-id", "") or _uuid.uuid4().hex[:12])
        event = normalize_webhook(source, delivery_id, va_id, _body(ctx))
        if event is None:
            # Verification pings, bot echoes, empty payloads: ack, don't learn.
            return {"ok": True, "queued": False, "reason": "ignored (ping/echo/empty)"}
        loop = get_service_loop(base)
        delivered = loop.emit(event)
        result = loop.last_result
        return {
            "ok": True,
            "queued": True,
            "event_id": event.event_id,
            "delivered": delivered,
            "decision": str(result.decision) if result else "none",
            "intervention_id": result.intervention_id if result else "",
            "received_at": _time.time(),
        }

    server.routes.register(
        "/api/webhooks/",
        inbound_webhook,
        method="POST",
        prefix=True,
        auth="open",
        description="Unified inbound webhooks per VA",
    )


__all__ = ["register_connector_routes"]
