"""In-console Stealth service: one shared loop + store per state dir.

The browser Console runs in its own process, so the Stealth tab needs a
process-local StealthLoop backed by the same SQLite journal pattern as
everywhere else. All helpers are pure enough to unit-test without HTTP.
Every pre-fill shown or sent passes through the STE simplifier.
"""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

_TEXT_KEYS = ("body", "text", "message", "content", "reply")


def extract_draft_text(action: dict[str, Any]) -> str:
    """Best-effort human text from an agent action payload."""
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def ste_prefill(action: dict[str, Any]) -> dict[str, Any]:
    """STE-simplified pre-fill for one action + the rules applied."""
    from ..stealth.ste import simplify

    original = extract_draft_text(action)
    result = simplify(original) if original else None
    return {
        "provider": str(action.get("provider", "")),
        "endpoint": str(action.get("endpoint", "")),
        "original": original,
        "ste_text": result.text if result else "",
        "ste_rules": result.rules_applied if result else [],
        "ste_warnings": result.warnings if result else [],
    }


def draft_actions(intervention: Any) -> list[dict[str, Any]]:
    """Action list behind an intervention (draft or agent provenance)."""
    context = getattr(intervention, "context", {}) or {}
    actions = context.get("draft") or []
    if not actions:
        provenance = getattr(intervention, "provenance", {}) or {}
        actions = provenance.get("actions") or []
    return [a for a in actions if isinstance(a, dict)]


_lock = threading.Lock()
_loops: dict[str, Any] = {}


def get_service_loop(state_dir: str | Path) -> Any:
    """Process-local StealthLoop with durable journal (singleton per dir)."""
    from ..stealth.context import ContextFabric, InMemoryRetriever
    from ..stealth.loop import StealthLoop
    from ..stealth.store import StealthStore

    key = str(Path(state_dir))
    with _lock:
        loop = _loops.get(key)
        if loop is None:
            loop = StealthLoop(
                fabric=ContextFabric(retrievers=[InMemoryRetriever()]),
                store=StealthStore(Path(key) / "ghost-stealth.sqlite3"),
            )
            _loops[key] = loop
        return loop


def approve_draft(
    loop: Any,
    intervention_id: str,
    *,
    final_text: str = "",
    connections: dict[str, str] | None = None,
    state_dir: str | Path | None = None,
) -> dict[str, Any]:
    """One-click approve: STE-check the final text, send when possible.

    Returns {approved, sent, detail, final_text, rules}. `sent` is True
    only when the Custom Auth Engine actually delivered every action;
    otherwise the approval is recorded and the text is returned for
    copy-paste / manual send — never claimed as sent.

    `connections` maps provider key -> entity_id holding the OAuth grant.
    """
    from ..stealth.intervention import InterventionOutcome, InterventionState
    from ..stealth.ste import simplify

    intervention = loop.interventions.get(intervention_id)
    if intervention is None:
        return {"ok": False, "error": "unknown intervention"}
    actions = draft_actions(intervention)
    if not actions:
        return {"ok": False, "error": "intervention has no draft actions"}
    # Apply an edited final text to the first action's body when given.
    if final_text.strip():
        payload = actions[0].setdefault("payload", {})
        if isinstance(payload, dict):
            for key in _TEXT_KEYS:
                if key in payload:
                    payload[key] = final_text
                    break
            else:
                payload["body"] = final_text
    checked = simplify(extract_draft_text(actions[0]))
    final = checked.text or extract_draft_text(actions[0])
    # Walk the lifecycle to READY regardless of entry state.
    state = intervention.state
    try:
        if state == InterventionState.QUEUED:
            intervention.transition(InterventionState.PREPARING)
            state = InterventionState.PREPARING
        if state == InterventionState.PREPARING:
            intervention.transition(InterventionState.READY)
    except ValueError as exc:
        return {"ok": False, "error": f"bad intervention state: {exc}"}
    # Attempt delivery through the Custom Auth Engine when a grant exists.
    sent, detail, results = False, "not sent", []
    connections = connections or {}
    try:
        from .auth_engine import PROVIDERS, CustomAuthEngine, EngineAction

        engine = CustomAuthEngine(Path(state_dir) if state_dir else Path.home() / ".ghostchimera")
        try:
            for action in actions:
                provider = str(action.get("provider", ""))
                entity_id = connections.get(provider, "")
                if not entity_id:
                    raise ValueError(f"no connected account mapped for provider '{provider}'")
                endpoint = str(action.get("endpoint", "/"))
                if endpoint.startswith("http"):
                    url = endpoint
                else:
                    base = PROVIDERS[provider].api_base if provider in PROVIDERS else ""
                    if not base or "{" in base:
                        raise ValueError(f"provider '{provider}' needs an absolute action URL")
                    url = base.rstrip("/") + "/" + endpoint.lstrip("/")
                results.append(
                    EngineAction(
                        provider=provider,
                        url=url,
                        payload=action.get("payload") if isinstance(action.get("payload"), dict) else {},
                    ).execute(engine, entity_id)
                )
        finally:
            engine.close()
        sent, detail = True, f"delivered {len(results)} action(s) via connected account"
    except Exception as exc:
        detail = f"approved but not sent ({type(exc).__name__}: {exc}); copy-paste the text below"
    intervention.provenance["approval"] = {
        "approved_at": time.time(),
        "sent": sent,
        "detail": detail,
        "final_text": final,
    }
    if loop.store is not None:
        with suppress(Exception):
            loop.store.record_intervention(intervention)
    if sent:
        with suppress(ValueError):
            loop.observe_outcome(intervention_id, InterventionOutcome.SUCCESSFUL)
    return {
        "ok": True,
        "approved": True,
        "sent": sent,
        "detail": detail,
        "final_text": final,
        "ste_rules": checked.rules_applied,
        "results": results,
    }


__all__ = ["approve_draft", "draft_actions", "extract_draft_text", "get_service_loop", "ste_prefill"]
