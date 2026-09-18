# -*- coding: utf-8 -*-
"""CAVEAT-769 — a figure a lane computed is evidence, and enforcement waits for a record.

Claim binding was enabled live once, on 2026-09-18, and reverted 25 minutes later: it had
deleted five CORRECT figures, among them the number a counting question had asked for. The
answers were right. The record was empty. These tests pin the two changes that follow:

1. the counts lanes file what they compute, so a COUNT is a row the binder can point at;
2. enforcement runs only when the turn's record accounts for the lane that answered, and
   otherwise degrades to record-only *and says why*.

Every case below is a shape that was MEASURED on real output, not one that was imagined.
"""
from __future__ import annotations

import json

import pytest

from orchestrator.services import claim_binder as cb
from orchestrator.services.building_metrics import (
    BuildingMetricsSnapshot,
    render_metrics_block,
    snapshot_figures,
)
from orchestrator.services.evidence import computed
from orchestrator.services.ontology_inventory import census_figures, render_census


@pytest.fixture(autouse=True)
def _clean_recorder():
    computed.reset()
    yield
    computed.reset()


def _census_rows():
    """The census this building really renders for a sensor question (measured, not made up)."""
    return [
        ("Sensor", 3248),
        ("Air_Quality_Sensor", 835),
        ("CO2_Sensor", 280),
        ("CO2_Level_Sensor", 274),
        ("PM2.5_Level_Sensor", 245),
        ("NO2_Level_Sensor", 41),
    ]


def _snapshot():
    return BuildingMetricsSnapshot(
        total_points=3512,
        total_sensors=3248,
        zone_count=298,
        floor_count=8,
        floor_kinds=[("Floor", 6), ("Rooftop", 1), ("Parking_Level", 1)],
        room_count=234,
        sensor_types=[("Air Quality Sensor", 835), ("Contact Sensor", 466)],
    )


# ── the recorder ─────────────────────────────────────────────────────────────


def test_a_recorded_figure_is_readable_back_in_the_shape_the_binder_indexes():
    computed.record("class_census", {"CO2_Sensor": 280})
    payload = computed.as_payload()
    assert payload == {"sources": {"class_census": {"CO2_Sensor": 280.0}}}


def test_a_turn_that_computed_nothing_records_nothing_rather_than_an_empty_shell():
    assert computed.as_payload() is None


def test_recording_the_same_field_twice_overwrites_rather_than_accumulating():
    computed.record("building_metrics", {"sensors_declared": 3248})
    computed.record("building_metrics", {"sensors_declared": 3248})
    assert computed.as_payload()["sources"]["building_metrics"] == {"sensors_declared": 3248.0}


def test_a_boolean_is_not_the_figure_one():
    """Letting ``True`` in would put a 1 in the evidence index for every flag a lane sets."""
    computed.record("x", {"ok": True, "n": 1})
    assert computed.as_payload()["sources"]["x"] == {"n": 1.0}


def test_reset_clears_this_turn():
    computed.record("x", {"n": 5})
    computed.reset()
    assert computed.as_payload() is None


def test_the_recorder_never_raises_on_hostile_input():
    computed.record("x", object())  # type: ignore[arg-type]
    computed.record("x", {None: "not a number"})
    assert computed.as_payload() is None


@pytest.mark.asyncio
async def test_one_turns_figures_cannot_bind_another_turns_claims():
    """The property the whole design rests on: figures are filed per request, not per process.

    Keyed by the request's trace id rather than held in a ContextVar, because a value ``set``
    inside a child task never propagates back to the parent — the figures would then be
    invisible to the response node, which is the very defect this file exists to close. Both
    halves are checked here: a concurrent turn sees nothing of this one, and a figure filed
    in a CHILD task is still visible to the parent.
    """
    import asyncio

    from orchestrator.services.logging_context import set_trace_id

    async def turn(trace: str, value: float) -> dict:
        set_trace_id(trace)

        async def deeper() -> None:  # a lane running in its own task
            computed.record("class_census", {"Some_Class": value})

        await asyncio.create_task(deeper())
        await asyncio.sleep(0)
        payload = computed.as_payload()
        computed.reset()
        return payload

    a, b = await asyncio.gather(turn("trace-a", 280), turn("trace-b", 41))
    assert a["sources"]["class_census"] == {"Some_Class": 280.0}
    assert b["sources"]["class_census"] == {"Some_Class": 41.0}


# ── what each lane records ───────────────────────────────────────────────────


def test_every_figure_the_metrics_block_states_was_recorded():
    """The contract, pinned: what is RENDERED must be what was FILED.

    Checked against the rendered text rather than against a list of field names, because a
    field renamed in one place and not the other is exactly how the gap opened.
    """
    snap = _snapshot()
    text = render_metrics_block(snap, "A Building")
    figures = set(snapshot_figures(snap).values())
    for token in ("3,512", "3,248", "298", "8", "234", "835", "466"):
        assert token in text
        assert float(token.replace(",", "")) in figures
    # the storey subtotal is stated in the prose and lives in no single snapshot field
    assert 6.0 in figures and "6 storeys" in text


def test_every_count_the_census_states_was_recorded():
    rows = _census_rows()
    text = render_census(rows, "A Building") or ""
    figures = census_figures(rows)
    for name, n in rows:
        assert str(n) in text
        assert figures[name] == float(n)


def test_rendering_a_census_files_its_counts_for_the_turn():
    render_census(_census_rows(), "A Building")
    assert computed.as_payload()["sources"]["class_census"]["CO2_Sensor"] == 280.0


def test_rendering_the_metrics_block_files_its_counts_for_the_turn():
    render_metrics_block(_snapshot(), "A Building")
    assert computed.as_payload()["sources"]["building_metrics"]["sensors_declared"] == 3248.0


# ── the defect itself, both halves ───────────────────────────────────────────


def _prose_lane_bus(**extra):
    bus = {"capability_result": {"success": True, "provenance": "ontology_inventory"}}
    bus.update(extra)
    return bus


def test_without_the_record_a_census_answer_looks_entirely_invented():
    """The state of the world on 2026-09-18 00:00, reproduced rather than remembered."""
    text = render_census(_census_rows(), "A Building") or ""
    computed.reset()  # the lane computed, and filed nothing
    report = cb.analyse(text, _prose_lane_bus(), mode="record")
    unbound = [c.raw for c in report.claims if c.binding == "unbound"]
    assert any("280" in u for u in unbound)


def test_with_the_record_the_number_the_question_asked_for_survives_enforcement():
    text = render_census(_census_rows(), "A Building") or ""
    bus = _prose_lane_bus(computed_figures=computed.as_payload())
    report = cb.analyse(text, bus, mode="enforce")
    assert report.enforced is True
    assert report.changed is False
    for _name, n in _census_rows():
        assert str(n) in report.answer


def test_the_metrics_block_survives_enforcement_once_its_counts_are_filed():
    text = render_metrics_block(_snapshot(), "A Building")
    bus = _prose_lane_bus(computed_figures=computed.as_payload())
    report = cb.analyse(text, bus, mode="enforce")
    assert report.enforced is True
    assert report.changed is False


def test_the_digits_inside_a_measurand_name_are_not_a_claim():
    """The 2 of CO2 was extracted as the figure 2, and its bullet — carrying 280 — deleted."""
    claims = cb.extract_claims("- **CO2 Sensor** - 280\n- **PM2.5 Level Sensor** - 245")
    values = sorted(c.value for c in claims if c.kind == "numeric" and c.value is not None)
    assert values == [245.0, 280.0]


def test_the_systems_own_reading_note_is_not_an_unsupported_verdict():
    """A disclosure written to stop a reader over-reading must not itself be caveated."""
    text = (
        "- **Particulate Matter Sensor** - 366\n\n"
        "_Note: in Brick this class is also the parent of TVOC sensors, so the total is "
        "broader than the name suggests._"
    )
    report = cb.analyse(
        text,
        {
            "sparql_result": {
                "success": True,
                "results": {"data": [{"cls": "Particulate_Matter_Sensor", "n": 366}]},
            }
        },
        mode="enforce",
    )
    assert not [c for c in report.claims if c.kind == "inference" and c.binding == "unbound"]


# ── completeness ─────────────────────────────────────────────────────────────


def _complete(answer, bus):
    report = cb.analyse(answer, bus, mode="record")
    return report.completeness


def test_a_turn_with_no_record_at_all_is_absent_and_never_enforced():
    c = _complete("The mean was 21.5 degrees.", {})
    assert c.status == cb.EV_ABSENT and not c.enforceable


def test_a_prose_lane_that_filed_no_computed_figure_is_partial():
    c = _complete("There are 280 of them.", _prose_lane_bus())
    assert c.status == cb.EV_PARTIAL and not c.enforceable
    assert "passage" in c.reason


def test_the_same_prose_lane_with_its_figures_filed_is_complete():
    c = _complete(
        "There are 280 of them.",
        _prose_lane_bus(computed_figures={"sources": {"class_census": {"CO2_Sensor": 280}}}),
    )
    assert c.status == cb.EV_COMPLETE and c.enforceable


def test_a_referenced_series_whose_readings_are_absent_is_partial():
    """The projection names a timeseries and no store lane produced rows: the figures that
    answer came from a read this record cannot see."""
    bus = {
        "sparql_result": {
            "success": True,
            "results": {"data": [{"sensor": "s1", "uuid": "abc-123"}]},
        }
    }
    c = _complete("It averaged 21.5 degrees.", bus)
    assert c.status == cb.EV_PARTIAL and "readings are not in this turn's record" in c.reason


def test_the_same_turn_with_the_readings_present_is_complete():
    bus = {
        "sparql_result": {
            "success": True,
            "results": {"data": [{"sensor": "s1", "uuid": "abc-123"}]},
        },
        "sql_result": {"success": True, "results": {"data": [{"value": 21.5}]}},
    }
    c = _complete("It averaged 21.5 degrees.", bus)
    assert c.status == cb.EV_COMPLETE


@pytest.mark.parametrize("unbound, total", [(17, 19), (99, 123), (9, 16)])
def test_the_three_unbound_rates_from_the_live_enforcement_run_withhold_enforcement(unbound, total):
    """The per-turn signatures CAVEAT-769 recorded, each on an answer that was CORRECT.

    A guard that believes most of an answer is fabricated is far likelier to be blind than
    right, and on the one live run it was blind three times out of three.
    """
    claims = [cb.Claim(kind="numeric", raw="x", start=0, end=1, sentence="s") for _ in range(total)]
    for i, c in enumerate(claims):
        c.binding = "unbound" if i < unbound else "bound"
    idx = cb.EvidenceIndex(available=True)
    c = cb.assess_completeness(
        {"register_result": {"success": True}}, idx, "register_result", claims
    )
    assert c.status == cb.EV_PARTIAL and not c.enforceable


def test_an_ordinary_unbound_figure_still_leaves_the_turn_enforceable():
    claims = [cb.Claim(kind="numeric", raw="x", start=0, end=1, sentence="s") for _ in range(10)]
    for i, c in enumerate(claims):
        c.binding = "unbound" if i < 1 else "bound"
    idx = cb.EvidenceIndex(available=True)
    c = cb.assess_completeness(
        {"register_result": {"success": True}}, idx, "register_result", claims
    )
    assert c.status == cb.EV_COMPLETE


def test_enforcement_is_withheld_and_the_record_says_why():
    report = cb.analyse("There are 280 of them.", _prose_lane_bus(), mode="enforce")
    assert report.enforced is False
    assert report.changed is False
    assert any("enforcement withheld" in n for n in report.notes)
    assert report.as_dict()["completeness"]["status"] == cb.EV_PARTIAL


def test_run_returns_the_original_text_when_enforcement_was_withheld():
    answer = "There are 280 of them."
    text, record = cb.run(answer, _prose_lane_bus(), mode="enforce")
    assert text == answer
    assert record["enforced"] is False
    json.dumps(record)  # the record rides in the response cache


# ── the precision rules the replay measured ──────────────────────────────────


def test_a_figure_the_question_states_is_not_a_figure_the_answer_invented():
    report = cb.analyse(
        "Which of these sessions is your 9 a.m. lecture?",
        {"sparql_result": {"success": True, "results": {"data": [{"id": "TS-0644"}]}}},
        mode="record",
        question="I have a 9 a.m. lecture. What is confirmed?",
    )
    nine = [c for c in report.claims if c.raw.strip().startswith("9")]
    assert nine and all(c.binding == "skipped" for c in nine)


def test_a_figure_inside_an_absence_sentence_is_not_an_assertion():
    report = cb.analyse(
        "The records do not contain any asset that reports a filter size for the units on "
        "floor 4.",
        {"sparql_result": {"success": True, "results": {"data": [{"cls": "Filter_Sensor"}]}}},
        mode="enforce",
    )
    assert report.changed is False


def test_a_total_of_figures_stated_beside_it_is_derived_not_invented():
    # Deliberately NOT one summable column: each figure is a different field, so the older
    # column-aggregate path cannot explain the total and only the stated arithmetic can.
    bus = {
        "sparql_result": {
            "success": True,
            "results": {"data": [{"talkMin": 45, "tourMin": 40, "questionsMin": 30}]},
        }
    }
    report = cb.analyse("Total time required: 45 + 40 + 30 = 115 minutes.", bus, mode="record")
    total = [c for c in report.claims if c.value == 115]
    assert total and total[0].binding == "derived"
    assert total[0].operation == "sum_of_stated"


def test_a_total_is_not_derived_from_addends_that_are_themselves_unevidenced():
    """The rule licenses arithmetic over evidence; it must not conjure a premise."""
    bus = {"sparql_result": {"success": True, "results": {"data": [{"m": 1}]}}}
    report = cb.analyse("Total time required: 45 + 40 + 30 = 115 minutes.", bus, mode="record")
    total = [c for c in report.claims if c.value == 115]
    assert total and total[0].binding == "unbound"


def test_the_same_duration_restated_in_hours_and_minutes_is_one_quantity():
    bus = {"sparql_result": {"success": True, "results": {"data": [{"m": 115}]}}}
    report = cb.analyse("It runs 115 minutes, so roughly 1 hour 55 minutes.", bus, mode="record")
    fifty_five = [c for c in report.claims if c.value == 55]
    assert fifty_five and fifty_five[0].binding == "derived"


def test_a_narrow_no_break_space_does_not_hide_a_unit():
    claims = cb.extract_claims("It runs 115 minutes.")
    assert any(c.value == 115 and c.unit == "minutes" for c in claims)


# ── the contracts that must not drift ────────────────────────────────────────


def test_every_lane_that_can_produce_evidence_is_read_by_the_binder():
    """The module's docstring has claimed this was pinned by a test since it was written."""
    from orchestrator.services.evidence.assemble import T02_LANES

    missing = [lane for lane in T02_LANES if lane not in cb._EVIDENCE_KEYS]
    assert not missing, f"lanes the binder cannot see: {missing}"


def test_the_bus_key_the_recorder_writes_is_the_bus_key_the_binder_reads():
    assert computed.BUS_KEY in cb._EVIDENCE_KEYS


def test_record_mode_still_never_changes_an_answer_whatever_the_record_says():
    answer = "Nine of them, at 999.9 degrees."
    text, record = cb.run(answer, _prose_lane_bus(), mode="record")
    assert text == answer and record["changed"] is False


def test_no_building_literal_lives_in_the_recorder():
    from pathlib import Path

    src = Path(computed.__file__).read_text(encoding="utf-8").lower()
    for literal in ("bldg1", "abacws", "cardiff"):
        assert literal not in src
