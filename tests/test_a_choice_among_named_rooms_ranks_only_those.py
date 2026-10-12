"""BUG-1492: a choice among rooms the question names ranks those rooms, over the period it names.

"Which of rooms 5.05 and 5.31 was warmer on 14 February 2025 between 10:00 and 12:00, and does
the warmer room have a recorded capacity of at least 10?" was ranked over 195 of 234 spaces, on
readings from the last three hours of 2026-10-10, and answered "Best match: Room 3.01".
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.deliberation import plan_executor as px
from orchestrator.services.deliberation.candidates import named_spaces
from orchestrator.services.deliberation.compiler import _fold_named_calendar_day
from orchestrator.services.deliberation.cqir import TimeBasis, TimeSpec

pytestmark = pytest.mark.unit

NS = "http://example.org/b#"
SPACES = [
    SimpleNamespace(space_iri=NS + "Room_5.05", label="Room 5.05 — Research Laboratory"),
    SimpleNamespace(space_iri=NS + "Room_5.31", label="Room 5.31 — Office"),
    SimpleNamespace(space_iri=NS + "Room_1.07", label="Room 1.07"),
    SimpleNamespace(space_iri=NS + "Lab_10", label="Lab 10"),
]


def test_two_named_rooms_are_the_candidates():
    q = "Which of rooms 5.05 and 5.31 was warmer on 14 February 2025 between 10:00 and 12:00?"
    assert named_spaces(q, SPACES) == ([NS + "Room_5.05", NS + "Room_5.31"], [])


def test_a_named_room_the_building_does_not_have_is_reported_not_dropped():
    q = "Which of Rooms 1.07, 1.44 and 1.45 is the quietest?"
    assert named_spaces(q, SPACES) == ([NS + "Room_1.07"], ["1.44", "1.45"])


def test_repeated_nouns_and_or_are_one_list():
    q = "Which had the lower CO2: Room 5.05 or Room 5.31?"
    assert named_spaces(q, SPACES) == ([NS + "Room_5.05", NS + "Room_5.31"], [])


@pytest.mark.parametrize(
    "question",
    [
        "Which is the coolest room to work in?",  # no names: the whole building
        "Is room 5.05 warm?",  # one name is the single-space anchor's job
        "Does room 5.05 and 10 people fit?",  # "10" is not shaped like "5.05"
    ],
)
def test_no_list_of_names_restricts_nothing(question):
    assert named_spaces(question, SPACES) == ([], [])


def test_an_identifier_matching_two_spaces_restricts_nothing():
    spaces = SPACES + [SimpleNamespace(space_iri=NS + "Annex_5.05", label="Annex 5.05")]
    assert named_spaces("rooms 5.05 and 5.31", spaces) == ([], [])


def test_the_compiler_takes_a_written_out_date_over_now():
    spec = TimeSpec(basis=TimeBasis.NOW)
    assert _fold_named_calendar_day(
        spec, "warmer on 14 February 2025 between 10:00 and 12:00", tz_name=None
    )
    assert spec.basis == TimeBasis.WINDOW
    assert (spec.resolved_start, spec.resolved_end) == (
        "2025-02-14 10:00:00",
        "2025-02-14 11:59:59",
    )


def test_the_compiler_leaves_a_future_date_and_a_forecast_alone():
    spec = TimeSpec(basis=TimeBasis.NOW)
    assert not _fold_named_calendar_day(spec, "will it be warm on 20 December 2099?", tz_name=None)
    assert spec.basis == TimeBasis.NOW and spec.resolved_start is None
    fc = TimeSpec(basis=TimeBasis.FORECAST)
    assert not _fold_named_calendar_day(fc, "on 14 February 2025", tz_name=None)


def test_a_written_out_hour_is_read_whole_at_ten_second_cadence():
    hours, limit, rows = px.fetch_plan(TimeBasis.WINDOW, 1.0, 4, 1, resolved=True)
    assert limit == 360 and rows == 1440
    # a duration window is unchanged (pinned elsewhere)
    assert px.fetch_plan(TimeBasis.WINDOW, 1.0, 4, 1)[1] == 60


def test_a_resolved_interval_too_wide_for_the_budget_falls_back():
    assert px.fetch_plan(TimeBasis.WINDOW, 24.0, 234, 4, resolved=True) == px.fetch_plan(
        TimeBasis.WINDOW, 24.0, 234, 4
    )


# BUG-1494 / BUG-1495: the compile of such a question, when the model's reply is imperfect.


def test_a_compile_reply_cut_after_its_last_value_is_closed_not_refused():
    from orchestrator.services.deliberation.compiler import _close_cut_json

    cut = '{"decision":"select_one","constraints":[{"modality":"temperature"}],"unmapped":[],"inspect":[]'
    assert _close_cut_json(cut)["constraints"] == [{"modality": "temperature"}]


@pytest.mark.parametrize("cut", ['{"a":"cut inside a str', '{"a":', '{"a":1}}', "no json at all"])
def test_a_reply_cut_mid_value_is_still_refused(cut):
    from orchestrator.services.deliberation.compiler import _close_cut_json

    assert _close_cut_json(cut) is None


def test_an_unmapped_clause_borrows_the_questions_own_direction_for_its_quantity():
    from orchestrator.services.deliberation import compiler as c
    from orchestrator.services.deliberation.cqir import DecisionKind, Direction

    known = {"temperature", "occupancy", "co2"}
    q = "Which of rooms 2.10 and 2.11 was warmer on 4 March 2025 between 09:00 and 11:00?"
    got = c._constraint_from_phrase(
        "temperature between 09:00 and 11:00", known, DecisionKind.SELECT_ONE, q
    )
    assert got is not None and (got.modality, got.direction) == ("temperature", Direction.MAXIMIZE)
    # a negated or two-ended question lends no direction
    assert c._polarity_elsewhere("which room is not warmer", "temperature") is None
    assert c._polarity_elsewhere("warm but not too hot or cold", "temperature") is None


def test_a_mapped_quantity_with_no_direction_takes_the_questions_polarity_word():
    """The live reply: modality temperature, direction "none", phrase without the word "warmer"."""
    from orchestrator.services.deliberation import compiler as c

    raw = (
        '{"decision":"select_one","constraints":[{"phrase":"temperature between 09:00 and 11:00",'
        '"modality":"temperature","direction":"none","hardness":"soft","threshold":null}],'
        '"spatial":[],"time":{"basis":"window","window_hours":2},"unmapped":[]}'
    )
    q = "Which of rooms 2.10 and 2.11 was warmer on 4 March 2025 between 09:00 and 11:00?"
    cq = c._parse_compiled(raw, q, {"temperature", "co2"})
    assert [(x.modality, x.direction.value) for x in cq.constraints] == [
        ("temperature", "maximize")
    ]
    assert not cq.signals


def _dossier(direction, values, hardness="soft"):
    from orchestrator.services.deliberation.dossier import (
        DossierConstraint,
        DossierEvidenceRow,
        DossierRanked,
        EvidenceDossier,
    )

    return EvidenceDossier(
        building_id="bx",
        raw_query="q",
        decision="select_one",
        constraints=[
            DossierConstraint(modality="temperature", direction=direction, hardness=hardness)
        ],
        evidence=[
            DossierEvidenceRow(
                space=s,
                modality="temperature",
                value=v,
                basis="mean over 2025-03-04 09:00-11:00",
                window_hours=2,
                n_points=700,
                sensor_uuid="u",
                stored_at="db",
            )
            for s, v in values
        ],
        ranked=[
            DossierRanked(rank=i, space=s, floor="F2", total=1.0, criteria={"temperature": v})
            for i, (s, v) in enumerate(values, 1)
        ],
    )


def test_a_band_tie_broken_by_the_readings_names_the_room_that_read_higher():
    from orchestrator.services.deliberation.dossier import _raw_leader

    lead = _raw_leader(_dossier("maximize", [("Room 2.10", 29.9), ("Room 2.11", 28.9)]))
    assert lead.startswith(
        "**Room 2.10 read the higher temperature: 29.9, against 28.9 for Room 2.11**"
    )
    assert "mean over 2025-03-04 09:00-11:00" in lead


@pytest.mark.parametrize(
    "direction, values",
    [
        (
            "above",
            [("Room 2.10", 29.9), ("Room 2.11", 28.9)],
        ),  # an unbounded filter stays a tie (BUG-868)
        ("maximize", [("Room 2.10", 28.9), ("Room 2.11", 28.9)]),  # equal readings: no leader
        ("maximize", [("Room 2.10", 28.0), ("Room 2.11", 28.9)]),  # order disagrees: claim nothing
    ],
)
def test_no_raw_leader_when_the_readings_do_not_decide(direction, values):
    from orchestrator.services.deliberation.dossier import _raw_leader

    assert _raw_leader(_dossier(direction, values)) == ""


def test_function_words_name_no_quantity_and_at_least_is_not_an_avoidance():
    from orchestrator.services.deliberation import compiler as c

    assert c._modality_from_lay_term("of") is None and c._modality_from_lay_term("on") is None
    assert not c._AVOIDANCE_RE.search("a recorded capacity of at least 10")
    assert not c._AVOIDANCE_RE.search("temperature less than 25 degrees")
    assert c._AVOIDANCE_RE.search("the least noisy room") and c._AVOIDANCE_RE.search("less stuffy")
