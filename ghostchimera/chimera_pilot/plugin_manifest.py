"""Plugin manifest format for Ghost Chimera.

Mirrors OpenClaw's ``openclaw.plugin.json`` plugin manifest pattern.
A :class:`PluginManifest` declares a plugin's capabilities, contracts,
config schema, and activation rules.  :class:`PluginLoader` discovers
manifests under ``~/.ghostchimera/plugins/<name>/plugin.json``.

Usage::

    from ghostchimera.chimera_pilot.plugin_manifest import (
        PluginManifest,
        PluginLoader,
        get_loader,
    )

    loader = get_loader()
    manifests = loader.discover()
    for m in manifests:
        if m.is_active:
            print(m.id, m.contracts)
"""

from __future__ import annotations

import importlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger("plugin_manifest")

# Default plugin search directory (override with GHOSTCHIMERA_PLUGINS_DIR)
_DEFAULT_PLUGINS_DIR = Path.home() / ".ghostchimera" / "plugins"


# ---------------------------------------------------------------------------
# PluginManifest
# ---------------------------------------------------------------------------


@dataclass
class PluginContracts:
    """Declares which Ghost Chimera contract IDs a plugin registers."""

    tools: list[str] = field(default_factory=list)
    skill_providers: list[str] = field(default_factory=list)
    image_generation_providers: list[str] = field(default_factory=list)
    speech_providers: list[str] = field(default_factory=list)
    web_search_providers: list[str] = field(default_factory=list)
    web_fetch_providers: list[str] = field(default_factory=list)
    media_understanding_providers: list[str] = field(default_factory=list)
    document_extractors: list[str] = field(default_factory=list)
    external_auth_providers: list[str] = field(default_factory=list)
    backends: list[str] = field(default_factory=list)
    tool_result_middleware: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginContracts:
        return cls(
            tools=data.get("tools", []),
            skill_providers=data.get("skillProviders", []),
            image_generation_providers=data.get("imageGenerationProviders", []),
            speech_providers=data.get("speechProviders", []),
            web_search_providers=data.get("webSearchProviders", []),
            web_fetch_providers=data.get("webFetchProviders", []),
            media_understanding_providers=data.get("mediaUnderstandingProviders", []),
            document_extractors=data.get("documentExtractors", []),
            external_auth_providers=data.get("externalAuthProviders", []),
            backends=data.get("backends", []),
            tool_result_middleware=data.get("agentToolResultMiddleware", []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "skillProviders": self.skill_providers,
            "imageGenerationProviders": self.image_generation_providers,
            "speechProviders": self.speech_providers,
            "webSearchProviders": self.web_search_providers,
            "webFetchProviders": self.web_fetch_providers,
            "mediaUnderstandingProviders": self.media_understanding_providers,
            "documentExtractors": self.document_extractors,
            "externalAuthProviders": self.external_auth_providers,
            "backends": self.backends,
            "agentToolResultMiddleware": self.tool_result_middleware,
        }


@dataclass
class PluginSetup:
    """Provider and environment requirements for plugin setup."""

    providers: list[dict[str, Any]] = field(default_factory=list)
    requires_runtime: bool = False
    config_migrations: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginSetup:
        return cls(
            providers=data.get("providers", []),
            requires_runtime=data.get("requiresRuntime", False),
            config_migrations=data.get("configMigrations", []),
        )


@dataclass
class PluginActivation:
    """Activation rules — controls when a plugin is loaded."""

    on_providers: list[str] = field(default_factory=list)
    on_capabilities: list[str] = field(default_factory=list)
    on_commands: list[str] = field(default_factory=list)
    enabled_by_default: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginActivation:
        return cls(
            on_providers=data.get("onProviders", []),
            on_capabilities=data.get("onCapabilities", []),
            on_commands=data.get("onCommands", []),
            enabled_by_default=data.get("enabledByDefault", False),
        )


@dataclass
class PluginManifest:
    """Parsed representation of a ``plugin.json`` manifest.

    Parameters
    ----------
    id:
        Unique plugin identifier (e.g. ``"my-search-plugin"``).
    name:
        Human-readable display name.
    version:
        Semver string.
    description:
        Short description.
    kind:
        Capability tags — any subset of
        ``["tool", "hook", "provider", "backend", "skill"]``.
    contracts:
        Contracts this plugin registers.
    setup:
        Provider and env-var requirements.
    activation:
        Rules controlling whether the plugin is loaded.
    config_schema:
        JSON Schema dict for the plugin's configuration block.
    plugin_dir:
        Filesystem path to the plugin directory (set by :class:`PluginLoader`).
    """

    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    kind: list[str] = field(default_factory=list)
    contracts: PluginContracts = field(default_factory=PluginContracts)
    setup: PluginSetup = field(default_factory=PluginSetup)
    activation: PluginActivation = field(default_factory=PluginActivation)
    config_schema: dict[str, Any] = field(default_factory=dict)
    plugin_dir: Path | None = None
    _enabled: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any], plugin_dir: Path | None = None) -> PluginManifest:
        activation = PluginActivation.from_dict(data.get("activation", {}))
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            kind=data.get("kind", []),
            contracts=PluginContracts.from_dict(data.get("contracts", {})),
            setup=PluginSetup.from_dict(data.get("setup", {})),
            activation=activation,
            config_schema=data.get("configSchema", {}),
            plugin_dir=plugin_dir,
            _enabled=activation.enabled_by_default,
        )

    @classmethod
    def from_file(cls, path: Path) -> PluginManifest:
        """Load a manifest from a ``plugin.json`` file."""
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data, plugin_dir=path.parent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "kind": self.kind,
            "contracts": self.contracts.to_dict(),
            "configSchema": self.config_schema,
            "enabled": self._enabled,
        }

    # ------------------------------------------------------------------
    # Runtime state
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """Validate *config* against the plugin's JSON Schema.

        Returns a list of error strings.  Requires ``jsonschema`` (optional).
        Falls back to a permissive check if not installed.
        """
        if not self.config_schema:
            return []
        try:
            import jsonschema  # type: ignore
            try:
                jsonschema.validate(config, self.config_schema)
                return []
            except jsonschema.ValidationError as exc:
                return [str(exc.message)]
        except ImportError:
            # jsonschema not installed — skip deep validation
            required = self.config_schema.get("required", [])
            return [f"Required config field missing: '{k}'" for k in required if k not in config]

    def check_env_requirements(self) -> list[str]:
        """Return a list of missing environment variables declared in setup."""
        missing = []
        for provider_spec in self.setup.providers:
            for env_var in provider_spec.get("envVars", []):
                if not os.environ.get(env_var):
                    missing.append(
                        f"Plugin '{self.id}' requires env var '{env_var}' "
                        f"(provider '{provider_spec.get('id', '?')}')"
                    )
        return missing

    def load_module(self) -> Any | None:
        """Import the plugin's Python module from ``plugin_dir/plugin.py``."""
        if self.plugin_dir is None:
            return None
        plugin_file = self.plugin_dir / "plugin.py"
        if not plugin_file.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"ghostchimera_plugin_{self.id}", plugin_file)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


# ---------------------------------------------------------------------------
# PluginLoader
# ---------------------------------------------------------------------------


class PluginLoader:
    """Discover and load plugin manifests from the plugins directory.

    The plugins directory is resolved in order:
    1. ``plugins_dir`` constructor argument.
    2. ``GHOSTCHIMERA_PLUGINS_DIR`` environment variable.
    3. ``~/.ghostchimera/plugins``.

    Each sub-directory of the plugins directory is scanned for a
    ``plugin.json`` file.  Valid manifests are loaded and activation state
    is applied.
    """

    def __init__(self, plugins_dir: Path | str | None = None) -> None:
        env_dir = os.environ.get("GHOSTCHIMERA_PLUGINS_DIR")
        self.plugins_dir = Path(plugins_dir or env_dir or _DEFAULT_PLUGINS_DIR)
        self._manifests: dict[str, PluginManifest] = {}
        self._lock = threading.Lock()
        self._discovered = False

    def discover(self, *, force: bool = False) -> list[PluginManifest]:
        """Scan the plugins directory and return all valid manifests.

        Parameters
        ----------
        force:
            Re-scan even if discovery already ran.
        """
        with self._lock:
            if self._discovered and not force:
                return list(self._manifests.values())
            self._manifests.clear()

        if not self.plugins_dir.exists():
            logger.debug("Plugins directory does not exist: %s", self.plugins_dir)
            return []

        found = []
        for child in sorted(self.plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "plugin.json"
            if not manifest_file.exists():
                continue
            try:
                manifest = PluginManifest.from_file(manifest_file)
                with self._lock:
                    self._manifests[manifest.id] = manifest
                found.append(manifest)
                logger.info("Discovered plugin '%s' v%s", manifest.id, manifest.version)
            except Exception as exc:
                logger.warning("Failed to load manifest %s: %s", manifest_file, exc)

        with self._lock:
            self._discovered = True

        return found

    def get(self, plugin_id: str) -> PluginManifest | None:
        """Return a manifest by plugin ID."""
        with self._lock:
            return self._manifests.get(plugin_id)

    def list_active(self) -> list[PluginManifest]:
        """Return enabled manifests."""
        with self._lock:
            return [m for m in self._manifests.values() if m.is_active]

    def enable(self, plugin_id: str) -> bool:
        """Enable a plugin by ID. Returns True if found."""
        with self._lock:
            m = self._manifests.get(plugin_id)
            if m is None:
                return False
            m.enable()
        return True

    def disable(self, plugin_id: str) -> bool:
        """Disable a plugin by ID. Returns True if found."""
        with self._lock:
            m = self._manifests.get(plugin_id)
            if m is None:
                return False
            m.disable()
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            manifests = list(self._manifests.values())
        return {
            "plugins_dir": str(self.plugins_dir),
            "discovered": self._discovered,
            "total": len(manifests),
            "active": sum(1 for m in manifests if m.is_active),
            "plugins": [m.to_dict() for m in manifests],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_loader: PluginLoader | None = None
_loader_lock = threading.Lock()


def get_loader(plugins_dir: Path | str | None = None) -> PluginLoader:
    """Return the process-wide singleton :class:`PluginLoader`."""
    global _loader
    if _loader is None:
        with _loader_lock:
            if _loader is None:
                _loader = PluginLoader(plugins_dir)
    return _loader


def reset_loader() -> None:
    """Reset the singleton (useful in tests)."""
    global _loader
    with _loader_lock:
        _loader = None


__all__ = [
    "PluginManifest",
    "PluginContracts",
    "PluginSetup",
    "PluginActivation",
    "PluginLoader",
    "get_loader",
    "reset_loader",
]
