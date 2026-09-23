"""Inbox triage: score now, not more polling.

Email triggers already fire on a 5-minute throttle; triage answers the
next question — *what needs focus*. Pure heuristics, zero tokens:
sender VIP status, urgency signals, direct address, thread history, and
newsletter demotion feed a 0–100 score mapped to three buckets:

- ``act_now`` (>= 70): direct, urgent, or VIP.
- ``today``   (40–69): worth reading today.
- ``fyi``     (< 40): digest material, never interrupts.

VIP senders are an explicit user list (console managed) — never inferred
silently. Ambiguous mid-range items may optionally spend one capped
Lite-class model call elsewhere; this module never calls models itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ACT_NOW_MIN = 70
TODAY_MIN = 40

_URGENCY = [
    "urgent",
    "asap",
    "immediately",
    "deadline",
    "due today",
    "due tomorrow",
    "action required",
    "approval needed",
    "needs your approval",
    "blocking",
    "blocked",
    "outage",
    "incident",
    "security alert",
    "payment failed",
    "expires today",
    "last chance",
    "time sensitive",
    "emergency",
]
_NEWSLETTER = [
    "newsletter",
    "digest",
    "weekly roundup",
    "monthly update",
    "promo",
    "sale ends",
    "discount",
    "% off",
    "unsubscribe",
    "view in browser",
    "noreply",
    "no-reply",
    "donotreply",
]


def _contains_any(haystack: str, needles: list[str]) -> str | None:
    lowered = haystack.lower()
    for needle in needles:
        if needle in lowered:
            return needle
    return None


def score_message(
    message: dict[str, Any],
    *,
    vip_senders: list[str] | None = None,
    user_email: str = "",
    thread_replied: bool = False,
) -> dict[str, Any]:
    """Score one normalized mail dict (from/subject/snippet keys)."""
    sender = str(message.get("from", "") or "")
    subject = str(message.get("subject", "") or "")
    snippet = str(message.get("snippet", "") or "")
    combined = f"{subject}\n{snippet}"
    score = 20  # baseline: it arrived, it counts a little
    reasons: list[str] = []

    sender_low = sender.lower()
    is_vip = any(vip.lower() in sender_low for vip in (vip_senders or []) if vip)
    if is_vip:
        score += 40
        reasons.append("VIP sender (+40)")
    hit = _contains_any(combined, _URGENCY)
    if hit:
        score += 25
        reasons.append(f"urgency signal {hit!r} (+25)")
    if user_email and user_email.lower() in combined.lower():
        score += 15
        reasons.append("addresses you directly (+15)")
    if thread_replied:
        score += 10
        reasons.append("ongoing thread (+10)")
    news = _contains_any(f"{sender_low}\n{combined}", _NEWSLETTER)
    if news:
        score -= 30
        reasons.append(f"bulk/newsletter pattern {news!r} (−30)")

    score = max(0, min(100, score))
    tier = "act_now" if score >= ACT_NOW_MIN else ("today" if score >= TODAY_MIN else "fyi")
    return {
        "uid": message.get("uid", ""),
        "from": sender,
        "subject": subject,
        "score": score,
        "tier": tier,
        "reasons": reasons,
    }


def triage_messages(
    messages: list[dict[str, Any]],
    *,
    vip_senders: list[str] | None = None,
    user_email: str = "",
    replied_uids: list[str] | None = None,
) -> dict[str, Any]:
    """Bucket scored messages; FYI collapses into a digest summary."""
    replied = set(replied_uids or [])
    scored = [
        score_message(
            message,
            vip_senders=vip_senders,
            user_email=user_email,
            thread_replied=message.get("uid", "") in replied,
        )
        for message in messages
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    buckets = {"act_now": [], "today": [], "fyi": []}
    for item in scored:
        buckets[item["tier"]].append(item)
    digest_lines = [f"• {item['from']} — {item['subject']} ({item['score']})" for item in buckets["fyi"][:10]]
    return {
        "buckets": buckets,
        "counts": {tier: len(items) for tier, items in buckets.items()},
        "digest": "\n".join(digest_lines) if digest_lines else "Nothing filed as FYI.",
    }


__all__ = ["ACT_NOW_MIN", "TODAY_MIN", "load_vip_senders", "save_vip_senders", "score_message", "triage_messages"]


def _vip_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "triage.json"


def load_vip_senders(state_dir: str | Path) -> list[str]:
    """Explicit VIP list. Empty by default — never inferred silently."""
    try:
        data = json.loads(_vip_path(state_dir).read_text(encoding="utf-8"))
        senders = data.get("vip_senders", []) if isinstance(data, dict) else []
        return [str(s).strip() for s in senders if str(s).strip()][:100]
    except (OSError, ValueError):
        return []


def save_vip_senders(state_dir: str | Path, senders: list[str]) -> list[str]:
    """Replace the VIP list. Returns the stored list."""
    cleaned = []
    for sender in senders:
        text = str(sender or "").strip()[:160]
        if text and text not in cleaned:
            cleaned.append(text)
    cleaned = cleaned[:100]
    path = _vip_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"vip_senders": cleaned}), encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot save VIP list: {exc}") from exc
    return cleaned
