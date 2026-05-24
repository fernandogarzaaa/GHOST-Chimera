"""OIDC configuration validation for SaaS mode."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    allowed_domains: tuple[str, ...] = ()
    admin_bootstrap_email: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["client_secret"] = "[redacted]" if self.client_secret else ""
        return payload


def validate_oidc_settings(settings: OIDCSettings) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.issuer.startswith("https://"):
        errors.append("OIDC issuer must be an https URL")
    if not settings.client_id.strip():
        errors.append("OIDC client id is required")
    if not settings.client_secret.strip():
        errors.append("OIDC client secret is required")
    if not settings.redirect_uri.startswith("https://") and not settings.redirect_uri.startswith("http://127.0.0.1"):
        errors.append("OIDC redirect URI must be https, except local 127.0.0.1 development callbacks")
    if not settings.allowed_domains:
        warnings.append("No allowed email domains configured; any verified OIDC email may request access")
    if settings.admin_bootstrap_email and "@" not in settings.admin_bootstrap_email:
        errors.append("Admin bootstrap email must be a valid email address")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "settings": settings.to_public_dict(),
    }
