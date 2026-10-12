"""Defects found by the third Open WebUI probe round (10 Oct 2026), one test per mechanism.

Synthetic questions and fixtures only; no building is read and no study wording is used.
"""

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit


# ── BUG-1565: "lab 4.20" is a named place ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "Is lab 4.20 stuffy right now?",
        "How warm is office 3.07?",
        "What's the CO2 in classroom 1.09?",
        "noise in rm 2.05",
    ],
)
def test_a_room_named_by_its_kind_and_id_is_a_place(q):
    from orchestrator.services.aggregate_support import names_a_place

    assert names_a_place(q)


def test_a_building_question_still_names_no_place():
    from orchestrator.services.aggregate_support import names_a_place

    assert not names_a_place("What is the average CO2 in the building right now?")


# ── BUG-1566: a comfort adjective about a named room is a reading, not a register row ─────


@pytest.mark.parametrize(
    "q",
    [
        "How bright is the seminar room 3.13 at the moment?",
        "How noisy is meeting room 4.11 now?",
        "how warm is lab 2.05",
    ],
)
def test_a_comfort_reading_of_a_named_room_is_recognised(q):
    from orchestrator.services.routing_contract import comfort_reading_of_a_named_room

    assert comfort_reading_of_a_named_room(q)


@pytest.mark.parametrize(
    "q",
    [
        "How bright is the future of smart buildings?",
        "Which seminar rooms have a projector?",
        "When does the seminar in room 3.13 start?",
    ],
)
def test_other_questions_are_not_comfort_readings(q):
    from orchestrator.services.routing_contract import comfort_reading_of_a_named_room

    assert not comfort_reading_of_a_named_room(q)


# ── BUG-1567: a lay term inside a longer lay term of another concept is not evidence ───────


def _m(cid, term):
    from orchestrator.services.concept_resolver import ConceptMatch

    return ConceptMatch(concept_id=cid, lay_term=term, brick_classes=["brick:X"], confidence="high")


def test_carbon_inside_carbon_monoxide_does_not_resolve_the_footprint_concept():
    from orchestrator.services.concept_resolver import drop_subsumed

    text = "is carbon monoxide being detected anywhere right now?"
    kept = drop_subsumed(
        [_m("carbon_monoxide", "carbon monoxide"), _m("carbon_footprint", "carbon")], text
    )
    assert [m.concept_id for m in kept] == ["carbon_monoxide"]


def test_a_term_that_also_stands_alone_keeps_its_concept():
    from orchestrator.services.concept_resolver import drop_subsumed

    text = "how much carbon did we emit, and what is the carbon monoxide level?"
    kept = drop_subsumed(
        [_m("carbon_monoxide", "carbon monoxide"), _m("carbon_footprint", "carbon")], text
    )
    assert {m.concept_id for m in kept} == {"carbon_monoxide", "carbon_footprint"}


# ── BUG-1568: "the open work orders" is not an order to open anything ───────────────────────


@pytest.mark.parametrize(
    "q,want",
    [
        ("List the open work orders for the lifts.", False),
        ("Is there an open window on floor 3?", False),
        ("Open the windows on floor 2.", True),
        ("Please open the door to room 1.06", True),
        ("Turn off the lights in room 1.06.", True),
        ("Unlock all the doors", True),
    ],
)
def test_an_adjective_is_not_a_command(q, want):
    from orchestrator.services.semantic_router import SemanticRouter

    assert SemanticRouter.is_control_command(q) is want


# ── BUG-1569: a room named by kind and id, and a booking request, in the events lane ───────


def _svc():
    from orchestrator.services.event_query_service import EventQueryService

    return EventQueryService("bldgX", None, ["Room_1.06", "Room_1.07", "Room_2.13"])


def test_a_room_is_resolved_by_its_id_when_the_question_does_not_say_room():
    assert _svc().resolve_room("Is computer lab 1.07 free now?") == "Room_1.07"
    assert _svc().resolve_room("is 2.13 free this afternoon") == "Room_2.13"


def test_an_unknown_id_resolves_to_nothing():
    assert _svc().resolve_room("Is lab 9.99 free now?") is None


@pytest.mark.parametrize(
    "q,kind",
    [
        ("Can I book room 2.13 for tomorrow afternoon?", "availability_check"),
        ("Could we reserve room 1.06 on Friday morning?", "availability_check"),
        ("Can I book a meeting room tomorrow?", "availability_list"),
    ],
)
def test_a_booking_request_is_an_availability_question(q, kind):
    from orchestrator.services.event_query_service import classify_event_question

    assert classify_event_question(q) == kind


def test_a_booking_request_answer_says_the_booking_is_not_made_here():
    from orchestrator.services.event_query_service import booking_request_note

    assert booking_request_note("Can I book room 2.13 for tomorrow afternoon?")
    assert booking_request_note("Is room 2.13 free tomorrow?") == ""


# ── BUG-1570: a chart caption is in building time ─────────────────────────────────────────


def test_the_caption_period_is_shown_in_building_time():
    from orchestrator.services import chart_policy as cp

    rows = [
        {"uuid": "u", "timestamp": "2026-10-08 14:30:00", "value": 1},
        {"uuid": "u", "timestamp": "2026-10-10 14:27:00", "value": 2},
    ]
    meta = {"u": {"label": "Room 1.01 temperature", "unit": "°C"}}
    assert "8 Oct 15:30 to 10 Oct 15:27" in cp.caption_header(rows, meta, tz_name="Europe/London")
    # No zone given: the stored times, as before.
    assert "8 Oct 14:30 to 10 Oct 14:27" in cp.caption_header(rows, meta)


# ── BUG-1571: a floor-named total is answered for that floor ───────────────────────────────


def test_a_floor_only_place_is_recognised():
    from orchestrator.services.aggregate_support import names_only_floors

    assert names_only_floors("How much water did floor 2 use this week?") == {"2"}
    assert names_only_floors("How much water did room 2.05 use this week?") is None
    assert names_only_floors("How much water did the building use this week?") is None


def test_the_breakdown_window_is_aligned_to_building_midnight_in_winter():
    from orchestrator.services import aggregate_breakdown as ab

    assert ab.aligned_start(datetime(2026, 1, 10, 9, 5), ab.DAY, "Europe/London") == datetime(
        2026, 1, 10, 0, 0
    )


# ── BUG-1580: PV generation follows the sun ──────────────────────────────────────────────


def _signal():
    import sys
    from pathlib import Path

    d = str(Path(__file__).resolve().parents[1] / "mysql-dummy-publish-dev")
    if d not in sys.path:
        sys.path.insert(0, d)
    return pytest.importorskip("sensor_signal")


def test_pv_output_is_zero_at_night_and_peaks_near_solar_noon():
    s = _signal()
    night = s.solar_fraction(datetime(2026, 10, 9, 1, 0))
    noon = s.solar_fraction(datetime(2026, 10, 9, 12, 0))  # 13:00 BST
    morning = s.solar_fraction(datetime(2026, 10, 9, 8, 0))
    assert night == 0.0
    assert noon > morning > 0.0


def test_pv_next_value_is_never_negative_and_zero_at_night():
    s = _signal()
    s.reset_state()
    v, _ = s.next_value("pv-test", "pv_kw", 0.0, 6.0, 2, datetime(2026, 10, 9, 2, 0))
    assert v == 0.0
    v, _ = s.next_value("pv-test", "pv_kw", 0.0, 6.0, 2, datetime(2026, 10, 9, 12, 0))
    assert 0.0 < v <= 6.0


def test_the_map_gives_pv_points_the_solar_shape_and_nothing_else():
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from derive_generation_shapes import PV_SHAPE, mark_generation_shapes

    points = {"a": {"value_col": "kwh"}, "b": {"value_col": "kwh"}}
    assert mark_generation_shapes(points, ["a", "missing"]) == 1
    assert points["a"]["value_col"] == PV_SHAPE and points["b"]["value_col"] == "kwh"


# ── BUG-1582: energy from power readings is an integral ──────────────────────────────────


def test_energy_from_power_is_integrated_not_summed():
    import asyncio
    from types import SimpleNamespace

    from orchestrator.services import aggregate_lane as al

    t0 = datetime(2026, 10, 9, 0, 0)
    agg = al.SensorAgg(
        uuid="pv1", n=97, total=97 * 2.0, first=t0, last=datetime(2026, 10, 10, 0, 0)
    )

    async def ready(members, storage_map, adapter_for, store_key):
        return {"s": (object(), list(members))}, []

    async def run_aggregates(adapter, members, window, limit, bands):
        return [agg], []

    orig = (al._stores_ready, al.run_aggregates)
    al._stores_ready, al.run_aggregates = ready, run_aggregates
    try:
        res = asyncio.run(
            al._answer_power_energy(
                "How much solar energy did we generate yesterday?",
                al.AggregateIntent("total", "building"),
                ["pv1"],
                {"pv1": "s"},
                {"pv1": SimpleNamespace(unit="kW", label="PV array 1", floor="")},
                al.Window("2026-10-09 00:00:00", "2026-10-09 23:59:59", "yesterday"),
                lambda k: None,
                lambda k: k,
                " in the building",
            )
        )
    finally:
        al._stores_ready, al.run_aggregates = orig
    # 2 kW held for 24 hours (97 readings 15 minutes apart) is 48 kWh, not 194.
    assert res and res["formatted_response"].startswith("**About 48 kWh was generated")


def test_a_bare_unit_token_is_displayed_as_a_reader_writes_it():
    from orchestrator.services.modality_units import display_unit

    assert display_unit("degC") == "°C"


def test_the_entity_templates_project_the_qudt_unit():
    import inspect

    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent)
    assert "SELECT DISTINCT ?sensor ?label ?type ?uuid ?storage ?unit WHERE" not in src
    assert src.count("?storage ?unit ?qunit WHERE") >= 2


def test_a_stated_db_limit_matches_a_noise_measurand():
    from orchestrator.services import aggregate_lane as al

    q = "Has the noise anywhere gone over 70 dB today?"
    for measurand in ("sound", "noise", "sound level"):
        t = al.asked_threshold(measurand, q)
        assert t is not None and t.value == 70.0 and t.unit == "dB"
    assert al.asked_threshold("co2", q) is None


def test_an_indoor_question_leaves_out_the_outdoor_sensor():
    from types import SimpleNamespace

    from orchestrator.services import aggregate_lane as al

    outside = SimpleNamespace(brick_class="brick:Outside_Air_Humidity_Sensor", room="", label="")
    exterior = SimpleNamespace(brick_class="", room="Building exterior", label="")
    room = SimpleNamespace(brick_class="brick:Zone_Air_Humidity_Sensor", room="Room 2.01", label="")
    assert al._is_outdoor(outside) and al._is_outdoor(exterior) and not al._is_outdoor(room)
    q = "Were any rooms more than 60% humidity this week?"
    assert al._INDOOR_WORDS.search(q) and not al._OUTDOOR_WORDS.search(q)
    assert al._OUTDOOR_WORDS.search("Was it more humid outside than in the rooms?")


def test_pm2_5_is_a_pollutant_not_a_room():
    from orchestrator.services.building_metrics import is_inventory_count_question

    assert is_inventory_count_question("How many PM2.5 sensors does the building have?")
    assert not is_inventory_count_question("How many sensors are there in 2.13?")


def test_an_expiry_verb_asks_for_a_date_not_the_expired_state():
    import re

    from orchestrator.services import register_projection as rp

    src = __import__("inspect").getsource(rp)
    # The verb forms are stripped before the state is matched, for any opening word.
    assert re.search(r"expir\(\?:e\|es\|ing\|y\|ies\)", src)


def test_a_change_question_is_not_a_period_summary():
    from orchestrator.services import aggregate_lane as al

    assert al.parse_intent("Has the CO2 in lab 2.05 gone up since this morning?") is None
    assert al.parse_intent("Did the temperature on floor 3 go down overnight?") is None
    assert al.parse_intent("What was the average CO2 on floor 2 yesterday?") is not None


def test_a_comparative_question_gets_a_yes_or_no_first():
    from orchestrator.services.comparison_lane import comparative_lead

    q = "Was floor 2 noisier yesterday than the day before?"
    assert comparative_lead(q, "Floor 2 mean", 50.1, 50.5).startswith("**No — the Floor 2 average")
    assert comparative_lead(q, "Floor 2 mean", 51.0, 50.5).startswith("**Yes")
    assert comparative_lead("Compare CO2 this week with last week", "building mean", 1, 2) == ""
    # A choice is not a yes/no question.
    assert comparative_lead("Which day was warmer, Monday or Tuesday?", "x mean", 1, 2) == ""
    assert comparative_lead("Is it warmer this week or last week?", "x mean", 1, 2) == ""


def test_will_it_get_stuffy_is_answered_against_the_listed_band():
    from orchestrator.services.forecasting.window_aggregate import comfort_verdict

    idx = ["2026-10-11 %02d:00:00" % h for h in range(24)]
    low = comfort_verdict(
        "Will room 2.01 get stuffy tomorrow?",
        idx,
        [700.0] * 24,
        [650.0] * 24,
        [750.0] * 24,
        unit="ppm",
        horizon_label="next 24 hours",
        tz_name="Europe/London",
    )
    high = comfort_verdict(
        "Will room 2.01 get stuffy tomorrow?",
        idx,
        [1200.0] * 24,
        [1100.0] * 24,
        [1300.0] * 24,
        unit="ppm",
        horizon_label="next 24 hours",
        tz_name="Europe/London",
    )
    assert low.startswith("**Unlikely:**") and high.startswith("**Likely yes:**")
    # A unit that is not the measurand's gives no verdict rather than a comparison across units.
    assert comfort_verdict("Will it get stuffy?", idx, [1.0] * 24, [], [], unit="kWh") is None
    assert comfort_verdict("Forecast CO2 tomorrow", idx, [1200.0] * 24, [], [], unit="ppm") is None


def test_a_caption_does_not_repeat_a_unit_the_labels_state():
    from orchestrator.services import chart_policy as cp

    rows = [{"uuid": "a", "timestamp": "2026-10-08 12:00:00", "value": 1}]
    meta = {"a": {"label": "PV Array 1 (kW)", "unit": "kW"}}
    assert "(kW) (kW)" not in cp.caption_header(rows, meta)


def test_a_forecast_scope_drops_the_possessive():
    from orchestrator.services.forecasting.scope import detect

    s = detect("Forecast the building's electricity use for tomorrow.")
    assert s is not None and s.scope_only == "the building"


def test_energy_per_floor_over_a_period_is_answered_in_the_store():
    from orchestrator.services import aggregate_lane as al

    q = "Make a bar chart of electricity use per floor this week."
    assert al.wants_lane(q, 6, False, True, ["energy"]).stat == "total"
    # 2026-10-11: a building total over a COMPLETED period ("yesterday") is now claimed too -- the
    # analytics narration invented its year -- and measured to move 0 of the 4,060 bank questions.
    # A period still running stays with the period summary.
    assert (
        al.wants_lane(
            "How much electricity has the building used this week?", 6, False, True, ["energy"]
        )
        is None
    )


def test_an_energy_rating_is_not_a_consumption_question():
    from orchestrator.services.routing_contract import _ENERGY_RATING_RE

    assert _ENERGY_RATING_RE.search("What is the building's energy rating?")
    assert _ENERGY_RATING_RE.search("Does it have an EPC?")
    assert not _ENERGY_RATING_RE.search("How much energy did floor 2 use?")


def test_when_was_the_building_opened_reads_the_build_year():
    from orchestrator.services.building_profile import detect_facet

    assert detect_facet("When was the building opened?") == "age"
    assert detect_facet("When was the meeting room opened?") is None


def test_gone_up_since_this_morning_compares_the_last_hour_with_the_morning():
    from orchestrator.services import aggregate_lane as al
    from orchestrator.services import comparison_windows as cw
    from orchestrator.services.comparison_lane import comparative_lead

    q = "Has the CO2 in lab 2.05 gone up since this morning?"
    pair = cw.since_morning_pair(q, "Europe/London", datetime(2026, 10, 10, 14, 52))
    assert pair is not None
    assert pair.baseline.start == "2026-10-10 05:00:00"  # 06:00 BST
    assert pair.current.end == "2026-10-10 14:52:00"
    assert al.parse_intent(pair.lane_question).stat == "mean"
    # Too early in the day for a morning to compare with.
    assert cw.since_morning_pair(q, "Europe/London", datetime(2026, 10, 10, 5, 30)) is None
    assert comparative_lead(q, "Room 2.05 mean", 891.0, 848.0).startswith("**Yes")


def test_a_count_question_gets_its_own_figure_first():
    from orchestrator.services.building_metrics import (
        BuildingMetricsSnapshot,
        asked_figure_lead,
        render_metrics_block,
    )

    snap = BuildingMetricsSnapshot(
        total_sensors=100,
        floor_count=8,
        floor_kinds=[("Floor", 6), ("Rooftop", 1), ("Parking_Level", 1)],
        room_count=50,
    )
    lead = asked_figure_lead(snap, "B", "How many floors does the building have?")
    assert lead.startswith("**B has 6 storeys.**") and "8 in all" in lead
    assert asked_figure_lead(snap, "B", "How many rooms are there?").startswith("**B has 50 rooms")
    assert asked_figure_lead(snap, "B", "Tell me about the building") == ""
    block = render_metrics_block(snap, "B", question="How many floors does the building have?")
    assert block.startswith("**B has 6 storeys.**")


def test_this_week_or_last_week_is_two_periods_but_co2_or_temperature_is_not():
    from orchestrator.services import comparison_windows as cw

    assert cw.split_question("Is floor 3 warmer this week or last week?") == (
        "Is floor 3 warmer this week",
        "last week?",
    )
    assert cw.split_question("Is CO2 or temperature higher on floor 2 today?") is None


def test_the_breakdown_window_is_aligned_to_building_midnight():
    from orchestrator.services import aggregate_breakdown as ab

    assert ab.aligned_start(datetime(2026, 1, 10, 9, 5), ab.DAY, "Europe/London") == datetime(
        2026, 1, 10, 0, 0
    )
