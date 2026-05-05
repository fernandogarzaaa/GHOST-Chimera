"""
Browser Operator Skill
======================

This skill performs simple HTTP GET requests to fetch remote resources.  It
can be used for lightweight web scraping and information retrieval.  More
complex browsing should be implemented by integrating with a headless
browser via a dedicated tool.

Supported actions:

- ``http_get`` – fetch the content at a given URL.
"""

from __future__ import annotations

from typing import Any

from ..tool_layer.browser import http_get
from .base import Skill


class BrowserOperatorSkill(Skill):
    name = "browser_operator"
    description = "Perform simple HTTP GET requests"
    actions = ["http_get"]

    def run(self, task: dict[str, Any]) -> Any:
        if task.get("action") != "http_get":
            raise ValueError("BrowserOperatorSkill only handles http_get tasks")
        url = task.get("url")
        if not url:
            raise ValueError("'url' is required for http_get task")
        return http_get(url, policy=task.get("_ghostchimera_policy"))
