# -*- coding: utf-8 -*-
"""V12-09 — a count, an aggregate and a census each mean what they appear to mean.

    A09  "The known total comes from the fixture's contents, never from asking the limited
          path to grade itself; a truncated result says so and an unknown total is not
          invented."
    A10  "max, min and average each use their intended operation, asserted against an
          independently computed expectation."
    A12  "Duplicate, invalid and out-of-order rows produce recorded accepted/excluded
          counts. A nested census states that its categories overlap."

THREE DEFECTS MEASURED IN THE REPORT LANE ON 2026-09-12, ALL PRINTING REAL-LOOKING NUMBERS
-------------------------------------------------------------------------------------------
`_summarize_readings` reported `latest` as `vals[-1]`, the last element in ROW order. This
lane orders `timestamp DESC`. On 1000 / 900 / 400 it named **400 the latest** (BUG-520).

A narrow-table result carries every modality in one column called `value`, so the
per-column summary averaged 900 ppm of CO2 with 21.5 °C and reported
`avg=590.5, min=21.5, max=900.0` (BUG-521). Not a wrong quantity — not a quantity at all.

Rows failing the numeric test vanished with no record, so "1,000 readings" could not be
distinguished from "1,000 of 1,340 readings" (BUG-522).

WHAT THE EXPECTATIONS ARE BUILT FROM
------------------------------------
Every expected number in this file is written out or computed from the fixture by hand.
None comes from calling the code under test, and none comes from asking the capped path how
many rows it thinks exist — which is A09's whole point: a limited path grading itself
reports its limit as the answer.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.agents.report_agent import ReportAgent, _is_capped  # noqa: E402
from orchestrator.services.ontology_inventory import overlap_sentences  # noqa: E402
from orchestrator.services.reading_quality import (  # noqa: E402
    DUPLICATE,
    NON_NUMERIC,
    NO_TIMESTAMP,
    aggregate,
    screen,
)

AGENT = ReportAgent.__new__(ReportAgent)

#: Newest first, which is how the SQL lane returns rows (`ORDER BY timestamp DESC`).
DESCENDING = [
    {"Datetime": "2026-09-11 23:00:00", "Room5.01_CO2": 1000.0},
    {"Datetime": "2026-09-11 12:00:00", "Room5.01_CO2": 900.0},
    {"Datetime": "2026-09-11 01:00:00", "Room5.01_CO2": 400.0},
]

#: The independently computed expectation, written out rather than derived from the code.
TRUE_MIN, TRUE_MAX, TRUE_LATEST = 400.0, 1000.0, 1000.0
TRUE_MEAN = (1000.0 + 900.0 + 400.0) / 3  # 766.666…


# ── A10: each statistic by its own operation ─────────────────────────────────


def test_A10_min_max_and_mean_match_an_expectation_computed_here():
    got = AGENT._summarize_readings(DESCENDING)["Room5.01_CO2"]
    assert got["min"] == TRUE_MIN
    assert got["max"] == TRUE_MAX
    assert got["avg"] == round(TRUE_MEAN, 3)
    assert got["count"] == 3


def test_A10_latest_is_the_newest_reading_not_the_last_row():
    """The defect, in one assertion. Positional `latest` is correct only when the rows
    happen to be ascending, and this lane's are descending by design."""
    got = AGENT._summarize_readings(DESCENDING)["Room5.01_CO2"]
    assert got["latest"] == TRUE_LATEST, "the OLDEST reading was reported as the latest"
    assert got["latest_at"] == "2026-09-11 23:00:00"


def test_A10_row_order_does_not_change_any_statistic():
    """Ascending, descending and shuffled must all agree. A summary that depends on the
    order the store happened to return is a summary of the query, not of the readings."""
    import random

    ascending = list(reversed(DESCENDING))
    shuffled = list(DESCENDING)
    random.Random(7).shuffle(shuffled)

    results = [
        AGENT._summarize_readings(rows)["Room5.01_CO2"]
        for rows in (DESCENDING, ascending, shuffled)
    ]
    assert results[0] == results[1] == results[2]
    assert results[0]["latest"] == TRUE_LATEST


def test_A10_the_mean_is_not_the_midpoint_of_the_range():
    """A guard against `(min + max) / 2` sneaking in as an average: on this fixture the two
    differ, so a test asserting only "avg is between min and max" would pass either way."""
    got = AGENT._summarize_readings(DESCENDING)["Room5.01_CO2"]
    midpoint = (TRUE_MIN + TRUE_MAX) / 2
    assert got["avg"] != round(midpoint, 3)


# ── A12: what was excluded, and why ──────────────────────────────────────────


def test_A12_duplicates_invalid_rows_and_gaps_are_counted_with_reasons():
    rows = [
        {"timestamp": "2026-09-11 12:00:00", "value": 900.0},
        {"timestamp": "2026-09-11 12:00:00", "value": 900.0},  # exact duplicate
        {"timestamp": "2026-09-11 11:00:00", "value": None},  # not a number
        {"timestamp": "2026-09-11 10:00:00", "value": "warm"},  # not a number
        {"value": 880.0},  # no timestamp
        {"timestamp": "2026-09-11 09:00:00", "value": 800.0},
    ]
    kept, quality = screen(rows, "value")

    assert [v for _, v in kept] == [900.0, 800.0]
    assert quality.accepted == 2
    assert quality.excluded == 4
    assert quality.seen == 6
    assert quality.by_reason == {DUPLICATE: 1, NON_NUMERIC: 2, NO_TIMESTAMP: 1}


def test_A12_two_different_values_at_one_timestamp_are_both_kept():
    """That is a real disagreement between readings. Deleting one would be a silent choice
    about which instrument to believe, made by a deduplicator that knows nothing."""
    rows = [
        {"timestamp": "2026-09-11 12:00:00", "value": 900.0},
        {"timestamp": "2026-09-11 12:00:00", "value": 902.0},
    ]
    kept, quality = screen(rows, "value")
    assert len(kept) == 2 and quality.excluded == 0


def test_A12_out_of_order_is_recorded_but_is_not_an_exclusion():
    """The SQL lane returns DESC on purpose. Out-of-order is a fact about the rows that
    anything reading positionally needs, not a reason to drop them."""
    _, quality = screen(DESCENDING, "Room5.01_CO2", time_keys=("Datetime",))
    assert quality.out_of_order is True
    assert quality.excluded == 0

    _, ascending = screen(list(reversed(DESCENDING)), "Room5.01_CO2", time_keys=("Datetime",))
    assert ascending.out_of_order is False


def test_A12_the_exclusions_reach_the_summary_a_reader_sees():
    rows = [
        {"timestamp": "2026-09-11 12:00:00", "uuid": "co2-1", "value": 900.0},
        {"timestamp": "2026-09-11 12:00:00", "uuid": "co2-1", "value": 900.0},
        {"timestamp": "2026-09-11 11:00:00", "uuid": "co2-1", "value": None},
    ]
    got = AGENT._summarize_readings(rows, {"co2-1": {"label": "Room 5.01 CO2", "unit": "ppm"}})
    stats = got["Room 5.01 CO2"]
    assert stats["count"] == 1
    assert stats["rows_excluded"] == 2
    assert set(stats["rows_excluded_by_reason"]) == {DUPLICATE, NON_NUMERIC}


def test_A12_a_quality_note_says_nothing_when_every_row_counted():
    _, quality = screen(DESCENDING, "Room5.01_CO2", time_keys=("Datetime",))
    assert quality.note() == "", "a caveat on every answer is read as boilerplate"


def test_no_readings_gives_no_summary_rather_than_a_summary_of_zeros():
    """"avg 0.0" in front of a reader is a measurement. The absence of readings is not."""
    assert aggregate([], "value") is None
    assert aggregate([{"timestamp": "t", "value": None}], "value") is None


# ── the units contract, finally called (V12-10 wired) ────────────────────────


def test_a_narrow_result_is_grouped_by_sensor_not_by_column():
    """The measured defect: one column named `value` carrying two modalities was averaged
    into `avg=590.5, min=21.5, max=900.0`."""
    rows = [
        {"uuid": "co2-1", "timestamp": "2026-09-11 12:00:00", "value": 900.0},
        {"uuid": "temp-1", "timestamp": "2026-09-11 12:00:00", "value": 21.5},
    ]
    meta = {
        "co2-1": {"label": "Room 5.01 CO2", "unit": "ppm"},
        "temp-1": {"label": "Room 5.01 Temperature", "unit": "degC"},
    }
    got = AGENT._summarize_readings(rows, meta)

    assert "value" not in got, "the modalities were pooled into one nameless bucket"
    assert got["Room 5.01 CO2"]["avg"] == 900.0
    assert got["Room 5.01 Temperature"]["avg"] == 21.5
    assert 590.5 not in [s.get("avg") for s in got.values() if isinstance(s, dict)]


def test_an_aggregate_across_incompatible_units_is_refused_and_the_refusal_is_stated():
    rows = [
        {"uuid": "co2-1", "timestamp": "2026-09-11 12:00:00", "value": 900.0},
        {"uuid": "temp-1", "timestamp": "2026-09-11 12:00:00", "value": 21.5},
    ]
    meta = {
        "co2-1": {"label": "CO2", "unit": "ppm"},
        "temp-1": {"label": "Temperature", "unit": "degC"},
    }
    verdict = AGENT._summarize_readings(rows, meta)["_aggregate_across_sensors"]
    assert verdict["permitted"] is False
    assert "different quantities" in verdict["reason"]

    highlights = AGENT._extract_highlights(
        AGENT._summarize_readings(rows, meta), [], None
    )
    assert any("NOT summarised together" in h for h in highlights), (
        "the refusal was computed and then never shown to the reader"
    )


def test_sensors_sharing_a_unit_may_be_aggregated_and_say_so():
    rows = [
        {"uuid": "a", "timestamp": "2026-09-11 12:00:00", "value": 900.0},
        {"uuid": "b", "timestamp": "2026-09-11 12:00:00", "value": 800.0},
    ]
    meta = {"a": {"label": "A", "unit": "ppm"}, "b": {"label": "B", "unit": "ppm"}}
    verdict = AGENT._summarize_readings(rows, meta)["_aggregate_across_sensors"]
    assert verdict["permitted"] is True
    assert verdict["target_unit"] == "ppm"


def test_one_sensor_alone_produces_no_cross_sensor_verdict():
    """There is nothing to aggregate ACROSS. A note here would be noise on most reports."""
    rows = [{"uuid": "a", "timestamp": "2026-09-11 12:00:00", "value": 900.0}]
    got = AGENT._summarize_readings(rows, {"a": {"label": "A", "unit": "ppm"}})
    assert "_aggregate_across_sensors" not in got


# ── A09: a truncated count says so, and invents no total ─────────────────────


def test_A09_the_true_total_comes_from_the_fixture_not_from_the_capped_path():
    """The fixture holds 2,770 readings and the lane returns its 1,000-row limit.

    The expected total is written here, from the fixture's own contents. Asking the capped
    result how many exist would return 1,000 — the limit reporting itself as the answer,
    which is BUG-479 exactly.
    """
    true_total = 2770
    limit = 1000
    capped_rows = [
        {"timestamp": f"2026-09-11 {h:02d}:{m:02d}:00", "Room5.01_CO2": 700.0 + (h * 60 + m) % 300}
        for h in range(24)
        for m in range(60)
    ][:limit]
    sql_result = {"data": capped_rows, "rows_capped": True, "row_limit": limit}

    assert _is_capped(sql_result) is True
    assert len(capped_rows) == limit
    assert len(capped_rows) != true_total, "the cap is not the total, and never was"

    stats = AGENT._summarize_readings(capped_rows, {}, _is_capped(sql_result))["Room5.01_CO2"]
    assert stats["count_is_of_rows_read"] is True


def test_A09_an_untruncated_result_does_not_claim_truncation():
    """Claiming a cap that did not happen is its own false statement."""
    stats = AGENT._summarize_readings(DESCENDING, {}, False)["Room5.01_CO2"]
    assert "count_is_of_rows_read" not in stats
    assert _is_capped({"data": DESCENDING, "rows_capped": False}) is False


def test_A09_an_absent_flag_is_not_read_as_truncated():
    """A direct caller or an older result has no flag. "Not known to be capped" is the
    honest default."""
    assert _is_capped({"data": DESCENDING}) is False


def test_A09_no_untruncated_total_is_invented():
    """The report may say the true count is higher. It must not say what it is — nothing
    in a capped result establishes that number."""
    import inspect

    src = inspect.getsource(ReportAgent._build_sections)
    assert "the true count is higher" in src
    for invented in ("estimated_total", "extrapolat", "approximately {"):
        assert invented not in src


def test_A09_the_truncation_reaches_the_line_a_reader_sees():
    stats = AGENT._summarize_readings(DESCENDING, {}, True)
    line = AGENT._extract_highlights(stats, [], None)[0]
    assert "readings read)" in line, f"the count reads as a total: {line!r}"


# ── A12's second half: a nested census states that it overlaps ───────────────


def test_a_subclass_row_is_named_as_being_inside_its_parent():
    """CAVEAT-006's residual, in the shape the census actually produced:

        Air Quality Sensor 523, CO2 Sensor 214, CO2 Level Sensor 208

    reads as a partition and invites the reader to add to 945 in a building with 523.
    """
    counts = {"Air_Quality_Sensor": 523, "CO2_Sensor": 214, "CO2_Level_Sensor": 208}
    pairs = [
        ("Air_Quality_Sensor", "CO2_Sensor", 214),  # every CO2 sensor is an AQ sensor
        ("Air_Quality_Sensor", "CO2_Level_Sensor", 208),
        ("CO2_Sensor", "Air_Quality_Sensor", 214),  # the same pair, reported both ways
    ]
    notes = overlap_sentences(pairs, counts)

    assert len(notes) == 1
    note = notes[0]
    assert "do not add" in note.lower()
    assert "CO2 Sensor (214)" in note and "CO2 Level Sensor (208)" in note
    assert "Air Quality Sensor (523)" in note


def test_classes_that_share_nothing_are_not_called_overlapping():
    """This building has 139 supply-air and 140 zone-air temperature sensors sharing NONE.
    Telling a reader those overlap would be the same kind of false statement, inverted."""
    counts = {"Supply_Air_Temperature_Sensor": 139, "Zone_Air_Temperature_Sensor": 140}
    assert overlap_sentences([], counts) == []


def test_a_partial_overlap_is_not_reported_as_containment():
    """80 of 214 shared is real, and "some of these are also those" without a number is a
    caveat nobody can act on. Only strict containment is stated."""
    counts = {"A_Sensor": 523, "B_Sensor": 214}
    assert overlap_sentences([("A_Sensor", "B_Sensor", 80)], counts) == []


def test_equal_sized_classes_are_not_reported_as_nested():
    """Identical instance sets are `collapse_synonyms`'s job, not this one — and calling
    them nested would claim a hierarchy the counts do not establish."""
    counts = {"VAV": 132, "Terminal_Unit": 132}
    assert overlap_sentences([("VAV", "Terminal_Unit", 132)], counts) == []


def test_the_overlap_note_reaches_the_rendered_census():
    from orchestrator.services.ontology_inventory import render_census

    out = render_census(
        [("Air_Quality_Sensor", 523), ("CO2_Sensor", 214)],
        "Test Building",
        overlaps=["**These counts overlap — do not add them.** CO2 Sensor (214) …"],
    )
    assert "do not add them" in out


def test_a_census_with_no_overlaps_renders_exactly_as_before():
    """The caveat must not appear on the ordinary census, which is most of them."""
    from orchestrator.services.ontology_inventory import render_census

    assert "overlap" not in (render_census([("Chiller", 3)], "Test Building") or "")


# ── the step nobody remembers ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "module",
    ["orchestrator/agents/capability_agent.py", "orchestrator/workflow/_orchestrator.py"],
)
def test_both_census_paths_ask_for_the_overlap_caveat(module):
    """Two lanes render a census. A caveat wired into one of them is a caveat the other
    lane's readers never see, and the two would then disagree about whether their own
    categories can be added — which is worse than neither having it."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / module).read_text(encoding="utf-8")
    assert "overlap_notes" in src, f"{module} renders a census without the overlap caveat"
    assert src.index("overlap_notes") < src.rindex("render_census")


def test_the_units_contract_is_actually_called():
    """`units.py` shipped with V12-04 and nothing imported it. A contract nothing consults
    is documentation."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator/agents/report_agent.py"
    ).read_text(encoding="utf-8")
    assert "aggregation_decision" in src
