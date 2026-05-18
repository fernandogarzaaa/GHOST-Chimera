"""Lightweight local latency telemetry for Ghost Console routes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from statistics import median
from typing import Any

DEFAULT_BUDGETS_MS = {
    "fast": 250.0,
    "interactive": 1000.0,
    "slow": 2500.0,
}
MAX_LATENCY_EVENTS = 500


def _latency_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "operator_latency.jsonl"


def _route_budget_ms(route: str) -> float:
    if any(part in route for part in ("/models/discovery/refresh", "/rag/builder", "/mcp/chimeralang/enable")):
        return DEFAULT_BUDGETS_MS["slow"]
    if any(part in route for part in ("/run", "/review-pr", "/memory/ingest", "/browser/snapshot")):
        return DEFAULT_BUDGETS_MS["slow"]
    if any(part in route for part in ("/models/discovery/ping", "/github/", "/operator/readiness")):
        return DEFAULT_BUDGETS_MS["interactive"]
    return DEFAULT_BUDGETS_MS["fast"]


def record_latency_event(
    state_dir: str | Path,
    *,
    route: str,
    method: str,
    duration_ms: float,
    ok: bool,
    error: str = "",
) -> dict[str, Any]:
    event = {
        "timestamp": time.time(),
        "route": route,
        "method": method.upper(),
        "duration_ms": round(float(duration_ms), 3),
        "budget_ms": _route_budget_ms(route),
        "ok": bool(ok),
        "error": str(error or "")[:160],
    }
    event["over_budget"] = event["duration_ms"] > event["budget_ms"]
    path = _latency_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    _trim_latency_events(path)
    return event


def _trim_latency_events(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_LATENCY_EVENTS:
        return
    path.write_text("\n".join(lines[-MAX_LATENCY_EVENTS:]) + "\n", encoding="utf-8")


def read_latency_events(state_dir: str | Path, *, limit: int = 200) -> list[dict[str, Any]]:
    path = _latency_path(state_dir)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, MAX_LATENCY_EVENTS)) :]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    return events


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 3)
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((percentile / 100.0) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def latency_summary(state_dir: str | Path, *, limit: int = 200) -> dict[str, Any]:
    events = read_latency_events(state_dir, limit=limit)
    durations = [float(event.get("duration_ms") or 0.0) for event in events]
    by_route: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_route.setdefault(str(event.get("route") or "unknown"), []).append(event)
    route_summaries = []
    for route, route_events in by_route.items():
        route_durations = [float(event.get("duration_ms") or 0.0) for event in route_events]
        route_summaries.append(
            {
                "route": route,
                "count": len(route_events),
                "p50_ms": round(float(median(route_durations)), 3) if route_durations else 0.0,
                "p95_ms": _percentile(route_durations, 95),
                "max_ms": round(max(route_durations), 3) if route_durations else 0.0,
                "budget_ms": _route_budget_ms(route),
                "over_budget_count": sum(1 for event in route_events if event.get("over_budget")),
                "error_count": sum(1 for event in route_events if not event.get("ok", True)),
            }
        )
    route_summaries.sort(key=lambda item: (item["over_budget_count"], item["p95_ms"], item["count"]), reverse=True)
    p95 = _percentile(durations, 95)
    slow_events = sorted(events, key=lambda item: float(item.get("duration_ms") or 0.0), reverse=True)[:10]
    return {
        "ok": True,
        "event_count": len(events),
        "p50_ms": round(float(median(durations)), 3) if durations else 0.0,
        "p95_ms": p95,
        "max_ms": round(max(durations), 3) if durations else 0.0,
        "over_budget_count": sum(1 for event in events if event.get("over_budget")),
        "error_count": sum(1 for event in events if not event.get("ok", True)),
        "status": "fast" if p95 <= DEFAULT_BUDGETS_MS["fast"] else "watch" if p95 <= DEFAULT_BUDGETS_MS["interactive"] else "slow",
        "budgets_ms": DEFAULT_BUDGETS_MS,
        "routes": route_summaries[:20],
        "slow_events": slow_events,
        "recommendations": latency_recommendations(route_summaries, p95),
    }


def latency_recommendations(route_summaries: list[dict[str, Any]], p95_ms: float) -> list[str]:
    recommendations: list[str] = []
    if not route_summaries:
        return ["Use the Console normally; latency telemetry will populate automatically."]
    if p95_ms > DEFAULT_BUDGETS_MS["interactive"]:
        recommendations.append("P95 latency is over 1s; prefer cached discovery results and defer network refreshes.")
    for route in route_summaries[:5]:
        if route.get("over_budget_count", 0) > 0:
            recommendations.append(f"Review {route['route']}: {route['over_budget_count']} calls exceeded its budget.")
    if not recommendations:
        recommendations.append("Latency is within the current operator budget.")
    return recommendations[:6]
