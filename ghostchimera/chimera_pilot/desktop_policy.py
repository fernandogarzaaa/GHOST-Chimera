"""Desktop action-class helpers shared by compiler, policy, and runtime."""

from __future__ import annotations

import datetime as dt
import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Any


class DesktopActionClass(StrEnum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


DESKTOP_ACTION_CLASSES = tuple(item.value for item in DesktopActionClass)
DEFAULT_ALLOWED_DESKTOP_ACTION_CLASSES = (
    DesktopActionClass.READ_ONLY.value,
    DesktopActionClass.MUTATING.value,
)
DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN = "confirm-destructive-desktop"
DEFAULT_DESKTOP_KILL_SWITCH_FILE = ".ghostchimera-desktop-stop"

_DEFAULT_BY_ACTION = {
    "move": DesktopActionClass.READ_ONLY,
    "click": DesktopActionClass.MUTATING,
    "double_click": DesktopActionClass.MUTATING,
    "right_click": DesktopActionClass.MUTATING,
    "type": DesktopActionClass.MUTATING,
    "hotkey": DesktopActionClass.MUTATING,
}

_DESTRUCTIVE_TERMS = (
    "delete",
    "remove",
    "erase",
    "format",
    "factory reset",
    "reset",
    "shutdown",
    "restart",
    "reboot",
    "uninstall",
    "discard",
    "close without saving",
    "overwrite",
)

_DESTRUCTIVE_HOTKEYS = {
    ("alt", "f4"),
    ("ctrl", "w"),
    ("ctrl", "q"),
    ("shift", "delete"),
}


def normalize_desktop_action_class(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text not in DESKTOP_ACTION_CLASSES:
        raise ValueError(f"Unknown desktop action class: {value}")
    return text


def infer_desktop_action_class(
    *,
    action: str,
    inputs: dict[str, Any] | None = None,
    objective: str = "",
) -> str:
    inputs = inputs or {}
    explicit = inputs.get("action_class")
    if explicit:
        return normalize_desktop_action_class(explicit)

    text = " ".join(
        str(value)
        for value in (
            objective,
            inputs.get("target", ""),
            inputs.get("text", ""),
        )
        if value is not None
    ).lower()
    if any(term in text for term in _DESTRUCTIVE_TERMS):
        return DesktopActionClass.DESTRUCTIVE.value

    keys = inputs.get("keys")
    if isinstance(keys, list):
        normalized_keys = tuple(str(key).strip().lower() for key in keys if str(key).strip())
        if normalized_keys in _DESTRUCTIVE_HOTKEYS:
            return DesktopActionClass.DESTRUCTIVE.value

    return _DEFAULT_BY_ACTION.get(action.strip().lower(), DesktopActionClass.MUTATING).value


def normalize_allowed_desktop_action_classes(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if values is None:
        return DEFAULT_ALLOWED_DESKTOP_ACTION_CLASSES
    normalized = tuple(dict.fromkeys(normalize_desktop_action_class(value) for value in values))
    return normalized or DEFAULT_ALLOWED_DESKTOP_ACTION_CLASSES


def destructive_desktop_confirmation_error(token: Any) -> str | None:
    if str(token or "").strip() == DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN:
        return None
    return f"Destructive live desktop actions require confirmation token '{DESTRUCTIVE_DESKTOP_CONFIRMATION_TOKEN}'"


def resolve_desktop_kill_switch_path(path: str | None = None) -> Path:
    configured = (path or "").strip() or os.environ.get("GHOSTCHIMERA_DESKTOP_KILL_SWITCH", "").strip()
    if not configured:
        configured = DEFAULT_DESKTOP_KILL_SWITCH_FILE
    return Path(configured).expanduser()


def write_desktop_stop_file(path: str | None = None, *, reason: str = "operator_stop") -> Path:
    target = resolve_desktop_kill_switch_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "reason": reason,
    }
    target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return target
