"""One place for identifier generation.

* :func:`stable_id` is a deterministic, non-cryptographic digest of its
  parts. Use it only where the *same* inputs must map to the *same* ID
  (dedupe/idempotency keys, peer keys, content addresses). Persisted IDs
  depend on its exact output, so the two historical variants are kept as
  explicit options rather than silently unified:

  - ``normalize=False`` (default): ``str(part)`` joined with ``|``;
  - ``normalize=True``: each part stripped and lower-cased first (used by
    capability admission, evolution and remote-control peer keys).

* :func:`unique_id` is for records that must never collide or be
  overwritten (approval checkpoints, runs): it mixes a random nonce into
  the digest, so two requests with identical inputs get distinct IDs.

* :func:`new_token` is an unguessable token for anything that might gate
  access (resume tokens, pairing secrets).
"""

from __future__ import annotations

import hashlib
import secrets


def _join(parts: tuple[object, ...], *, normalize: bool) -> str:
    if normalize:
        return "|".join(str(part).strip().lower() for part in parts if part is not None)
    return "|".join(str(part) for part in parts if part is not None)


def stable_id(*parts: object, length: int = 16, normalize: bool = False) -> str:
    """Deterministic hex ID (SHA-1 prefix; not for security)."""
    raw = _join(parts, normalize=normalize)
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:length]


def unique_id(*parts: object, length: int = 16) -> str:
    """Hex ID that is unique per call even for identical *parts*."""
    return stable_id(*parts, secrets.token_hex(16), length=length)


def new_token(nbytes: int = 24) -> str:
    """URL-safe random token suitable for authorization use."""
    return secrets.token_urlsafe(nbytes)


__all__ = ["new_token", "stable_id", "unique_id"]
