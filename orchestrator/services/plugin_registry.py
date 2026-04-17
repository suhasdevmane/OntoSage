"""
Phase 6.7 — Plugin Architecture for Extensible Agents
=======================================================
Provides a lightweight, convention-based plugin registry that allows
third-party agents, analysers, and data adapters to be registered and
discovered at runtime — without modifying core OntoSage source files.

Plugin types supported:
  agent      — Custom LangGraph node agents
  analyser   — Analytics modules for AnalyticsEngine
  exporter   — Data export format handlers
  adapter    — Storage / DB backend adapters

Discovery:
  1. Environment variable ONTOSAGE_PLUGINS (comma-separated paths)
  2. Python entry_points group 'ontosage.plugins' (pip-installable plugins)
  3. Auto-scan of a 'plugins/' directory in project root

Usage:
    # Register a plugin programmatically
    from orchestrator.services.plugin_registry import PluginRegistry

    registry = PluginRegistry()

    @registry.agent("weather_agent")
    class WeatherAgent:
        async def run(self, state, query): ...

    # Discover installed plugins
    registry.auto_discover()

    # Use a plugin
    agent_cls = registry.get_agent("weather_agent")

    # In agents that accept plugins (e.g. AnalyticsEngine):
    engine.register_analyser("weather_correlation", WeatherCorrelationAnalyser)
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Plugin base classes (optional — plugins don't have to subclass these)
# ─────────────────────────────────────────────────────────────────────────────


class AgentPlugin:
    """Base class for agent plugins."""

    name: str = "unnamed_agent"
    description: str = ""

    async def run(self, state: Any, query: str) -> Dict:
        raise NotImplementedError


class AnalyserPlugin:
    """Base class for analytics plugins."""

    name: str = "unnamed_analyser"
    supported_types: List[str] = []

    def run(self, request: Any) -> Any:
        raise NotImplementedError


class ExporterPlugin:
    """Base class for export format plugins."""

    name: str = "unnamed_exporter"
    format_id: str = "custom"

    async def export(self, data: Any, title: str) -> Dict:
        raise NotImplementedError


class AdapterPlugin:
    """Base class for storage adapter plugins."""

    name: str = "unnamed_adapter"
    backend_id: str = "custom"

    async def connect(self): ...
    async def query(self, sql: str) -> List[Dict]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Plugin metadata
# ─────────────────────────────────────────────────────────────────────────────


class PluginInfo:
    def __init__(self, plugin_type: str, plugin_id: str, cls: Type, source: str = "programmatic"):
        self.plugin_type = plugin_type  # "agent", "analyser", "exporter", "adapter"
        self.plugin_id = plugin_id
        self.cls = cls
        self.source = source
        self.metadata = getattr(cls, "_plugin_metadata", {})

    def instantiate(self, **kwargs) -> Any:
        return self.cls(**kwargs)

    def __repr__(self):
        return f"PluginInfo({self.plugin_type}:{self.plugin_id} from {self.source})"


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


class PluginRegistry:
    """
    Central registry for all OntoSage plugins.

    Thread-safe for reads. Writes should happen at startup.
    """

    VALID_TYPES = ("agent", "analyser", "exporter", "adapter")

    def __init__(self, plugins_dir: str = "plugins/"):
        self._registry: Dict[str, Dict[str, PluginInfo]] = {t: {} for t in self.VALID_TYPES}
        self._plugins_dir = Path(plugins_dir)

    # ─────────────────────────────────────────────────────────────────────────
    # Registration
    # ─────────────────────────────────────────────────────────────────────────

    def register(
        self, plugin_type: str, plugin_id: str, cls: Type, source: str = "programmatic"
    ) -> PluginInfo:
        """Register a plugin class."""
        if plugin_type not in self.VALID_TYPES:
            raise ValueError(f"Unknown plugin type: {plugin_type!r}. Valid: {self.VALID_TYPES}")
        info = PluginInfo(plugin_type, plugin_id, cls, source)
        self._registry[plugin_type][plugin_id] = info
        logger.info(f"Plugin registered: {plugin_type}/{plugin_id} ({source})")
        return info

    # Decorator factories

    def agent(self, plugin_id: str, **meta):
        """Decorator: @registry.agent('my_agent')"""

        def decorator(cls):
            cls._plugin_metadata = meta
            self.register("agent", plugin_id, cls)
            return cls

        return decorator

    def analyser(self, plugin_id: str, **meta):
        """Decorator: @registry.analyser('my_analyser')"""

        def decorator(cls):
            cls._plugin_metadata = meta
            self.register("analyser", plugin_id, cls)
            return cls

        return decorator

    def exporter(self, plugin_id: str, **meta):
        """Decorator: @registry.exporter('my_format')"""

        def decorator(cls):
            cls._plugin_metadata = meta
            self.register("exporter", plugin_id, cls)
            return cls

        return decorator

    def adapter(self, plugin_id: str, **meta):
        """Decorator: @registry.adapter('my_backend')"""

        def decorator(cls):
            cls._plugin_metadata = meta
            self.register("adapter", plugin_id, cls)
            return cls

        return decorator

    # ─────────────────────────────────────────────────────────────────────────
    # Retrieval
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, plugin_type: str, plugin_id: str) -> Optional[PluginInfo]:
        return self._registry.get(plugin_type, {}).get(plugin_id)

    def get_agent(self, plugin_id: str) -> Optional[Type]:
        info = self.get("agent", plugin_id)
        return info.cls if info else None

    def get_analyser(self, plugin_id: str) -> Optional[Type]:
        info = self.get("analyser", plugin_id)
        return info.cls if info else None

    def get_exporter(self, plugin_id: str) -> Optional[Type]:
        info = self.get("exporter", plugin_id)
        return info.cls if info else None

    def get_adapter(self, plugin_id: str) -> Optional[Type]:
        info = self.get("adapter", plugin_id)
        return info.cls if info else None

    def list_plugins(self, plugin_type: Optional[str] = None) -> List[PluginInfo]:
        if plugin_type:
            return list(self._registry.get(plugin_type, {}).values())
        return [p for t in self._registry.values() for p in t.values()]

    # ─────────────────────────────────────────────────────────────────────────
    # Auto-discovery
    # ─────────────────────────────────────────────────────────────────────────

    def auto_discover(self) -> int:
        """
        Discover and load plugins from:
          1. plugins/ directory (if it exists)
          2. ONTOSAGE_PLUGINS env var (comma-separated module paths)
          3. Python entry_points (if importlib.metadata available)
        Returns number of plugins discovered.
        """
        count = 0
        count += self._discover_from_dir()
        count += self._discover_from_env()
        count += self._discover_from_entry_points()
        logger.info(f"Plugin auto-discovery: {count} plugin(s) found")
        return count

    def _discover_from_dir(self) -> int:
        """Scan plugins/ directory for Python modules."""
        if not self._plugins_dir.exists():
            return 0
        count = 0
        for py_file in self._plugins_dir.glob("**/*.py"):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"ontosage_plugin.{py_file.stem}", str(py_file)
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                # Find classes with _plugin_metadata attribute
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if hasattr(obj, "_plugin_metadata") and hasattr(obj, "_plugin_type"):
                        self.register(obj._plugin_type, obj._plugin_id, obj, source=str(py_file))
                        count += 1
                logger.debug(f"Scanned plugin file: {py_file}")
            except Exception as e:
                logger.warning(f"Plugin load error ({py_file}): {e}")
        return count

    def _discover_from_env(self) -> int:
        """Load modules listed in ONTOSAGE_PLUGINS env var."""
        env_mods = os.environ.get("ONTOSAGE_PLUGINS", "")
        if not env_mods:
            return 0
        count = 0
        for mod_path in env_mods.split(","):
            mod_path = mod_path.strip()
            if not mod_path:
                continue
            try:
                mod = importlib.import_module(mod_path)
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if hasattr(obj, "_plugin_metadata") and hasattr(obj, "_plugin_type"):
                        self.register(obj._plugin_type, obj._plugin_id, obj, source=mod_path)
                        count += 1
            except Exception as e:
                logger.warning(f"ONTOSAGE_PLUGINS env load error ({mod_path}): {e}")
        return count

    def _discover_from_entry_points(self) -> int:
        """Load registered Python package entry_points."""
        count = 0
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="ontosage.plugins")
            for ep in eps:
                try:
                    cls = ep.load()
                    plugin_type = getattr(cls, "_plugin_type", None)
                    plugin_id = getattr(cls, "_plugin_id", ep.name)
                    if plugin_type in self.VALID_TYPES:
                        self.register(plugin_type, plugin_id, cls, source=f"entry_point:{ep.name}")
                        count += 1
                except Exception as e:
                    logger.warning(f"Entry point load error ({ep.name}): {e}")
        except ImportError:
            pass
        return count

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────

    def summary(self) -> str:
        lines = [f"Plugin Registry ({sum(len(v) for v in self._registry.values())} plugins)"]
        for ptype, plugins in self._registry.items():
            if plugins:
                lines.append(f"  {ptype}:")
                for pid, info in plugins.items():
                    lines.append(f"    • {pid} ({info.source})")
        return "\n".join(lines)

    def __repr__(self):
        counts = {t: len(v) for t, v in self._registry.items()}
        return f"PluginRegistry({counts})"


# ─────────────────────────────────────────────────────────────────────────────
# Global registry singleton
# ─────────────────────────────────────────────────────────────────────────────

_global_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = PluginRegistry()
        _global_registry.auto_discover()
    return _global_registry


def reset_plugin_registry():
    global _global_registry
    _global_registry = None
