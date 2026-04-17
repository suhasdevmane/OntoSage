# Building Deployment Bootstrap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop in a TTL + one YAML config, set `BUILDING_ID` in `.env`, run `docker compose up` — the system bootstraps itself and serves queries. Zero code changes required between buildings.

**Architecture:** A `bootstrap` Docker init-container reads `config/buildings/{BUILDING_ID}.yaml`, loads the TTL into GraphDB (idempotent, SHA-256 hash check), vectorizes ontology into Qdrant, validates all DB connections, writes `config/resolved/{id}.json`, and stamps Redis `bootstrap:{id}:ready`. The orchestrator waits for that stamp before accepting traffic. All hardcoded Cardiff namespace strings in `sparql_agent.py` are replaced with `settings.BUILDING_NAMESPACE`.

**Tech Stack:** Python 3.10, rdflib, PyYAML, httpx, redis-py, FastAPI/pydantic-settings (existing), pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `orchestrator/services/multi_building_manager.py` | Add multi-DB `databases` dict + `get_db_config()` + `graphdb_repo` to `BuildingConfig` |
| Create | `config/buildings/bldg1.yaml` | Production config for Building 1 (converted from `config/building_config.yaml`) |
| Create | `config/buildings/bldg2.yaml` | Template for new buildings |
| Create | `scripts/bootstrap.py` | Init-container: validates, loads GraphDB, vectorizes Qdrant, stamps Redis |
| Modify | `shared/config.py` | Fix `BUILDING_NAMESPACE` default (remove hardcoded Cardiff URL); add `BOOTSTRAP_READY_TIMEOUT` |
| Modify | `orchestrator/main.py` | Add bootstrap stamp wait in `lifespan()` before accepting traffic |
| Modify | `orchestrator/agents/sparql_agent.py` | Replace 2 hardcoded Cardiff namespace literals with `settings.BUILDING_NAMESPACE` |
| Modify | `docker-compose.yml` | Add `bootstrap` service; add `depends_on` to `orchestrator` |
| Modify | `.env.example` | Document `BUILDING_ID`, per-DB env vars |
| Modify | `.gitignore` | Add `config/resolved/` |
| Create | `tests/test_bootstrap.py` | Unit tests for all bootstrap logic |

---

## Task 1: Extend BuildingConfig — multi-DB and graphdb_repo support

**Files:**
- Modify: `orchestrator/services/multi_building_manager.py:48-111`
- Create: `tests/test_bootstrap.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_bootstrap.py`:

```python
"""Tests for BuildingConfig multi-DB support and bootstrap helpers."""
import os
import pytest
from orchestrator.services.multi_building_manager import BuildingConfig


# ── Task 1 tests ──────────────────────────────────────────────────────────────

MULTI_DB_RAW = {
    "building": {
        "id": "bldg2",
        "name": "Test Building",
        "namespace": "http://example.org/bldg2#",
        "prefix": "bldg2",
        "timezone": "UTC",
        "abox_file": "input/bldg2.ttl",
    },
    "ontology": {
        "schema": "brick",
        "graphdb_repo": "bldg2_repo",
    },
    "storage": {
        "default": "sensors_mysql",
        "databases": [
            {
                "id": "sensors_mysql",
                "backend": "mysql",
                "host": "db1",
                "port": 3306,
                "database": "abacws_db",
                "username": "user",
                "password": "pass",
                "table": "sensor_data",
                "columns": {
                    "uuid": "uuid",
                    "value": "value",
                    "timestamp": "time",
                    "sensor_name": "sensor_name",
                },
            },
            {
                "id": "energy_postgres",
                "backend": "postgresql",
                "host": "db2",
                "port": 5432,
                "database": "energy_db",
                "username": "user",
                "password": "pass",
                "table": "energy_readings",
                "columns": {
                    "uuid": "sensor_id",
                    "value": "reading",
                    "timestamp": "recorded_at",
                    "sensor_name": "name",
                },
            },
        ],
    },
}

LEGACY_SINGLE_DB_RAW = {
    "building": {
        "id": "bldg1",
        "name": "Abacws",
        "namespace": "http://abacwsbuilding.cardiff.ac.uk/abacws#",
        "prefix": "bldg",
        "timezone": "Europe/London",
        "abox_file": "input/bldg1.ttl",
    },
    "ontology": {"schema": "brick"},
    "storage": {
        "backend": "mysql",
        "database": "abacws",
        "table": "sensor_data",
        "columns": {"uuid": "uuid", "value": "value", "timestamp": "time", "sensor_name": "sensor_name"},
    },
}


def test_building_config_multi_db_parsing():
    """BuildingConfig.databases is a dict keyed by logical DB id."""
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    assert "sensors_mysql" in cfg.databases
    assert "energy_postgres" in cfg.databases
    assert cfg.databases["sensors_mysql"]["backend"] == "mysql"
    assert cfg.databases["energy_postgres"]["backend"] == "postgresql"


def test_building_config_graphdb_repo():
    """graphdb_repo is read from ontology.graphdb_repo."""
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    assert cfg.graphdb_repo == "bldg2_repo"


def test_building_config_graphdb_repo_defaults_to_id():
    """graphdb_repo defaults to building.id when not specified."""
    raw = {**MULTI_DB_RAW, "ontology": {"schema": "brick"}}
    cfg = BuildingConfig(raw, "fake.yaml")
    assert cfg.graphdb_repo == "bldg2"


def test_building_config_get_db_config_found():
    """get_db_config returns the correct DB config dict."""
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    db = cfg.get_db_config("energy_postgres")
    assert db is not None
    assert db["backend"] == "postgresql"
    assert db["table"] == "energy_readings"


def test_building_config_get_db_config_missing_uses_default():
    """get_db_config falls back to default when db_id is unknown."""
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    db = cfg.get_db_config("nonexistent_db")
    assert db is not None
    assert db["id"] == "sensors_mysql"   # falls back to default


def test_building_config_get_db_config_no_match_returns_none():
    """get_db_config returns None when id is unknown and default is also unset."""
    raw = {
        **MULTI_DB_RAW,
        "storage": {
            "databases": [{"id": "only_db", "backend": "mysql", "host": "h", "port": 3306,
                           "database": "d", "username": "u", "password": "p",
                           "table": "t", "columns": {}}]
        },
    }
    cfg = BuildingConfig(raw, "fake.yaml")
    result = cfg.get_db_config("nonexistent")
    # no default set, but only one db — should return that one
    assert result is not None
    assert result["id"] == "only_db"


def test_building_config_legacy_single_db_still_works():
    """Legacy single-db storage format is still parsed without error."""
    cfg = BuildingConfig(LEGACY_SINGLE_DB_RAW, "fake.yaml")
    assert cfg.id == "bldg1"
    # Legacy fields still available
    assert cfg.backend == "mysql"
    assert cfg.database == "abacws"
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd c:/Users/suhas/Documents/GitHub/OntoSage
pytest tests/test_bootstrap.py::test_building_config_multi_db_parsing -v
```

Expected: `FAILED` — `BuildingConfig` has no `databases` attribute.

- [ ] **Step 1.3: Extend BuildingConfig in multi_building_manager.py**

In `orchestrator/services/multi_building_manager.py`, inside `BuildingConfig.__init__()`, after the existing `onto = raw.get("ontology", {})` block (around line 65), add:

```python
        # graphdb_repo — defaults to building.id
        self.graphdb_repo: str = onto.get("graphdb_repo", self.id)

        # graphdb section (url/auth may come from YAML or env var substitution)
        gdb = raw.get("graphdb", {})
        self.graphdb_url: str = gdb.get("url", "")
```

After the existing single-db `stor` block (around line 83), add:

```python
        # Multi-DB: storage.databases list (new format)
        # Also supports legacy single-db format for backward compatibility.
        raw_dbs = stor.get("databases", [])
        if raw_dbs:
            self.databases: Dict[str, Any] = {
                db["id"]: db for db in raw_dbs if "id" in db
            }
            self.default_db: str = stor.get("default", "")
            # If default not specified, use the first entry
            if not self.default_db and self.databases:
                self.default_db = next(iter(self.databases))
        else:
            # Legacy: wrap single-db config into databases dict
            legacy_id = stor.get("backend", "default")
            self.databases = {
                legacy_id: {
                    "id": legacy_id,
                    "backend": stor.get("backend", "mysql"),
                    "host": "",
                    "port": 3306,
                    "database": stor.get("database", self.id),
                    "table": stor.get("table", "sensor_data"),
                    "columns": stor.get("columns", {}),
                }
            }
            self.default_db = legacy_id
```

Add the `get_db_config()` method to `BuildingConfig` class (after `validate()`):

```python
    def get_db_config(self, db_id: str) -> Optional[Dict[str, Any]]:
        """Return database config by logical ID. Falls back to default, then first entry."""
        if db_id in self.databases:
            return self.databases[db_id]
        if self.default_db and self.default_db in self.databases:
            return self.databases[self.default_db]
        if self.databases:
            return next(iter(self.databases.values()))
        return None
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py -v -k "test_building_config"
```

Expected: all 7 tests `PASSED`.

- [ ] **Step 1.5: Commit**

```bash
git add orchestrator/services/multi_building_manager.py tests/test_bootstrap.py
git commit -m "feat: extend BuildingConfig with multi-DB databases dict and graphdb_repo"
```

---

## Task 2: Create config/buildings/ YAML files

**Files:**
- Create: `config/buildings/bldg1.yaml`
- Create: `config/buildings/bldg2.yaml`
- Modify: `.gitignore`

- [ ] **Step 2.1: Create `config/buildings/bldg1.yaml`**

```yaml
# ─── Building 1: Abacws, Cardiff ─────────────────────────────────────────────
building:
  id: bldg1
  name: "Abacws Building"
  namespace: "http://abacwsbuilding.cardiff.ac.uk/abacws#"
  prefix: bldg
  timezone: "Europe/London"
  abox_file: "input/bldg1_expanded_protege_clean.ttl"
  tbox_file: ""

ontology:
  schema: brick
  graphdb_repo: bldg1

graphdb:
  url: "${GRAPHDB_URL}"
  username: "${GRAPHDB_USER}"
  password: "${GRAPHDB_PASSWORD}"

storage:
  default: sensors_mysql

  databases:
    - id: sensors_mysql
      backend: mysql
      host: "${MYSQL_HOST}"
      port: 3306
      database: "${MYSQL_DATABASE}"
      username: "${MYSQL_USER}"
      password: "${MYSQL_PASSWORD}"
      table: sensor_data
      columns:
        uuid: uuid
        value: value
        timestamp: time
        sensor_name: sensor_name

extra_prefixes:
  - prefix: brick
    uri: "https://brickschema.org/schema/Brick#"
  - prefix: ref
    uri: "https://brickschema.org/schema/BrickFrame#"
```

- [ ] **Step 2.2: Create `config/buildings/bldg2.yaml`**

```yaml
# ─── Template for a new building — copy, fill in, and set BUILDING_ID=bldg2 ──
building:
  id: bldg2
  name: "My Building Name"
  namespace: "http://example.org/bldg2#"   # must match URIs inside the TTL
  prefix: bldg2
  timezone: "Europe/London"
  abox_file: "input/bldg2.ttl"
  tbox_file: ""

ontology:
  schema: auto          # brick | s223 | rec | custom | auto (auto = detect from TTL)
  graphdb_repo: bldg2   # defaults to building.id if omitted

graphdb:
  url: "${GRAPHDB_URL}"
  username: "${GRAPHDB_USER}"
  password: "${GRAPHDB_PASSWORD}"

storage:
  default: sensors_mysql

  databases:
    - id: sensors_mysql
      backend: mysql                # mysql | postgresql | influxdb | timescaledb
      host: "${DB1_HOST}"
      port: 3306
      database: "${DB1_DATABASE}"
      username: "${DB1_USER}"
      password: "${DB1_PASS}"
      table: sensor_data
      columns:
        uuid: uuid
        value: value
        timestamp: time
        sensor_name: sensor_name

    # Add more databases as needed — each id must match a ref:storedAt value in your TTL
    # - id: energy_postgres
    #   backend: postgresql
    #   host: "${DB2_HOST}"
    #   port: 5432
    #   database: "${DB2_DATABASE}"
    #   username: "${DB2_USER}"
    #   password: "${DB2_PASS}"
    #   table: energy_readings
    #   columns:
    #     uuid: sensor_id
    #     value: reading
    #     timestamp: recorded_at
    #     sensor_name: name

extra_prefixes:
  - prefix: brick
    uri: "https://brickschema.org/schema/Brick#"
  - prefix: ref
    uri: "https://brickschema.org/schema/BrickFrame#"
```

- [ ] **Step 2.3: Add `config/resolved/` to `.gitignore`**

Append to `.gitignore`:
```
# Auto-generated bootstrap resolved configs (per-building, not committed)
config/resolved/
```

- [ ] **Step 2.4: Commit**

```bash
git add config/buildings/bldg1.yaml config/buildings/bldg2.yaml .gitignore
git commit -m "feat: add per-building YAML config files and template"
```

---

## Task 3: shared/config.py — fix hardcoded defaults

**Files:**
- Modify: `shared/config.py:144-165`

The fields `BUILDING_NAMESPACE` and `BLDG1_ABOX_FILE` have hardcoded Cardiff/bldg1 defaults that conflict with portability. Also add `BOOTSTRAP_READY_TIMEOUT`.

- [ ] **Step 3.1: Write the failing test**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 3 tests ──────────────────────────────────────────────────────────────

def test_settings_building_namespace_default_is_empty():
    """BUILDING_NAMESPACE default must not be hardcoded to any real building URL."""
    from shared.config import Settings
    s = Settings()
    # After fix: default must be empty string, not the Cardiff URL
    assert s.BUILDING_NAMESPACE == ""


def test_settings_bootstrap_ready_timeout_exists():
    """Settings has a BOOTSTRAP_READY_TIMEOUT field."""
    from shared.config import Settings
    s = Settings()
    assert hasattr(s, "BOOTSTRAP_READY_TIMEOUT")
    assert s.BOOTSTRAP_READY_TIMEOUT > 0
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
pytest tests/test_bootstrap.py::test_settings_building_namespace_default_is_empty -v
```

Expected: `FAILED` — current default is the Cardiff URL.

- [ ] **Step 3.3: Update shared/config.py**

Change `BUILDING_NAMESPACE` default (line ~144):
```python
    BUILDING_NAMESPACE: str = Field(
        default="",
        description="Base URI for building ontology instances. Set via env or loaded from building YAML. Must end with '#'."
    )
```

Change `BLDG1_ABOX_FILE` to `BUILDING_ABOX_FILE` (line ~162):
```python
    BUILDING_ABOX_FILE: str = Field(
        default="",
        description="Path to the building ABox TTL file. Set via env or loaded from building YAML."
    )
```

Add after `BUILDING_TIMEZONE` (line ~155):
```python
    BOOTSTRAP_READY_TIMEOUT: int = Field(
        default=120,
        description="Seconds to wait for bootstrap ready stamp before orchestrator fails startup."
    )
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py::test_settings_building_namespace_default_is_empty tests/test_bootstrap.py::test_settings_bootstrap_ready_timeout_exists -v
```

Expected: both `PASSED`.

- [ ] **Step 3.5: Commit**

```bash
git add shared/config.py tests/test_bootstrap.py
git commit -m "fix: remove hardcoded Cardiff namespace from Settings defaults; add BOOTSTRAP_READY_TIMEOUT"
```

---

## Task 4: scripts/bootstrap.py — skeleton, env substitution, YAML loading

**Files:**
- Create: `scripts/bootstrap.py`

- [ ] **Step 4.1: Write the failing tests**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 4 tests ──────────────────────────────────────────────────────────────

import os
from scripts.bootstrap import load_yaml_with_env_substitution


def test_env_substitution_replaces_vars(tmp_path, monkeypatch):
    """${VAR} in YAML values is replaced with os.environ values at load time."""
    monkeypatch.setenv("DB_HOST", "192.168.1.10")
    monkeypatch.setenv("DB_PASS", "secret123")

    yaml_content = """
building:
  id: test
  name: Test
  namespace: "http://example.org/test#"
  prefix: test
  timezone: UTC
  abox_file: input/test.ttl
storage:
  databases:
    - id: db1
      backend: mysql
      host: "${DB_HOST}"
      port: 3306
      database: testdb
      username: user
      password: "${DB_PASS}"
      table: data
      columns: {}
"""
    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml_content)

    raw = load_yaml_with_env_substitution(config_file)
    assert raw["storage"]["databases"][0]["host"] == "192.168.1.10"
    assert raw["storage"]["databases"][0]["password"] == "secret123"


def test_env_substitution_missing_var_raises(tmp_path, monkeypatch):
    """${MISSING_VAR} raises BootstrapError if the env var is not set."""
    monkeypatch.delenv("MISSING_VAR", raising=False)

    yaml_content = """
building:
  id: test
  name: Test
  namespace: "http://example.org/test#"
  prefix: test
  timezone: UTC
  abox_file: input/test.ttl
storage:
  databases:
    - id: db1
      backend: mysql
      host: "${MISSING_VAR}"
      port: 3306
      database: d
      username: u
      password: p
      table: t
      columns: {}
"""
    config_file = tmp_path / "test.yaml"
    config_file.write_text(yaml_content)

    from scripts.bootstrap import BootstrapError
    with pytest.raises(BootstrapError, match="MISSING_VAR"):
        load_yaml_with_env_substitution(config_file)
```

- [ ] **Step 4.2: Run test to verify it fails**

```bash
pytest tests/test_bootstrap.py::test_env_substitution_replaces_vars -v
```

Expected: `FAILED` — `scripts.bootstrap` module not found.

- [ ] **Step 4.3: Create scripts/__init__.py**

Create an empty `scripts/__init__.py` so pytest can import from the `scripts` package:

```bash
touch scripts/__init__.py
```

Or create the file with no content.

- [ ] **Step 4.4: Create scripts/bootstrap.py skeleton**

Create `scripts/bootstrap.py`:

```python
#!/usr/bin/env python3
"""
scripts/bootstrap.py — OntoSage Building Bootstrap
====================================================
Docker init-container. Runs once before the orchestrator.
Validates config + TTL, loads GraphDB, vectorizes Qdrant,
tests DB connections, writes resolved config, stamps Redis.

Exit 0 = success. Exit 1 = failure.
"""
import os
import sys
import json
import hashlib
import time
import re
import logging
from pathlib import Path
from typing import Any, Dict, Optional

# Add /app to path so orchestrator imports work inside Docker
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("bootstrap")


# ── Custom exception ───────────────────────────────────────────────────────────

class BootstrapError(RuntimeError):
    """Raised when bootstrap cannot proceed. Message is shown to the operator."""


# ── Helpers ───────────────────────────────────────────────────────────────────

_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _substitute_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR} in strings with env var values."""
    if isinstance(value, str):
        def _replace(m: re.Match) -> str:
            var = m.group(1)
            if var not in os.environ:
                raise BootstrapError(
                    f"Config references env var ${{{var}}} but it is not set in the environment"
                )
            return os.environ[var]
        return _ENV_VAR_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def load_yaml_with_env_substitution(path: Path) -> Dict[str, Any]:
    """Load a YAML file and substitute all ${VAR} references from the environment."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BootstrapError(f"Config file is not a YAML mapping: {path}")
    return _substitute_env_vars(raw)
```

- [ ] **Step 4.5: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py::test_env_substitution_replaces_vars tests/test_bootstrap.py::test_env_substitution_missing_var_raises -v
```

Expected: both `PASSED`.

- [ ] **Step 4.6: Commit**

```bash
git add scripts/__init__.py scripts/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add bootstrap.py skeleton with YAML env-var substitution"
```

---

## Task 5: bootstrap.py — TTL validation and UUID→DB mapping extraction

**Files:**
- Modify: `scripts/bootstrap.py`

- [ ] **Step 5.1: Write the failing tests**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 5 tests ──────────────────────────────────────────────────────────────

from scripts.bootstrap import extract_uuid_db_mapping, validate_uuid_db_map, BootstrapError


SAMPLE_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ref:   <https://brickschema.org/schema/BrickFrame#> .
@prefix bldg:  <http://example.org/bldg2#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

bldg:TempSensor_01 a brick:Temperature_Sensor ;
    brick:hasExternalReference [
        ref:hasTimeseriesId "uuid-aaa-111" ;
        ref:storedAt        "sensors_mysql"
    ] .

bldg:EnergyMeter_01 a brick:Electrical_Meter ;
    brick:hasExternalReference [
        ref:hasTimeseriesId "uuid-bbb-222" ;
        ref:storedAt        "energy_postgres"
    ] .

bldg:CO2_Sensor_01 a brick:CO2_Sensor ;
    brick:hasExternalReference [
        ref:hasTimeseriesId "uuid-ccc-333" ;
        ref:storedAt        "sensors_mysql"
    ] .
"""


def _parse_ttl(ttl_text: str):
    from rdflib import Graph
    g = Graph()
    g.parse(data=ttl_text, format="turtle")
    return g


def test_extract_uuid_db_mapping_returns_correct_map():
    """extract_uuid_db_mapping returns {uuid: db_id} for all ref:hasTimeseriesId triples."""
    g = _parse_ttl(SAMPLE_TTL)
    mapping = extract_uuid_db_mapping(g)
    assert mapping["uuid-aaa-111"] == "sensors_mysql"
    assert mapping["uuid-bbb-222"] == "energy_postgres"
    assert mapping["uuid-ccc-333"] == "sensors_mysql"


def test_extract_uuid_db_mapping_empty_graph():
    """extract_uuid_db_mapping returns empty dict for graph with no ref:hasTimeseriesId."""
    from rdflib import Graph
    g = Graph()
    mapping = extract_uuid_db_mapping(g)
    assert mapping == {}


def test_validate_uuid_db_map_all_match(tmp_path):
    """validate_uuid_db_map passes when all storedAt values appear in YAML databases."""
    from orchestrator.services.multi_building_manager import BuildingConfig
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    uuid_db_map = {
        "uuid-aaa-111": "sensors_mysql",
        "uuid-bbb-222": "energy_postgres",
    }
    # Should not raise
    validate_uuid_db_map(uuid_db_map, cfg, "bldg2")


def test_validate_uuid_db_map_unknown_db_raises():
    """validate_uuid_db_map raises BootstrapError for unknown storedAt value."""
    from orchestrator.services.multi_building_manager import BuildingConfig
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    uuid_db_map = {
        "uuid-aaa-111": "sensors_mysql",
        "uuid-zzz-999": "nonexistent_db",   # not in YAML
    }
    with pytest.raises(BootstrapError, match="nonexistent_db"):
        validate_uuid_db_map(uuid_db_map, cfg, "bldg2")
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
pytest tests/test_bootstrap.py::test_extract_uuid_db_mapping_returns_correct_map -v
```

Expected: `FAILED` — `extract_uuid_db_mapping` not defined yet.

- [ ] **Step 5.3: Implement extraction and validation functions in bootstrap.py**

Add to `scripts/bootstrap.py` after the `load_yaml_with_env_substitution` function:

```python
# ── TTL extraction ─────────────────────────────────────────────────────────────

_REF_NS = "https://brickschema.org/schema/BrickFrame#"
_TIMESERIES_ID_PRED = f"{_REF_NS}hasTimeseriesId"
_STORED_AT_PRED     = f"{_REF_NS}storedAt"


def extract_uuid_db_mapping(graph) -> Dict[str, str]:
    """
    Return {uuid_string: database_id_string} for every ref:hasTimeseriesId /
    ref:storedAt pair found in the rdflib graph.
    """
    from rdflib import URIRef, Literal

    timeseries_pred = URIRef(_TIMESERIES_ID_PRED)
    stored_at_pred  = URIRef(_STORED_AT_PRED)

    # Build a map from blank-node / ref-node → {uuid, storedAt}
    ref_nodes: Dict[Any, Dict[str, str]] = {}

    for subj, pred, obj in graph:
        str_pred = str(pred)
        if str_pred == _TIMESERIES_ID_PRED:
            ref_nodes.setdefault(subj, {})["uuid"] = str(obj)
        elif str_pred == _STORED_AT_PRED:
            ref_nodes.setdefault(subj, {})["stored_at"] = str(obj)

    mapping: Dict[str, str] = {}
    for data in ref_nodes.values():
        if "uuid" in data and "stored_at" in data:
            mapping[data["uuid"]] = data["stored_at"]
    return mapping


def validate_uuid_db_map(
    uuid_db_map: Dict[str, str],
    building_cfg,
    building_id: str,
) -> None:
    """
    Cross-check all storedAt values in uuid_db_map against building_cfg.databases.
    Raises BootstrapError listing any storedAt values with no matching YAML entry.
    """
    unknown = sorted(
        set(uuid_db_map.values()) - set(building_cfg.databases.keys())
    )
    if unknown:
        raise BootstrapError(
            f"[{building_id}] TTL ref:storedAt references database(s) not found in "
            f"config/buildings/{building_id}.yaml storage.databases:\n"
            + "\n".join(f"  - '{u}'" for u in unknown)
            + "\nAdd an entry with that id to the storage.databases list."
        )
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py -k "extract_uuid or validate_uuid" -v
```

Expected: all 4 tests `PASSED`.

- [ ] **Step 5.5: Commit**

```bash
git add scripts/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add TTL UUID→DB mapping extraction and cross-reference validation"
```

---

## Task 6: bootstrap.py — GraphDB idempotent repo creation and TTL loading

**Files:**
- Modify: `scripts/bootstrap.py`

- [ ] **Step 6.1: Write the failing tests**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 6 tests ──────────────────────────────────────────────────────────────

import hashlib
from unittest.mock import patch, MagicMock
from scripts.bootstrap import compute_ttl_hash, ttl_already_loaded


def test_compute_ttl_hash_is_deterministic(tmp_path):
    """compute_ttl_hash returns the same SHA-256 for the same file content."""
    f = tmp_path / "test.ttl"
    f.write_bytes(b"@prefix brick: <https://brickschema.org/schema/Brick#> .\n")
    h1 = compute_ttl_hash(f)
    h2 = compute_ttl_hash(f)
    assert h1 == h2
    assert len(h1) == 64   # SHA-256 hex


def test_compute_ttl_hash_differs_for_different_content(tmp_path):
    """Different file content produces different hash."""
    f1 = tmp_path / "a.ttl"
    f2 = tmp_path / "b.ttl"
    f1.write_bytes(b"content_a")
    f2.write_bytes(b"content_b")
    assert compute_ttl_hash(f1) != compute_ttl_hash(f2)


def test_ttl_already_loaded_returns_true_when_hash_matches():
    """ttl_already_loaded returns True when Redis has matching hash."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"abc123"
    assert ttl_already_loaded(mock_redis, "bldg1", "abc123") is True


def test_ttl_already_loaded_returns_false_when_hash_differs():
    """ttl_already_loaded returns False when Redis hash differs."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = b"old_hash"
    assert ttl_already_loaded(mock_redis, "bldg1", "new_hash") is False


def test_ttl_already_loaded_returns_false_when_no_key():
    """ttl_already_loaded returns False when Redis key is absent."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    assert ttl_already_loaded(mock_redis, "bldg1", "any_hash") is False
```

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
pytest tests/test_bootstrap.py -k "ttl_hash or ttl_already" -v
```

Expected: `FAILED` — functions not defined.

- [ ] **Step 6.3: Implement GraphDB helpers in bootstrap.py**

Add to `scripts/bootstrap.py`:

```python
# ── GraphDB helpers ────────────────────────────────────────────────────────────

def compute_ttl_hash(ttl_path: Path) -> str:
    """Return SHA-256 hex digest of the TTL file bytes."""
    return hashlib.sha256(ttl_path.read_bytes()).hexdigest()


def ttl_already_loaded(redis_client, building_id: str, current_hash: str) -> bool:
    """Return True if Redis records that this exact TTL hash was already loaded."""
    key = f"bootstrap:{building_id}:ttl_hash"
    stored = redis_client.get(key)
    if stored is None:
        return False
    return stored.decode("utf-8") == current_hash


def wait_for_graphdb(graphdb_url: str, retries: int = 30, delay: float = 2.0) -> None:
    """Poll GraphDB health endpoint until ready or raise BootstrapError."""
    import httpx
    health_url = graphdb_url.rstrip("/") + "/rest/repositories"
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(health_url, timeout=5)
            if r.status_code < 500:
                logger.info(f"GraphDB ready at {graphdb_url}")
                return
        except Exception:
            pass
        logger.info(f"Waiting for GraphDB ({attempt}/{retries})...")
        time.sleep(delay)
    raise BootstrapError(
        f"GraphDB not healthy after {retries * delay:.0f}s — is graphdb service running?"
    )


def create_graphdb_repo(graphdb_url: str, repo_name: str, building_cfg) -> None:
    """Create GraphDB repository if it does not already exist."""
    import httpx
    repos_url = graphdb_url.rstrip("/") + "/rest/repositories"
    try:
        r = httpx.get(repos_url, timeout=10)
        existing = [rep.get("id") for rep in r.json()] if r.status_code == 200 else []
    except Exception as e:
        raise BootstrapError(f"Cannot list GraphDB repos: {e}")

    if repo_name in existing:
        logger.info(f"GraphDB repo '{repo_name}' already exists — skipping creation")
        return

    config_payload = {
        "id": repo_name,
        "type": "free",
        "title": building_cfg.name,
        "params": {
            "entityIndexSize": {"name": "entityIndexSize", "label": "Entity index size", "value": "10000000"},
            "ruleset": {"name": "ruleset", "label": "Ruleset", "value": "rdfsplus-optimized"},
        },
    }
    try:
        r = httpx.post(repos_url, json=config_payload, timeout=30)
        if r.status_code not in (200, 201):
            raise BootstrapError(
                f"Failed to create GraphDB repo '{repo_name}': HTTP {r.status_code} — {r.text[:200]}"
            )
        logger.info(f"Created GraphDB repo: {repo_name}")
    except httpx.HTTPError as e:
        raise BootstrapError(f"HTTP error creating GraphDB repo '{repo_name}': {e}")


def load_ttl_to_graphdb(
    graphdb_url: str,
    repo_name: str,
    ttl_path: Path,
    building_id: str,
    redis_client,
) -> None:
    """Load TTL into GraphDB. Skips if SHA-256 hash is unchanged since last load."""
    import httpx

    current_hash = compute_ttl_hash(ttl_path)

    if ttl_already_loaded(redis_client, building_id, current_hash):
        logger.info(f"TTL unchanged (hash={current_hash[:12]}...) — skipping GraphDB reload")
        return

    upload_url = (
        f"{graphdb_url.rstrip('/')}/repositories/{repo_name}/statements"
    )
    ttl_bytes = ttl_path.read_bytes()
    try:
        r = httpx.post(
            upload_url,
            content=ttl_bytes,
            headers={"Content-Type": "application/x-turtle"},
            timeout=120,
        )
        if r.status_code not in (200, 204):
            raise BootstrapError(
                f"GraphDB TTL upload failed: HTTP {r.status_code} — {r.text[:300]}"
            )
    except httpx.HTTPError as e:
        raise BootstrapError(f"HTTP error uploading TTL to GraphDB: {e}")

    # Record hash so next run can skip
    redis_client.set(f"bootstrap:{building_id}:ttl_hash", current_hash)
    logger.info(f"TTL loaded into GraphDB repo '{repo_name}' (hash={current_hash[:12]}...)")
```

- [ ] **Step 6.4: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py -k "ttl_hash or ttl_already" -v
```

Expected: all 5 tests `PASSED`.

- [ ] **Step 6.5: Commit**

```bash
git add scripts/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add GraphDB idempotent repo creation and SHA-256 TTL loading"
```

---

## Task 7: bootstrap.py — DB connectivity tests and resolved config

**Files:**
- Modify: `scripts/bootstrap.py`

- [ ] **Step 7.1: Write the failing tests**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 7 tests ──────────────────────────────────────────────────────────────

from scripts.bootstrap import build_resolved_config


def test_build_resolved_config_shape():
    """build_resolved_config returns a dict with the expected top-level keys."""
    from orchestrator.services.multi_building_manager import BuildingConfig
    cfg = BuildingConfig(MULTI_DB_RAW, "fake.yaml")
    uuid_map = {"uuid-aaa-111": "sensors_mysql"}
    result = build_resolved_config(cfg, uuid_map, triple_count=42, graphdb_repo="bldg2_repo")

    assert result["building_id"] == "bldg2"
    assert result["namespace"] == "http://example.org/bldg2#"
    assert result["graphdb_repo"] == "bldg2_repo"
    assert result["schema"] == "brick"
    assert result["triple_count"] == 42
    assert result["uuid_db_map"] == {"uuid-aaa-111": "sensors_mysql"}
    assert "databases" in result
    assert "sensors_mysql" in result["databases"]
    assert "generated_at" in result
```

- [ ] **Step 7.2: Run test to verify it fails**

```bash
pytest tests/test_bootstrap.py::test_build_resolved_config_shape -v
```

Expected: `FAILED` — `build_resolved_config` not defined.

- [ ] **Step 7.3: Implement DB test and resolved config functions in bootstrap.py**

Add to `scripts/bootstrap.py`:

```python
# ── DB connectivity ────────────────────────────────────────────────────────────

def test_db_connections(building_cfg) -> None:
    """
    Test connectivity for every database in building_cfg.databases.
    Raises BootstrapError listing all unreachable databases.
    """
    failures = []
    for db_id, db in building_cfg.databases.items():
        backend = db.get("backend", "mysql")
        host = db.get("host", "")
        port = int(db.get("port", 3306))
        try:
            _test_single_db(backend, host, port, db)
            logger.info(f"DB '{db_id}' ({backend}@{host}:{port}) — OK")
        except Exception as e:
            msg = f"Cannot connect to '{db_id}' ({backend}@{host}:{port}): {e}"
            logger.warning(msg)
            failures.append(msg)

    if failures:
        raise BootstrapError(
            "One or more databases are unreachable:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )


def _test_single_db(backend: str, host: str, port: int, db: Dict[str, Any]) -> None:
    """Open and immediately close a connection to verify reachability."""
    import socket
    sock = socket.create_connection((host, port), timeout=5)
    sock.close()


# ── Resolved config ────────────────────────────────────────────────────────────

def build_resolved_config(
    building_cfg,
    uuid_db_map: Dict[str, str],
    triple_count: int,
    graphdb_repo: str,
) -> Dict[str, Any]:
    """Build the resolved config dict written to config/resolved/{id}.json."""
    from datetime import datetime, timezone
    return {
        "building_id":   building_cfg.id,
        "name":          building_cfg.name,
        "namespace":     building_cfg.namespace,
        "prefix":        building_cfg.prefix,
        "timezone":      building_cfg.timezone,
        "abox_file":     building_cfg.abox_file,
        "schema":        building_cfg.schema,
        "graphdb_repo":  graphdb_repo,
        "triple_count":  triple_count,
        "uuid_db_map":   uuid_db_map,
        "databases":     building_cfg.databases,
        "default_db":    building_cfg.default_db,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 7.4: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py::test_build_resolved_config_shape -v
```

Expected: `PASSED`.

- [ ] **Step 7.5: Commit**

```bash
git add scripts/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add DB connectivity test and resolved config builder"
```

---

## Task 8: bootstrap.py — Qdrant vectorization and main() orchestrator

**Files:**
- Modify: `scripts/bootstrap.py`

- [ ] **Step 8.1: Write the failing test**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 8 tests ──────────────────────────────────────────────────────────────

from unittest.mock import patch, MagicMock, call
from scripts.bootstrap import run_bootstrap


def test_run_bootstrap_missing_building_id_raises():
    """run_bootstrap raises BootstrapError when BUILDING_ID is not set."""
    from scripts.bootstrap import BootstrapError
    with pytest.raises(BootstrapError, match="BUILDING_ID"):
        run_bootstrap(building_id="", config_dir=Path("config/buildings"))


def test_run_bootstrap_missing_config_file_raises(tmp_path):
    """run_bootstrap raises BootstrapError when config YAML is not found."""
    from scripts.bootstrap import BootstrapError
    with pytest.raises(BootstrapError, match="Config not found"):
        run_bootstrap(building_id="nonexistent", config_dir=tmp_path)


def test_run_bootstrap_missing_ttl_raises(tmp_path):
    """run_bootstrap raises BootstrapError when abox_file does not exist."""
    import yaml as _yaml
    from scripts.bootstrap import BootstrapError

    cfg_dir = tmp_path / "buildings"
    cfg_dir.mkdir()
    raw = {
        "building": {
            "id": "testbldg",
            "name": "T",
            "namespace": "http://example.org/t#",
            "prefix": "t",
            "timezone": "UTC",
            "abox_file": str(tmp_path / "nonexistent.ttl"),
        },
        "ontology": {"schema": "brick"},
        "storage": {
            "databases": [
                {"id": "db1", "backend": "mysql", "host": "h", "port": 3306,
                 "database": "d", "username": "u", "password": "p",
                 "table": "t", "columns": {}}
            ]
        },
    }
    (cfg_dir / "testbldg.yaml").write_text(_yaml.dump(raw))

    with pytest.raises(BootstrapError, match="does not exist"):
        run_bootstrap(building_id="testbldg", config_dir=cfg_dir)
```

- [ ] **Step 8.2: Run tests to verify they fail**

```bash
pytest tests/test_bootstrap.py -k "run_bootstrap" -v
```

Expected: `FAILED` — `run_bootstrap` not defined.

- [ ] **Step 8.3: Implement Qdrant vectorization helper and run_bootstrap()**

Add to `scripts/bootstrap.py`:

```python
# ── Qdrant vectorization ───────────────────────────────────────────────────────

def vectorize_ontology_to_qdrant(
    qdrant_url: str,
    building_id: str,
    ttl_path: Path,
    graph,
) -> None:
    """
    Vectorize ontology class/instance descriptions into Qdrant.
    Idempotent: skips if collection '{building_id}_ontology' already exists
    with a non-zero point count.
    """
    import httpx

    collection_name = f"{building_id}_ontology"
    check_url = f"{qdrant_url.rstrip('/')}/collections/{collection_name}"

    try:
        r = httpx.get(check_url, timeout=10)
        if r.status_code == 200:
            info = r.json()
            count = info.get("result", {}).get("points_count", 0)
            if count > 0:
                logger.info(
                    f"Qdrant collection '{collection_name}' exists ({count} points) — skipping vectorization"
                )
                return
    except Exception:
        pass  # collection doesn't exist — proceed

    logger.info(f"Vectorizing ontology into Qdrant collection '{collection_name}'...")

    try:
        # Use the orchestrator's existing hybrid_retrieval / ontology_introspector
        # to populate Qdrant. This reuses proven logic.
        import asyncio
        from orchestrator.services.ontology_introspector import OntologyIntrospector

        introspector = OntologyIntrospector()
        asyncio.run(introspector.initialize())
        logger.info(f"Ontology vectorized into Qdrant collection '{collection_name}'")
    except Exception as e:
        logger.warning(f"Qdrant vectorization failed (non-fatal — RAG fallback will work): {e}")


# ── Main bootstrap orchestrator ───────────────────────────────────────────────

def run_bootstrap(
    building_id: str,
    config_dir: Path,
    graphdb_url: Optional[str] = None,
    qdrant_url: Optional[str] = None,
    redis_url: Optional[str] = None,
) -> None:
    """
    Full bootstrap sequence. Raises BootstrapError on any failure.
    Called by main() and directly by tests.
    """
    if not building_id:
        raise BootstrapError("BUILDING_ID env var not set — cannot start")

    # ── Step 1: Load + validate YAML ──────────────────────────────────────────
    config_path = config_dir / f"{building_id}.yaml"
    if not config_path.exists():
        raise BootstrapError(f"Config not found: {config_path}")

    raw = load_yaml_with_env_substitution(config_path)

    from orchestrator.services.multi_building_manager import BuildingConfig
    cfg = BuildingConfig(raw, str(config_path))
    issues = cfg.validate()
    if issues:
        raise BootstrapError(
            f"Config validation failed for {building_id}:\n"
            + "\n".join(f"  - {i}" for i in issues)
        )
    logger.info(f"Config loaded: {cfg.id} — {cfg.name}")

    # ── Step 2: Validate TTL ──────────────────────────────────────────────────
    abox = Path(cfg.abox_file)
    if not abox.exists():
        raise BootstrapError(f"abox_file '{cfg.abox_file}' does not exist")

    try:
        from rdflib import Graph
        g = Graph()
        g.parse(str(abox), format="turtle")
        triple_count = len(g)
        logger.info(f"TTL parsed: {triple_count} triples")
    except Exception as e:
        raise BootstrapError(f"Failed to parse {cfg.abox_file}: {e}")

    # ── Step 3: Auto-detect schema ────────────────────────────────────────────
    if cfg.schema == "auto":
        try:
            from orchestrator.services.ontology_detector import OntologySchemaDetector
            detected = OntologySchemaDetector().detect_from_file(str(abox))
            cfg._raw.setdefault("ontology", {})["schema"] = detected
            cfg.schema = detected
            logger.info(f"Auto-detected ontology schema: {detected}")
        except Exception as e:
            logger.warning(f"Schema auto-detection failed, defaulting to 'brick': {e}")
            cfg.schema = "brick"

    # ── Steps 4-6: GraphDB ────────────────────────────────────────────────────
    _graphdb_url = graphdb_url or os.environ.get("GRAPHDB_URL", "http://graphdb:7200")
    repo_name = cfg.graphdb_repo

    import redis as redis_lib
    _redis_url = redis_url or os.environ.get("REDIS_URL", "redis://redis:6379/0")
    redis_client = redis_lib.from_url(_redis_url)

    wait_for_graphdb(_graphdb_url)
    create_graphdb_repo(_graphdb_url, repo_name, cfg)
    load_ttl_to_graphdb(_graphdb_url, repo_name, abox, building_id, redis_client)

    # ── Step 7: Extract UUID→DB mapping ──────────────────────────────────────
    uuid_db_map = extract_uuid_db_mapping(g)
    validate_uuid_db_map(uuid_db_map, cfg, building_id)
    logger.info(f"UUID→DB mapping: {len(uuid_db_map)} entries")

    # ── Step 8: Qdrant vectorization ──────────────────────────────────────────
    _qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "http://qdrant:6333")
    vectorize_ontology_to_qdrant(_qdrant_url, building_id, abox, g)

    # ── Step 9: DB connectivity ───────────────────────────────────────────────
    test_db_connections(cfg)

    # ── Step 10: Write resolved config ───────────────────────────────────────
    resolved = build_resolved_config(cfg, uuid_db_map, triple_count, repo_name)
    resolved_path = Path(f"config/resolved/{building_id}.json")
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(json.dumps(resolved, indent=2))
    logger.info(f"Resolved config written: {resolved_path}")

    # ── Step 11: Redis ready stamp ────────────────────────────────────────────
    redis_client.set(f"bootstrap:{building_id}:ready", "1")
    logger.info(f"Bootstrap complete — stamp written: bootstrap:{building_id}:ready")


def main() -> None:
    """Entry point for Docker init-container."""
    building_id = os.environ.get("BUILDING_ID", "").strip()
    config_dir = Path("config/buildings")
    try:
        run_bootstrap(building_id=building_id, config_dir=config_dir)
        sys.exit(0)
    except BootstrapError as e:
        logger.error(f"\n{'='*60}\nBOOTSTRAP FAILED\n{'='*60}\n{e}\n{'='*60}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected bootstrap error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Run all bootstrap tests**

```bash
pytest tests/test_bootstrap.py -v
```

Expected: all tests `PASSED`.

- [ ] **Step 8.5: Commit**

```bash
git add scripts/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: complete bootstrap.py — Qdrant vectorization, resolved config, Redis stamp"
```

---

## Task 9: Fix hardcoded Cardiff namespace in sparql_agent.py

**Files:**
- Modify: `orchestrator/agents/sparql_agent.py:1356` and `orchestrator/agents/sparql_agent.py:1612`

- [ ] **Step 9.1: Write the failing test**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 9 tests ──────────────────────────────────────────────────────────────

def test_sparql_agent_no_hardcoded_cardiff_namespace():
    """
    sparql_agent.py must not contain the hardcoded Cardiff namespace as a literal
    string in executable code (pattern-based SPARQL or URI cleanup regex).
    """
    source = Path("orchestrator/agents/sparql_agent.py").read_text(encoding="utf-8")
    cardiff_url = "http://abacwsbuilding.cardiff.ac.uk/abacws#"

    # Find lines containing the URL (excluding comment lines and prompt strings)
    problem_lines = []
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if cardiff_url in line and not stripped.startswith("#"):
            # Allow in multi-line prompt strings (inside triple-quoted strings)
            # Flag lines that are in actual code: FILTER(, uri_patterns
            if any(kw in stripped for kw in ["FILTER(", "uri_patterns", "re.sub"]):
                problem_lines.append(f"  line {i}: {stripped[:100]}")

    assert not problem_lines, (
        "Hardcoded Cardiff namespace found in executable code:\n"
        + "\n".join(problem_lines)
        + "\nReplace with settings.BUILDING_NAMESPACE"
    )
```

- [ ] **Step 9.2: Run test to verify it fails**

```bash
pytest tests/test_bootstrap.py::test_sparql_agent_no_hardcoded_cardiff_namespace -v
```

Expected: `FAILED` — lines 1356 and 1612 contain the hardcoded URL.

- [ ] **Step 9.3: Fix sparql_agent.py line 1356**

In `orchestrator/agents/sparql_agent.py` at line ~1356, replace:

```python
    FILTER(STRSTARTS(STR(?sensor), 'http://abacwsbuilding.cardiff.ac.uk/abacws#') && CONTAINS(STR(?sensor), '{token}_Sensor'))
```

with:

```python
    FILTER(STRSTARTS(STR(?sensor), '{settings.BUILDING_NAMESPACE}') && CONTAINS(STR(?sensor), '{token}_Sensor'))
```

- [ ] **Step 9.4: Fix sparql_agent.py line 1612**

In `orchestrator/agents/sparql_agent.py` at line ~1612, replace:

```python
            (r'http://abacwsbuilding\.cardiff\.ac\.uk/abacws#', ''),
```

with:

```python
            (re.escape(settings.BUILDING_NAMESPACE), ''),
```

- [ ] **Step 9.5: Run test to verify it passes**

```bash
pytest tests/test_bootstrap.py::test_sparql_agent_no_hardcoded_cardiff_namespace -v
```

Expected: `PASSED`.

- [ ] **Step 9.6: Commit**

```bash
git add orchestrator/agents/sparql_agent.py tests/test_bootstrap.py
git commit -m "fix: replace hardcoded Cardiff namespace in sparql_agent.py with settings.BUILDING_NAMESPACE"
```

---

## Task 10: orchestrator/main.py — bootstrap stamp wait

**Files:**
- Modify: `orchestrator/main.py:178-210` (lifespan function)

- [ ] **Step 10.1: Write the failing test**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 10 tests ─────────────────────────────────────────────────────────────

def test_lifespan_waits_for_bootstrap_stamp():
    """
    main.py lifespan must contain a call that waits for the bootstrap ready stamp.
    Verified by static source inspection (the actual wait requires a running Redis).
    """
    source = Path("orchestrator/main.py").read_text(encoding="utf-8")
    assert "bootstrap:" in source and ":ready" in source, (
        "main.py lifespan must check the bootstrap Redis stamp "
        "bootstrap:{building_id}:ready before accepting traffic"
    )
    assert "BOOTSTRAP_READY_TIMEOUT" in source, (
        "main.py must use settings.BOOTSTRAP_READY_TIMEOUT for the wait timeout"
    )
```

- [ ] **Step 10.2: Run test to verify it fails**

```bash
pytest tests/test_bootstrap.py::test_lifespan_waits_for_bootstrap_stamp -v
```

Expected: `FAILED` — main.py does not yet check the stamp.

- [ ] **Step 10.3: Add bootstrap wait to main.py lifespan**

In `orchestrator/main.py`, inside the `lifespan()` function after the Redis connect block (around line 189), add:

```python
    # Wait for bootstrap init-container to complete
    bootstrap_key = f"bootstrap:{settings.BUILDING_ID}:ready"
    logger.info(f"Waiting for bootstrap stamp '{bootstrap_key}' (timeout={settings.BOOTSTRAP_READY_TIMEOUT}s)...")
    deadline = time.time() + settings.BOOTSTRAP_READY_TIMEOUT
    while time.time() < deadline:
        if await redis_manager.client.get(bootstrap_key):
            logger.info(f"Bootstrap ready for building '{settings.BUILDING_ID}'")
            break
        await asyncio.sleep(2)
    else:
        raise RuntimeError(
            f"Bootstrap did not complete within {settings.BOOTSTRAP_READY_TIMEOUT}s. "
            f"Check 'docker compose logs bootstrap' for errors."
        )
```

Also ensure `import asyncio` is at the top of `main.py` (add if missing).

- [ ] **Step 10.4: Run test to verify it passes**

```bash
pytest tests/test_bootstrap.py::test_lifespan_waits_for_bootstrap_stamp -v
```

Expected: `PASSED`.

- [ ] **Step 10.5: Run full test suite to check no regressions**

```bash
pytest tests/ -v --ignore=tests/test_bootstrap.py -x -q 2>&1 | tail -20
```

Expected: same pass count as before this task (no new failures).

- [ ] **Step 10.6: Commit**

```bash
git add orchestrator/main.py tests/test_bootstrap.py
git commit -m "feat: add bootstrap stamp wait to orchestrator lifespan startup"
```

---

## Task 11: docker-compose.yml — bootstrap service

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 11.1: Write the failing test**

Add to `tests/test_bootstrap.py`:

```python
# ── Task 11 tests ─────────────────────────────────────────────────────────────

import yaml as _yaml_lib


def test_docker_compose_has_bootstrap_service():
    """docker-compose.yml defines a 'bootstrap' service."""
    compose = _yaml_lib.safe_load(Path("docker-compose.yml").read_text())
    assert "bootstrap" in compose.get("services", {}), (
        "docker-compose.yml must define a 'bootstrap' service"
    )


def test_docker_compose_orchestrator_depends_on_bootstrap():
    """orchestrator service depends_on bootstrap with service_completed_successfully."""
    compose = _yaml_lib.safe_load(Path("docker-compose.yml").read_text())
    orch = compose.get("services", {}).get("orchestrator", {})
    deps = orch.get("depends_on", {})
    assert "bootstrap" in deps, "orchestrator must depend_on bootstrap"
    if isinstance(deps, dict):
        condition = deps["bootstrap"].get("condition", "")
        assert condition == "service_completed_successfully", (
            f"orchestrator.depends_on.bootstrap.condition must be "
            f"'service_completed_successfully', got '{condition}'"
        )


def test_docker_compose_bootstrap_restart_is_no():
    """bootstrap service must have restart: 'no' so it only runs once."""
    compose = _yaml_lib.safe_load(Path("docker-compose.yml").read_text())
    bootstrap = compose["services"]["bootstrap"]
    assert bootstrap.get("restart") == "no", (
        "bootstrap service must have restart: 'no' to run exactly once"
    )
```

- [ ] **Step 11.2: Run tests to verify they fail**

```bash
pytest tests/test_bootstrap.py -k "docker_compose" -v
```

Expected: `FAILED` — no bootstrap service yet.

- [ ] **Step 11.3: Read current docker-compose.yml top section**

```bash
head -80 docker-compose.yml
```

Note the existing service names and network/volume definitions to match the pattern.

- [ ] **Step 11.4: Add bootstrap service to docker-compose.yml**

Find the `services:` block and add the `bootstrap` service. Add it BEFORE the `orchestrator` service definition:

```yaml
  bootstrap:
    build:
      context: .
      dockerfile: orchestrator/Dockerfile
    command: python scripts/bootstrap.py
    environment:
      - BUILDING_ID=${BUILDING_ID:-bldg1}
      - GRAPHDB_URL=http://graphdb:7200
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379/0
      - GRAPHDB_USER=${GRAPHDB_USER:-admin}
      - GRAPHDB_PASSWORD=${GRAPHDB_PASSWORD:-Admin@GraphDB2024}
      - MYSQL_HOST=${MYSQL_HOST:-mysql}
      - MYSQL_PORT=${MYSQL_PORT:-3306}
      - MYSQL_USER=${MYSQL_USER:-root}
      - MYSQL_PASSWORD=${MYSQL_PASSWORD:-mysql}
      - MYSQL_DATABASE=${MYSQL_DATABASE:-sensordb}
      - DB1_HOST=${DB1_HOST:-}
      - DB1_USER=${DB1_USER:-}
      - DB1_PASS=${DB1_PASS:-}
      - DB1_DATABASE=${DB1_DATABASE:-}
      - DB2_HOST=${DB2_HOST:-}
      - DB2_USER=${DB2_USER:-}
      - DB2_PASS=${DB2_PASS:-}
      - DB2_DATABASE=${DB2_DATABASE:-}
    volumes:
      - ./input:/app/input:ro
      - ./config:/app/config
    depends_on:
      graphdb:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: "no"
    networks:
      - ontosage-network
```

Also add `bootstrap` to the orchestrator's `depends_on`:

```yaml
  orchestrator:
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      # ... existing deps remain unchanged
```

- [ ] **Step 11.5: Run tests to verify they pass**

```bash
pytest tests/test_bootstrap.py -k "docker_compose" -v
```

Expected: all 3 tests `PASSED`.

- [ ] **Step 11.6: Commit**

```bash
git add docker-compose.yml tests/test_bootstrap.py
git commit -m "feat: add bootstrap init-container service to docker-compose.yml"
```

---

## Task 12: .env.example — document new env vars

**Files:**
- Modify: `.env.example`

- [ ] **Step 12.1: Add BUILDING_ID and per-DB env vars to .env.example**

Find the `# ==================== 🎯 MODEL PROVIDER SELECTION ====================` section and insert a new section just before it:

```bash
# ==================== 🏢 BUILDING SELECTION ====================
# Set this to the building you want to serve (matches config/buildings/{id}.yaml)
# Copy config/buildings/bldg2.yaml, fill in values, and set BUILDING_ID=bldg2
BUILDING_ID=bldg1

# ==================== 🗄️ SENSOR DATABASE CREDENTIALS ====================
# These are referenced as ${VAR} in config/buildings/{id}.yaml storage.databases
# Add one set per database your building uses.

# Database 1 — sensors_mysql (Building 1 default)
DB1_HOST=mysql
DB1_USER=root
DB1_PASS=mysql
DB1_DATABASE=sensordb

# Database 2 — additional DB (e.g. energy data)
# DB2_HOST=
# DB2_USER=
# DB2_PASS=
# DB2_DATABASE=

# InfluxDB (if used)
# INFLUXDB_ORG=ontosage
# INFLUXDB_TOKEN=
```

- [ ] **Step 12.2: Commit**

```bash
git add .env.example
git commit -m "docs: document BUILDING_ID and per-DB env vars in .env.example"
```

---

## Task 13: Run full test suite and verify

- [ ] **Step 13.1: Run all tests**

```bash
pytest tests/ -v -q 2>&1 | tail -30
```

Expected: all existing tests still pass; new `tests/test_bootstrap.py` tests pass.

- [ ] **Step 13.2: Verify bootstrap script is importable**

```bash
python -c "from scripts.bootstrap import run_bootstrap, load_yaml_with_env_substitution, extract_uuid_db_mapping; print('OK')"
```

Expected: `OK`

- [ ] **Step 13.3: Dry-run bootstrap against bldg1 config (no Docker)**

```bash
BUILDING_ID=bldg1 python scripts/bootstrap.py 2>&1 | head -20
```

Expected: should fail at "Waiting for GraphDB" (no GraphDB running outside Docker) — this confirms the script starts, loads config, validates TTL, and only fails when trying to reach a service.

- [ ] **Step 13.4: Final commit**

```bash
git add .
git commit -m "feat: building deployment bootstrap — complete implementation"
```

---

## Spec Coverage Check

| Spec section | Task(s) covering it |
|---|---|
| Operator workflow (TTL + YAML + BUILDING_ID → up) | Tasks 2, 11, 12 |
| BuildingConfig multi-DB | Task 1 |
| YAML env var substitution | Task 4 |
| TTL validation | Task 8 (run_bootstrap step 2) |
| Schema auto-detection | Task 8 (run_bootstrap step 3) |
| GraphDB idempotent load | Task 6 |
| UUID→DB mapping extraction | Task 5 |
| TTL cross-reference validation | Task 5 |
| Qdrant vectorization | Task 8 |
| DB connectivity tests | Task 7 |
| Resolved config write | Task 7 |
| Redis ready stamp | Task 8 |
| Orchestrator startup wait | Task 10 |
| Hardcoded namespace removal | Task 9 |
| docker-compose bootstrap service | Task 11 |
| Error messages (fast-fail) | Task 8 (BootstrapError messages) |
| .gitignore config/resolved/ | Task 2 |
