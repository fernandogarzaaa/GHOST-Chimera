"""
Skill Base Class
================

All skills must inherit from this base class.  A skill declares which
actions it supports and implements a :meth:`run` method to perform the
action.  Skills can also provide a human readable description.

OpenClaw skill metadata enrichment
------------------------------------
Skills may declare :attr:`requires_env`, :attr:`requires_bins`,
:attr:`version`, and :attr:`primary_env` to expose their requirements to
the setup wizard, doctor, and SkillRegistry.  Call
:meth:`check_requirements` to get a list of unmet requirements at runtime.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any


class Skill(ABC):
    """Base class for skills.

    Attributes
    ----------
    name : str
        Unique name of the skill.
    description : str
        Human friendly description of what the skill does.
    actions : Iterable[str]
        Actions that this skill can handle.  The executor uses this list to
        find the appropriate skill for each task.
    version : str
        Semver string for compatibility checking.  ``"0.0.0"`` by default.
    requires_env : list[str]
        Environment variable names that the skill requires
        (e.g. ``["OPENAI_API_KEY"]``).  Mirrors the ClawHub ``SKILL.md``
        ``metadata.openclaw.requires.env`` frontmatter field.
    requires_bins : list[str]
        External binary names that must be present on ``PATH``
        (e.g. ``["git", "docker"]``).  Mirrors
        ``metadata.openclaw.requires.bins``.
    primary_env : str
        The single most important environment variable for the setup wizard
        to prompt for.  Mirrors ``metadata.openclaw.primaryEnv``.
    """

    name: str = "base"
    description: str = "Base skill"
    actions: Iterable[str] = []
    version: str = "0.0.0"
    requires_env: list[str] = []
    requires_bins: list[str] = []
    primary_env: str = ""

    @abstractmethod
    def run(self, task: dict[str, Any]) -> Any:
        """Perform a task and return a result.

        Parameters
        ----------
        task : dict
            Task dictionary containing at least an ``action`` key.

        Returns
        -------
        Any
            Result of performing the task.
        """

    def check_requirements(self) -> list[str]:
        """Return a list of unmet requirement descriptions.

        Checks both :attr:`requires_env` (via ``os.environ``) and
        :attr:`requires_bins` (via ``shutil.which``).  An empty list
        means the skill is ready to run.

        Returns
        -------
        list[str]
            Human-readable descriptions of each unmet requirement.
        """
        import os

        problems: list[str] = []
        for var in self.requires_env:
            if not os.environ.get(var):
                problems.append(f"Environment variable '{var}' is not set (required by skill '{self.name}')")
        for binary in self.requires_bins:
            if shutil.which(binary) is None:
                problems.append(f"Binary '{binary}' not found on PATH (required by skill '{self.name}')")
        return problems
