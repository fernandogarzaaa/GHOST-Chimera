"""Desktop action-class helpers shared by compiler, policy, and runtime."""

from __future__ import annotations

from enum import StrEnum
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
