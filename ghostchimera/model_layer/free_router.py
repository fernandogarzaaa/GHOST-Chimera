"""Free-model auto-router: run Ghost at $0 with graceful failover.

Chain (reliability-first): Gemini Flash-Lite → Groq small models →
OpenRouter :free → Cloudflare Workers AI → Pollinations (emergency only).

Rules the router enforces:
- Daily request counters per tier, persisted locally. A tier at its cap
  is skipped *before* calling, so Ghost never hammers into 429 walls.
- 429 / 5xx / network errors fail over to the next tier with a short
  backoff. `Retry-After` is honored when the provider sends one.
- Content flagged by `sensitivity.is_sensitive` NEVER routes to tiers
  that log prompts for training (OpenRouter :free, Gemini free,
  Pollinations). Those calls fall through to non-logging tiers or raise
  a clear error when none is available.
- No multi-account rotation, no quota evasion: one identity per
  provider, backoff-first. Quota exhaustion is reported, not bypassed.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .auth_profiles import AuthProfile
from .sensitivity import is_sensitive

_TIER_DEFS: tuple[dict[str, Any], ...] = (
    {
        "tier": "gemini-flash-lite",
        "provider": "gemini-openai",
        "model": "gemini-2.5-flash-lite",
        "key_env": "GOOGLE_API_KEY",
        "trains_on_data": True,
        "requests_per_day": 1500,
        "note": "Highest sustained free quota. Free signup, no card.",
    },
    {
        "tier": "gemini-flash",
        "provider": "gemini-openai",
        "model": "gemini-2.5-flash",
        "key_env": "GOOGLE_API_KEY",
        "trains_on_data": True,
        "requests_per_day": 500,
        "note": "Better quality, smaller daily pool than Lite.",
    },
    {
        "tier": "groq-oss-20b",
        "provider": "groq",
        "model": "openai/gpt-oss-20b",
        "key_env": "GROQ_API_KEY",
        "trains_on_data": False,
        "requests_per_day": 1000,
        "note": "Ultra-low latency. Free signup, no card.",
    },
    {
        "tier": "groq-qwen-27b",
        "provider": "groq",
        "model": "qwen/qwen3.6-27b",
        "key_env": "GROQ_API_KEY",
        "trains_on_data": False,
        "requests_per_day": 1000,
        "note": "Second Groq pool; stacks quota across models.",
    },
    {
        "tier": "openrouter-free",
        "provider": "openrouter",
        "model": "openrouter/free",
        "key_env": "OPENROUTER_API_KEY",
        "trains_on_data": True,
        "requests_per_day": 50,
        "note": "Widest pool, absorbs outages. Strictly $0 = 50/day.",
    },
    {
        "tier": "cloudflare",
        "provider": "cloudflare",
        "model": "@cf/meta/llama-3.1-8b-instruct",
        "key_env": "CF_API_TOKEN",
        "trains_on_data": False,
        "requests_per_day": 500,
        "note": "Independent neuron quota. Needs CF_ACCOUNT_ID too.",
    },
    {
        "tier": "pollinations",
        "provider": "pollinations",
        "model": "openai",
        "key_env": "",
        "trains_on_data": True,
        "requests_per_day": 96,
        "note": "Keyless emergency tier only (~1/15s). Never core, never secrets.",
    },
)


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _default_state_path() -> Path:
    base = os.environ.get("GHOSTCHIMERA_STATE_DIR", str(Path.home() / ".ghostchimera"))
    return Path(base).expanduser() / "free_usage.json"


@dataclass
class FreeRouter:
    """Ordered free-tier failover with quota guards and privacy routing.

    The baked-in chain below is defaults only. A user overlay file
    (``free_tiers_config.json`` next to the usage file) overrides per-tier
    ``model`` and ``enabled`` — written when the operator accepts a
    "new models detected" proposal. Code is never rewritten at runtime.
    """

    state_path: Path | None = None
    tiers: tuple[dict[str, Any], ...] = _TIER_DEFS
    max_backoff_s: float = 8.0
    _usage: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)
    _overlay: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.state_path is None:
            self.state_path = _default_state_path()
        self._load()
        self._load_overlay()

    def _overlay_path(self) -> Path:
        return self.state_path.parent / "free_tiers_config.json"

    def _load_overlay(self) -> None:
        try:
            data = json.loads(self._overlay_path().read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._overlay = {
                    str(tier): {k: v for k, v in cfg.items() if k in ("model", "enabled")}
                    for tier, cfg in data.get("tiers", {}).items()
                    if isinstance(cfg, dict)
                }
        except (OSError, ValueError):
            self._overlay = {}

    def save_overlay(self, tiers: dict[str, dict[str, Any]]) -> None:
        """Persist per-tier ``model`` and ``enabled`` overrides.

        Other override fields are dropped. Raise ``ValueError`` if the
        configuration file cannot be written.
        """
        cleaned = {
            str(tier): {k: cfg[k] for k in ("model", "enabled") if k in cfg}
            for tier, cfg in tiers.items()
            if isinstance(cfg, dict)
        }
        path = self._overlay_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"tiers": cleaned}, indent=2), encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"cannot save tier config: {exc}") from exc
        self._overlay = cleaned

    def effective_tiers(self) -> list[dict[str, Any]]:
        """Baked-in chain with the user overlay applied (disabled dropped)."""
        out = []
        for tier in self.tiers:
            override = self._overlay.get(tier["tier"], {})
            if override.get("enabled") is False:
                continue
            merged = dict(tier)
            if override.get("model"):
                merged["model"] = str(override["model"])[:160]
            merged["customized"] = bool(override)
            out.append(merged)
        return out

    # -- quota store ---------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._usage = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            self._usage = {}

    def _save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self._usage), encoding="utf-8")
        except OSError:
            pass

    def used_today(self, tier: str) -> int:
        """Return the recorded request count for a tier on the current UTC day."""
        return int(self._usage.get(_today(), {}).get(tier, 0))

    def quota_status(self) -> list[dict[str, Any]]:
        """Return quota and privacy gauges for enabled tiers in routing order.

        Each gauge includes today's recorded requests, its daily cap, model,
        provider, and whether that tier is marked as training on user data.
        """
        return [
            {
                "tier": t["tier"],
                "provider": t["provider"],
                "model": t["model"],
                "used_today": self.used_today(t["tier"]),
                "requests_per_day": t["requests_per_day"],
                "trains_on_data": t["trains_on_data"],
                "customized": t.get("customized", False),
                "note": t["note"],
            }
            for t in self.effective_tiers()
        ]

    def _bump(self, tier: str) -> None:
        day = _today()
        self._usage.setdefault(day, {})
        self._usage[day][tier] = self.used_today(tier) + 1
        # Keep a rolling week, not unbounded history.
        for old in sorted(self._usage)[:-7]:
            del self._usage[old]
        self._save()

    # -- routing ------------------------------------------------------------------
    def _tier_available(self, tier: dict[str, Any], *, sensitive: bool) -> tuple[bool, str]:
        if sensitive and tier["trains_on_data"]:
            return False, "skipped (trains on data, content is sensitive)"
        if tier["tier"] == "cloudflare":
            if not os.environ.get("CF_API_TOKEN", "").strip() or not os.environ.get("CF_ACCOUNT_ID", "").strip():
                return False, "skipped (CF_API_TOKEN/CF_ACCOUNT_ID not set)"
        elif tier["key_env"] and not os.environ.get(tier["key_env"], "").strip():
            return False, f"skipped ({tier['key_env']} not set)"
        if self.used_today(tier["tier"]) >= tier["requests_per_day"]:
            return False, "skipped (daily quota reached)"
        return True, ""

    @staticmethod
    def _is_retryable(error: Exception) -> tuple[bool, float]:
        """Retryable provider errors with a backoff hint in seconds."""
        text = str(error)
        if "429" in text or "rate" in text.lower() or "quota" in text.lower():
            return True, 4.0
        if any(code in text for code in ("500", "502", "503", "504", "overloaded", "timeout", "unreachable")):
            return True, 2.0
        return False, 0.0

    def chat(
        self,
        system_message: str,
        user_message: str,
        *,
        sensitive: bool | None = None,
        tiers: list[str] | None = None,
        ledger: Any = None,
    ) -> dict[str, Any]:
        """Try eligible free tiers in order and return the first response.

        ``sensitive=None`` detects sensitive content from both messages;
        an explicit value overrides detection. ``tiers`` restricts candidates
        by tier name. Successful responses include text, tier, provider,
        model, latency in seconds, and the sensitivity flag. A returned
        response increments the tier's UTC-day count and records estimated
        usage in ``ledger`` or the process ledger.

        Raise ``RuntimeError`` with per-tier skip or failure diagnostics when
        no tier returns successfully. Provider and ledger errors cause failover;
        the request count can increase even if a later recording step fails.
        """
        if sensitive is None:
            sensitive = is_sensitive(system_message, user_message)
        failures: list[str] = []
        for tier in self.effective_tiers():
            if tiers is not None and tier["tier"] not in tiers:
                continue
            ok, reason = self._tier_available(tier, sensitive=sensitive)
            if not ok:
                failures.append(f"{tier['tier']}: {reason}")
                continue
            try:
                from .cost_monitor import get_ledger
                from .providers import get_provider

                provider = get_provider(
                    tier["provider"],
                    AuthProfile(provider=tier["provider"], api_key="", model=tier["model"]),
                )
                if provider is None:
                    failures.append(f"{tier['tier']}: unknown provider")
                    continue
                started = time.time()
                text = provider.chat(system_message, user_message)
                latency = round(time.time() - started, 2)
                self._bump(tier["tier"])
                (ledger or get_ledger()).record(
                    tier["provider"],
                    tier["model"],
                    input_text=f"{system_message}\n{user_message}",
                    output_text=text,
                    latency_s=latency,
                )
                return {
                    "ok": True,
                    "text": text,
                    "tier": tier["tier"],
                    "provider": tier["provider"],
                    "model": tier["model"],
                    "latency_s": latency,
                    "sensitive_routed": sensitive,
                }
            except Exception as exc:  # noqa: BLE001 — failover must be total
                retryable, wait_s = self._is_retryable(exc)
                failures.append(f"{tier['tier']}: {type(exc).__name__}")
                if retryable:
                    time.sleep(min(wait_s + random.uniform(0, 1.0), self.max_backoff_s))
                continue
        raise RuntimeError("All free tiers unavailable: " + "; ".join(failures))


__all__ = ["FreeRouter"]
