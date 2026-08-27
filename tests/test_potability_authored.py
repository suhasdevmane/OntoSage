# -*- coding: utf-8 -*-
"""bldg1's potability statement, and the check that it is complete (2026-08-27).

The reader landed first and the claim deliberately did not: bldg1 is a real
building, and a synthetic "the water is safe to drink" claim about one is the harm
Module P guards against. The building's owner has now supplied the two facts the
schema requires -- potable since the building opened on 2020-01-01, published by
Cardiff University Estates -- so the statement is authored.

The validator here is the general half. A drinkability claim missing its authority
or its date is not a weaker claim, it is one nobody can check, and it must not
reach a building unchallenged.
"""

from pathlib import Path

import pytest

from orchestrator.services.capability_graph_resolver import CapabilityFact
from orchestrator.services.input_validators import (
    validate_building_input,
    validate_potability_statements,
)

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_STATEMENT = _REPO / "bldg1" / "bldg1_potability.ttl"


def _ttl(d: Path, body: str) -> Path:
    p = d / "x.ttl"
    p.write_text(body, encoding="utf-8")
    return d


_COMPLETE = """@prefix ontosage: <http://ontosage.org/capabilities#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
bldg:P a ontosage:PotabilityStatement ;
    ontosage:potabilityValue "potable" ;
    ontosage:potabilityAuthority "Estates" ;
    ontosage:potabilityIssuedOn "2020-01-01"^^xsd:date .
"""


# ── the general check ────────────────────────────────────────────────────────
def test_a_complete_statement_passes(tmp_path):
    assert validate_potability_statements(_ttl(tmp_path, _COMPLETE)) == (True, [])


@pytest.mark.parametrize(
    "drop,expected",
    [
        ("ontosage:potabilityAuthority", "issuing authority"),
        ("ontosage:potabilityIssuedOn", "date it was issued"),
        ("ontosage:potabilityValue", "value"),
    ],
)
def test_a_statement_missing_a_required_term_is_refused(tmp_path, drop, expected):
    body = "\n".join(ln for ln in _COMPLETE.splitlines() if drop not in ln)
    # keep the block terminated after dropping a line
    body = body.replace(
        " ;\n    ontosage:potabilityIssuedOn", " ;\n    ontosage:potabilityIssuedOn"
    )
    if not body.rstrip().endswith("."):
        body = body.rstrip().rstrip(";") + " ."
    ok, issues = validate_potability_statements(_ttl(tmp_path, body))
    assert not ok
    assert any(expected in i for i in issues), issues


def test_an_unrecognised_value_is_refused(tmp_path):
    """ "probably fine" is not one of the three things this vocabulary can mean."""
    body = _COMPLETE.replace('"potable"', '"probably fine"')
    ok, issues = validate_potability_statements(_ttl(tmp_path, body))
    assert not ok
    assert any("probably fine" in i for i in issues), issues


def test_a_building_with_no_statements_passes(tmp_path):
    _ttl(tmp_path, "@prefix x: <http://e/> .\nx:A a x:B .\n")
    assert validate_potability_statements(tmp_path) == (True, [])


def test_a_statement_named_only_in_a_comment_is_not_checked(tmp_path):
    body = "# bldg:P a ontosage:PotabilityStatement would need an authority\n"
    assert validate_potability_statements(_ttl(tmp_path, body)) == (True, [])


# ── bldg1's actual statement ─────────────────────────────────────────────────
def test_bldg1_statement_is_complete_and_attributed():
    if not _STATEMENT.is_file():
        pytest.skip("bldg1 potability statement not present")
    ok, issues = validate_potability_statements(_REPO / "bldg1")
    assert ok, "\n".join(issues)
    text = _STATEMENT.read_text(encoding="utf-8")
    assert "Cardiff University Estates" in text
    assert "2020-01-01" in text
    assert '"potable"' in text


def test_the_statement_is_not_flagged_as_simulated():
    """It is a real claim by a real authority. Marking it simulated would make the
    building's own published statement read as demo data.

    Reads the TRIPLES, not the prose: the file's own comment explains that it
    carries no isSimulated flag, and a first pass at this test failed on that
    sentence — the same "validator reading a comment as data" mistake the dangling
    reference check made an hour earlier.
    """
    from orchestrator.services.input_validators import _strip_turtle_comments

    if not _STATEMENT.is_file():
        pytest.skip("bldg1 potability statement not present")
    triples = _strip_turtle_comments(_STATEMENT.read_text(encoding="utf-8"))
    assert "isSimulated" not in triples


def test_it_covers_both_refill_points_on_every_floor():
    """Twelve outlets: two per floor across six floors. A statement scoped to half
    of them would leave the other half unanswered."""
    if not _STATEMENT.is_file():
        pytest.skip("bldg1 potability statement not present")
    text = _STATEMENT.read_text(encoding="utf-8")
    for floor in range(6):
        assert f"Amenity_DrinkingWater_Floor{floor} " in text or f"Floor{floor}," in text
        assert f"Amenity_DrinkingWater_Floor{floor}_b" in text


def test_the_answer_reads_with_its_owner_and_date():
    """The whole point of Module P: the claim never appears without who published it."""
    out = CapabilityFact(
        label="Drinking water quality",
        answer="Water from the building's drinking-water points is safe to drink.",
        potability="potable",
        potability_authority="Cardiff University Estates",
        potability_issued_on="2020-01-01",
    ).render()
    assert "safe to drink" in out
    assert "Cardiff University Estates" in out and "2020-01-01" in out


def test_the_check_runs_as_part_of_building_validation():
    ok, report = validate_building_input("bldg1", _REPO)
    assert "potability claims" in report["files"], sorted(report["files"])
    assert report["files"]["potability claims"]["ok"], report["files"]["potability claims"][
        "issues"
    ]
