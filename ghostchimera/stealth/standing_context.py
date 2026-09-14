"""Standing Context: durable, versioned user summary for hosts and tasks.

Where the User Model is the full belief state, Standing Context is its
stable, shareable projection: identity, communication style, active work,
and preferences, rendered within a token budget for a specific host or
task. Revisions advance only when content actually changes, so generated
host files (CLAUDE.md-style) are rewritten solely on real updates while
dynamic state stays ephemeral in the runtime.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .user_model import UserModel

TRUNCATION_MARKER = "\n[...truncated...]"


@dataclass
class StandingSection:
    """One named block of the standing context with provenance."""

    name: str
    lines: list[str] = field(default_factory=list)
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "lines": list(self.lines), "provenance": self.provenance}


def _top_targets(relations: dict[str, dict[str, float]], prefix: str, limit: int = 5) -> list[str]:
    scored: dict[str, float] = {}
    for bucket in relations.values():
        for target, weight in bucket.items():
            if target.startswith(prefix):
                scored[target] = scored.get(target, 0.0) + weight
    return sorted(scored, key=lambda target: scored[target], reverse=True)[: max(0, limit)]


def _matches_task(text: str, task: str) -> bool:
    if not task:
        return True
    keywords = [word.lower() for word in task.split() if len(word) > 3]
    lowered = text.lower()
    return not keywords or any(keyword in lowered for keyword in keywords)


class StandingContext:
    """Versioned projection of a UserModel for hosts and tasks."""

    def __init__(self) -> None:
        self.revision = 0
        self.updated_at = 0.0
        self._sections: list[StandingSection] = []
        self._fingerprint = ""

    @property
    def sections(self) -> list[StandingSection]:
        """The sections from the most recent refresh."""

        return list(self._sections)

    def refresh(self, user_model: UserModel) -> bool:
        """Rebuild from the model; return True when content changed."""

        sections = self._build(user_model)
        fingerprint = hashlib.sha256(
            "\n".join(section.name + "\n" + "\n".join(section.lines) for section in sections).encode("utf-8")
        ).hexdigest()
        if fingerprint == self._fingerprint:
            return False
        self._sections = sections
        self._fingerprint = fingerprint
        self.revision += 1
        self.updated_at = time.time()
        return True

    def _build(self, user_model: UserModel) -> list[StandingSection]:
        sections: list[StandingSection] = []
        identity_lines: list[str] = []
        seen: set[str] = set()
        for trait in user_model.confirmed_traits("identity"):
            if trait.key not in seen:
                seen.add(trait.key)
                identity_lines.append(f"{trait.key}: {trait.value}")
        if identity_lines:
            sections.append(
                StandingSection(
                    name="identity",
                    lines=sorted(identity_lines),
                    provenance=f"{len(identity_lines)} identity facts",
                )
            )
        communication = [f"{trait.key}: {trait.value}" for trait in user_model.confirmed_traits("communication")]
        if communication:
            sections.append(
                StandingSection(name="communication", lines=sorted(communication), provenance="confirmed traits")
            )
        relations = user_model.relations()
        people = _top_targets(relations, "person:")
        projects = _top_targets(relations, "project:")
        work_lines = [f"person: {name.split('person:', 1)[1]}" for name in people[:5]]
        work_lines += [f"project: {name.split('project:', 1)[1]}" for name in projects[:5]]
        if work_lines:
            sections.append(StandingSection(name="work", lines=work_lines, provenance="weighted work graph"))
        personality = [
            f"{trait.key}: {trait.value} (confidence {trait.confidence:.2f})"
            for trait in user_model.confirmed_traits("personality")
        ]
        if personality:
            sections.append(
                StandingSection(name="personality", lines=sorted(personality), provenance="confirmed traits")
            )
        return sections

    def render(self, *, host: str = "", task: str = "", max_chars: int = 2000) -> str:
        """Render the latest refresh within a character budget."""

        lines = ["# Standing context"]
        if host or task:
            lines.append(f"host={host or '-'} task={task or '-'}")
        rendered_any = False
        for section in self._sections:
            section_lines = section.lines
            if task and section.name == "work":
                section_lines = [line for line in section_lines if _matches_task(line, task)]
            if not section_lines:
                continue
            rendered_any = True
            lines.append(f"## {section.name}")
            lines.extend(section_lines)
        if not rendered_any:
            lines.append("(no confirmed traits yet)")
        block = "\n".join(lines).strip()
        budget = max(0, max_chars)
        if len(block) > budget:
            block = block[:budget].rstrip() + TRUNCATION_MARKER
        return block

    def to_dict(self) -> dict[str, Any]:
        """Serializable revision snapshot."""

        return {
            "revision": self.revision,
            "updated_at": self.updated_at,
            "sections": [section.to_dict() for section in self._sections],
        }

    def write_if_changed(self, path: str | Path, *, host: str = "", max_chars: int = 4000) -> bool:
        """Write the rendered block only when it differs; return True on write."""

        target = Path(path)
        block = self.render(host=host, max_chars=max_chars)
        try:
            if target.is_file() and target.read_text(encoding="utf-8") == block:
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(block, encoding="utf-8")
        except OSError:
            return False
        return True


__all__ = ["StandingContext", "StandingSection", "TRUNCATION_MARKER"]
