# -*- coding: utf-8 -*-
"""WB-07: a storage key naming a registry database takes the nature that database declares."""

from unittest.mock import patch

import pytest

from orchestrator.services import provenance as pv

pytestmark = pytest.mark.unit

CONFIG = {"databases": {"wide": {"type": "mysql", "nature": "real"},
                        "demo": {"type": "mysql_narrow", "nature": "synthetic", "label": "Demo table"},
                        "silent": {"type": "mysql"}}}


def _tags(key):
    with patch("orchestrator.services.adapters.registry.adapter_registry._load_yaml_config",
               return_value=CONFIG):
        return pv.build_tags([f"store:{key}"], registry=None)


def test_a_real_database_is_live_sensor_data():
    assert _tags("wide")[0].label == "Live Sensor Data" and not _tags("wide")[0].synthetic


def test_a_synthetic_database_is_labelled_simulated():
    tag = _tags("demo")[0]
    assert tag.synthetic and tag.label == "Demo table"


def test_undeclared_nature_is_still_unknown():
    assert _tags("silent")[0].label == "Unknown Source"
    assert _tags("absent")[0].label == "Unknown Source"
