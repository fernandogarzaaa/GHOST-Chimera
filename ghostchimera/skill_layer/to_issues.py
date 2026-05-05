"""
To Issues Skill
===============

This skill converts a high‑level plan or specification into a list of
individually actionable issues.  It does not interact with external
services (such as GitHub) but instead returns a human‑readable list that
could be used to create issues manually.  The plan is assumed to be a
single string containing tasks separated by newlines, semicolons or the
word "and".

Supported actions:

- ``to_issues`` – convert the provided ``plan`` into a list of issues.

Example task::

    {
        "action": "to_issues",
        "plan": "Implement feature A; write tests for B; update documentation"
    }

The skill will return::

    1. Implement feature A
    2. Write tests for B
    3. Update documentation

"""

from __future__ import annotations

import re
from typing import Any

from .base import Skill


class ToIssuesSkill(Skill):
    """Convert a free‑form plan into a list of discrete issues."""

    name = "to_issues"
    description = "Break a plan or specification into a numbered list of issues"
    actions = ["to_issues"]

    def run(self, task: dict[str, Any]) -> Any:
        action = task.get("action")
        if action != "to_issues":
            raise ValueError(f"ToIssuesSkill only handles to_issues tasks, got {action}")
        plan = task.get("plan")
        if not plan:
            raise ValueError("'plan' is required for to_issues task")
        # Split the plan into candidate issue descriptions.  We treat
        # semicolons, newlines and the word 'and' as separators.  Multiple
        # consecutive separators are collapsed.  We strip whitespace and
        # capitalise the first letter of each issue.
        # Normalise line breaks and replace semicolons with newlines
        text = str(plan)
        # Replace the word ' and ' with a newline to split on
        text = re.sub(r"\band\b", "\n", text, flags=re.IGNORECASE)
        # Replace semicolons with newlines
        text = text.replace(";", "\n")
        # Split by newlines
        raw_items = [item.strip() for item in text.splitlines()]
        # Filter out empty strings
        items: list[str] = [item for item in raw_items if item]
        if not items:
            return "No issues could be extracted from the provided plan."
        # Capitalise the first letter of each item
        formatted = [item[0].upper() + item[1:] if item else item for item in items]
        # Build numbered list
        lines = [f"{i}. {issue}" for i, issue in enumerate(formatted, start=1)]
        return "\n".join(lines)
