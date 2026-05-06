"""
Cognition Layer
===============

This module contains a small symbolic reasoning engine for ordering planned
tasks.  It keeps the planner dependency-free while still honoring explicit
task dependencies before execution.
"""

from __future__ import annotations

from typing import Any


def linearise_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return tasks in dependency-safe execution order.

    Tasks may declare an identifier with ``id``, ``task_id``, or ``name`` and
    dependencies with ``depends_on``, ``dependencies``, or ``after``.  Unknown
    dependency names are ignored so model-generated plans can still execute
    when they reference external context.  Cycles among known tasks are
    rejected because they cannot be executed deterministically.
    """
    indexed = list(enumerate(tasks))
    identifiers: dict[str, int] = {}
    for index, task in indexed:
        task_id = _task_identifier(task)
        if task_id:
            identifiers.setdefault(task_id, index)

    dependencies: dict[int, set[int]] = {index: set() for index, _task in indexed}
    dependents: dict[int, set[int]] = {index: set() for index, _task in indexed}
    for index, task in indexed:
        for dep_name in _dependency_names(task):
            dep_index = identifiers.get(dep_name)
            if dep_index is None or dep_index == index:
                continue
            dependencies[index].add(dep_index)
            dependents[dep_index].add(index)

    ready = [index for index, _task in indexed if not dependencies[index]]
    ordered_indices: list[int] = []
    while ready:
        current = ready.pop(0)
        ordered_indices.append(current)
        for dependent in sorted(dependents[current]):
            dependencies[dependent].discard(current)
            if not dependencies[dependent] and dependent not in ordered_indices and dependent not in ready:
                ready.append(dependent)
        ready.sort()

    if len(ordered_indices) != len(tasks):
        unresolved = [str(_task_identifier(tasks[index]) or index) for index in dependencies if dependencies[index]]
        raise ValueError(f"Task dependency cycle detected: {', '.join(unresolved)}")

    return [tasks[index] for index in ordered_indices]


def _task_identifier(task: dict[str, Any]) -> str:
    for key in ("id", "task_id", "name"):
        value = task.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _dependency_names(task: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("depends_on", "dependencies", "after"):
        value = task.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            names.append(value.strip())
        elif isinstance(value, (list, tuple, set)):
            names.extend(str(item).strip() for item in value if str(item).strip())
    return names
