# -*- coding: utf-8 -*-
"""W1-05 — "which rooms have NO temperature sensor" is answered from the coverage matrix.

Measured live 2026-09-23 BEFORE this lane existed. Three phrasings, three wrong answers, and
the first is the one that matters:

    "Which rooms have no temperature sensor?"
    -> "All of the rooms that are recorded in the building model have at least one temperature
        sensor. The query shows a sensor count for every room (e.g., Room0.01 has 15 sensors...)"

The query behind that narration returned a TOTAL sensor count per room. It cannot distinguish a
temperature sensor from a door contact, so the conclusion does not follow from the evidence at
any strength -- and it was stated without hedging, alongside a fabricated "Total spaces
recorded: 100" for a building with 234.

The set difference was never the hard part. `deliberation/coverage_audit.py` has answered
exactly this since V4 and nothing asked it.
"""

from __future__ import annotations

import pytest

from orchestrator.services import coverage_gap as gap

pytestmark = pytest.mark.unit

#: A building's declared modalities. Nothing in the module may depend on these particular names.
MODALITIES = ("temperature", "co2", "noise", "humidity", "occupancy", "illuminance", "water_flow")


class _Space:
    """The shape `CoverageAuditor.audit` returns, with only what this module reads."""

    def __init__(self, label, statuses):
        self.label = label
        self.modalities = {m: {"status": s} for m, s in statuses.items()}


# ── detection: the shape, and everything that merely resembles it ────────────────────


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Which rooms have no temperature sensor?", "temperature"),
        ("Which spaces have no CO2 sensor?", "co2"),
        ("Are there any rooms without a noise sensor?", "noise"),
        ("which offices lack humidity sensors", "humidity"),
        ("which rooms are missing occupancy monitoring", "occupancy"),
        ("what zones have no illuminance sensors fitted", "illuminance"),
    ],
)
def test_the_gap_question_is_recognised_in_the_ways_people_write_it(question, expected):
    assert gap.detect(question, MODALITIES) == expected


@pytest.mark.parametrize(
    "question",
    [
        "which rooms have a temperature sensor",  # the positive question
        "which rooms have no people in them",  # occupancy READING, not instrumentation
        "which rooms are not too warm",  # comfort, not coverage
        "no parking today",  # no space noun
        "which rooms have no radiation sensor",  # a quantity this building does not declare
        "how many temperature sensors are there",  # a count, not a gap
    ],
)
def test_a_question_that_only_resembles_the_shape_is_left_alone(question):
    """Returning None hands the question back to the lane exactly as it was.

    The radiation case is the one worth stating: a quantity the building does not declare must
    stay unresolved so the honest "not measured" decline still fires, rather than being answered
    "every room lacks it" -- which is true and useless and reads as a fault.
    """
    assert gap.detect(question, MODALITIES) is None


def test_the_longest_modality_name_wins():
    """A building declaring both `water_flow` and `water_flow_hot` must not answer the wrong one."""
    mods = ("water_flow", "water_flow_hot")
    assert gap.detect("which rooms have no water flow hot sensor", mods) == "water_flow_hot"


def test_nothing_is_recognised_for_a_building_that_declares_nothing():
    assert gap.detect("which rooms have no temperature sensor", ()) is None


# ── the fold: three states, never two ────────────────────────────────────────────────


def test_missing_unbacked_and_present_are_counted_apart():
    """"No sensor" and "a sensor that reports nothing" are different facts.

    Merging them would send somebody to install hardware that is already fitted -- the
    four-kinds-of-nothing distinction this project keeps everywhere else.
    """
    spaces = [
        _Space("Room 1.01", {"temperature": "present"}),
        _Space("Room 1.02", {"temperature": "missing"}),
        _Space("Room 1.03", {"temperature": "unbacked"}),
        _Space("Room 1.04", {"temperature": "missing"}),
    ]
    got = gap.summarise(spaces, "temperature")
    assert (got.present, got.missing, got.unbacked, got.total) == (1, 2, 1, 4)
    assert got.missing_labels == ["Room 1.02", "Room 1.04"]
    assert got.unbacked_labels == ["Room 1.03"]


def test_a_space_the_audit_never_judged_is_not_counted_as_a_gap():
    """Absence of a judgement is not evidence of absence.

    Counting an unaudited space as missing would report a gap nobody measured, which is the
    fabrication this whole lane exists to remove.
    """
    spaces = [_Space("Room 1.01", {"temperature": "present"}), _Space("Plant Room", {})]
    got = gap.summarise(spaces, "temperature")
    assert got.total == 1 and got.missing == 0


# ── the rendering: every number from the matrix ──────────────────────────────────────


def test_a_gap_is_reported_with_its_count_its_population_and_the_names():
    spaces = [_Space("Room 1.02", {"co2": "missing"})] + [
        _Space(f"Room 2.{i:02d}", {"co2": "present"}) for i in range(9)
    ]
    text = gap.render(gap.summarise(spaces, "co2"))
    assert "1 of 10 spaces have no co2 sensor" in text
    assert "9 have one that reports readings" in text
    assert "Room 1.02" in text
    assert "`co2`" in text, "the answer must say which coverage it tested"


def test_no_gap_is_stated_as_a_positive_finding_not_as_silence():
    spaces = [_Space(f"Room {i}", {"temperature": "present"}) for i in range(234)]
    text = gap.render(gap.summarise(spaces, "temperature"))
    assert "234 spaces" in text and "temperature sensor" in text
    assert "None is missing one" in text


def test_a_fitted_but_silent_sensor_is_named_as_a_different_problem():
    spaces = [
        _Space("Room 1.01", {"noise": "present"}),
        _Space("Room 1.02", {"noise": "unbacked"}),
    ]
    text = gap.render(gap.summarise(spaces, "noise"))
    assert "Room 1.02" in text
    assert "fitted but not reporting" in text
    assert "different problem" in text


def test_an_unaudited_quantity_says_so_rather_than_reporting_a_clean_sheet():
    """total == 0 must never render as "every space has one"."""
    text = gap.render(gap.summarise([], "temperature"))
    assert "no coverage record" in text
    assert "Every one" not in text


def test_a_long_gap_list_is_capped_and_says_how_many_more():
    spaces = [_Space(f"Room {i:03d}", {"co2": "missing"}) for i in range(40)]
    text = gap.render(gap.summarise(spaces, "co2"))
    assert "40 of 40" in text
    assert "and 28 more" in text, "a reader cannot use 40 room names; the count is the answer"


# ── the module may not know anything about a building ────────────────────────────────


def test_the_module_names_no_building_no_space_and_no_class():
    """The EXECUTABLE source only.

    The prose names `brick:hasLocation` on purpose -- that is the explanation of which idioms
    the audit already covers, and a guard that forbade explaining itself would be paid for in
    the next maintainer's hour. A literal in the LOGIC is what would break the next building.
    """
    import ast
    from pathlib import Path

    src = Path("orchestrator/services/coverage_gap.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree))
    for literal in ("bldg1", "bldg2", "abacws", "brick:", "cardiff", "temperature_sensor"):
        assert literal.lower() not in code.lower(), literal


def test_the_answer_never_claims_the_building_lacks_the_quantity():
    """It must survive the absence guard, which exists to catch exactly that claim.

    A scoped, counted absence is a statement about part of the building. Before the guard was
    made sentence-scoped it replaced this correct answer with a building-wide correction.
    """
    from orchestrator.services.absence_guard import detect_absence_claim

    spaces = [_Space("Room 1.02", {"noise": "missing"})] + [
        _Space(f"Room 2.{i:02d}", {"noise": "present"}) for i in range(233)
    ]
    text = gap.render(gap.summarise(spaces, "noise"))
    assert detect_absence_claim(text) is None, text[:200]
