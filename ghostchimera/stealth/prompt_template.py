"""Chat prompt templates with roles, history slots, partials, few-shot.

LangChain-inspired (``ChatPromptTemplate`` / ``MessagesPlaceholder`` /
``.partial()`` / few-shot examples), implemented dependency-free on the
``{{VAR}}`` substitution convention already used by
:mod:`ghostchimera.stealth.agent_prompt`.

Message roles are ``system`` / ``human`` / ``assistant``. History slots
accept message dicts (``{"role": ..., "content": ...}``) or
``(role, content)`` tuples and pass them through untouched.

Usage::

    from ghostchimera.stealth.prompt_template import ChatPromptTemplate

    template = ChatPromptTemplate.from_messages([
        ("system", "You are {{ROLE}}."),
        ("placeholder", "history"),
        ("human", "{{QUESTION}}"),
    ]).partial(ROLE="a helpful assistant")

    messages = template.format(history=[{"role": "human", "content": "hi"}], QUESTION="go")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VARIABLE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def _substitute(template: str, variables: dict[str, Any]) -> str:
    """Replace ``{{NAME}}`` placeholders; unknown names are left in place."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(variables[name]) if name in variables else match.group(0)

    return _VARIABLE.sub(replace, template)


@dataclass(frozen=True)
class ChatMessage:
    """One rendered message: a role plus its content."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class FewShotExamples:
    """Capped example list rendered as alternating human/assistant turns.

    Only the most recent ``max_examples`` are kept so prompts stay bounded.
    """

    examples: list[tuple[str, str]] = field(default_factory=list)
    max_examples: int = 4
    human_prefix: str = "Example input:"
    assistant_prefix: str = "Example output:"

    def messages(self) -> list[ChatMessage]:
        kept = self.examples[-max(0, self.max_examples) :] if self.max_examples else []
        rendered: list[ChatMessage] = []
        for human_text, assistant_text in kept:
            rendered.append(ChatMessage(role="human", content=f"{self.human_prefix}\n{human_text}"))
            rendered.append(ChatMessage(role="assistant", content=f"{self.assistant_prefix}\n{assistant_text}"))
        return rendered


@dataclass
class ChatPromptTemplate:
    """Ordered message specs rendered against variables and history.

    Each spec is one of:

    * ``(role, template)`` — rendered with ``{{VAR}}`` substitution.
    * ``("placeholder", name)`` — spliced in from the ``name`` format kwarg
      as a message list (history slot).
    * ``FewShotExamples`` — expanded to capped example turns.
    """

    message_specs: list[Any] = field(default_factory=list)
    partial_variables: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_messages(cls, messages: list[Any]) -> ChatPromptTemplate:
        return cls(message_specs=list(messages))

    def partial(self, **variables: Any) -> ChatPromptTemplate:
        """Return a copy with *variables* pre-bound (LangChain ``.partial``)."""
        merged = {**self.partial_variables, **variables}
        return ChatPromptTemplate(message_specs=list(self.message_specs), partial_variables=merged)

    def input_variables(self) -> list[str]:
        """Names still unbound after partials (placeholders excluded)."""
        names: list[str] = []
        for spec in self.message_specs:
            if isinstance(spec, FewShotExamples):
                continue
            if isinstance(spec, (tuple, list)) and len(spec) == 2 and spec[0] != "placeholder":
                for match in _VARIABLE.finditer(str(spec[1])):
                    if match.group(1) not in self.partial_variables and match.group(1) not in names:
                        names.append(match.group(1))
        return names

    def format(self, **variables: Any) -> list[ChatMessage]:
        """Render to a message list. History slots pass through untouched."""
        bound = {**self.partial_variables, **variables}
        rendered: list[ChatMessage] = []
        for spec in self.message_specs:
            if isinstance(spec, FewShotExamples):
                for message in spec.messages():
                    rendered.append(
                        ChatMessage(
                            role=message.role,
                            content=_substitute(message.content, bound),
                        )
                    )
            elif isinstance(spec, (tuple, list)) and len(spec) == 2:
                role, template = spec
                if role == "placeholder":
                    rendered.extend(_as_messages(bound.get(template, [])))
                else:
                    rendered.append(ChatMessage(role=str(role), content=_substitute(str(template), bound)))
            else:
                raise ValueError(f"Invalid message spec: {spec!r}")
        return rendered

    def format_system(self, **variables: Any) -> str:
        """Render and join as a single system-style string (legacy callers)."""
        return "\n".join(message.content for message in self.format(**variables))


def _as_messages(history: Any) -> list[ChatMessage]:
    """Normalize a history slot to ``ChatMessage`` without touching content."""
    if not history:
        return []
    normalized: list[ChatMessage] = []
    for item in history:
        if isinstance(item, ChatMessage):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(ChatMessage(role=str(item.get("role", "human")), content=str(item.get("content", ""))))
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            normalized.append(ChatMessage(role=str(item[0]), content=str(item[1])))
        else:
            raise ValueError(f"Invalid history item: {item!r}")
    return normalized


__all__ = ["ChatMessage", "ChatPromptTemplate", "FewShotExamples"]
