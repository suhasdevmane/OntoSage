# -*- coding: utf-8 -*-
"""A relation whose object nothing declares is a silent hole (V10 W1-2, BUG-438).

WHAT THIS GENERALISES
---------------------
`validate_dangling_references` has caught `brick:isPointOf` pointing at a phantom AHU since
BUG-249. It could not catch `ontosage:statusOf` pointing at a phantom lift, because the
predicate list was `brick:` only.

So 14 of bldg1's 64 asset statuses named an IRI with zero triples -- the reception, the
cafe, the makerspace, the prayer room, the showers, the lift -- and every one answered
*"not recorded in this building's model"* about a thing the building has. The validator was
working exactly as written and had nothing to say, which is the least useful kind of
passing check.

THE SECOND DEFECT, FOUND BY FIXING THE FIRST
--------------------------------------------
Extending the predicate list immediately reported 19 amenities across three buildings as
declared nowhere. They were declared -- as FULL IRIs:

    <http://.../abacws#Amenity_StudyArea_Floor0>
        a ontosage:Amenity , ontosage:StudyArea ;

and the declaration matcher only recognised prefixed names. With the check limited to
`brick:` that gap had never shown. A validator that cries wolf is one people switch off,
and it would have taken the real findings with it -- so the matcher now reads both
notations and compares on local names.

These tests PLANT the defect in a fixture rather than asserting the current tree is clean.
A check that passes everywhere may simply be broken, and that is exactly what the original
was.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.input_validators import (  # noqa: E402
    _ONTOSAGE_REFERENCE_PREDICATES,
    validate_dangling_references,
)

_PREAMBLE = (
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
    "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
    "@prefix bldg: <http://example.org/b#> .\n\n"
)


def _building(tmp_path: Path, **files: str) -> Path:
    d = tmp_path / "b"
    d.mkdir()
    for name, body in files.items():
        (d / f"{name}.ttl").write_text(_PREAMBLE + body, encoding="utf-8")
    return d


# ── the defect this exists to catch ──────────────────────────────────────────


def test_a_status_pointing_at_an_undeclared_asset_is_reported(tmp_path):
    """The lift, in miniature."""
    d = _building(
        tmp_path,
        status='bldg:status_lift_0 a ontosage:AssetStatus ;\n'
        '    ontosage:statusOf bldg:Lift_Main ;\n'
        '    ontosage:statusValue "operational" .\n',
    )
    ok, issues = validate_dangling_references(d)
    assert not ok
    assert any("Lift_Main" in i for i in issues), issues


def test_the_same_status_passes_once_the_asset_is_declared(tmp_path):
    d = _building(
        tmp_path,
        assets="bldg:Lift_Main a ontosage:Lift ;\n" '    rdfs:label "Main lift"@en .\n',
        status='bldg:status_lift_0 a ontosage:AssetStatus ;\n'
        '    ontosage:statusOf bldg:Lift_Main ;\n'
        '    ontosage:statusValue "operational" .\n',
    )
    ok, issues = validate_dangling_references(d)
    assert ok, issues


def test_a_declaration_written_as_a_full_iri_counts(tmp_path):
    """The false-positive class. 19 real amenities were reported as phantoms."""
    d = _building(
        tmp_path,
        catalogue="<http://example.org/b#Amenity_StudyArea_Floor0>\n"
        "    a ontosage:Amenity ;\n"
        '    rdfs:label "Study area"@en .\n',
        status="bldg:amenity_status_0 a ontosage:AssetStatus ;\n"
        "    ontosage:statusOf bldg:Amenity_StudyArea_Floor0 ;\n"
        '    ontosage:statusValue "operational" .\n',
    )
    ok, issues = validate_dangling_references(d)
    assert ok, f"a full-IRI declaration was not recognised: {issues}"


def test_a_reference_written_as_a_full_iri_is_still_checked(tmp_path):
    """Symmetry: the notation must not decide whether a check runs."""
    d = _building(
        tmp_path,
        catalogue="bldg:Cafe_Ground a ontosage:Amenity .\n",
        status="bldg:amenity_status_1 a ontosage:AssetStatus ;\n"
        "    ontosage:locatedIn bldg:Cafe_Ground ;\n"
        '    ontosage:statusValue "operational" .\n',
    )
    ok, issues = validate_dangling_references(d)
    assert ok, issues


# ── coverage of the predicate list ───────────────────────────────────────────


@pytest.mark.parametrize("predicate", ["statusOf", "locatedIn", "servesSpace", "coversAsset"])
def test_each_building_entity_relation_is_checked(predicate, tmp_path):
    body = (
        "bldg:thing_0 a ontosage:AssetStatus ;\n"
        f"    ontosage:{predicate} bldg:Phantom ;\n"
        '    rdfs:label "x"@en .\n'
    )
    d = _building(tmp_path, subject=body)
    ok, issues = validate_dangling_references(d)
    assert not ok, f"ontosage:{predicate} pointing at nothing was not reported"
    assert any("Phantom" in i for i in issues)


def test_vocabulary_relations_are_deliberately_excluded():
    """`measuresQuantityKind` and `answeredBy` point at ONTOLOGY terms, declared in
    ontology/ rather than in a building's files. Checking them would report every correctly
    modelled building as broken, which is how a useful check becomes noise."""
    assert "measuresQuantityKind" not in _ONTOSAGE_REFERENCE_PREDICATES
    assert "answeredBy" not in _ONTOSAGE_REFERENCE_PREDICATES
    assert "statusOf" in _ONTOSAGE_REFERENCE_PREDICATES


def test_the_shipped_buildings_are_clean():
    """Asserted LAST, and only meaningful because every test above proves the check fires."""
    repo = Path(__file__).resolve().parent.parent
    # A BUILDING is a directory with a building.yaml. `bldg2_source/` and `bldg3_source/`
    # hold the original vendor exports, which the system never loads; a glob on `bldg*`
    # swept them in and reported a dangling `bldg:chiller` in a file no building uses. A
    # check that reports defects in data nobody loads is a check people learn to skip.
    dirs = [
        p
        for p in repo.glob("bldg*")
        if p.is_dir() and (p / "building.yaml").exists() and any(p.glob("*.ttl"))
    ]
    active = repo / "input"
    if (active / "building.yaml").exists() and any(active.glob("*.ttl")):
        dirs.append(active)
    assert dirs, "no building found; the discovery is wrong"
    for d in dirs:
        ok, issues = validate_dangling_references(d)
        assert ok, f"{d.name}: {issues[:6]}"
