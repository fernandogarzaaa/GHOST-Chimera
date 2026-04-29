"""
Planner
=======

The planner is responsible for breaking down a high level natural language
request into a structured list of tasks.  A task is represented as a
dictionary with an ``action`` key and optional free‑form parameters.  For
example, the input ``"create a file hello.txt with content 'Hello world'"``
would yield a single task:

.. code-block:: python

    {"action": "write_file", "path": "hello.txt", "content": "Hello world"}

More advanced planners might return multi‑step plans.  This implementation
uses a very simple heuristic and falls back to a language model when
available.
"""

from __future__ import annotations

import json
import os
from typing import List, Dict, Any

from ..model_layer.llm import LLM


class Planner:
    """Convert free text requests into structured task lists."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def _heuristic_plan(self, request: str) -> List[Dict[str, Any]]:
        """Fallback heuristic planner.

        This very simple planner recognises a few common patterns and
        constructs the corresponding task dictionaries.  If it cannot
        recognise the request it will produce a single ``"ask_llm"`` task to
        delegate to the language model.
        """
        req_lower = request.strip().lower()
        tasks: List[Dict[str, Any]] = []
        # Create file pattern: "create a file X with content Y"
        if req_lower.startswith("create a file") and "with content" in req_lower:
            try:
                # naive parsing
                parts = req_lower.split("create a file", 1)[1].strip()
                path_part, content_part = parts.split("with content", 1)
                path = path_part.strip().strip("\"'")
                content = content_part.strip().strip("\"'")
                tasks.append({"action": "write_file", "path": path, "content": content})
            except Exception:
                # fall back to llm
                tasks.append({"action": "ask_llm", "prompt": request})
        elif req_lower.startswith("run command"):
            # Execute a shell command
            command = request.split("run command", 1)[1].strip()
            tasks.append({"action": "shell", "command": command})
        elif req_lower.startswith("fetch ") or req_lower.startswith("get "):
            # Simple URL fetch pattern: fetch http://example.com
            parts = request.split(maxsplit=1)
            if len(parts) == 2 and parts[1].startswith("http"):
                url = parts[1].strip()
                tasks.append({"action": "http_get", "url": url})
            else:
                tasks.append({"action": "ask_llm", "prompt": request})
        # Simple code search pattern: "search code for <query>" or "search codebase for <query>"
        # We support both "search code for" and "search the codebase for" forms.  If such a
        # pattern is matched, the remainder of the string after "for" becomes the query.
        elif req_lower.startswith("search code for") or req_lower.startswith("search the code for") or req_lower.startswith("search codebase for"):
            try:
                # Split on 'for' and strip the query
                query = request.split("for", 1)[1].strip()
                if not query:
                    raise ValueError
                tasks.append({"action": "code_search", "query": query})
            except Exception:
                tasks.append({"action": "ask_llm", "prompt": request})
        # Detect requests to break a plan into issues.  We look for the word "issue" (singular or plural)
        # combined with verbs like "break", "split", "convert", "turn", "create" or "make".  When a colon
        # separates the instruction from the plan (e.g. "Break this into issues: step1; step2"), we extract
        # the substring after the colon as the plan.  Otherwise we fall back to the LLM.
        elif (
            "issue" in req_lower
            and any(word in req_lower for word in ["break", "split", "convert", "turn", "create", "make"])
        ):
            if ":" in request:
                plan_text = request.split(":", 1)[1].strip()
                if plan_text:
                    tasks.append({"action": "to_issues", "plan": plan_text})
                else:
                    tasks.append({"action": "ask_llm", "prompt": request})
            else:
                # Without a colon, the plan is ambiguous; delegate to the LLM
                tasks.append({"action": "ask_llm", "prompt": request})
        # Detect requests to break a plan into issues.  We look for the word "issue" (singular or plural)
        # combined with verbs like "break", "split", "convert", "turn", "create" or "make".  When a colon
        # separates the instruction from the plan (e.g. "Break this into issues: step1; step2"), we extract
        # the substring after the colon as the plan.  Otherwise we fall back to the LLM.
        elif (
            "issue" in req_lower
            and any(word in req_lower for word in ["break", "split", "convert", "turn", "create", "make"])
        ):
            if ":" in request:
                plan_text = request.split(":", 1)[1].strip()
                if plan_text:
                    tasks.append({"action": "to_issues", "plan": plan_text})
                else:
                    tasks.append({"action": "ask_llm", "prompt": request})
            else:
                # Without a colon, the plan is ambiguous; delegate to the LLM
                tasks.append({"action": "ask_llm", "prompt": request})
        else:
            # Unknown pattern, ask LLM to decide
            tasks.append({"action": "ask_llm", "prompt": request})
        return tasks

    def plan(self, request: str) -> List[Dict[str, Any]]:
        """Plan a request into tasks.

        The method first uses heuristic rules.  If the heuristics produce an
        ``"ask_llm"`` task and the LLM is available, it delegates to the LLM
        to produce a more detailed plan.
        """
        tasks = self._heuristic_plan(request)
        # If tasks contain a fallback ask_llm and we have a working LLM, try
        # to let the model propose a plan.  The LLM is expected to return
        # JSON describing a list of tasks.
        if len(tasks) == 1 and tasks[0].get("action") == "ask_llm" and self.llm.available:
            prompt = tasks[0]["prompt"]
            system_message = (
                "You are a task planner. You must convert a user request into a JSON "
                "array of tasks. Each task must be a JSON object with an 'action' key "
                "and optional parameters. Supported actions include: 'shell', 'write_file', "
                "'read_file', 'http_get', 'code_search', 'to_issues', 'ask_llm'. If you cannot decide, just return a single "
                "task with action 'ask_llm' and the original prompt. Return only valid JSON."
            )
            llm_response = self.llm.chat(system_message, prompt)
            try:
                tasks = json.loads(llm_response)
            except Exception:
                # If parsing fails, keep the fallback
                tasks = tasks
        return tasks