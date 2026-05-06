"""
Skill Base Class
================

All skills must inherit from this base class.  A skill declares which
actions it supports and implements a :meth:`run` method to perform the
action.  Skills can also provide a human readable description.
"""

from __future__ import annotations

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
    """

    name: str = "base"
    description: str = "Base skill"
    actions: Iterable[str] = []

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
