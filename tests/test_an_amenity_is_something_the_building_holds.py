# -*- coding: utf-8 -*-
"""BUG-1333 — the false-absence guard and the router must both see the AMENITY family.

Two defects, one graph, measured live on 2026-09-30/2026-10-01 against a building holding
**24 ``ontosage:ToiletFacility``** (12 of them accessible, two per floor 0–5), 18
``ontosage:AccessibilityFeature`` and 16 ``ontosage:DrinkingWater``:

1. *"None of the recorded series refers to a toilet, restroom, or accessibility facility"* —
   the guard built for exactly that sentence RAN (``describes_retrieval_wide`` returns True on the
   verbatim text) and had nothing to correct with, because ``record_registry.record_classes``
   discovers only ``ontosage:Record``/``ontosage:IntervalRecord`` descendants and a toilet hangs
   off ``ontosage:Amenity``. ``ontosage:AccessibleRoute`` IS a Record, so a ROUTE question was
   protected and a TOILET question was not.
2. *"I couldn't tie that question to a reading I can give you, so I have no figure for it."* —
   the deterministic amenity probe matched **thirty** of the building's own triples and logged
   every one, and the concept-stage rule ``capability_measurand_is_data`` then converted the turn
   to ``sensor_data`` because ``hbco:empty_space`` declares the bare lay term *"available"*.

Every test below uses the question text as a reader typed it. The counterfactuals are marked: each
one fails on the code as it stood before 2026-10-01.
"""

import pytest

from orchestrator.services import absence_wording as aw
from orchestrator.services import routing_contract as rc
from orchestrator.services.record_registry import RecordClass, _terms_for

pytestmark = pytest.mark.unit

#: The question exactly as it was asked live.
TOILET_Q = "Is a Changing Places toilet available in this building?"
LONG_TOILET_Q = (
    "Is a Changing Places toilet available in or near Abacws, and what are the current "
    "verified access arrangements?"
)

#: The answer exactly as it was produced live on 2026-09-30 (BUG-1333's Description).
NARRATED_TOILET_ABSENCE = (
    "I did not find Changing Places toilet at or near Abacws in the records I searched. "
    "None of the recorded series refers to a toilet, restroom, or accessibility facility, and "
    "no access-arrangement data is present in the available records. Because the dataset was "
    "truncated, I cannot confirm whether such a toilet exists elsewhere in the building."
)


def _toilets(n: int = 24) -> RecordClass:
    """The ToiletFacility class as ``held_amenity_classes`` builds it from the live graph."""
    lays = "toilet|toilets|washroom|washrooms|accessible toilet|wc"
    return RecordClass(
        "ToiletFacility",
        "Toilet facility",
        n,
        _terms_for("ToiletFacility", "Toilet facility", lays),
    )


def _circulation() -> RecordClass:
    return RecordClass(
        "CirculationTime",
        "Circulation time",
        21,
        _terms_for("CirculationTime", "Circulation time", "authorised route|walking time"),
    )


# ── 1. the guard can now contradict an absence about an amenity ──────────────────────────


def test_the_guard_had_nothing_to_correct_with_and_that_was_the_whole_defect():
    """COUNTERFACTUAL. Records alone cannot contradict it — this is the OLD behaviour, pinned.

    It must keep passing: the fix adds a second source, it does not change what records do.
    """
    assert aw.describes_retrieval_wide(NARRATED_TOILET_ABSENCE) is True, (
        "the first gate passed live, so the guard ran; if this ever goes False the diagnosis "
        "in BUG-1333 no longer holds and the row must be re-read before anything is changed"
    )
    assert (
        aw.false_absence_note(
            NARRATED_TOILET_ABSENCE, TOILET_Q, [_circulation()], "Abacws Building"
        )
        is None
    )


def test_a_false_absence_about_a_toilet_is_contradicted_from_the_amenity_the_building_holds():
    """COUNTERFACTUAL: fails before 2026-10-01 — ``amenities`` did not exist."""
    note = aw.false_absence_note(
        NARRATED_TOILET_ABSENCE,
        TOILET_Q,
        [_circulation()],
        "Abacws Building",
        amenities=[_toilets()],
    )
    assert note, "the building holds 24 toilet facilities; the absence is false"
    assert "24 toilet facilities" in note
    assert "should not have implied it holds none" in note
    # The reader must not be handed the internal vocabulary the original answer used.
    for banned in ("recorded series", "truncated", "dataset", "sorry"):
        assert banned not in note.lower()


def test_an_amenity_is_not_described_as_a_register_the_building_keeps():
    """An occupant asking about a toilet must not be pointed at paperwork."""
    note = aw.false_absence_note(
        NARRATED_TOILET_ABSENCE, TOILET_Q, [], "Abacws Building", amenities=[_toilets()]
    )
    assert note and "keeps toilet facility records" not in note


def test_one_amenity_is_singular():
    note = aw.false_absence_note(
        NARRATED_TOILET_ABSENCE, TOILET_Q, [], "Abacws Building", amenities=[_toilets(1)]
    )
    assert note and "1 toilet facility," in note


def test_a_register_still_wins_when_both_match_so_the_wording_is_unchanged_for_records():
    """The record path keeps its own sentence: a register has fields a follow-up can ask about.

    Question and answer are the verbatim pair the circulation register was fixed on (wave 5,
    tail F), so this also pins that passing an amenity list does not disturb it.
    """
    route_q = (
        "I need to carry approved service or event materials to another floor. Which authorised "
        "route is currently suitable?"
    )
    narrated = (
        "I'm sorry, but the information returned only lists the building's floors (e.g., "
        "“Floor 0 (Ground Floor)”, “Floor 1 (First Floor)”, etc.). It does "
        "not contain any records of authorised routes that would allow you to move approved "
        "service or event materials between floors. The field that would hold that information "
        "is not present in these results."
    )
    note = aw.false_absence_note(
        narrated, route_q, [_circulation()], "Abacws Building", amenities=[_toilets()]
    )
    assert note and "keeps circulation time records" in note


def test_a_true_absence_about_an_amenity_the_building_does_not_hold_is_left_alone():
    """No amenity class matches a swimming pool, so the decline stands. Both directions matter."""
    narrated = (
        "I'm sorry, but the information returned only lists the building's floors. It does not "
        "contain any record of a swimming pool."
    )
    assert (
        aw.false_absence_note(
            narrated, "is there a swimming pool?", [], "Abacws Building", amenities=[_toilets()]
        )
        is None
    )


def test_an_unreadable_amenity_list_changes_nothing():
    """An empty list means "nothing known", never "nothing held"."""
    assert (
        aw.false_absence_note(
            NARRATED_TOILET_ABSENCE, TOILET_Q, [], "Abacws Building", amenities=[]
        )
        is None
    )
    assert (
        aw.false_absence_note(
            NARRATED_TOILET_ABSENCE, TOILET_Q, [], "Abacws Building", amenities=None
        )
        is None
    )


# ── 2. the router must not throw the building's own triples away for one lay term ────────


def _ctx(query: str, amenity_facts: int, concepts=None, amenity_subject=None):
    """A concept-stage context as ``_orchestrator`` builds it.

    ``amenity_subject`` defaults to ``amenity_facts`` -- every matched amenity is what the
    question is about -- because that is the case these tests were written for and it is
    MEASURED, not assumed: for ``TOILET_Q`` the live resolver returns 30 matches and at least
    one survives ``subject_facts``, which is why the lane answers it in ~1.1 s.

    Pass ``amenity_subject=0`` for the opposite case, which is a real live defect and now has
    its own test below: a question whose words merely TOUCH an amenity's vocabulary ('Working
    Hours' matching "the next 12 hours") must not make the contract stand down, because the
    capability lane discards such a topic as "not the subject" and then declines (BUG-1396).
    """
    normalized = {
        "intent": "capability",
        "concepts": (
            concepts
            if concepts is not None
            else [{"concept_id": "empty_space", "brick_classes": ["brick:Occupancy_Count_Sensor"]}]
        ),
        "entities": [],
        "capability_amenity_facts": amenity_facts,
        "capability_amenity_subject": (
            amenity_facts if amenity_subject is None else amenity_subject
        ),
    }
    return rc._Ctx(query=query, ql=query.lower(), normalized=normalized, sr=None)


def test_without_the_marker_the_rule_still_converts_a_measurand_question():
    """COUNTERFACTUAL for the fix's narrowness: BUG-225's behaviour is untouched at 0 facts."""
    assert rc._r_capability_measurand_is_data(_ctx(TOILET_Q, 0)) == "sensor_data"


@pytest.mark.parametrize("question", [TOILET_Q, LONG_TOILET_Q])
def test_thirty_matching_amenity_triples_outrank_the_bare_lay_term_available(question):
    """COUNTERFACTUAL: returns 'sensor_data' before 2026-10-01, which is the live defect."""
    assert rc._r_capability_measurand_is_data(_ctx(question, 30)) is None


def test_a_question_that_asks_for_a_figure_still_reaches_the_data_lane():
    """BUG-225 is not reopened: "how many parking bays are free right now?" is a reading.

    The capability lane answered that one with the building's CATERING amenities while a parking
    sensor sat in the graph with 5,090 rows, so an amenity match must NOT claim it.
    """
    lane = rc._r_capability_measurand_is_data(_ctx("how many parking bays are free right now?", 12))
    assert lane in ("sensor_data", "analytics"), lane


def test_the_stand_down_needs_a_measurand_to_be_reached_at_all():
    """No measurand resolved means the rule was never going to fire; the marker changes nothing."""
    assert rc._r_capability_measurand_is_data(_ctx(TOILET_Q, 30, concepts=[])) is None


# ── 2b. an amenity the question's WORDS touched is not an amenity it is ABOUT ────────────

#: Verbatim from the regression gate, case #4, which this shape broke on 2026-10-01.
FORECAST_Q = (
    "Project the noise level in the atrium for the next 12 hours and show the error of each "
    "candidate model."
)


def test_a_word_match_that_is_not_the_subject_does_not_stand_the_rule_down():
    """BUG-1396, and it is the regression this stand-down caused on the gate.

    Live, reproduced deterministically:
        [ttl-route] capability via ontology triples: ['Working Hours']  <- "the next 12 hours"
        [routing-contract] capability_measurand_is_data stood down: 1 amenity triples match
        [capability] topics ['Working Hours'] match words but are not the subject
        -> "I could not find this in <building>'s documents."
    One amenity MATCHED and none was the SUBJECT, so the contract handed a forecast question to
    a lane that immediately threw the topic away. The forecast lane never ran.
    """
    lane = rc._r_capability_measurand_is_data(_ctx(FORECAST_Q, 1, amenity_subject=0))
    assert lane == "sensor_data", (
        "a forecast question is being kept by the capability lane on the strength of one "
        "amenity word match; got %r" % lane
    )


def test_a_subject_match_still_stands_the_rule_down_at_the_same_count():
    """The CONTRAST that proves the discrimination, not just the direction.

    Same single amenity, same question count — only whether it is the subject differs. Without
    this, the test above would also pass on a rule that had simply stopped standing down.
    """
    assert rc._r_capability_measurand_is_data(_ctx(TOILET_Q, 1, amenity_subject=1)) is None
    assert rc._r_capability_measurand_is_data(_ctx(TOILET_Q, 1, amenity_subject=0)) == "sensor_data"


def test_the_subject_count_is_published_by_the_dialogue_agent():
    """A marker with no writer is not a signal (lesson #157), so pin the writer too."""
    import inspect

    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    assert '"capability_amenity_subject"' in src
    assert "subject_facts" in src


# ── 3. the discovery query is keyed on the graph, and its roots are stated once ──────────


def test_the_amenity_query_excludes_the_umbrella_class_itself():
    """GraphDB materialises ``?c rdfs:subClassOf ?c``, so ``o:Amenity`` is its own descendant.

    Without the filter the guard would name "amenity" — 71 instances, and useless to a reader.
    """
    from orchestrator.services.record_registry import _AMENITY_DISCOVER_QUERY

    assert "rdfs:subClassOf+ o:Amenity" in _AMENITY_DISCOVER_QUERY
    assert "FILTER(?cls != o:Amenity)" in _AMENITY_DISCOVER_QUERY


def test_amenity_is_not_a_record_root_and_the_reason_is_written_down():
    """Measured and rejected: a third root costs 251 by-name declines to gain 20 questions."""
    from orchestrator.services import record_registry as rr

    assert rr._RECORD_ROOTS == ("Record", "IntervalRecord")
    assert "o:Record o:IntervalRecord" in rr._DISCOVER_QUERY
    assert "Amenity" not in rr._DISCOVER_QUERY


def test_the_reach_harness_reads_the_roots_from_the_product():
    """A second copy of the roots is how a measurement comes to be taken over the wrong set."""
    import re
    from pathlib import Path

    source = Path("scripts/register_reach.py").read_text(encoding="utf-8")
    assert "_RECORD_ROOTS" in source
    # No hardcoded VALUES ?root list left in the harness.
    assert not re.search(r"VALUES \?root \{ o:Record", source)
