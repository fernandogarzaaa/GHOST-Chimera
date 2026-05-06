"""Auth profile primitives for model providers.

Mirrors OpenClaw's ``AuthProfileCredential`` pattern: credentials are
assembled once (from env, a credential pool, or explicit injection) and
passed into providers at construction time, so providers never reach into
``os.environ`` directly.

Supported ``auth_kind`` values:
    ``api_key``  – a static bearer/API key (most providers)
    ``oauth``    – short-lived token with optional refresh capability
    ``token``    – arbitrary access token (no refresh)
    ``custom``   – provider-specific credential bundle
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

AuthKind = Literal["api_key", "oauth", "token", "custom"]


@dataclass
class AuthProfile:
    """Immutable credential snapshot passed into provider constructors.

    Parameters
    ----------
    provider:
        Provider identifier, e.g. ``"openai"`` or ``"anthropic"``.
    auth_kind:
        One of ``"api_key"``, ``"oauth"``, ``"token"``, ``"custom"``.
    api_key:
        Static API key (used when ``auth_kind == "api_key"``).
    oauth_token:
        Short-lived access token (used when ``auth_kind == "oauth"``).
    base_url:
        Optional override for the provider's base URL.
    model:
        Optional default model identifier.
    expires_at:
        Unix timestamp after which this profile should be considered stale.
        ``0.0`` means no expiry.
    """

    provider: str
    auth_kind: AuthKind = "api_key"
    api_key: str = ""
    oauth_token: str = ""
    base_url: str = ""
    model: str = ""
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() > self.expires_at

    @property
    def effective_token(self) -> str:
        """Return whichever token is relevant for the auth_kind."""
        if self.auth_kind == "oauth":
            return self.oauth_token
        return self.api_key


@dataclass
class OAuthCredential:
    """Forward-compatible OAuth credential skeleton.

    This is not a full OAuth flow implementation — it is a shape contract
    that unblocks future OAuth support without coupling providers to a
    specific flow library today.

    Call :meth:`refresh` to renew an expired token.  Concrete OAuth flows
    must subclass and override :meth:`_do_refresh`.
    """

    token: str
    refresh_token: str = ""
    token_url: str = ""
    client_id: str = ""
    expires_at: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() > self.expires_at

    def refresh(self) -> OAuthCredential:
        """Attempt to refresh the token.

        Raises
        ------
        NotImplementedError
            Always, until a concrete subclass provides :meth:`_do_refresh`.
        """
        return self._do_refresh()

    def _do_refresh(self) -> OAuthCredential:
        raise NotImplementedError(
            "OAuthCredential.refresh() is not yet implemented. "
            "Subclass OAuthCredential and override _do_refresh() with the "
            "provider-specific token refresh logic."
        )

    def to_auth_profile(self, provider: str, **kwargs) -> AuthProfile:
        """Convert to an AuthProfile for passing into a provider constructor."""
        return AuthProfile(
            provider=provider,
            auth_kind="oauth",
            oauth_token=self.token,
            expires_at=self.expires_at,
            **kwargs,
        )


__all__ = ["AuthKind", "AuthProfile", "OAuthCredential"]
