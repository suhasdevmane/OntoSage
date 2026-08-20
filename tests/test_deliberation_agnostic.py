# -*- coding: utf-8 -*-
"""V4-T32: building-agnosticism certification — source scan (C3).

The deliberation package scan lives in test_coverage_audit.py; this extends the
same guarantee to every V4 SATURATE/benchmark SCRIPT: the pipeline that
saturated three different buildings did it with zero building literals in code.
Identity always comes from the active building (input/env.building, .env,
building.yaml) — never from source.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]

# every script the V4 saturation + benchmark pipeline executes
_V4_SCRIPTS = [
    "audit_coverage.py",
    "saturate_building.py",
    "backfill_saturation.py",
    "generate_amenity_locations.py",
    "generate_l7_bank.py",
    "l7_grader.py",
    "ablation_llm_ranked.py",
    "ablation_agent_loop.py",
    # V5 scripts
    "generate_access_policies.py",
]

_BANNED = re.compile(r"abacws|cardiff|bldg[123]\b|buildsys\.org", re.IGNORECASE)


def test_no_building_literals_in_v4_scripts():
    for name in _V4_SCRIPTS:
        py = _REPO / "scripts" / name
        assert py.exists(), f"expected V4 script missing: scripts/{name}"
        hits = [m.group(0) for m in _BANNED.finditer(py.read_text(encoding="utf-8"))]
        assert not hits, f"building literal(s) {hits} in scripts/{name}"


def test_saturation_modalities_config_is_building_neutral():
    cfg = _REPO / "config" / "saturation_modalities.yaml"
    assert cfg.exists()
    hits = [m.group(0) for m in _BANNED.finditer(cfg.read_text(encoding="utf-8"))]
    assert not hits, f"building literal(s) {hits} in config/saturation_modalities.yaml"
