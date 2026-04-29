"""
Tech Support Skill
==================

This skill responds to basic technical support questions.  It uses the LLM
module when available to generate answers to free‑form queries.  When the
language model is not configured it will return a polite message informing
the user to check their configuration or contact a human.

Supported actions:

- ``ask_llm`` – ask the large language model a question.  The task should
  include a ``prompt`` key with the user question.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import Skill
from ..model_layer.llm import LLM


class TechSupportSkill(Skill):
    name = "tech_support"
    description = "Answer technical questions using a language model"
    actions = ["ask_llm"]

    def __init__(self) -> None:
        # Create an LLM instance for this skill.  It will read its
        # configuration from environment variables.
        self.llm = LLM()

    def run(self, task: Dict[str, Any]) -> Any:
        action = task.get("action")
        if action != "ask_llm":
            raise ValueError(f"TechSupportSkill only handles ask_llm tasks, got {action}")
        prompt = task.get("prompt")
        if not prompt:
            raise ValueError("'prompt' is required for ask_llm task")
        if self.llm.available:
            # Compose a polite system prompt instructing the model to answer as a
            # helpful technical assistant.
            system_message = (
                "You are GhostChimera's technical support assistant. "
                "Answer user questions clearly and concisely. If you are unsure "
                "or the question is unrelated to your knowledge domain, say that you "
                "do not know."
            )
            return self.llm.chat(system_message, prompt)
        return (
            "The language model is not configured.  Please set your OpenAI API key "
            "in the environment variable OPENAI_API_KEY to enable this skill."
        )