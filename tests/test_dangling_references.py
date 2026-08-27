# -*- coding: utf-8 -*-
"""Nothing may point at a thing the building never declared (BUG-249, 2026-08-27).

bldg1 declared fourteen ``brick:AHU`` instances for six physical air handlers,
under three naming schemes. Investigating it turned up something worse than
duplication:

* ``AHU_Floor0``–``AHU_Floor5`` were **never declared anywhere**.
  ``provision_plant_points.py`` wrote thirty points with
  ``brick:isPointOf bldg:AHU_FloorN`` against subjects that exist in no TTL, and a
  reasoner typed those dangling references as equipment from the property's range.
  That is where the extra "instances" came from: the live graph looked complete
  while ``input/`` could not reproduce it.
* Seven ``VAV_Floor5_*`` had the same problem, with fourteen points under them —
  and because the provisioner takes a point's floor from its equipment, twelve of
  those points carried no location at all, making them invisible to the
  floor-scoped template. The phantom cascaded.
* ``equipment_linkage.ttl`` located two pumps at ``bldg:Building``; this building's
  building is ``bldg:AbacwsBuilding``.
* bldg2's chilled-water meter named ``bldg:chiller`` as what it measures. No
  chiller was declared.

None of this is visible in a live graph, because inference papers over exactly
this shape. It is visible in the source files, which is where the check runs.
"""

from pathlib import Path

import pytest

from orchestrator.services.input_validators import (
    _strip_turtle_comments,
    validate_building_input,
    validate_dangling_references,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]


def _ttl(d: Path, name: str, body: str) -> None:
    (d / name).write_text(body, encoding="utf-8")


# ── it fires on the shape that was actually shipped ──────────────────────────
def test_a_point_hanging_off_an_undeclared_subject_is_caught(tmp_path):
    _ttl(
        tmp_path,
        "points.ttl",
        "bldg:AHU_Floor5_Fan_Status a brick:Fan_Status ;\n"
        "    brick:isPointOf bldg:AHU_Floor5 .\n",
    )
    ok, issues = validate_dangling_references(tmp_path)
    assert not ok
    assert any("bldg:AHU_Floor5 " in i for i in issues), issues


def test_a_declared_subject_in_another_file_is_fine(tmp_path):
    """Buildings split declarations across files; only the SET must be closed."""
    _ttl(tmp_path, "points.ttl", "bldg:P a brick:Fan_Status ;\n    brick:isPointOf bldg:AHU_F5 .\n")
    _ttl(tmp_path, "equipment.ttl", "bldg:AHU_F5 a brick:Air_Handling_Unit .\n")
    assert validate_dangling_references(tmp_path) == (True, [])


def test_a_comma_list_is_checked_member_by_member(tmp_path):
    """`feeds A, B, C` hides a bad member behind two good ones."""
    _ttl(
        tmp_path,
        "e.ttl",
        "bldg:AHU a brick:AHU ;\n    brick:feeds bldg:Z1 , bldg:Z2 , bldg:Z_Missing .\n"
        "bldg:Z1 a brick:Zone .\nbldg:Z2 a brick:Zone .\n",
    )
    ok, issues = validate_dangling_references(tmp_path)
    assert not ok
    assert len(issues) == 1 and "Z_Missing" in issues[0]


def test_vocabulary_terms_are_not_reported(tmp_path):
    """brick:, ontosage: and friends are declared in files this scan skips; flagging
    them would bury every finding that means something."""
    _ttl(
        tmp_path,
        "e.ttl",
        "bldg:S a brick:Sensor ;\n    brick:hasLocation bldg:Floor5 ;\n"
        "    brick:isPointOf bldg:AHU .\nbldg:Floor5 a brick:Floor .\nbldg:AHU a brick:AHU .\n",
    )
    assert validate_dangling_references(tmp_path) == (True, [])


# ── and does not read prose as data ──────────────────────────────────────────
def test_a_name_inside_a_comment_is_not_a_reference(tmp_path):
    """The check's first run reported `bldg:VAV_Floor5_` — a name that exists
    nowhere, read out of a comment describing the very defect it was hunting
    (`bldg:VAV_Floor5_*`, truncated at the asterisk). A validator that manufactures
    findings is one nobody trusts."""
    _ttl(
        tmp_path,
        "e.ttl",
        "# points once said brick:isPointOf bldg:VAV_Floor5_* and nothing declared it\n"
        "bldg:S a brick:Sensor ;\n    brick:isPointOf bldg:AHU_F5 .\n"
        "bldg:AHU_F5 a brick:AHU .\n",
    )
    assert validate_dangling_references(tmp_path) == (True, [])


@pytest.mark.parametrize(
    "line,expected",
    [
        ("bldg:A a brick:B .  # a comment", "bldg:A a brick:B .  "),
        ("<http://x.org/ns#Thing> a brick:B .", "<http://x.org/ns#Thing> a brick:B ."),
        ('bldg:A rdfs:label "a # sign" .', 'bldg:A rdfs:label "a # sign" .'),
        ("# whole line", ""),
    ],
)
def test_the_hash_only_starts_a_comment_where_it_legally_can(line, expected):
    """A `#` inside an IRI or a quoted literal is not a comment; cutting there would
    silently truncate real triples."""
    assert _strip_turtle_comments(line) == expected


# ── every shipped building is closed, and stays closed ───────────────────────
@pytest.mark.parametrize("building", ["bldg1", "bldg2", "bldg3"])
def test_shipped_buildings_have_no_dangling_references(building):
    d = _REPO / building
    if not d.is_dir():
        pytest.skip(f"{building} is not present in this checkout")
    ok, issues = validate_dangling_references(d)
    assert ok, "\n".join(issues)


def test_a_missing_directory_is_not_an_error():
    assert validate_dangling_references(_REPO / "no_such_building") == (True, [])


def test_the_check_runs_as_part_of_building_validation():
    ok, report = validate_building_input("bldg1", _REPO)
    assert "entity references" in report["files"], sorted(report["files"])
    assert report["files"]["entity references"]["ok"], report["files"]["entity references"][
        "issues"
    ]


# ── the AHU merge itself ─────────────────────────────────────────────────────
def test_bldg1_declares_one_identity_per_air_handler():
    """Six physical units, six individuals, one naming scheme. Both AHU_FN and
    AHU_FloorN participated in brick:feeds, so an answer naming the equipment
    serving a space could list two air handlers where the building has one."""
    import re

    d = _REPO / "bldg1"
    if not d.is_dir():
        pytest.skip("bldg1 is not present in this checkout")
    names = set()
    for f in d.glob("*.ttl"):
        if f.name.lower().startswith("brick"):
            continue
        text = _strip_turtle_comments(f.read_text(encoding="utf-8", errors="replace"))
        names |= {
            m for m in re.findall(r"bldg:(AHU[_\-]?(?:F|Floor)?\d+)\b", text) if not m.endswith("_")
        }
    assert names == {"AHU_F0", "AHU_F1", "AHU_F2", "AHU_F3", "AHU_F4", "AHU_F5"}, sorted(names)


def test_every_plant_point_can_be_placed_on_a_floor():
    """The provisioner takes a point's floor from its equipment, so a phantom parent
    left twelve VAV points with no location — reachable only through equipment that
    did not exist, and invisible to the floor-scoped template that answers "on floor
    5" for every ordinary sensor."""
    rdflib = pytest.importorskip("rdflib")
    f = _REPO / "bldg1" / "bldg1_plant_points.ttl"
    if not f.is_file():
        pytest.skip("bldg1 plant points not present")
    brick = rdflib.Namespace("https://brickschema.org/schema/Brick#")
    g = rdflib.Graph()
    g.parse(str(f), format="turtle")
    points = {s for s, _p, _o in g.triples((None, brick.isPointOf, None))}
    unplaced = sorted(
        str(s).rsplit("#", 1)[-1] for s in points if g.value(s, brick.hasLocation) is None
    )
    assert unplaced == [], unplaced
