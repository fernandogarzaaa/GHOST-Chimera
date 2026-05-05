"""
Skill Manager
=============

Loads and manages skills from the ``ghostchimera.skill_layer`` package.  A
skill is a class inheriting from :class:`ghostchimera.skill_layer.base.Skill`
that declares a ``name``, an ``actions`` list and implements a ``run``
method.  When the executor receives a task it asks the skill manager for a
skill that can handle the given action.

The manager supports lazy loading to improve startup performance.  Skills are
imported only when first needed.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil

from ..skill_layer.base import Skill


class SkillManager:
    """Discover and register available skills."""

    def __init__(self, package: str = "ghostchimera.skill_layer", logger: logging.Logger = None) -> None:
        self.package = package
        self.logger = logger or logging.getLogger(__name__)
        self._skills: dict[str, Skill] = {}
        self._action_to_skill: dict[str, Skill] = {}
        self._discover_skills()

    def _discover_skills(self) -> None:
        """Import all modules in the default skill package and any extra directories.

        Skills are first discovered in the built‑in ``ghostchimera.skill_layer``
        package.  Additional skills can be loaded from directories specified
        in the ``GHOSTCHIMERA_EXTRA_SKILLS`` environment variable.  The
        environment variable should contain a list of directories separated
        by ``os.pathsep`` (``:`` on Unix, ``;`` on Windows).  All ``*.py``
        files in those directories will be imported and any subclasses of
        :class:`ghostchimera.skill_layer.base.Skill` will be registered.
        """
        # Discover built‑in skills from the package
        package = importlib.import_module(self.package)
        for loader, name, is_pkg in pkgutil.iter_modules(package.__path__):
            if is_pkg:
                continue
            full_name = f"{self.package}.{name}"
            try:
                module = importlib.import_module(full_name)
            except Exception as exc:
                self.logger.warning("Failed to import skill module %s: %s", full_name, exc)
                continue
            self._register_skills_from_module(module)

        # Discover skills from extra directories, if configured
        extra = os.environ.get("GHOSTCHIMERA_EXTRA_SKILLS", "").strip()
        if extra:
            for path in extra.split(os.pathsep):
                path = path.strip()
                if not path:
                    continue
                self._load_skills_from_directory(path)

    def _register_skills_from_module(self, module) -> None:
        """Register all Skill subclasses defined in a module."""
        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)
            if isinstance(attribute, type) and issubclass(attribute, Skill) and attribute is not Skill:
                try:
                    instance = attribute()
                    self.register(instance)
                except Exception as exc:
                    self.logger.warning("Failed to instantiate skill %s: %s", attribute, exc)

    def _load_skills_from_directory(self, directory: str) -> None:
        """Import all Python files in a directory and register skills found therein."""
        import glob
        import importlib.util

        py_files = glob.glob(os.path.join(directory, "*.py"))
        for file_path in py_files:
            module_name = os.path.splitext(os.path.basename(file_path))[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec and spec.loader:
                try:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)  # type: ignore[call-arg]
                    self._register_skills_from_module(module)
                except Exception as exc:
                    self.logger.warning("Failed to import skill file %s: %s", file_path, exc)

    def register(self, skill: Skill) -> None:
        """Register a skill instance."""
        if skill.name in self._skills:
            self.logger.warning("Skill with name %s already registered", skill.name)
            return
        self._skills[skill.name] = skill
        for action in skill.actions:
            if action in self._action_to_skill:
                self.logger.warning(
                    "Action %s already handled by skill %s; overriding with skill %s",
                    action,
                    self._action_to_skill[action].name,
                    skill.name,
                )
            self._action_to_skill[action] = skill

    def get_skill_for_action(self, action: str) -> Skill | None:
        """Return the skill instance capable of handling the given action."""
        return self._action_to_skill.get(action)
