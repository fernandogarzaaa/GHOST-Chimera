"""MiniMind-assisted GitHub work discovery helpers."""

from __future__ import annotations

from typing import Any


def rank_work_items(items: list[dict[str, Any]], personal_context: str = "") -> list[dict[str, Any]]:
    """Rank GitHub work items using deterministic urgency and user-context signals."""

    context = personal_context.lower()
    ranked: list[dict[str, Any]] = []
    for item in items:
        labels = {str(label).lower() for label in item.get("labels") or []}
        title = str(item.get("title") or "").lower()
        score = 0.0
        if item.get("assigned"):
            score += 2.0
        if "bug" in labels or "failure" in title or "failing" in title:
            score += 1.5
        if "release" in title and "release" in context:
            score += 1.0
        if "ci" in title and "ci" in context:
            score += 0.5
        enriched = dict(item)
        enriched["score"] = round(score, 3)
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: item["score"], reverse=True)
