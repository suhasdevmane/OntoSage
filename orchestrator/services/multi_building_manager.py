"""
Phase 5.7 — Multi-Building Configuration Manager
==================================================
Enables OntoSage to serve MULTIPLE buildings simultaneously by dynamically
loading, caching, and routing between building-specific configurations.

Key capabilities:
  • Discover all building configs in a directory
  • Load and cache parsed configurations
  • Route queries to the correct building by ID, alias, or ontology namespace
  • Hot-reload changed configs without restart
  • Validate configs at load time

Usage:
    from orchestrator.services.multi_building_manager import MultiBuildingConfigManager

    mgr = MultiBuildingConfigManager("config/buildings/")
    mgr.load_all()

    # Get config for a specific building
    cfg = mgr.get_config("bldg1")

    # Detect building from a SPARQL query namespace
    cfg = mgr.detect_from_namespace("http://abacwsbuilding.cardiff.ac.uk/abacws#")
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    import yaml
    YAML_OK = True
except ImportError:
    YAML_OK = False

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

class BuildingConfig:
    """Parsed, validated representation of a single building's configuration."""

    def __init__(self, raw: Dict[str, Any], source_file: str):
        self.source_file = source_file
        self._raw = raw

        # Core identity
        bldg = raw.get("building", {})
        self.id          = bldg.get("id", "unknown")
        self.name        = bldg.get("name", self.id)
        self.namespace   = bldg.get("namespace", "")
        self.prefix      = bldg.get("prefix", "bldg")
        self.timezone    = bldg.get("timezone", "UTC")
        self.abox_file   = bldg.get("abox_file", "")
        self.tbox_file   = bldg.get("tbox_file", "")

        # Ontology
        onto = raw.get("ontology", {})
        self.schema      = onto.get("schema", "brick")
        self.schema_uri  = onto.get("schema_uri", "https://brickschema.org/schema/Brick#")
        self.extra_prefixes = onto.get("extra_prefixes", [])

        # Storage
        stor = raw.get("storage", {})
        self.backend     = stor.get("backend", "mysql")
        self.database    = stor.get("database", self.id)
        self.table       = stor.get("table", "sensor_data")
        cols             = stor.get("columns", {})
        self.col_uuid    = cols.get("uuid", "uuid")
        self.col_value   = cols.get("value", "value")
        self.col_time    = cols.get("timestamp", "time")
        self.col_sensor  = cols.get("sensor_name", "sensor_name")

        # Computed
        self._last_loaded = time.time()
        self._file_hash   = ""

    def to_dict(self) -> Dict:
        return self._raw

    @property
    def sparql_prefix_block(self) -> str:
        """Build a SPARQL PREFIX block for this building."""
        lines = [f"PREFIX {self.prefix}: <{self.namespace}>"]
        for ep in self.extra_prefixes:
            lines.append(f"PREFIX {ep['prefix']}: <{ep['uri']}>")
        return "\n".join(lines)

    def validate(self) -> List[str]:
        """Return a list of validation warnings (empty = valid)."""
        issues = []
        if not self.id:
            issues.append("Missing building.id")
        if not self.namespace.endswith("#") and not self.namespace.endswith("/"):
            issues.append(f"namespace '{self.namespace}' should end with '#' or '/'")
        if not self.abox_file:
            issues.append("Missing building.abox_file")
        if self.schema not in ("brick", "rec", "s223", "custom"):
            issues.append(f"Unknown ontology.schema: {self.schema}")
        return issues

    def __repr__(self):
        return f"BuildingConfig(id={self.id!r}, name={self.name!r}, schema={self.schema!r})"


# ─────────────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────────────

class MultiBuildingConfigManager:
    """
    Discovers, loads, and routes between multiple building configurations.

    Config discovery order:
      1. All *.yaml files in the given directory matching pattern *_building_config.yaml
         OR any YAML file containing a "building:" top-level key.
      2. The BUILDING_CONFIG_FILE env var (if set) is always included.
    """

    def __init__(self, config_dir: str = "config/"):
        self._config_dir = Path(config_dir)
        self._configs: Dict[str, BuildingConfig] = {}   # id → config
        self._namespace_index: Dict[str, str] = {}      # namespace → id
        self._file_mtimes: Dict[str, float] = {}        # path → mtime

    # ─────────────────────────────────────────────────────────────────────────
    # Discovery & loading
    # ─────────────────────────────────────────────────────────────────────────

    def discover_config_files(self) -> List[Path]:
        """Find all building config YAML files in the config directory."""
        if not self._config_dir.exists():
            logger.warning(f"Config directory not found: {self._config_dir}")
            return []

        candidates = list(self._config_dir.glob("**/*.yaml")) + \
                     list(self._config_dir.glob("**/*.yml"))

        # Filter: must contain a "building:" key
        valid = []
        for p in candidates:
            try:
                content = p.read_text(encoding="utf-8")
                if "building:" in content:
                    valid.append(p)
            except Exception:
                pass

        # Also include BUILDING_CONFIG_FILE env var if set
        env_file = os.environ.get("BUILDING_CONFIG_FILE")
        if env_file:
            env_path = Path(env_file)
            if env_path.exists() and env_path not in valid:
                valid.append(env_path)

        logger.info(f"Discovered {len(valid)} building config file(s)")
        return valid

    def load_all(self) -> int:
        """Load (or reload) all discovered configs. Returns count loaded."""
        paths = self.discover_config_files()
        loaded = 0
        for path in paths:
            try:
                cfg = self._load_file(path)
                if cfg:
                    self._register(cfg)
                    loaded += 1
            except Exception as e:
                logger.error(f"Failed to load config {path}: {e}")
        logger.info(f"Loaded {loaded} building configurations")
        return loaded

    def _load_file(self, path: Path) -> Optional[BuildingConfig]:
        """Parse a YAML file and return a BuildingConfig."""
        if not YAML_OK:
            raise RuntimeError("PyYAML not installed — cannot load building configs")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "building" not in raw:
            return None
        cfg = BuildingConfig(raw, str(path))
        issues = cfg.validate()
        if issues:
            logger.warning(f"Config {path} has issues: {issues}")
        self._file_mtimes[str(path)] = path.stat().st_mtime
        return cfg

    def _register(self, cfg: BuildingConfig):
        """Register a config, indexing by id and namespace."""
        self._configs[cfg.id] = cfg
        if cfg.namespace:
            self._namespace_index[cfg.namespace] = cfg.id
        logger.info(f"Registered building: {cfg.id!r} ({cfg.name})")

    # ─────────────────────────────────────────────────────────────────────────
    # Hot-reload
    # ─────────────────────────────────────────────────────────────────────────

    def reload_changed(self) -> List[str]:
        """Check for changed config files and reload them. Returns IDs reloaded."""
        reloaded = []
        for path_str, old_mtime in list(self._file_mtimes.items()):
            path = Path(path_str)
            if not path.exists():
                continue
            new_mtime = path.stat().st_mtime
            if new_mtime > old_mtime:
                try:
                    cfg = self._load_file(path)
                    if cfg:
                        self._register(cfg)
                        reloaded.append(cfg.id)
                        logger.info(f"Hot-reloaded config: {cfg.id!r}")
                except Exception as e:
                    logger.error(f"Hot-reload failed for {path}: {e}")
        return reloaded

    # ─────────────────────────────────────────────────────────────────────────
    # Routing / lookup
    # ─────────────────────────────────────────────────────────────────────────

    def get_config(self, building_id: str) -> Optional[BuildingConfig]:
        """Get config by building ID."""
        return self._configs.get(building_id)

    def get_default(self) -> Optional[BuildingConfig]:
        """Return the first/only config, or the one matching BUILDING_CONFIG_FILE."""
        env_id = os.environ.get("BUILDING_ID")
        if env_id and env_id in self._configs:
            return self._configs[env_id]
        if len(self._configs) == 1:
            return next(iter(self._configs.values()))
        # If multiple, fall back to env var config
        env_file = os.environ.get("BUILDING_CONFIG_FILE", "")
        for cfg in self._configs.values():
            if cfg.source_file == env_file:
                return cfg
        return next(iter(self._configs.values()), None)

    def detect_from_namespace(self, namespace: str) -> Optional[BuildingConfig]:
        """Match a namespace URI to a registered building."""
        bldg_id = self._namespace_index.get(namespace)
        if bldg_id:
            return self._configs.get(bldg_id)
        # Partial match
        for ns, bid in self._namespace_index.items():
            if namespace.startswith(ns) or ns.startswith(namespace.rstrip("#/")):
                return self._configs.get(bid)
        return None

    def detect_from_query(self, user_query: str) -> Optional[BuildingConfig]:
        """
        Detect building from user query by matching building name, ID, or namespace.
        Returns the matched config or None (caller should fall back to default).
        """
        q_lower = user_query.lower()
        for cfg in self._configs.values():
            if (cfg.id.lower() in q_lower or
                    cfg.name.lower() in q_lower or
                    cfg.prefix.lower() in q_lower):
                return cfg
        return None

    def list_buildings(self) -> List[Dict]:
        """Return summary list of all registered buildings."""
        return [
            {
                "id": cfg.id,
                "name": cfg.name,
                "schema": cfg.schema,
                "namespace": cfg.namespace,
                "backend": cfg.backend,
                "abox_file": cfg.abox_file,
            }
            for cfg in self._configs.values()
        ]

    def summary(self) -> str:
        """Human-readable summary of registered buildings."""
        if not self._configs:
            return "No buildings registered."
        lines = [f"Registered buildings ({len(self._configs)}):"]
        for cfg in self._configs.values():
            lines.append(f"  • {cfg.id!r} — {cfg.name} ({cfg.schema}, {cfg.backend})")
        return "\n".join(lines)

    def __repr__(self):
        return f"MultiBuildingConfigManager(buildings={list(self._configs.keys())})"


# ─────────────────────────────────────────────────────────────────────────────
# Global singleton (imported by other modules)
# ─────────────────────────────────────────────────────────────────────────────

_global_manager: Optional[MultiBuildingConfigManager] = None


def get_building_manager(config_dir: str = "config/") -> MultiBuildingConfigManager:
    """
    Return (or create) the global MultiBuildingConfigManager.
    Call this instead of instantiating directly.
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = MultiBuildingConfigManager(config_dir)
        _global_manager.load_all()
    return _global_manager


def reset_building_manager():
    """Reset global manager (useful in tests)."""
    global _global_manager
    _global_manager = None
