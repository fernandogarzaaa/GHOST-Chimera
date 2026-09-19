"""App-password mail access (IMAP, read-only, consent-gated, local-only).

Uses provider-issued app passwords stored in the auth-engine custom-key
vault (kind ``app_password``) — never account passwords. Fetch is gated on
Personal MiniMind email-crawl consent, returns headers + short snippets
(full bodies stay on the server), and scrubs one-time codes / reset links
before anything reaches the model. Stdlib-only (imaplib).
"""

from __future__ import annotations

import contextlib
import email
import email.header
import email.utils
import imaplib
import re
from typing import Any

IMAP_HOSTS: dict[str, tuple[str, int]] = {
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
    "yahoo": ("imap.mail.yahoo.com", 993),
}

DEFAULT_MAX_MESSAGES = 10
DEFAULT_SNIPPET_CHARS = 500

# Best-effort scrubbing: OTP codes and credential-reset links must never
# reach the model (prompt-injection exfiltration vector).
_OTP_RE = re.compile(r"(?i)\b(?:otp|verification|security|2fa|two-factor|passcode)[^\n]{0,40}?(\b\d{4,8}\b)")
_CODE_RE = re.compile(r"(?i)\b(code|token|pin)\s*(?:is|:)?\s*(\b\d{4,8}\b)")
_RESET_RE = re.compile(r"https?://\S*(?:reset|recover|verify-email|magic-link|one-time)[^\s]*", re.IGNORECASE)


def scrub_sensitive(text: str) -> str:
    """Mask OTP codes and reset/magic links. Best-effort, not a guarantee."""
    scrubbed = _OTP_RE.sub(lambda m: m.group(0).replace(m.group(1), "[code-filtered]"), text)
    scrubbed = _CODE_RE.sub(lambda m: m.group(0).replace(m.group(2), "[code-filtered]"), scrubbed)
    scrubbed = _RESET_RE.sub("[link-filtered]", scrubbed)
    return scrubbed


def _decode_header(value: str) -> str:
    try:
        parts = email.header.decode_header(value or "")
        return "".join(
            chunk.decode(charset or "utf-8", "replace") if isinstance(chunk, bytes) else chunk
            for chunk, charset in parts
        )
    except Exception:
        return str(value or "")


def _snippet(message: email.message.Message, *, max_chars: int) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition") or ""
            ):
                try:
                    payload = part.get_payload(decode=True) or b""
                    text = payload.decode(part.get_content_charset() or "utf-8", "replace")
                    return scrub_sensitive(text.strip()[:max_chars])
                except Exception:
                    continue
        return ""
    try:
        payload = message.get_payload(decode=True) or b""
        text = payload.decode(message.get_content_charset() or "utf-8", "replace")
        return scrub_sensitive(text.strip()[:max_chars])
    except Exception:
        return ""


def fetch_inbox(
    email_address: str,
    app_password: str,
    *,
    provider: str = "gmail",
    host: str = "",
    max_messages: int = DEFAULT_MAX_MESSAGES,
    query: str = "UNSEEN",
    snippet_chars: int = DEFAULT_SNIPPET_CHARS,
    connection_factory: Any = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Read-only inbox fetch. Returns headers + snippets (OTP-scrubbed)."""
    email_address = (email_address or "").strip()
    if not email_address or "@" not in email_address:
        raise ValueError("a valid email address is required")
    if not app_password:
        raise ValueError("an app password is required (provider-issued, not the account password)")
    default_host, default_port = IMAP_HOSTS.get(provider, IMAP_HOSTS["gmail"])
    target_host = host.strip() or default_host
    factory = connection_factory or imaplib.IMAP4_SSL

    def _connect():
        try:
            return factory(target_host, default_port, timeout=timeout)
        except TypeError:
            return factory(target_host, default_port)

    mail = _connect()
    try:
        mail.login(email_address, app_password)
        typ, _ = mail.select("INBOX", readonly=True)
        if typ != "OK":
            raise ValueError("could not open INBOX read-only")
        criteria = query.strip() or "UNSEEN"
        typ, data = mail.search(None, criteria)
        if typ != "OK":
            raise ValueError(f"search failed: {criteria!r}")
        uids = (data[0] or b"").split()[-max(1, max_messages) :]
        messages = []
        for uid in reversed(uids):
            typ, fetched = mail.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            msg = email.message_from_bytes(fetched[0][1])
            messages.append(
                {
                    "uid": uid.decode("ascii", "replace"),
                    "from": _decode_header(msg.get("From", "")),
                    "subject": _decode_header(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                    "snippet": _snippet(msg, max_chars=snippet_chars),
                }
            )
        return {"ok": True, "provider": provider, "host": target_host, "messages": messages}
    except imaplib.IMAP4.error as exc:
        raise ValueError(f"mail login failed (wrong app password or IMAP disabled?): {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            mail.logout()


def resolve_app_password(engine: Any, entity_id: str, *, key_id: str = "", label: str = "") -> dict[str, str]:
    """Find a stored app-password key and reveal it for the fetch.

    `provider_hint` on the key holds the email address (set at import).
    """
    keys = engine.store.list_custom_keys(entity_id)
    match = None
    for key in keys:
        if key["kind"] != "app_password":
            continue
        if (key_id and key["id"] == key_id) or (label and key["label"] == label):
            match = key
            break
    if match is None:
        raise ValueError("no such app-password key; save one in Stored Keys first")
    revealed = engine.reveal_custom_key(entity_id, match["id"])
    email_address = (match["provider_hint"] or "").strip()
    if "@" not in email_address:
        raise ValueError(
            f"key '{match['label']}' has no email address attached; re-save it with the address as the hint"
        )
    return {"email": email_address, "secret": revealed["secret"], "label": match["label"]}


__all__ = [
    "DEFAULT_MAX_MESSAGES",
    "IMAP_HOSTS",
    "fetch_inbox",
    "resolve_app_password",
    "scrub_sensitive",
]
