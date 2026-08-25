# -*- coding: utf-8 -*-
"""Plant / BMS telemetry as a first-class source (V6-T26).

Master Package D asks for the BMS to be **integrated, not duplicated**: the points a control
system already holds should become answerable rather than being re-instrumented with a second
set of IoT sensors that then disagree with the first.

The integration itself is config — six modalities in `saturation_modalities.yaml` carrying
`scope: equipment`, each Brick class verified present in the shipped TBox. What needed code was
the **join**: the path from a space to the plant serving it, so a diagnosis can say *the AHU's
fan ran 0% of the window* instead of *ventilation is probably insufficient*.

Four properties here were each a live defect first, and each is the kind that returns quietly:

1. **The topology is the one the graph actually has.** An AHU feeds an `HVAC_Zone`, never a
   Room — 0 direct against 73 zone-mediated on bldg1. The obvious query returns nothing.
2. **Equivalent Brick classes must not annihilate.** The most-specific-class filter, written
   without its inner guard, deleted supply-air temperature entirely because Brick declares it
   equivalent to discharge-air temperature and each is then a subclass of the other.
3. **The point count is a number in an answer.** Reasoning returns one point once per matched
   superclass; unguarded that reported 9 points for 7.
4. **An empty config must fail loudly.** `plant_modalities()` read the wrong key first and
   returned `[]` with no exception — a plant lane silently certain the building had no plant.
"""

import re
from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.plant_state import (
    PlantContext,
    build_query,
    context_from_rows,
    equipment_query,
    plant_brick_classes,
    plant_modalities,
    preferred_classes,
)

pytestmark = pytest.mark.unit

SPACE = "http://x#Room5.01"


def _plant_state_body(src: str) -> str:
    """Just the `_plant_state` method.

    Bounded at the next sibling definition on purpose: slicing to a marker further down the
    file swept in the pre-existing heuristic causes and made the score assertion below read
    their numbers instead of the plant ones. A test that measures the wrong region is the
    same failure as a grader that reads the wrong key.
    """
    start = src.index("    async def _plant_state")
    rest = src[start + 10 :]
    ends = [
        m
        for m in (
            rest.find("\n    async def "),
            rest.find("\n    def "),
            rest.find("\n    @staticmethod"),
        )
        if m > 0
    ]
    return rest[: min(ends)] if ends else rest


def _row(point, equip, cls, uuid="", label=""):
    return {"point": point, "equip": equip, "cls": cls, "uuid": uuid, "label": label}


# ── the config is actually read (positive control) ───────────────────────────


def test_the_shipped_config_declares_equipment_scoped_modalities():
    """A POSITIVE CONTROL, not a formality.

    The first implementation read `raw.get("modalities")` from a function that returns the
    modality map itself. It returned `[]`, raised nothing, and every downstream check passed
    while the plant lane believed the building had no plant. An empty list is a legal value
    here, so only an assertion that it is NON-empty can catch the wiring being wrong.
    """
    mods = plant_modalities()
    assert mods, (
        "no equipment-scoped modalities found — either the config lost them or the reader is "
        "looking at the wrong key again (the failure that returns [] instead of raising)"
    )
    assert "fan_state" in mods and "damper_position" in mods


def test_every_equipment_modality_contributes_brick_classes():
    classes = plant_brick_classes()
    assert classes
    assert "Fan_Status" in classes
    assert "Damper_Position_Sensor" in classes


def test_preferred_classes_come_from_config_not_a_hardcoded_list():
    """The tie-break between equivalent class names must be config-driven, or it is a
    building literal in building-agnostic code."""
    prefs = preferred_classes()
    assert "Supply_Air_Temperature_Sensor" in prefs
    assert set(prefs).issubset(set(plant_brick_classes()))


# ── the query matches the graph's real shape ─────────────────────────────────


def test_the_query_traverses_the_zone_because_an_ahu_never_feeds_a_room():
    """Measured on bldg1: 0 AHU→Room, 73 AHU→HVAC_Zone. Written the obvious way, this
    returned nothing for every room in the building."""
    q = build_query(SPACE, ["Fan_Status"])
    assert f"?equip brick:feeds <{SPACE}>" in q, "the direct path is missing"
    assert f"?zone brick:isPartOf <{SPACE}>" in q, (
        "the zone-mediated path is missing — this is the ONLY path that resolves on a "
        "building modelled the way Brick recommends"
    )
    assert "UNION" in q


def test_the_specificity_filter_cannot_annihilate_equivalent_classes():
    """Brick declares Supply_Air_Temperature_Sensor and Discharge_Air_Temperature_Sensor
    equivalent, so under reasoning each is a subclass of the other. Without the inner guard
    both are filtered and the point VANISHES — a connected sensor reported as absent, which
    is worse than the duplicate the filter exists to remove. Observed live."""
    q = build_query(SPACE, ["Supply_Air_Temperature_Sensor"])
    outer = q[q.index("FILTER NOT EXISTS") :]
    assert (
        outer.count("FILTER NOT EXISTS") >= 2
    ), "the equivalence guard is gone; equivalent classes will delete each other"
    assert "?cls rdfs:subClassOf ?sub" in outer


def test_no_proximity_or_name_matching_anywhere_in_the_query():
    """Both hops must be asserted triples. Inferring containment from a name or a floor
    number is how BUG-189 produced a confident answer about a room that did not exist."""
    q = build_query(SPACE, ["Fan_Status"]) + equipment_query(SPACE)
    for banned in ("CONTAINS", "REGEX", "STRSTARTS", "nearest", "distance"):
        assert banned.lower() not in q.lower(), f"{banned} implies an inferred relationship"


def test_equipment_query_is_asked_separately_from_points():
    """'no equipment declared' and 'equipment declared but unconnected' are different
    answers for different people, so they cannot collapse into one empty result."""
    assert "isPointOf" not in equipment_query(SPACE)
    assert "brick:feeds" in equipment_query(SPACE)


# ── counting ─────────────────────────────────────────────────────────────────


def test_one_point_returned_under_two_classes_counts_once():
    """Reasoning yields a row per matched superclass. Unguarded this reported 9 points for
    7 — a fabricated number in a user-facing sentence, not a cosmetic duplicate."""
    rows = [
        _row("http://x#P1", "http://x#AHU", "http://x#Filter_Differential_Pressure_Sensor", "u1"),
        _row("http://x#P1", "http://x#AHU", "http://x#Differential_Pressure_Sensor", "u1"),
    ]
    ctx = context_from_rows(SPACE, rows, [])
    assert len(ctx.points) == 1
    assert "1 point(s)" in ctx.describe()


def test_the_row_carrying_a_uuid_wins():
    """A point with no timeseries id cannot be read. Keeping the unreadable duplicate would
    make a connected point look unconnected — the exact inversion of the truth."""
    rows = [
        _row("http://x#P1", "http://x#AHU", "http://x#Fan_Status", ""),
        _row("http://x#P1", "http://x#AHU", "http://x#Fan_Status", "u1"),
    ]
    ctx = context_from_rows(SPACE, rows, [])
    assert ctx.points[0].uuid == "u1"


def test_duplicate_resolution_is_deterministic():
    """The same question must name the same point the same way between runs."""
    rows = [
        _row("http://x#P1", "http://x#AHU", "http://x#Discharge_Air_Temperature_Sensor", "u1"),
        _row("http://x#P1", "http://x#AHU", "http://x#Supply_Air_Temperature_Sensor", "u1"),
    ]
    first = context_from_rows(SPACE, rows, []).points[0].kind
    second = context_from_rows(SPACE, list(reversed(rows)), []).points[0].kind
    assert first == second, "the surviving class name depends on row order"
    assert first == "Supply_Air_Temperature_Sensor", "config preference was not applied"


# ── honesty of absence ───────────────────────────────────────────────────────


def test_equipment_declared_but_unconnected_says_so_and_names_the_remedy():
    """'No plant data' reads as 'nothing is wrong with the plant'. They are opposite messages
    to a facilities team, so the absence branch must name what would answer the question."""
    ctx = context_from_rows(SPACE, [], [{"equip": "http://x#AHU_F5"}])
    text = ctx.describe()
    assert "AHU_F5" in text
    assert "no plant points are connected" in text
    assert "cannot say" in text, "the sentence does not admit the limit"
    assert "Connecting the BMS points" in text, "no remedy offered"


def test_no_equipment_at_all_is_reported_as_a_graph_gap_not_a_finding():
    text = PlantContext(space_iri=SPACE).describe()
    assert "gap in the graph" in text
    assert "not a finding about the plant" in text


def test_plant_state_is_labelled_as_equipment_never_as_the_room():
    """A supply-air temperature of 14 °C is a fact about the duct. Presenting it as the room's
    reading is the substitution the non-substitution rule forbids."""
    rows = [_row("http://x#P1", "http://x#AHU_F5", "http://x#Fan_Status", "u1")]
    text = context_from_rows(SPACE, rows, []).describe()
    assert "EQUIPMENT, not the room" in text
    assert "AHU_F5" in text


# ── routing ──────────────────────────────────────────────────────────────────


class TestPlantRouting:
    """Measured live with the points connected and readable: three of five plant questions
    were answered from documents by the pre-LLM capability probe. Fourth member of BUG-231's
    family, after wayfinding, deliberation and event-store questions."""

    @pytest.mark.parametrize(
        "q",
        [
            "What is the filter differential pressure on AHU_F5?",
            "Is the supply fan running on floor 5?",
            "What is the damper position of VAV_Floor5_West?",
            "What is the supply air temperature of the air handling unit on floor 5?",
        ],
    )
    def test_plant_questions_are_recognised(self, q):
        from orchestrator.services.routing_contract import plant_point_question

        assert plant_point_question(q), f"{q!r} will be answered from a document"

    @pytest.mark.parametrize(
        "q",
        [
            "What is the air temperature in room 5.01?",
            "how warm is it in 5.16?",
            "what is the co2 in 5.01?",
            "how many people are in the building?",
            "show me floor 3",
            "is room 5.01 free?",
        ],
    )
    def test_room_questions_are_not_dragged_into_the_plant_lane(self, q):
        """The costlier direction. Answering "how warm is 5.16" from a duct sensor would be a
        wrong answer that looks right, where a misrouted plant question merely looks unhelpful."""
        from orchestrator.services.routing_contract import plant_point_question

        assert not plant_point_question(q), f"{q!r} would be answered from plant telemetry"

    def test_the_measurand_vocabulary_is_derived_from_config(self):
        """A building declaring a seventh equipment-scoped modality must be recognised without
        a code change — the portability claim this whole turn rests on."""
        from orchestrator.services.routing_contract import _plant_measurand_re

        pattern = _plant_measurand_re().pattern
        for mod in plant_modalities():
            head = re.escape(mod.split("_")[0])
            assert head in pattern, f"{mod} contributed nothing to the pattern"

    def test_the_capability_probe_bypasses_plant_questions(self):
        from pathlib import Path

        src = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
        assert "plant_point_question as _plant_point_question" in src
        assert (
            "not _plant_point_question(user_query)" in src
        ), "plant questions still have no bypass; documents will answer them first"

    def test_the_contract_routes_plant_questions_to_sensor_data(self):
        from orchestrator.services.routing_contract import apply_contract

        for q in (
            "What is the filter differential pressure on AHU_F5?",
            "Is the supply fan running?",
        ):
            st = {"intent": "capability", "concepts": [], "entities": []}
            apply_contract(q, st, stage="parse")
            assert st["intent"] == "sensor_data", f"{q!r} routed to {st['intent']}"


# ── diagnosis integration ────────────────────────────────────────────────────


def test_diagnosis_gathers_plant_state_and_publishes_its_figures():
    """Live before this: "why is room 5.01 stuffy?" reported the CO2 mean and then GUESSED —
    "the elevated average suggests that ventilation is insufficient" — while the fan state and
    damper position were connected and readable. A guess phrased as a suggestion is still a
    claim the data does not support.

    The figures must reach the payload: the numeric guard refuses an answer whose prose carries
    numbers the evidence does not, which is what caught the T24 note.
    """
    from pathlib import Path

    src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
    assert "async def _plant_state" in src
    assert "causes.extend(plant_notes)" in src, "plant findings never reach the cause list"
    assert '"plant": plant_figures' in src, (
        "plant figures are not in the payload; the numeric guard will refuse any answer "
        "quoting a fan percentage or damper position"
    )
    body = _plant_state_body(src)
    assert "except Exception" in body, "a plant lookup failure must not cost the diagnosis"
    assert 'figures["plant_note"]' in body, "unconnected plant is not named in the payload"


def test_a_measured_plant_cause_outranks_the_heuristic_ones():
    """A fan that is actually off is evidence; "systems often run a setback schedule" is a
    guess. If the guess can outrank the measurement the ranking is inverted."""
    from pathlib import Path

    src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
    body = _plant_state_body(src)
    scores = [float(m) for m in re.findall(r"\(\s*(\d+\.\d+)\s*,\s*\n?\s*f?\"", body)]
    assert scores, "no scored plant causes found"
    assert min(scores) > 2.0, (
        f"plant causes score {scores}, which does not beat the time-coincidence heuristics "
        "(1.0-2.0) they are meant to supersede"
    )


# ── the diagnosis lane must actually be reachable ────────────────────────────


class TestWhyQuestionsReachDiagnosis:
    """Wiring the diagnosis lane to plant state is worthless if no question reaches it.

    Measured live: "Why is room 5.01 stuffy?" was classified `capability` by the LLM, and
    `capability_measurand_is_data` -- which runs in an EARLIER stage than `why_diagnosis`, and
    claims first because rules stop at the first match -- converted it to `sensor_data`. The
    diagnosis lane never ran. The answer reported the CO2 mean and then guessed at the cause
    while the fan state and damper position that would have answered it were connected and
    readable.

    This predates V6-T26: every why-question the classifier labelled `capability` skipped the
    V5-T20 diagnosis lane entirely.
    """

    @pytest.mark.parametrize(
        "q",
        [
            "Why is room 5.01 stuffy?",
            "Why is 5.16 so warm?",
            "Why is it stuffy in room 5.01?",
        ],
    )
    def test_a_why_question_reaches_diagnosis_from_capability(self, q):
        from orchestrator.services.routing_contract import apply_contract

        st = {"intent": "capability", "concepts": [{"brick_classes": ["brick:CO2_Level_Sensor"]}]}
        for stage in ("parse", "concept", "post"):
            apply_contract(q, st, stage=stage)
        assert st["intent"] == "diagnosis", (
            f"{q!r} routed to {st['intent']} — the diagnosis lane is unreachable for this "
            "phrasing, so plant state can never be cited no matter how it is wired"
        )

    @pytest.mark.parametrize(
        "q",
        [
            "What is the CO2 in room 5.01?",
            "How stuffy is it in 5.16?",
        ],
    )
    def test_ordinary_measurand_questions_still_reach_the_data_lane(self, q):
        """The guard must be narrow. BUG-225's rule exists because the capability lane
        absorbed 88% of measurement questions; taking anything more than why-questions from it
        would reopen that."""
        from orchestrator.services.routing_contract import apply_contract

        st = {"intent": "capability", "concepts": [{"brick_classes": ["brick:CO2_Level_Sensor"]}]}
        for stage in ("parse", "concept", "post"):
            apply_contract(q, st, stage=stage)
        assert st["intent"] in (
            "sensor_data",
            "analytics",
        ), f"{q!r} routed to {st['intent']} — the measurand rule stopped working"


# ── the diagnosis lane's own honesty ─────────────────────────────────────────


class TestDiagnosisHonestyPaths:
    """Two defects the diagnosis lane carried while it was effectively unreachable.

    Both surfaced only once why-questions actually started arriving there, which is the point
    worth remembering: a lane nothing routes to accumulates defects nobody can see.
    """

    def test_the_no_data_reply_carries_its_referent_so_the_guard_cannot_suppress_it(self):
        """A room name is numerically indistinguishable from a reading.

        "I have no co2 readings for Room 5.01" was destroyed by the numeric guard — "5.01"
        appeared in the prose and in no payload field, so a correct, useful honest answer was
        replaced with "a number in the text could not be traced back to the underlying data".
        The mechanism built to protect honesty deleted an honest answer. Same shape as
        BUG-242, where a report id was judged as a sensor reading.
        """
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        head = src.index("if window_mean is None:")
        block = src[head : head + 1600]
        assert '"referent": label' in block, (
            "the no-data reply still omits the referent; the numeric guard will suppress every "
            "room-scoped 'no readings' message"
        )

    def test_the_referent_matcher_normalises_both_sides(self):
        """The token dropped "." and the label kept it, so "5.01" -> "501" was compared with
        "room 5.01". That match could never succeed for ANY label form, so every room-scoped
        why-question silently fell through to a whole-building average — a wrong-scope answer
        that reads exactly like a right one."""
        from orchestrator.services.anomaly.diagnosis import DiagnosisService, _squash

        class _S:
            def __init__(self, label):
                self.label = label
                self.floor = "5"
                self.space_iri = "http://x#" + label
                self.modalities = {}

        for label in ("Room 5.01", "Room5.01", "Room_5.01", "Room 5.01 — Research Laboratory"):
            kind, hits = DiagnosisService.resolve_referent("why is room 5.01 stuffy", [_S(label)])
            assert kind == "room", f"{label!r} fell through to {kind} scope"
            assert hits and hits[0].label == label

        assert _squash("Room 5.01") == "room501"

    def test_a_room_question_does_not_match_an_unrelated_room(self):
        """Normalising more aggressively must not make the matcher looser about WHICH room."""
        from orchestrator.services.anomaly.diagnosis import DiagnosisService

        class _S:
            def __init__(self, label):
                self.label = label
                self.floor = "5"
                self.space_iri = "http://x#" + label
                self.modalities = {}

        kind, hits = DiagnosisService.resolve_referent(
            "why is room 5.01 stuffy", [_S("Room 5.02"), _S("Room 2.14")]
        )
        assert kind != "room" or not hits, "matched a room the question did not name"

    def test_identical_causes_are_not_listed_four_times(self):
        """Live: "a sensor reporting gap overlaps the window" appeared as explanations 1, 2, 3
        and 4 — one per overlapping episode. Repetition reads as corroboration; it was the same
        fact four times."""
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert "_seen_cause" in src, "duplicate causes are still emitted as separate explanations"
        assert src.index("_seen_cause") < src.index(
            "causes.sort(key=lambda c: -c[0])"
        ), "dedup must run before ranking, or duplicates occupy the top slots"


# ── the two SPARQL executor shapes ───────────────────────────────────────────


class TestExecutorShapes:
    """`for_space` is called with TWO different executors in this codebase, and they return
    different things.

    * `ontology_manager.run_sparql_select` -> {"ok": bool, "rows": [{col: value}]}
    * `deliberation.live.sparql_exec`      -> raw SPARQL-JSON {"results": {"bindings": [...]}}

    Written against only the first, this module was handed the second by the diagnosis lane.
    The mismatch raised inside a broad `except`, and the caller got an empty context that
    rendered as **"No equipment is declared as serving this space"** — fluent, plausible, and
    false about a room served by an AHU and a VAV with seven connected points. The diagnosis
    lane therefore never cited plant state, while every unit test here passed.

    Anything that touches an executor must be exercised against BOTH shapes.
    """

    @staticmethod
    def _sparql_json():
        return {
            "results": {
                "bindings": [
                    {
                        "point": {"value": "http://x#AHU_F5_Fan_Status"},
                        "equip": {"value": "http://x#AHU_F5"},
                        "cls": {"value": "http://x#Fan_Status"},
                        "uuid": {"value": "u1"},
                    }
                ]
            }
        }

    @staticmethod
    def _rows_shape():
        return {
            "ok": True,
            "rows": [
                {
                    "point": "http://x#AHU_F5_Fan_Status",
                    "equip": "http://x#AHU_F5",
                    "cls": "http://x#Fan_Status",
                    "uuid": "u1",
                }
            ],
        }

    def test_rows_of_reads_the_rows_shape(self):
        from orchestrator.services.evidence.plant_state import rows_of

        got = rows_of(self._rows_shape())
        assert len(got) == 1 and got[0]["uuid"] == "u1"

    def test_rows_of_reads_raw_sparql_json(self):
        from orchestrator.services.evidence.plant_state import rows_of

        got = rows_of(self._sparql_json())
        assert len(got) == 1, "SPARQL-JSON bindings were not unwrapped"
        assert got[0]["uuid"] == "u1", "binding values were not unwrapped from {'value': ...}"
        assert got[0]["equip"] == "http://x#AHU_F5"

    def test_rows_of_is_empty_for_nothing_rather_than_raising(self):
        from orchestrator.services.evidence.plant_state import rows_of

        for empty in (None, {}, {"ok": False}, {"results": {}}):
            assert rows_of(empty) == []

    @pytest.mark.asyncio
    async def test_for_space_works_with_a_raw_sparql_json_executor(self):
        """The executor the diagnosis lane actually passes. This is the test whose absence let
        the bug ship."""
        from orchestrator.services.evidence.plant_state import for_space

        payload = self._sparql_json()

        async def exec_sparql_json(query):
            if "isPointOf" in query:
                return payload
            return {"results": {"bindings": [{"equip": {"value": "http://x#AHU_F5"}}]}}

        ctx = await for_space("http://x#Room5.01", exec_sparql_json)
        assert ctx.has_points, "the raw SPARQL-JSON executor still yields an empty context"
        assert ctx.points[0].equipment_name == "AHU_F5"

    @pytest.mark.asyncio
    async def test_for_space_works_with_a_rows_executor(self):
        from orchestrator.services.evidence.plant_state import for_space

        async def exec_rows(query):
            if "isPointOf" in query:
                return self._rows_shape()
            return {"ok": True, "rows": [{"equip": "http://x#AHU_F5"}]}

        ctx = await for_space("http://x#Room5.01", exec_rows)
        assert ctx.has_points
        assert ctx.points[0].equipment_name == "AHU_F5"

    @pytest.mark.asyncio
    async def test_for_space_never_passes_a_limit_keyword(self):
        """One executor accepts `limit`, the other does not. Bounds ride in the query text so a
        single call works for both — probing with a keyword the callee rejects is precisely how
        the mismatch stayed invisible behind the broad except."""
        seen = {}

        async def exec_strict(query):  # no **kwargs on purpose
            seen["query"] = query
            return {"ok": True, "rows": []}

        from orchestrator.services.evidence.plant_state import for_space

        await for_space("http://x#Room5.01", exec_strict)
        assert "LIMIT" in seen.get("query", ""), "the bound is no longer in the query text"

    @pytest.mark.asyncio
    async def test_a_missing_executor_is_an_empty_context_not_a_crash(self):
        from orchestrator.services.evidence.plant_state import for_space

        ctx = await for_space("http://x#Room5.01", None)
        assert not ctx.has_points and "gap in the graph" in ctx.describe()


# ── a low fan runtime is not a finding ───────────────────────────────────────


class TestFanSignalIsCoincidenceNotSchedule:
    """The first version raised the fan as the leading cause whenever it ran under half the
    window. Live, that produced:

        "AHU_F5's supply fan ran for only 39.6% of the window — the space was barely being
        ventilated"

    39.6% of 24 hours is roughly one working day. The system had diagnosed a **normal
    schedule** as the explanation for a warm room: fluent, specific, numerically exact, and
    about nothing. A plausible-sounding diagnosis of nothing is worse than no diagnosis,
    because it stops the search.

    The measured signal is COINCIDENCE — the fan off while the room sat above its own average.
    """

    START = datetime(2026, 8, 1, 0, 0)

    @classmethod
    def _hours(cls, values):
        return [(cls.START + timedelta(hours=i), float(v)) for i, v in enumerate(values)]

    def _off_pct(self, fan, room, mean):
        from orchestrator.services.anomaly.diagnosis import DiagnosisService

        return DiagnosisService._off_while_elevated(
            self._hours(fan), self._hours(room), mean, self.START, self.START + timedelta(hours=24)
        )

    def test_a_normal_overnight_schedule_is_not_a_finding(self):
        """Fan off 00:00-08:00 and 18:00-24:00, room warm only while the fan runs. Runtime is
        41% — under the old threshold — and nothing is wrong."""
        fan = [0] * 8 + [1] * 10 + [0] * 6
        room = [18] * 8 + [24] * 10 + [18] * 6
        pct = self._off_pct(fan, room, 21.0)
        assert pct == 0.0, f"a normal schedule scored {pct}% off-while-elevated"

    def test_a_fan_that_is_off_while_the_room_is_hot_is_a_finding(self):
        """The real fault: the room stays above its average all afternoon with the fan down."""
        fan = [1] * 8 + [0] * 10 + [1] * 6
        room = [18] * 8 + [26] * 10 + [18] * 6
        pct = self._off_pct(fan, room, 21.0)
        assert pct == 100.0, f"an all-afternoon outage scored {pct}%"

    def test_the_threshold_is_stated_where_the_note_is_raised(self):
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert "off_while_elevated" in src
        assert "off_pct >= 50.0" in src, "the coincidence threshold is no longer explicit"

    def test_no_room_series_yields_no_finding_rather_than_a_clean_bill(self):
        """Unknown and fine are different answers."""
        assert self._off_pct([0] * 24, [], 21.0) is None

    def test_no_elevated_samples_yields_no_finding(self):
        """If the room never rose above its own average, there is nothing for the fan to
        explain — and dividing by zero elevated samples would be an invented percentage."""
        assert self._off_pct([0] * 24, [20] * 24, 25.0) is None

    def test_fan_state_is_matched_as_a_step_not_interpolated(self):
        """A reading is matched to the fan sample IN FORCE at that moment. Nearest-in-either-
        direction would let a fan that started later explain an earlier elevation."""
        from orchestrator.services.anomaly.diagnosis import DiagnosisService

        src = DiagnosisService._off_while_elevated.__doc__ or ""
        assert "step function" in src
        # the room is hot for hours 0-3 while the fan is off, then the fan starts
        pct = self._off_pct([0] * 4 + [1] * 20, [26] * 4 + [20] * 20, 21.0)
        assert pct == 100.0

    def test_a_fan_off_every_night_in_a_night_warm_building_is_not_a_finding(self):
        """The schedule problem in its second disguise.

        A fan off overnight, in a building whose rooms are warmest overnight, coincides with the
        elevation 100% of the time — in every room, every night. Raw coincidence therefore
        reproduces exactly the failure the coincidence measure was introduced to fix. The
        finding is LIFT: the fan off MORE during the elevated periods than across the window.
        """
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert "base_off" in src and "lift" in src
        assert "(lift or 0) >= 20.0" in src, "the lift threshold is gone; raw coincidence is back"

    def test_the_note_states_both_figures_so_the_reader_can_judge(self):
        """ "Off 100% of the elevated time" alone is unreadable without the base rate; 100
        against 95 is noise and 100 against 20 is a finding."""
        from pathlib import Path

        src = Path("orchestrator/services/anomaly/diagnosis.py").read_text(encoding="utf-8")
        assert "of the window overall" in src
        assert "concentrated in" in src
