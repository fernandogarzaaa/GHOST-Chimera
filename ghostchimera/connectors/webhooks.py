"""Unified inbound webhooks: Gmail / Slack / Zendesk -> Ghost events.

Mirrors the production ingestion contract: POST /webhooks/{source}/{va_id}
normalizes provider payloads into one event shape, the loop/queue takes it
from there, and the endpoint answers 200 immediately. Provider signature
verification stays upstream (gateway/HMAC layer); these are pure mappers.
"""

from __future__ import annotations

from typing import Any

from ..stealth.events import Event, new_event


def _gmail_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers = {}
    for part in (payload.get("payload") or {}).get("headers", []) or []:
        if isinstance(part, dict) and part.get("name"):
            headers[str(part["name"]).lower()] = str(part.get("value", ""))
    return headers


def normalize_gmail_push(delivery_id: str, va_id: str, payload: dict[str, Any]) -> Event | None:
    """Gmail push/watch notification or full message resource -> email.received."""
    headers = _gmail_headers(payload)
    subject = headers.get("subject", "") or str(payload.get("snippet", ""))[:200]
    sender = headers.get("from", "")
    message_id = str(payload.get("id") or delivery_id)
    thread = str(payload.get("threadId", ""))
    labels = payload.get("labelIds") or []
    return new_event(
        "email.received",
        source="gmail",
        actor=sender,
        payload={
            "va_id": va_id,
            "message_id": message_id,
            "thread_id": thread,
            "subject": subject,
            "labels": labels,
            "relevance": 0.7,
            "confidence": 0.8,
            "benefit": 0.6,
        },
        event_id=f"gmail-{va_id}-{message_id}",
        confidence=0.8,
    )


def normalize_slack_event(delivery_id: str, va_id: str, payload: dict[str, Any]) -> Event | None:
    """Slack Events API envelope -> message event (url_verification is handled upstream)."""
    event = payload.get("event") or {}
    if payload.get("type") == "url_verification":
        return None  # answered by the verification layer, not the loop
    if not isinstance(event, dict) or event.get("type") not in ("message", "app_mention"):
        return None
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return None  # never learn from our own echoes
    text = str(event.get("text", ""))[:2000]
    if not text.strip():
        return None
    return new_event(
        "agent.prompt_submitted" if event.get("type") == "app_mention" else "note.created",
        source="slack",
        actor=str(event.get("user", "")),
        payload={
            "va_id": va_id,
            "channel": str(event.get("channel", "")),
            "thread_ts": str(event.get("thread_ts") or event.get("ts", "")),
            "text": text,
            "relevance": 0.7,
            "confidence": 0.8,
            "benefit": 0.6,
        },
        event_id=f"slack-{va_id}-{event.get('channel', '')}-{event.get('ts', delivery_id)}",
        confidence=0.8,
    )


def normalize_zendesk_ticket(delivery_id: str, va_id: str, payload: dict[str, Any]) -> Event | None:
    """Zendesk ticket webhook / trigger payload -> ticket event."""
    ticket = payload.get("ticket") or payload
    if not isinstance(ticket, dict) or "id" not in ticket:
        return None
    status = str(ticket.get("status", "new"))
    event_type = "agent.prompt_submitted" if status in ("new", "open") else "agent.response_completed"
    return new_event(
        event_type,
        source="zendesk",
        actor=str((ticket.get("requester") or {}).get("email", "") or ticket.get("requester_id", "")),
        payload={
            "va_id": va_id,
            "ticket_id": ticket.get("id"),
            "subject": str(ticket.get("subject", ""))[:300],
            "priority": str(ticket.get("priority", "normal")),
            "tags": list(ticket.get("tags") or [])[:20],
            "relevance": 0.8,
            "confidence": 0.85,
            "benefit": 0.7,
        },
        event_id=f"zendesk-{va_id}-{ticket.get('id')}-{delivery_id}",
        confidence=0.85,
    )


NORMALIZERS = {
    "gmail": normalize_gmail_push,
    "slack": normalize_slack_event,
    "zendesk": normalize_zendesk_ticket,
}


def normalize_webhook(source: str, delivery_id: str, va_id: str, payload: dict[str, Any]) -> Event | None:
    """Unified entry: source + delivery id + VA + raw payload -> Event|None."""
    normalizer = NORMALIZERS.get(source)
    if normalizer is None:
        return None
    return normalizer(delivery_id, va_id, payload)


__all__ = [
    "NORMALIZERS",
    "normalize_gmail_push",
    "normalize_slack_event",
    "normalize_webhook",
    "normalize_zendesk_ticket",
]
