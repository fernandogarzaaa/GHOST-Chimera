"""Skill registry with workspace-based dynamic discovery.

Mirrors OpenClaw's skill workspace pattern where external skills live under
``~/.openclaw/workspace/skills/<name>/SKILL.md``.  Ghost Chimera's version
scans ``~/.ghostchimera/skills/<name>/skill.py`` for :class:`Skill` subclasses
and auto-registers them alongside the bundled skills.

Layout expected for external skills::

    ~/.ghostchimera/skills/
        my_skill/
            skill.py       # defines one or more Skill subclasses

Usage::

    from ghostchimera.skill_layer.registry import SkillRegistry, get_registry

    registry = get_registry()               # singleton, auto-populated
    skill = registry.get_skill("my_skill")  # by name
    all_skills = registry.list_skills()     # dict[name -> Skill]

The :class:`SkillRegistry` intentionally delegates to
:class:`~ghostchimera.agent_core.skill_manager.SkillManager` for the built-in
package scan and adds workspace discovery on top.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from pathlib import Path

from .base import Skill

logger = logging.getLogger(__name__)

# Default workspace root (overridable via env var)
_DEFAULT_SKILLS_DIR = Path(
    os.environ.get("GHOSTCHIMERA_SKILLS_DIR", "~/.ghostchimera/skills")
).expanduser()


class SkillRegistry:
    """Discover and expose skills from bundled packages and the user workspace.

    Parameters
    ----------
    skills_dir:
        Path to the workspace skills directory.  Defaults to
        ``~/.ghostchimera/skills``.  Override via ``GHOSTCHIMERA_SKILLS_DIR``.
    extra_dirs:
        Additional directories to scan for skill modules (on top of the
        workspace directory).
    auto_discover:
        If ``True`` (default), bundled skills are imported and workspace
        skills are scanned at construction time.
    """

    def __init__(
        self,
        *,
        skills_dir: Path | str | None = None,
        extra_dirs: list[str | Path] | None = None,
        auto_discover: bool = True,
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()
        self.skills_dir = Path(skills_dir).expanduser() if skills_dir else _DEFAULT_SKILLS_DIR
        self._extra_dirs: list[Path] = [Path(d).expanduser() for d in (extra_dirs or [])]

        if auto_discover:
            self._discover_bundled()
            self._discover_workspace()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_bundled(self) -> None:
        """Import all built-in skill modules from ``ghostchimera.skill_layer``."""
        import importlib
        import pkgutil

        try:
            package = importlib.import_module("ghostchimera.skill_layer")
        except Exception as exc:
            logger.warning("Could not import ghostchimera.skill_layer: %s", exc)
            return

        for _loader, name, is_pkg in pkgutil.iter_modules(package.__path__):
            if is_pkg or name in {"base", "registry"}:
                continue
            full_name = f"ghostchimera.skill_layer.{name}"
            try:
                module = importlib.import_module(full_name)
                self._register_from_module(module)
            except Exception as exc:
                logger.warning("Failed to import bundled skill module %s: %s", full_name, exc)

    def _discover_workspace(self) -> None:
        """Scan the workspace skills directory for external skill modules.

        Each subdirectory is expected to contain a ``skill.py`` file.  All
        :class:`Skill` subclasses found inside are registered automatically.
        """
        dirs_to_scan: list[Path] = [self.skills_dir] + self._extra_dirs
        for base_dir in dirs_to_scan:
            if not base_dir.is_dir():
                continue
            for skill_dir in sorted(base_dir.iterdir()):
                skill_file = skill_dir / "skill.py"
                if not skill_file.is_file():
                    continue
                self._load_skill_file(skill_file)

    def _load_skill_file(self, path: Path) -> None:
        """Import a single ``skill.py`` file and register its Skill subclasses."""
        module_name = f"ghostchimera_workspace_skill_{path.parent.name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for %s", path)
            return
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[call-arg]
            self._register_from_module(module)
        except Exception as exc:
            logger.warning("Failed to load skill file %s: %s", path, exc)

    def _register_from_module(self, module) -> None:
        """Register all Skill subclasses found in *module*."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Skill) and attr is not Skill:
                try:
                    instance = attr()
                    self.register(instance)
                except Exception as exc:
                    logger.warning("Failed to instantiate skill class %s: %s", attr, exc)

    # ------------------------------------------------------------------
    # Registry interface
    # ------------------------------------------------------------------

    def register(self, skill: Skill) -> None:
        """Register a skill instance by name.

        If a skill with the same name is already registered a warning is
        emitted and the existing registration is kept.
        """
        with self._lock:
            if skill.name in self._skills:
                logger.warning("Skill '%s' already registered; skipping duplicate", skill.name)
                return
            self._skills[skill.name] = skill
            logger.debug("Registered skill '%s'", skill.name)

    def get_skill(self, name: str) -> Skill | None:
        """Return the skill registered under *name*, or ``None``."""
        with self._lock:
            return self._skills.get(name)

    def list_skills(self) -> dict[str, Skill]:
        """Return a snapshot of all registered skills keyed by name."""
        with self._lock:
            return dict(self._skills)

    def skill_names(self) -> list[str]:
        """Return a sorted list of registered skill names."""
        with self._lock:
            return sorted(self._skills)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: SkillRegistry | None = None
_registry_lock = threading.Lock()


def get_registry(*, reset: bool = False) -> SkillRegistry:
    """Return the process-wide SkillRegistry singleton.

    Parameters
    ----------
    reset:
        If ``True``, discard any cached instance and build a fresh one.
        Useful in tests.
    """
    global _registry
    if _registry is None or reset:
        with _registry_lock:
            if _registry is None or reset:
                _registry = SkillRegistry()
    return _registry


__all__ = ["SkillRegistry", "get_registry"]
