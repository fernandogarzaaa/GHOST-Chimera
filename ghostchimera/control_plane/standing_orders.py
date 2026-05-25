"""Persistent Standing Orders for bounded autonomous programs."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

StandingObjectiveRunner = Any


def _now() -> float:
    return time.time()


def _state_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "standing_orders.json"


def _events_path(state_dir: str | Path) -> Path:
    return Path(state_dir).expanduser() / "standing_orders_events.jsonl"


def _stable_order_id(title: str, scope: str, created_at: float) -> str:
    raw = f"{title.strip().lower()}|{scope.strip().lower()}|{created_at:.6f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _clean_list(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:240] for item in value[:limit] if str(item).strip()]


def _redact_delivery(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if redacted.get("delivery_target"):
        redacted["delivery_target_configured"] = True
        redacted["delivery_target"] = "[redacted]"
    return redacted


def _default_state() -> dict[str, Any]:
    return {"orders": {}}


def _objective_text(order: dict[str, Any]) -> str:
    parts = [
        f"Standing order: {order.get('title')}",
        f"Scope: {order.get('scope')}",
        f"Objective: {order.get('objective')}",
    ]
    allowed = order.get("allowed_actions") if isinstance(order.get("allowed_actions"), list) else []
    gates = order.get("approval_gates") if isinstance(order.get("approval_gates"), list) else []
    if allowed:
        parts.append("Allowed actions: " + "; ".join(str(item) for item in allowed))
    if gates:
        parts.append("Approval gates: " + "; ".join(str(item) for item in gates))
    return "\n".join(parts)


class StandingOrderStore:
    """Local JSON store for operator-approved standing authority."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = _state_path(self.state_dir)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _default_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _default_state()
        if not isinstance(payload, dict):
            return _default_state()
        payload.setdefault("orders", {})
        return payload

    def _save(self, data: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"ts": _now(), "event": event_type, **_redact_delivery(payload)}
        with _events_path(self.state_dir).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        scope = str(payload.get("scope") or "general").strip()
        objective = str(payload.get("objective") or "").strip()
        if not title:
            raise ValueError("title is required")
        if not objective:
            raise ValueError("objective is required")
        if len(title) > 160 or len(scope) > 160 or len(objective) > 4000:
            raise ValueError("standing order fields are too long")
        data = self._load()
        created_at = _now()
        order = {
            "id": _stable_order_id(title, scope, created_at),
            "title": title,
            "scope": scope,
            "objective": objective,
            "allowed_actions": _clean_list(payload.get("allowed_actions")),
            "approval_gates": _clean_list(payload.get("approval_gates")),
            "delivery_channel": str(payload.get("delivery_channel") or "").strip()[:80],
            "delivery_target": str(payload.get("delivery_target") or "").strip()[:500],
            "status": "disabled",
            "created_at": created_at,
            "updated_at": created_at,
            "last_run_at": 0.0,
            "run_count": 0,
            "failure_count": 0,
            "last_result": {},
        }
        data["orders"][order["id"]] = order
        self._save(data)
        self._event("standing_order_created", {"order_id": order["id"], "title": title, "scope": scope})
        return {"ok": True, "order": _redact_delivery(order)}

    def list_orders(self) -> dict[str, Any]:
        data = self._load()
        orders = [_redact_delivery(order) for order in data["orders"].values() if isinstance(order, dict)]
        orders.sort(key=lambda item: str(item.get("title") or ""))
        return {
            "ok": True,
            "orders": orders,
            "counts": {
                "orders": len(orders),
                "enabled": len([order for order in orders if order.get("status") == "enabled"]),
                "disabled": len([order for order in orders if order.get("status") == "disabled"]),
            },
        }

    def enable_order(self, order_id: str) -> dict[str, Any]:
        return self._set_status(order_id, "enabled")

    def disable_order(self, order_id: str) -> dict[str, Any]:
        return self._set_status(order_id, "disabled")

    def _set_status(self, order_id: str, status: str) -> dict[str, Any]:
        data = self._load()
        order = data["orders"].get(order_id)
        if not isinstance(order, dict):
            return {"ok": False, "error": "Standing order not found."}
        order["status"] = status
        order["updated_at"] = _now()
        data["orders"][order_id] = order
        self._save(data)
        self._event("standing_order_status_changed", {"order_id": order_id, "status": status})
        return {"ok": True, "order": _redact_delivery(order)}

    def run_order(self, order_id: str, *, objective_runner: Any | None = None) -> dict[str, Any]:
        data = self._load()
        order = data["orders"].get(order_id)
        if not isinstance(order, dict):
            return {"ok": False, "error": "Standing order not found."}
        if order.get("status") != "enabled":
            return {"ok": False, "error": "Standing order is disabled.", "order": _redact_delivery(order)}
        objective = _objective_text(order)
        result = {"ok": True, "preview": True, "objective": objective}
        if objective_runner is not None:
            result = objective_runner(objective)
        order["last_run_at"] = _now()
        order["run_count"] = int(order.get("run_count") or 0) + 1
        if not result.get("ok", True):
            order["failure_count"] = int(order.get("failure_count") or 0) + 1
        order["last_result"] = {"ok": bool(result.get("ok", True)), "preview": bool(result.get("preview", False))}
        order["updated_at"] = _now()
        data["orders"][order_id] = order
        self._save(data)
        self._event(
            "standing_order_run",
            {"order_id": order_id, "ok": bool(result.get("ok", True)), "title": order.get("title", "")},
        )
        return {"ok": bool(result.get("ok", True)), "order": _redact_delivery(order), "result": _redact_delivery(result)}


__all__ = ["StandingOrderStore"]
