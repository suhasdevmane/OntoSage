# -*- coding: utf-8 -*-
"""What a sensor class MEASURES, stated by us (CAVEAT-286, 2026-08-27).

Brick 1.4 asserts, at Brick_v1.4.ttl:31248:

    brick:TVOC_Sensor rdfs:subClassOf brick:Particulate_Matter_Sensor .

so every TVOC sensor is a particulate-matter sensor by inference -- 35 of them in
bldg1, beside 34 PM1, 34 PM10 and 35 PM2.5. "How many particulate matter sensors
does this building have?" counts a GAS measurement among the solids.

Brick is not simply wrong: its own definition of that class is "Detects pollutants
in the ambient air", and a VOC sensor belongs under that reading. The NAME is what
misleads.

Two fixes were considered and rejected, and the rejection is the interesting part:

* **Editing the vendored Brick file.** "We use Brick 1.4" has to stay true. A
  locally-patched copy makes the conformance claim false and the divergence
  invisible.
* **owl:disjointWith.** Declaring TVOC_Sensor disjoint from a class it is a
  subclass of makes it UNSATISFIABLE -- every TVOC sensor becomes a contradiction,
  which is a worse answer than the one being corrected.

So ontology/measurand_kinds.ttl states what each confusable class measures, in
OntoSage's own vocabulary, and nothing contradicts Brick. A count rolled up the
hierarchy then says what it swept in.
"""

import json
from pathlib import Path

import pytest

from orchestrator.services.measurand_kinds import (
    foreign_descendants,
    measurand_label,
    measurand_of,
    rollup_note,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


# -- the declarations ---------------------------------------------------------
@pytest.mark.parametrize(
    "cls,expected",
    [
        ("Particulate_Matter_Sensor", "ParticulateMatter"),
        ("PM2.5_Level_Sensor", "ParticulateMatter"),
        ("PM10_Level_Sensor", "ParticulateMatter"),
        ("TVOC_Sensor", "VolatileOrganicCompounds"),
        ("TVOC_Level_Sensor", "VolatileOrganicCompounds"),
        ("CO_Level_Sensor", "CarbonMonoxide"),
        ("CO2_Level_Sensor", "CarbonDioxide"),
        ("NO2_Level_Sensor", "NitrogenDioxide"),
    ],
)
def test_each_confusable_class_declares_what_it_measures(cls, expected):
    assert measurand_of(cls) == expected


def test_pm2_5_is_spelled_the_way_brick_spells_it():
    """An earlier hardcoded table said PM2_5_Level_Sensor with underscores while
    Brick spells it PM2.5_Level_Sensor with a dot, so that entry matched NOTHING and
    the particulate family was quietly half its intended size. Reading the
    declarations fixes it by construction."""
    assert measurand_of("PM2.5_Level_Sensor") == "ParticulateMatter"
    assert measurand_of("PM2_5_Level_Sensor") == ""


def test_an_undeclared_class_returns_nothing_rather_than_guessing():
    assert measurand_of("Temperature_Sensor") == ""
    assert measurand_of("") == ""


def test_the_gases_are_distinguishable_from_each_other():
    """QUDT stops at VolumeFraction, which cannot tell CO from NO2 -- and telling
    those apart is the half of CAVEAT-286 that was a real defect."""
    kinds = {
        measurand_of(c) for c in ("CO_Sensor", "CO2_Sensor", "NO2_Level_Sensor", "TVOC_Sensor")
    }
    assert len(kinds) == 4


# -- the derived roll-up ------------------------------------------------------
def test_the_particulate_class_is_known_to_sweep_in_tvoc():
    assert set(foreign_descendants("Particulate_Matter_Sensor")) == {
        "TVOC_Sensor",
        "TVOC_Level_Sensor",
    }


def test_a_class_with_no_foreign_descendants_reports_none():
    assert foreign_descendants("CO2_Level_Sensor") == ()
    assert foreign_descendants("Temperature_Sensor") == ()


def test_the_rollup_map_is_derived_not_hand_written():
    """A hand-maintained list drifts from the ontology it describes. Re-running the
    deriver after a Brick upgrade is how it stays true."""
    data = json.loads((_REPO / "config" / "measurand_rollups.json").read_text(encoding="utf-8"))
    assert "DERIVED by scripts/derive_measurand_rollups.py" in data["_comment"]
    assert "Brick_v1.4.ttl" in data["brick_source"]


def test_the_committed_rollup_matches_what_the_deriver_produces():
    """--check exists so a stale file is a test failure rather than a wrong answer."""
    import importlib.util

    path = _REPO / "scripts" / "derive_measurand_rollups.py"
    spec = importlib.util.spec_from_file_location("_derive_rollups", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fresh = mod.build()
    committed = json.loads(
        (_REPO / "config" / "measurand_rollups.json").read_text(encoding="utf-8")
    )
    assert fresh["rollups"] == committed["rollups"]


# -- the disclosure -----------------------------------------------------------
def test_the_note_names_the_classes_not_just_the_quantity():
    """ "Includes gases" tells a reader something is off and not what to do about it.
    Naming TVOC_Level_Sensor tells them which figure to subtract."""
    note = rollup_note("Particulate_Matter_Sensor")
    assert note is not None
    assert "TVOC_Level_Sensor" in note and "TVOC_Sensor" in note
    assert "volatile organic compounds" in note
    assert "particulate matter" in note


def test_a_clean_class_gets_no_note():
    assert rollup_note("CO2_Level_Sensor") is None
    assert rollup_note("Temperature_Sensor") is None
    assert rollup_note("") is None


def test_the_census_carries_the_note():
    from orchestrator.services.ontology_inventory import render_census

    out = render_census([("Particulate_Matter_Sensor", 378)], "Test Building")
    assert "TVOC" in out
    assert "broader than the name suggests" in out


def test_the_census_of_a_clean_class_is_unchanged():
    from orchestrator.services.ontology_inventory import render_census

    out = render_census([("Temperature_Sensor", 120)], "Test Building")
    assert "TVOC" not in out and "_Note" not in out


def test_a_label_is_available_for_every_declared_measurand():
    for kind in ("ParticulateMatter", "VolatileOrganicCompounds", "NitrogenDioxide"):
        assert measurand_label(kind) and measurand_label(kind) != kind


# -- and Brick is not fought --------------------------------------------------
def test_the_vendored_brick_file_still_asserts_the_subclass():
    """If someone "fixes" this by editing Brick, the conformance claim silently
    becomes false. This test is here to make that edit visible."""
    for candidate in ("bldg1", "bldg2", "bldg3", "input"):
        p = _REPO / candidate / "Brick_v1.4.ttl"
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            assert "rdfs:subClassOf brick:Particulate_Matter_Sensor" in text
            return
    pytest.skip("no vendored Brick TBox in this checkout")


def test_no_disjointness_is_asserted_against_a_superclass():
    """owl:disjointWith between TVOC_Sensor and Particulate_Matter_Sensor would make
    TVOC_Sensor unsatisfiable -- every TVOC sensor a contradiction."""
    text = (_REPO / "ontology" / "measurand_kinds.ttl").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "disjointWith" not in body
