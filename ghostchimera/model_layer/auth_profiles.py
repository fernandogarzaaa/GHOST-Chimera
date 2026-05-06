"""Auth profile primitives for model providers.

Mirrors OpenClaw's ``AuthProfileCredential`` pattern: credentials are
assembled once (from env, a credential pool, or explicit injection) and
passed into providers at construction time.  When no profile is supplied,
providers fall back to reading from ``os.environ`` directly.

Supported ``auth_kind`` values:
    ``api_key``  – a static bearer/API key (most providers)
    ``oauth``    – short-lived token with optional refresh capability
    ``token``    – arbitrary access token (no refresh)
    ``custom``   – provider-specific credential bundle

External auth providers
-----------------------
Concrete OAuth flows or third-party auth services implement
:class:`ExternalAuthProvider` and register themselves with the
:class:`~ghostchimera.chimera_pilot.credential_pool.CredentialPool` via
``pool.register_auth_provider()``.  The pool then calls
:meth:`ExternalAuthProvider.refresh` whenever a stored
:class:`OAuthCredential` expires.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

AuthKind = Literal["api_key", "oauth", "token", "custom"]


@dataclass(frozen=True)
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

    Call :meth:`refresh` to validate whether the current token is still usable.
    Expired credentials must be refreshed through a registered
    :class:`ExternalAuthProvider`; the credential object itself does not perform
    network token exchange.
    """

    token: str
    refresh_token: str = ""
    token_url: str = ""
    client_id: str = ""
    expires_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return time.time() > self.expires_at

    def refresh(self) -> OAuthCredential:
        """Attempt to refresh the token.

        Raises
        ------
        RuntimeError
            If the token is expired and no external auth provider has refreshed
            it first.
        """
        if not self.is_expired:
            return self
        raise RuntimeError(
            "OAuthCredential is expired. Register an ExternalAuthProvider with "
            "CredentialPool.refresh_credential() to perform provider-specific "
            "token refresh."
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


# ---------------------------------------------------------------------------
# ExternalAuthProvider  (Gap 8)
# ---------------------------------------------------------------------------


class ExternalAuthProvider(ABC):
    """Abstract base for pluggable external authentication providers.

    Mirrors OpenClaw's ``externalAuthProviders`` contract.  Concrete
    implementations handle token exchange, refresh, and revocation for
    third-party OAuth services.

    Register with the credential pool::

        from ghostchimera.chimera_pilot.credential_pool import get_pool
        get_pool().register_auth_provider("my_service", MyAuthProvider())

    The pool will call :meth:`refresh` automatically when the stored
    :class:`OAuthCredential` for the provider is expired.
    """

    provider_id: str = "base_external_auth"
    """Unique identifier matching the provider name in the credential pool."""

    auth_methods: list[str] = ["api-key"]
    """Auth methods supported: ``"api-key"``, ``"oauth"``, ``"token"``."""

    @abstractmethod
    def authorize(self, scope: str = "") -> AuthProfile:
        """Obtain a fresh :class:`AuthProfile`.

        Parameters
        ----------
        scope:
            Optional permission scope string.

        Returns
        -------
        AuthProfile
            A valid, non-expired credential profile.
        """

    @abstractmethod
    def refresh(self, credential: OAuthCredential) -> OAuthCredential:
        """Refresh an expired :class:`OAuthCredential`.

        Parameters
        ----------
        credential:
            The expired credential to renew.

        Returns
        -------
        OAuthCredential
            A new, valid credential.
        """

    def revoke(self, credential: OAuthCredential) -> None:
        """Revoke a credential when the provider supports revocation.

        Revocation is optional for external providers; the base behavior simply
        returns when a provider only supports refresh.
        """
        return None

    def validate_config(self) -> list[str]:
        """Return configuration errors.  Empty list means OK."""
        return []


__all__ = ["AuthKind", "AuthProfile", "OAuthCredential", "ExternalAuthProvider"]
