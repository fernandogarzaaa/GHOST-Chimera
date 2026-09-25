"""Daily free-tier re-check: availability probing on by default.

Free-model IDs, limits, and uptime rotate fast (especially community
tiers). This monitor re-probes every tier once per 24h and refreshes the
status snapshot the Console reads — model availability, latency, and the
model IDs each endpoint currently advertises. Probing uses metadata
endpoints only (``/models`` listings); it never spends chat quota.

Runs on by default (single daemon thread, jittered start). Disable via
``set_enabled(False)`` or the Console Usage tab. State lives in
``free_tiers_status.json`` under the state dir.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CHECK_INTERVAL_S = 24 * 3600
STARTUP_JITTER_S = 300.0
PROBE_TIMEOUT_S = 15.0

# Metadata endpoints per provider key (not per tier: one probe covers all
# tiers sharing a provider). Placeholders are filled from the environment.
_PROVIDER_PROBES: tuple[dict[str, Any], ...] = (
    {
        "provider": "gemini-openai",
        "url": "https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        "key_env": "GOOGLE_API_KEY",
        "model_ids_jsonpath": ("models", "name"),
    },
    {
        "provider": "groq",
        "url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
        "auth_header": True,
        "model_ids_jsonpath": ("data", "id"),
    },
    {
        "provider": "openrouter",
        "url": "https://openrouter.ai/api/v1/models",
        "key_env": "OPENROUTER_API_KEY",
        "auth_header": False,
        "model_ids_jsonpath": ("data", "id"),
    },
    {
        "provider": "cloudflare",
        "url": "https://api.cloudflare.com/client/v4/accounts/{account}/ai/models/search",
        "key_env": "CF_API_TOKEN",
        "account_env": "CF_ACCOUNT_ID",
        "auth_header": True,
        "auth_scheme": "Bearer",
        "model_ids_jsonpath": ("result", "name"),
    },
    {
        "provider": "pollinations",
        "url": "https://gen.pollinations.ai/v1/models",
        "key_env": "",
        "model_ids_jsonpath": ("data", "id"),
    },
)


def _fetch_json(url: str, *, api_key: str = "", timeout: float = PROBE_TIMEOUT_S) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "ghostchimera/0.4"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8", "replace"))


def _extract_ids(payload: Any, path: tuple[str, str]) -> list[str]:
    """Pull model ids from {collection: [{id/name: ...}]} shapes."""
    if not isinstance(payload, dict):
        return []
    items = payload.get(path[0], [])
    if not isinstance(items, list):
        return []
    ids = []
    for item in items:
        if isinstance(item, dict) and item.get(path[1]):
            ids.append(str(item[path[1]])[:160])
    return ids[:200]


def probe_provider(provider: str, *, fetch_fn=None) -> dict[str, Any]:
    """Read a provider's model list without making a chat request.

    ``fetch_fn`` can replace the metadata fetcher. Unknown providers,
    missing credentials, and fetch failures return ``ok: False`` with an
    error; a missing credential also sets ``skipped``. Successful results
    include model IDs, elapsed seconds, and a check timestamp.
    """
    spec = next((s for s in _PROVIDER_PROBES if s["provider"] == provider), None)
    if spec is None:
        return {"provider": provider, "ok": False, "error": "no probe defined"}
    key = os.environ.get(spec["key_env"], "").strip() if spec["key_env"] else ""
    if spec["key_env"] and not key:
        return {"provider": provider, "ok": False, "error": f"{spec['key_env']} not set", "skipped": True}
    url = spec["url"]
    if "{key}" in url:
        url = url.replace("{key}", urllib.parse.quote(key, safe=""))
    if "{account}" in url:
        account = os.environ.get(spec.get("account_env", ""), "").strip()
        if not account:
            return {"provider": provider, "ok": False, "error": f"{spec.get('account_env')} not set", "skipped": True}
        url = url.replace("{account}", urllib.parse.quote(account, safe=""))
    fetch = fetch_fn or _fetch_json
    started = time.time()
    try:
        payload = fetch(url, api_key=key if spec.get("auth_header") else "")
        latency = round(time.time() - started, 2)
        return {
            "provider": provider,
            "ok": True,
            "latency_s": latency,
            "models_seen": _extract_ids(payload, spec["model_ids_jsonpath"]),
            "checked_at": time.time(),
        }
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        return {
            "provider": provider,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "latency_s": round(time.time() - started, 2),
            "checked_at": time.time(),
        }


class FreeTierMonitor:
    """24h re-check daemon with persisted snapshot. On by default."""

    def __init__(self, state_dir: str | Path, *, interval_s: float = CHECK_INTERVAL_S) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self.state_dir / "free_tiers_status.json"
        self._interval = max(60.0, float(interval_s))
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False

    # -- state ------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        with contextlib.suppress(OSError):
            self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def is_enabled(self) -> bool:
        return bool(self._load().get("enabled", True))

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """Persist the enabled flag and start or stop this monitor's thread."""
        state = self._load()
        state["enabled"] = bool(enabled)
        self._save(state)
        if enabled:
            self.ensure_running()
        else:
            self.stop()
        return {"ok": True, "enabled": bool(enabled)}

    def status(self) -> dict[str, Any]:
        """Last snapshot + freshness for the Console (never triggers a probe)."""
        state = self._load()
        last = float(state.get("last_check_at", 0) or 0)
        age = time.time() - last if last else -1
        return {
            "enabled": bool(state.get("enabled", True)),
            "last_check_at": last,
            "age_s": round(age, 1) if age >= 0 else -1,
            "stale": age < 0 or age > self._interval * 1.5,
            "tiers": state.get("tiers", {}),
        }

    # -- probing -------------------------------------------------------------------
    def check_now(self) -> dict[str, Any]:
        """Probe each provider once and persist the resulting snapshot.

        Return ``ok: True`` with per-provider results, including failures
        reported by individual probes.
        """
        results: dict[str, Any] = {}
        for spec in _PROVIDER_PROBES:
            results[spec["provider"]] = probe_provider(spec["provider"])
        state = self._load()
        state["tiers"] = results
        state["last_check_at"] = time.time()
        self._save(state)
        return {"ok": True, "tiers": results}

    def propose_updates(self) -> dict[str, Any]:
        """Diff advertised models against the known baseline.

        The first call with a successful snapshot per provider seeds the
        baseline silently. Later calls can propose newly advertised models
        or a pinned model absent from the snapshot. Returns {proposals: [...]}
        where each proposal is {tier, provider, kind, current_model,
        candidates[], dismissed} with kind in (new_models, pin_stale). This
        call persists newly seeded baselines; it does not fetch model lists.
        """
        from .free_router import _TIER_DEFS

        state = self._load()
        tiers = state.get("tiers", {})
        known = state.get("known_models", {})
        if not isinstance(known, dict):
            known = {}
        dismissed = state.get("dismissed", [])
        if not isinstance(dismissed, list):
            dismissed = []
        proposals = []
        seeded_this_run: set[str] = set()
        for tier in _TIER_DEFS:
            provider = tier["provider"]
            snap = tiers.get(provider, {})
            if not snap.get("ok"):
                continue
            seen = [m for m in snap.get("models_seen", []) if isinstance(m, str)]
            if provider not in known:
                # First sight seeds the baseline silently — neither new-model
                # nor pin proposals until the next check has something to
                # compare against (covers multi-tier providers too).
                known[provider] = sorted(set(seen))[:200]
                seeded_this_run.add(provider)
                continue
            if provider in seeded_this_run:
                continue
            fresh = [m for m in seen if m not in set(known[provider])]
            if fresh:
                key = f"{tier['tier']}:new"
                if key not in dismissed:
                    proposals.append(
                        {
                            "tier": tier["tier"],
                            "provider": provider,
                            "kind": "new_models",
                            "current_model": tier["model"],
                            "candidates": fresh[:12],
                            "dismissed": False,
                        }
                    )
            current = tier["model"]
            if seen and current not in seen:
                key = f"{tier['tier']}:pin:{current}"
                if key not in dismissed:
                    proposals.append(
                        {
                            "tier": tier["tier"],
                            "provider": provider,
                            "kind": "pin_stale",
                            "current_model": current,
                            "candidates": seen[:12],
                            "dismissed": False,
                        }
                    )
        state["known_models"] = known
        self._save(state)
        return {"ok": True, "proposals": proposals}

    def dismiss_proposal(self, tier: str, kind: str, current_model: str = "") -> dict[str, Any]:
        """Persist a dismissal for a tier's new-model or stale-pin proposal.

        ``current_model`` distinguishes stale-pin dismissals. The returned
        ``dismissed`` value is the stored proposal key.
        """
        state = self._load()
        dismissed = state.get("dismissed", [])
        if not isinstance(dismissed, list):
            dismissed = []
        key = f"{tier}:pin:{current_model}" if kind == "pin_stale" else f"{tier}:new"
        if key not in dismissed:
            dismissed.append(key)
        state["dismissed"] = dismissed[-200:]
        self._save(state)
        return {"ok": True, "dismissed": key}

    # -- daemon ----------------------------------------------------------------------
    def ensure_running(self) -> bool:
        """Start a daemon thread if enabled; return whether one is alive or started."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            if not self.is_enabled():
                return False
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="ghost-free-tiers", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _loop(self) -> None:
        time.sleep(random.uniform(0, min(STARTUP_JITTER_S, self._interval / 4)))
        while self._running:
            try:
                if self.is_enabled():
                    self.check_now()
            except Exception:
                pass
            for _ in range(int(self._interval)):
                if not self._running:
                    return
                time.sleep(1)


__all__ = ["FreeTierMonitor", "probe_provider"]
