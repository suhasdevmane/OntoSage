# -*- coding: utf-8 -*-
"""Five defects from the hand read of run 3 (docs/phase0/phase0_run3_read.md, 2026-09-17).

Each one states a figure that CANNOT be true, or labels data as something it is not.
A domain expert spots every one of them on sight, which is why they are the most
damaging shape of wrong answer this system produces.

ROW 99 -- a visitor asking where to sit was shown, as the evidence behind a
recommendation: `occupancy: -7.719` and `co2: -260.986`. Minus eight people, and a
carbon-dioxide concentration below zero. Both came from the tier-2 forecaster -- a
least-squares trend on a falling series runs straight through zero -- and nothing
between the model and the answer asked whether the result could be a quantity at all.
The graph declares what each quantity CAN be, and the ranking lane never looked.

ROW 132 -- "Floor 4 has the highest mean flow rate (14.2 m3/s) and the highest peak
(292 m3/s)", used as the basis for recommending filtration plant and a leak-detection
routine. 292 m3/s is a river. This one is a UNIT defect and not a data defect, and the
distinction decides the fix: rescaling a correct number would be worse than the bug.
The evidence is asserted below -- the ontology declares water flow in L/min with a
physical maximum of 2000, the modality config declares L/s, and both figures sit inside
those bands. Only the unit string was invented, by a last-resort table in the metadata
builder that typed every flow point "m3/s".

ROW 120 -- "**Latest snapshot (2026-09-12 17:50:00)**" printed over a window the same
answer described as running to 17 Sep, with "so the heating circuit is healthy" attached.
The stamp shown was the OLDEST reading, not the newest. This is the BUG-520 shape at a
SECOND site: that one was fixed in the report lane's `_summarize_readings`, which the SQL
narration lane does not use. Its rows arrive newest-first from `ORDER BY timestamp DESC`
-- until a privacy clamp sends them through `_coarsen`, which rebuckets them oldest-first,
while the prompt goes on calling row 1 the newest.

ROWS 139 and 146 -- the `rdfs:comment` OntoSage writes on its own record classes, quoted
to a reader as though it answered their question: "The three stream columns are separate
deliberately ... collapsing them into a single stream field makes that disagreement
unrepresentable when the disagreement IS the answer." That is a note to a developer about
how a register is modelled. Brick's own definitions stay eligible; only the annotations
OntoSage wrote about its own data model are withheld.

ROW 80 -- "**The building's events store doesn't record that.**" The reader does not know
what an events store is. The sentence after it already lists what the building keeps.
"""

from __future__ import annotations

import asyncio
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.deliberation.capability_schema import (  # noqa: E402
    AdmissionResult,
    BuildingCapabilitySchema,
)
from orchestrator.services.deliberation.coverage_audit import (  # noqa: E402
    STATUS_PRESENT,
    SpaceCoverage,
)
from orchestrator.services.deliberation.cqir import (  # noqa: E402
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    TimeBasis,
    TimeSpec,
)
from orchestrator.services.deliberation.dossier import (  # noqa: E402
    DossierRanked,
    EvidenceDossier,
    render_answer,
)
from orchestrator.services.deliberation.plan_executor import execute  # noqa: E402
from orchestrator.services.physical_bands import (  # noqa: E402
    Band,
    Implausible,
    band_for_measurand,
    band_for_modality,
    declared_bands,
    excluded_sentence,
)

NS = "http://example.org/anybldg#"

#: The two figures the run actually printed, and one from the same answer that is fine.
ROW99_OCCUPANCY = -7.719
ROW99_CO2 = -260.986
ROW99_GOOD_CO2 = 792.531

#: The two figures row 132 recommended plant on.
ROW132_MEAN_FLOW = 14.2
ROW132_PEAK_FLOW = 292.0


# ── 1. the bands are readable without a graph handle ─────────────────────────


def test_the_declarations_are_read_from_the_shared_tbox():
    bands = declared_bands()
    assert bands, "no physical bands parsed from ontology/measurand_kinds.ttl"
    assert bands["CarbonDioxide"].low == 350 and bands["CarbonDioxide"].high == 40000
    assert bands["OccupancyCount"].low == 0


def test_a_modality_resolves_to_a_band_through_the_buildings_own_config():
    """No quantity, class or number is named here -- the chain is
    modality -> Brick class (the building's config) -> measurand -> band (the TBox)."""
    assert band_for_modality("co2") is not None
    assert band_for_modality("occupancy") is not None


def test_the_two_values_row_99_printed_are_rejected_and_its_third_is_kept():
    co2, occ = band_for_modality("co2"), band_for_modality("occupancy")
    assert not co2.holds(ROW99_CO2), "a negative CO2 concentration was accepted"
    assert not occ.holds(ROW99_OCCUPANCY), "a negative headcount was accepted"
    assert co2.holds(ROW99_GOOD_CO2), "a perfectly ordinary CO2 reading was rejected"


def test_a_modality_with_no_declared_band_is_not_treated_as_impossible():
    """Absence of a declaration is not evidence. A guard that failed closed here would
    silence every quantity the ontology has not reached yet."""
    assert band_for_modality("definitely_not_a_modality") is None


def test_a_modality_spanning_two_bands_takes_the_WIDER_one():
    """`occupancy` covers a counting sensor and a motion contact, whose bands are
    0..10000 people and 0..1. The narrower one would announce every ordinary headcount
    as impossible; the union still rejects a negative, which is all this catches."""
    occ = band_for_modality("occupancy")
    assert occ.holds(24.0), "a room with 24 people in it was called impossible"
    assert not occ.holds(ROW99_OCCUPANCY)


# ── 2. what is excluded is counted and named, never hidden ───────────────────


def test_the_sentence_counts_the_exclusions_and_names_them():
    bad = [
        Implausible("u1", ROW99_CO2, Band("CarbonDioxide", 350, 40000, "ppm"), "Room 5.03 co2"),
        Implausible(
            "u2", ROW99_OCCUPANCY, Band("OccupancyCount", 0, 10000, "people"), "Room 5.03 occupancy"
        ),
    ]
    note = excluded_sentence(bad)
    assert "2 readings were outside the physically possible range and were excluded" in note
    assert "-260.986" in note and "Room 5.03 co2" in note
    assert "-7.719" in note


def test_one_exclusion_reads_as_one():
    note = excluded_sentence([Implausible("u1", -1.0, Band("OccupancyCount", 0, 10, "people"))])
    assert "1 reading was outside the physically possible range and was excluded" in note


def test_nothing_excluded_says_nothing():
    assert excluded_sentence([]) == ""


def test_the_sentence_does_not_blame_the_building_or_name_internal_machinery():
    note = excluded_sentence([Implausible("u1", -5.0, Band("CarbonDioxide", 350, 40000, "ppm"))])
    lowered = note.lower()
    for forbidden in ("simulated", "synthetic", "fake", "database", "table", "sql", "forecaster"):
        assert forbidden not in lowered


# ── 3. the ranking lane drops them before they can be scored ─────────────────


@dataclass
class _FakeResult:
    success: bool = True
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""


class _FakeAdapter:
    def __init__(self, rows):
        self._rows = rows

    def build_timeseries_query(self, uuids, ts_col, start, end, limit=1000):
        return "SELECT ..."

    async def execute_query(self, sql):
        return _FakeResult(data=self._rows)


def _space(local, modality, floor="floor5"):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=local, floor=floor)
    sc.modalities = {
        modality: {
            "status": STATUS_PRESENT,
            "sensor": "",
            "uuid": f"u-{local}",
            "stored_at": f"{modality}_data",
        }
    }
    return sc


def _schema(locals_, modality):
    return BuildingCapabilitySchema(
        building_id="anybldg",
        namespace=NS,
        spaces=[_space(x, modality) for x in locals_],
        amenities=[],
    )


def _rows(uuid_, values):
    return [
        {"timestamp": f"2026-09-17 {10 + i:02d}:00:00", "uuid": uuid_, "value": v}
        for i, v in enumerate(values)
    ]


def _ir(modality, basis=TimeBasis.FORECAST, horizon=24.0):
    return CQIR(
        decision=DecisionKind.RANK_ALL,
        constraints=[Constraint(modality=modality, direction=Direction.MINIMIZE)],
        time=TimeSpec(basis=basis, horizon_hours=horizon),
    )


def _run_ranking(modality, series, forecast_value):
    async def _forecaster(series_, horizon):
        return forecast_value, "linear-trend"

    adapter = _FakeAdapter(_rows("u-Room5.03", series))
    return asyncio.run(
        execute(
            _ir(modality),
            AdmissionResult(verdict="admit"),
            _schema(["Room5.03"], modality),
            adapter_getter=lambda t: adapter,
            forecaster=_forecaster,
        )
    )


def test_a_forecast_below_zero_never_becomes_evidence():
    """Row 99's exact mechanism: a falling series, a linear trend, a negative point."""
    out = _run_ranking("co2", [900, 800, 700, 600, 500, 400], ROW99_CO2)
    assert out.impossible_readings, "a negative CO2 forecast was ranked on"
    assert "-260.986" in out.impossible_readings[0], "the excluded value was not named"
    for cell in out.evidence:
        assert cell.value != ROW99_CO2, "the impossible value survived into the evidence table"
    for rec in out.forecasts:
        assert rec.forecast_value != ROW99_CO2


def test_a_negative_headcount_never_becomes_evidence():
    out = _run_ranking("occupancy", [9, 7, 5, 3, 2, 1], ROW99_OCCUPANCY)
    assert out.impossible_readings
    assert "-7.719" in out.impossible_readings[0]


def test_the_exclusion_is_reported_not_silently_dropped():
    out = _run_ranking("co2", [900, 800, 700, 600, 500, 400], ROW99_CO2)
    joined = " ".join(out.impossible_readings)
    assert "outside the physically possible range" in joined
    assert "excluded" in joined


def test_a_possible_forecast_is_left_alone():
    """792.531 ppm came out of the SAME answer. A guard that suppressed it would be a
    worse failure than the one it prevents."""
    out = _run_ranking("co2", [900, 800, 700, 600, 500, 400], ROW99_GOOD_CO2)
    assert out.impossible_readings == []
    assert any(r.forecast_value == ROW99_GOOD_CO2 for r in out.forecasts)


def test_a_modality_with_no_band_is_ranked_as_before():
    """`noise` declares no band in the shared TBox. Nothing may be excluded for it."""
    out = _run_ranking("noise", [40, 41, 42, 43, 44, 45], 38.0)
    assert out.impossible_readings == []


# ── 4. the reader is told, in the answer, not only in the dossier ────────────


def _dossier_with(note):
    return EvidenceDossier(
        building_id="anybldg",
        raw_query="where is a calm place to sit?",
        decision="list_matching",
        coverage_summary="1 of 1 spaces considered",
        ranked=[
            DossierRanked(
                rank=1, space="Room 5.03", floor="Floor5", total=0.75, criteria={"noise": 31.0}
            )
        ],
        impossible_readings=[note] if note else [],
    )


def test_the_rendered_answer_carries_the_exclusion_sentence():
    note = excluded_sentence(
        [Implausible("u1", ROW99_CO2, Band("CarbonDioxide", 350, 40000, "ppm"), "Room 5.03 co2")]
    )
    text = render_answer(_dossier_with(note))
    assert "outside the physically possible range" in text
    assert "Room 5.03 co2" in text


def test_an_answer_with_nothing_excluded_gains_no_sentence():
    text = render_answer(_dossier_with(""))
    assert "physically possible range" not in text


# ── 5. row 132: the unit was wrong, the number was not ───────────────────────


def test_the_ontology_declares_water_flow_per_MINUTE_not_per_second():
    """The evidence that decides row 132. If the reading were really m3/s the fix would
    be to rescale it; it is not, so the fix is the unit."""
    band = band_for_measurand("WaterFlow")
    assert band is not None
    assert band.unit == "L/min"
    assert band.high == 2000


def test_both_of_row_132s_figures_are_possible_readings_of_the_declared_quantity():
    band = band_for_measurand("WaterFlow")
    assert band.holds(ROW132_MEAN_FLOW), "the mean flow was a perfectly ordinary reading"
    assert band.holds(ROW132_PEAK_FLOW), "the peak flow was a perfectly ordinary reading"


def test_the_last_resort_unit_table_no_longer_invents_a_flow_unit():
    """`m3/s` came from nowhere but this table. The graph distinguishes water flow from
    air flow and this coarse kind cannot, so it must supply nothing rather than a guess
    wrong by four orders of magnitude."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator as W

    o = types.SimpleNamespace()
    unit_for_kind = types.MethodType(W._unit_for_kind, o)
    assert unit_for_kind("flow") == ""
    # The units that ARE knowable from the coarse kind are untouched.
    assert unit_for_kind("temperature") == "°C"
    assert unit_for_kind("co2") == "ppm"


def test_no_flow_sensor_is_handed_a_per_second_volumetric_unit():
    from orchestrator.services.modality_units import unit_for_sensor

    brick = "https://brickschema.org/schema/Brick#"
    for cls in ("Water_Flow_Sensor", "Water_Meter", "Hot_Water_Flow_Sensor", "Air_Flow_Sensor"):
        assert unit_for_sensor(brick + cls, cls.replace("_", " ")) != "m³/s"


# ── 6. row 120: the stamp shown belongs to the value shown ───────────────────


ASCENDING_LIKE_A_CLAMPED_WINDOW = [
    {"timestamp": "2026-09-12 17:50:00", "uuid": "u-b1", "value": 57.16},
    {"timestamp": "2026-09-14 09:00:00", "uuid": "u-b1", "value": 61.40},
    {"timestamp": "2026-09-17 23:37:00", "uuid": "u-b1", "value": 68.01},
]


def _narration_prompt(rows):
    """The prompt the model is handed, with the model itself stubbed out."""
    from orchestrator.agents import sql_agent as sql_agent_module

    captured = {}

    async def _capture(prompt, task_type=None):
        captured["prompt"] = prompt
        return "ok"

    original = sql_agent_module.llm_manager.generate
    sql_agent_module.llm_manager.generate = _capture
    try:
        agent = sql_agent_module.SQLAgent.__new__(sql_agent_module.SQLAgent)
        asyncio.run(agent._format_results(rows, "what's the delta-T?", "SELECT ...", {}))
    finally:
        sql_agent_module.llm_manager.generate = original
    return captured["prompt"]


def test_the_oldest_reading_is_not_listed_first_when_the_rows_arrive_ascending():
    """`_coarsen` emits oldest-first whenever a privacy clamp applies, and row 120's
    answer carried the clamp disclosure. The ten rows shown must be the ten NEWEST."""
    prompt = _narration_prompt(ASCENDING_LIKE_A_CLAMPED_WINDOW)
    first_row = prompt.split("1. ", 1)[1].split("\n", 1)[0]
    assert "68.01" in first_row, "the oldest reading was presented as record 1"
    assert "57.16" not in first_row


def test_the_header_names_the_same_stamp_the_first_row_carries():
    """Stated, not implied. The header's stamp and record 1's stamp are one reading --
    which is the whole of what row 120 got wrong."""
    prompt = _narration_prompt(ASCENDING_LIKE_A_CLAMPED_WINDOW)
    assert "NEWEST FIRST" in prompt
    header = prompt.split("1. ", 1)[0]
    named = header.rsplit("the one at ", 1)[1].split(":\n", 1)[0].strip()
    first_row = prompt.split("1. ", 1)[1].split("\n", 1)[0]
    assert named and named in first_row, f"header named {named!r}, record 1 was {first_row!r}"


def test_the_word_latest_is_reserved_for_the_reading_it_belongs_to():
    prompt = " ".join(_narration_prompt(ASCENDING_LIKE_A_CLAMPED_WINDOW).lower().split())
    assert "the timestamp you print must be the one belonging to the value you print" in prompt


def test_rows_whose_time_cannot_be_read_are_not_promoted_to_latest():
    rows = [{"uuid": "u", "value": 1.0}] + ASCENDING_LIKE_A_CLAMPED_WINDOW
    prompt = _narration_prompt(rows)
    first_row = prompt.split("1. ", 1)[1].split("\n", 1)[0]
    assert "68.01" in first_row


# ── 7. rows 139 / 146: schema documentation is not an answer ─────────────────


WASTE_POINT_COMMENT = (
    "One bin or container: its station, what the SYSTEM records it as, what the bin is "
    "LABELLED, what its aperture physically accepts, its fill against an approved threshold, "
    "and when it is next collected. The three stream columns are separate deliberately -- a "
    "point recorded as general waste, labelled mixed recycling and fitted with a narrow slot "
    "is one people will use wrongly, and collapsing them into a single stream field makes "
    "that disagreement unrepresentable when the disagreement IS the answer. Fill threshold "
    "is per point, because a 240-litre bin in a busy atrium and a 60-litre one in a quiet "
    "corridor do not cross 'full' at the same percentage."
)


def test_the_tbox_annotation_set_is_built_from_the_ontology_files():
    from orchestrator.agents.sparql_agent import schema_documentation_literals

    known = schema_documentation_literals()
    assert known, "no schema annotations parsed from ontology/"
    normalised = " ".join(WASTE_POINT_COMMENT.split())
    assert normalised in known, "the comment quoted in run-3 row 139 was not recognised"


def test_a_design_note_is_withheld_from_the_answer():
    from orchestrator.agents.sparql_agent import redact_schema_documentation

    bindings = [
        {
            "label": {"value": "Waste collection point"},
            "def": {"value": WASTE_POINT_COMMENT},
        }
    ]
    kept, withheld = redact_schema_documentation(bindings)
    assert withheld == 1
    assert kept == [{"label": {"value": "Waste collection point"}}]


def test_a_row_that_was_nothing_but_a_design_note_goes_with_it():
    from orchestrator.agents.sparql_agent import redact_schema_documentation

    kept, withheld = redact_schema_documentation([{"def": {"value": WASTE_POINT_COMMENT}}])
    assert kept == [] and withheld == 1


def test_a_re_wrapped_literal_still_matches_itself():
    from orchestrator.agents.sparql_agent import redact_schema_documentation

    wrapped = WASTE_POINT_COMMENT.replace(" ", "\n  ", 3)
    kept, withheld = redact_schema_documentation([{"def": {"value": wrapped}, "x": {"value": "1"}}])
    assert withheld == 1 and kept == [{"x": {"value": "1"}}]


def test_a_definition_the_shared_tbox_did_not_write_survives():
    """Brick's own comments are genuine definitions and must keep reaching readers --
    only the annotations OntoSage wrote about its own data model are withheld."""
    from orchestrator.agents.sparql_agent import redact_schema_documentation

    brick_def = (
        "Measures the concentration of carbon dioxide in the air of a space, "
        "reported in parts per million."
    )
    bindings = [{"label": {"value": "CO2 Sensor"}, "def": {"value": brick_def}}]
    kept, withheld = redact_schema_documentation(bindings)
    assert withheld == 0 and kept == bindings


def test_the_formatter_withholds_before_the_rows_become_content():
    """Filtering the prose afterwards would still have put the note in the prompt."""
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._format_results)
    body = src.split("summary_prompt = ", 1)[0]
    assert "redact_schema_documentation(bindings)" in body


# ── 8. row 80: internal storage vocabulary in user-visible text ──────────────


def test_a_decline_names_what_the_building_keeps_not_where_it_is_kept():
    from orchestrator.services.event_query_service import EventQueryService

    svc = EventQueryService.__new__(EventQueryService)
    text = svc._not_an_event_kind_held("which three alternatives are closest?")[
        "formatted_response"
    ]
    assert "events store" not in text.lower()
    # The list of what IS held was always the useful half of that answer.
    for kept in ("bookings", "work orders", "entrance counts", "anomalies"):
        assert kept in text.lower()


def test_the_other_reader_facing_sentence_lost_it_too():
    """The read-failure message said the same thing. A `"source"` key may still say
    `events store` -- that is provenance the pipeline records, never text a reader sees."""
    import inspect

    from orchestrator.services import event_query_service

    src = inspect.getsource(event_query_service)
    assert "The building's events store" not in src
    assert "couldn't read the events store" not in src


def test_the_orchestrator_node_says_it_the_same_way():
    """The node has its own copy of the read-failure message; fixing one and not the
    other leaves the phrase on whichever path fails first."""
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "couldn't read the events store" not in src
