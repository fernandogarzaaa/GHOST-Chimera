"""Credential pool — multi-provider auth, rotation, quota tracking.

Patterns adapted from Hermes-Agent's CredentialPool (Nous Research, MIT licensed).
Ghost Chimera's pool is a focused credential store that maps provider names to
auth secrets, tracks per-provider quotas, and rotates keys automatically.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import GhostChimeraConfig
from ..logging_config import get_logger
from ..model_layer.providers import PROVIDERS, BaseProvider

logger = get_logger("credential_pool")

# ---------------------------------------------------------------------------
# Credential store entry
# ---------------------------------------------------------------------------

@dataclass
class CredentialEntry:
    """A single provider credential with metadata."""
    provider: str
    api_key: str
    api_secret: str = ""
    oauth_token: str = ""
    model: str = ""
    base_url: str = ""
    quota_limit: int = 0  # 0 = unlimited
    quota_used: int = 0
    last_rotated: float = 0.0
    expires_at: float = 0.0
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() > self.expires_at

    @property
    def is_available(self) -> bool:
        return self.enabled and not self.is_expired and bool(self.api_key)

    def usage_pct(self) -> float:
        if self.quota_limit <= 0:
            return 0.0
        return min(1.0, self.quota_used / self.quota_limit)


@dataclass
class ProviderHealth:
    """Health of a provider from credential pool's perspective."""
    provider: str
    available: bool
    usage_pct: float
    last_error: str = ""
    request_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    @property
    def success_rate(self) -> float:
        total = self.request_count or 1
        return self.success_count / total

    def record_success(self) -> None:
        self.success_count += 1
        self.request_count += 1

    def record_failure(self, error: str = "") -> None:
        self.failure_count += 1
        self.request_count += 1
        if error and not self.last_error:
            self.last_error = error[:200]


# ---------------------------------------------------------------------------
# Credential pool — singleton store
# ---------------------------------------------------------------------------

class CredentialPool:
    """Multi-provider credential management with rotation and quota tracking.

    Architecture:
        1. Initialize from env vars (GHOSTCHIMERA_*_API_KEY)
        2. Add providers dynamically
        3. Query availability before use
        4. Rotate keys on expiration or failure threshold
        5. Track per-provider quota usage
    """
    """Multi-provider credential management with rotation and quota tracking.

    Architecture:
        1. Initialize from env vars (GHOSTCHIMERA_*_API_KEY)
        2. Add providers dynamically
        3. Query availability before use
        4. Rotate keys on expiration or failure threshold
        5. Track per-provider quota usage
    """

    def __init__(self, config: GhostChimeraConfig | None = None):
        self._creds: dict[str, CredentialEntry] = {}
        self._health: dict[str, ProviderHealth] = {}
        self._lock = threading.RLock()
        self.config = config or GhostChimeraConfig.from_env()
        self._initialized = False

    def initialize_from_env(self) -> int:
        """Load credentials from environment variables. Returns count loaded."""
        loaded = 0
        for provider_name, _provider_cls in PROVIDERS.items():
            key_var = f"{provider_name.upper()}_API_KEY"
            api_key = os.environ.get(key_var)
            if not api_key:
                api_key = os.environ.get(f"GHOSTCHIMERA_{key_var}")
            if not api_key:
                continue

            entry = CredentialEntry(
                provider=provider_name,
                api_key=api_key,
                model=os.environ.get(f"{provider_name.upper()}_MODEL", ""),
                base_url=os.environ.get(f"{provider_name.upper()}_BASE_URL", ""),
                quota_limit=int(os.environ.get(f"{provider_name.upper()}_QUOTA_LIMIT", "0")),
                quota_used=int(os.environ.get(f"{provider_name.upper()}_QUOTA_USED", "0")),
                expires_at=float(os.environ.get(f"{provider_name.upper()}_EXPIRES_AT", "0")),
                metadata={
                    "source": "env",
                    "loaded_at": time.time(),
                },
            )
            with self._lock:
                self._creds[provider_name] = entry
                self._health[provider_name] = ProviderHealth(
                    provider=provider_name,
                    available=entry.is_available,
                    usage_pct=entry.usage_pct(),
                )
            logger.info("Loaded credential for provider %s", provider_name)
            loaded += 1

        self._initialized = loaded > 0
        return loaded

    def add_credential(
        self,
        provider: str,
        api_key: str,
        api_secret: str = "",
        oauth_token: str = "",
        model: str = "",
        base_url: str = "",
        quota_limit: int = 0,
        expires_at: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialEntry:
        """Add or update a credential."""
        entry = CredentialEntry(
            provider=provider,
            api_key=api_key,
            api_secret=api_secret,
            oauth_token=oauth_token,
            model=model,
            base_url=base_url,
            quota_limit=quota_limit,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        with self._lock:
            self._creds[provider] = entry
            self._health[provider] = ProviderHealth(
                provider=provider,
                available=entry.is_available,
                usage_pct=entry.usage_pct(),
            )
        logger.info("Added credential for provider %s", provider)
        return entry

    def get_credential(self, provider: str) -> CredentialEntry | None:
        """Get credential for a provider, checking availability.

        If the entry carries an ``oauth_token`` and is expired, an OAuth
        refresh is attempted (via :class:`~ghostchimera.model_layer.auth_profiles.OAuthCredential`).
        The refresh is a no-op stub today — it logs a warning and returns
        ``None`` — but the hook is in place for future OAuth flows.
        """
        with self._lock:
            entry = self._creds.get(provider)
        if entry is None:
            return None
        if entry.is_expired and entry.oauth_token:
            # Attempt OAuth refresh (stub — raises NotImplementedError in practice)
            try:
                from ..model_layer.auth_profiles import OAuthCredential
                oauth = OAuthCredential(
                    token=entry.oauth_token,
                    expires_at=entry.expires_at,
                )
                refreshed = oauth.refresh()
                # If refresh succeeds, update the stored entry with the new token
                new_entry = CredentialEntry(
                    **{
                        **entry.__dict__,
                        "oauth_token": refreshed.token,
                        "expires_at": refreshed.expires_at,
                    }
                )
                with self._lock:
                    self._creds[provider] = new_entry
                return new_entry
            except NotImplementedError:
                logger.warning(
                    "OAuth token for %s is expired and no refresh implementation is available", provider
                )
                return None
            except Exception as exc:
                logger.warning("OAuth refresh for %s failed: %s", provider, exc)
                return None
        if not entry.is_available:
            logger.warning("Credential for %s is not available (expired/revoked)", provider)
            return None
        return entry

    def get_provider_instance(self, provider: str) -> BaseProvider | None:
        """Get a provider instance configured with the credential.

        Builds an :class:`~ghostchimera.model_layer.auth_profiles.AuthProfile`
        from the stored :class:`CredentialEntry` and passes it to the provider
        constructor, making the pool the single authoritative credential source
        (OpenClaw-style auth injection).
        """
        entry = self.get_credential(provider)
        if not entry:
            return None
        provider_cls = PROVIDERS.get(provider)
        if not provider_cls:
            return None
        from ..model_layer.auth_profiles import AuthProfile
        profile = AuthProfile(
            provider=provider,
            auth_kind="oauth" if entry.oauth_token and not entry.api_key else "api_key",
            api_key=entry.api_key,
            oauth_token=entry.oauth_token,
            base_url=entry.base_url,
            model=entry.model,
            expires_at=entry.expires_at,
        )
        return provider_cls(profile)

    def rotate_credential(self, provider: str, new_api_key: str) -> CredentialEntry:
        """Rotate a credential. Returns the new entry."""
        with self._lock:
            entry = self._creds.get(provider)
            if not entry:
                raise KeyError(f"No credential found for provider {provider}")
            new_entry = CredentialEntry(
                provider=provider,
                api_key=new_api_key,
                api_secret=entry.api_secret,
                oauth_token=entry.oauth_token,
                model=entry.model,
                base_url=entry.base_url,
                quota_limit=entry.quota_limit,
                quota_used=entry.quota_used,
                last_rotated=time.time(),
                expires_at=entry.expires_at,
                enabled=True,
                metadata={**entry.metadata, "rotated": True, "rotation_count": entry.metadata.get("rotation_count", 0) + 1},
            )
            self._creds[provider] = new_entry
            self._health[provider] = ProviderHealth(
                provider=provider,
                available=True,
                usage_pct=new_entry.usage_pct(),
            )
        logger.info("Rotated credential for %s (rotation #%d)", provider, new_entry.metadata["rotation_count"])
        return new_entry

    def record_request(self, provider: str, success: bool, error: str = "") -> None:
        """Record a request outcome for quota tracking."""
        with self._lock:
            if provider not in self._health:
                self._health[provider] = ProviderHealth(provider=provider, available=False, usage_pct=0.0)
            if success:
                self._health[provider].record_success()
            else:
                self._health[provider].record_failure(error)
            # Update quota usage
            entry = self._creds.get(provider)
            if entry:
                new_entry = CredentialEntry(
                    **{**entry.__dict__, "quota_used": entry.quota_used + 1},
                )
                self._creds[provider] = new_entry

    def select_best_provider(self, exclude: set[str] | None = None) -> str | None:
        """Select the best available provider based on success rate and quota."""
        exclude = exclude or set()
        with self._lock:
            candidates = []
            for name, entry in self._creds.items():
                if name in exclude:
                    continue
                if not entry.is_available:
                    continue
                health = self._health.get(name)
                if health and (health.usage_pct > 0.9 or health.success_rate < 0.5):
                    continue
                candidates.append((name, health.success_rate if health else 1.0, 1.0 - entry.usage_pct()))

        if not candidates:
            # Fallback to any available
            for name, entry in self._creds.items():
                if name not in exclude and entry.is_available:
                    return name
            return None

        # Score by weighted success rate + remaining quota
        candidates.sort(key=lambda x: (x[1] * 0.6 + x[2] * 0.4), reverse=True)
        return candidates[0][0]

    def list_credentials(self) -> list[dict]:
        """List credential status for all providers (sensitive data masked)."""
        with self._lock:
            result = []
            for name, entry in self._creds.items():
                result.append({
                    "provider": name,
                    "available": entry.is_available,
                    "usage_pct": entry.usage_pct(),
                    "model": entry.model,
                    "expires_at": entry.expires_at,
                    "key_masked": self._mask_key(entry.api_key),
                    "health": self._health.get(name).__dict__ if self._health.get(name) else None,
                })
            return result

    def _mask_key(self, key: str) -> str:
        if not key or len(key) <= 4:
            return "****"
        return key[:4] + "***"

    def status(self) -> dict[str, Any]:
        """Pool status summary."""
        with self._lock:
            return {
                "initialized": self._initialized,
                "provider_count": len(self._creds),
                "available_count": sum(1 for e in self._creds.values() if e.is_available),
                "providers": self.list_credentials(),
            }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_pool: CredentialPool | None = None
_pool_lock = threading.Lock()


def get_pool(config: GhostChimeraConfig | None = None) -> CredentialPool:
    """Get the singleton credential pool, initializing from env on first call."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = CredentialPool(config)
                _pool.initialize_from_env()
    return _pool


def reset_pool() -> None:
    """Reset the singleton (for testing)."""
    global _pool
    with _pool_lock:
        _pool = None


__all__ = [
    "CredentialPool",
    "CredentialEntry",
    "ProviderHealth",
    "get_pool",
    "reset_pool",
]
