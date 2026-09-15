# -*- coding: utf-8 -*-
"""BUG-541: registering a backend appends text; comments survive and no secret is written."""

import importlib.util
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_SPEC = importlib.util.spec_from_file_location(
    "_seed", Path(__file__).resolve().parent.parent / "scripts" / "seed_timeseries_backends.py"
)
seed = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed)

REGISTRY = """# A documented registry. This comment must survive.
databases:
  # the real store
  database1:
    type: mysql
    password: "${MYSQL_PASSWORD:-mysql}"   # placeholder, never a literal
"""


def test_appending_keeps_every_existing_byte_and_parses(tmp_path):
    p = tmp_path / "database_registry.yaml"
    p.write_text(REGISTRY, encoding="utf-8")
    blocks = seed.registry_blocks(["timescale", "cassandra"], existing={"database1"})
    seed.append_registry_blocks(p, REGISTRY, blocks)
    out = p.read_text(encoding="utf-8")
    assert out.startswith(REGISTRY)
    data = yaml.safe_load(out)["databases"]
    assert set(data) == {"database1", "timescaledb", "cassandra"}
    assert data["timescaledb"]["password"] == "${TIMESCALE_PASSWORD}"
    assert "ontosage_ts_secret" not in out


def test_an_existing_entry_is_not_appended_twice():
    assert seed.registry_blocks(["timescale"], existing={"timescaledb"}) == []


def test_a_registry_whose_last_key_is_not_databases_is_refused(tmp_path):
    text = "databases:\n  a:\n    type: mysql\nother: 1\n"
    p = tmp_path / "r.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit):
        seed.append_registry_blocks(p, text, seed.registry_blocks(["timescale"], existing=set()))
    assert p.read_text(encoding="utf-8") == text
