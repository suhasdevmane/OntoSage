# -*- coding: utf-8 -*-
"""One thing, one name (2026-08-27).

The disease this catches, in the forms bldg1 actually had it:

* ``CO2_Level_Sensor5.01`` beside ``CO2_Level_Sensor_5.01`` -- 4 triples against
  242. The short one carried no label and no timeseries reference, so a count of
  the CO2 class was inflated and half the identities could answer nothing.
* ``oxygen_level_gas_sensor_5.01`` beside ``Oxygen_O2_Percentage_Gas_Sensor_5.01``.
* Fourteen AHU individuals for six physical air handlers, under three spellings
  (BUG-249).

The rebuild removed all of them. This stops them coming back.

**It is not a house-style checker, deliberately.** Brick places no requirement on
an instance's local name -- rdf:type carries the class, and `AHU_F0` is a better
name for a human than `Air_Handling_Unit_F0`. Measured on bldg1: 2,058 of 2,857
typed instances have names that do not start with their class term, and nearly all
of them are good names. Renaming those would touch thousands of IRIs, every
timeseries link and every floor-plan binding, and would fix nothing that produces
a wrong answer. What is worth forbidding is the same identity spelled two ways.
"""

from pathlib import Path

import pytest

from orchestrator.services.input_validators import (
    validate_building_input,
    validate_identity_collisions,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


#: Every real building file binds this, and the check requires it: scoping to the
#: building's own namespace is what keeps vocabulary out of the comparison.
_PREFIX = "@prefix bldg: <http://example.org/bldg#> .\n"


def _ttl(d: Path, name: str, body: str) -> None:
    (d / name).write_text(_PREFIX + body, encoding="utf-8")


# -- the collisions bldg1 actually had ---------------------------------------
def test_a_missing_underscore_is_caught(tmp_path):
    _ttl(
        tmp_path,
        "a.ttl",
        "bldg:CO2_Level_Sensor_5.01 a brick:CO2_Level_Sensor .\n"
        "bldg:CO2_Level_Sensor5.01 a brick:CO2_Level_Sensor .\n",
    )
    ok, issues = validate_identity_collisions(tmp_path)
    assert not ok
    assert any("CO2_Level_Sensor5.01" in i for i in issues), issues


def test_a_case_difference_is_caught(tmp_path):
    _ttl(tmp_path, "a.ttl", "bldg:AHU_F5 a brick:AHU .\nbldg:ahu_f5 a brick:AHU .\n")
    assert validate_identity_collisions(tmp_path)[0] is False


def test_a_hyphen_against_an_underscore_is_caught(tmp_path):
    """AHU-F5 and AHU_F5 were two identities for one air handler."""
    _ttl(tmp_path, "a.ttl", "bldg:AHU_F5 a brick:AHU .\nbldg:AHU-F5 a brick:AHU .\n")
    assert validate_identity_collisions(tmp_path)[0] is False


def test_a_collision_across_two_files_is_caught(tmp_path):
    """Buildings split declarations across files; the collision usually spans them."""
    _ttl(tmp_path, "a.ttl", "bldg:Room_5.01 a brick:Room .\n")
    _ttl(tmp_path, "b.ttl", "bldg:Room5.01 a brick:Room .\n")
    assert validate_identity_collisions(tmp_path)[0] is False


# -- and the names it must leave alone ---------------------------------------
def test_genuinely_different_names_are_fine(tmp_path):
    _ttl(
        tmp_path,
        "a.ttl",
        "bldg:AHU_F5 a brick:AHU .\nbldg:AHU_F4 a brick:AHU .\n"
        "bldg:Room_5.01 a brick:Room .\nbldg:Room_5.02 a brick:Room .\n",
    )
    assert validate_identity_collisions(tmp_path) == (True, [])


def test_an_abbreviation_is_not_a_defect(tmp_path):
    """AHU_F0 for an Air_Handling_Unit is a good name. Brick requires nothing of
    an instance's local name; rdf:type carries the class."""
    _ttl(
        tmp_path,
        "a.ttl",
        "bldg:AHU_F0 a brick:Air_Handling_Unit .\n"
        "bldg:AED_Floor3 a brick:Automated_External_Defibrillator .\n",
    )
    assert validate_identity_collisions(tmp_path) == (True, [])


def test_vocabulary_terms_are_not_compared(tmp_path):
    """A CLASS and a PROPERTY differing only by initial case is a normal RDF
    convention, not one thing named twice. A first pass compared every prefix and
    reported eight such "collisions" per building — Geometry/geometry,
    Region/region, ValueShape/valueShape — which would have made this a check
    nobody reads."""
    _ttl(
        tmp_path,
        "a.ttl",
        "brick:Room a owl:Class .\nbrick:room a owl:Class .\n"
        "rec:Geometry a owl:Class .\nrec:geometry a owl:ObjectProperty .\n",
    )
    assert validate_identity_collisions(tmp_path) == (True, [])


def test_a_missing_directory_is_not_an_error():
    assert validate_identity_collisions(_REPO / "no_such_building") == (True, [])


# -- every shipped building is clean, and stays clean ------------------------
@pytest.mark.parametrize("building", ["bldg1", "bldg2", "bldg3"])
def test_shipped_buildings_have_one_name_per_identity(building):
    d = _REPO / building
    if not d.is_dir():
        pytest.skip(f"{building} is not present in this checkout")
    ok, issues = validate_identity_collisions(d)
    assert ok, "\n".join(issues)


def test_the_check_runs_as_part_of_building_validation():
    root = _REPO / "input" if (_REPO / "input" / "building.yaml").is_file() else _REPO
    ok, report = validate_building_input("bldg1", root)
    assert "identity collisions" in report["files"], sorted(report["files"])
