"""Desktop semantic target parsing helpers."""

from __future__ import annotations

import re
from typing import Any

_TARGET_FIELDS = ("app", "window", "control", "text")
_TARGET_PATTERN = re.compile(
    r"\b(app|window|control|text)\s*=\s*(\"[^\"]+\"|'[^']+'|[^,;]+?)(?=\s+\w+\s*=|$|[,;])",
    re.IGNORECASE,
)


def normalize_target_descriptor(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for field in _TARGET_FIELDS:
        raw = value.get(field)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            normalized[field] = text
    return normalized


def parse_target_descriptor(text: str) -> dict[str, str]:
    descriptor: dict[str, str] = {}
    for match in _TARGET_PATTERN.finditer(text):
        key = match.group(1).lower()
        value = match.group(2).strip().strip("\"'")
        if value:
            descriptor[key] = value
    return descriptor


def resolve_target_descriptor(inputs: dict[str, Any]) -> dict[str, str]:
    explicit = normalize_target_descriptor(inputs.get("target_descriptor"))
    if explicit:
        return explicit
    target = str(inputs.get("target", "")).strip()
    if not target:
        return {}
    return parse_target_descriptor(target)


def collect_target_scopes_from_inputs(inputs: dict[str, Any]) -> list[dict[str, str]]:
    scopes: list[dict[str, str]] = []
    descriptor = resolve_target_descriptor(inputs)
    if descriptor:
        scopes.append(descriptor)
    plan = inputs.get("plan")
    if isinstance(plan, list):
        for step in plan:
            if not isinstance(step, dict):
                continue
            step_descriptor = resolve_target_descriptor(step)
            if step_descriptor:
                scopes.append(step_descriptor)
    return scopes

