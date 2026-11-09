"""Three defects found by gate case #14 on 2026-11-07, and BUG-1689.

"Which meeting room is best right now for a group of eight who need good air quality?" compiled to
IN_SPACE 'Meeting Room'. Ten labels carry the phrase, so admission asked "'Meeting Room' matches
several spaces -- which one?", and the answer-relevance gate then judged that QUESTION as an answer
("does not recommend a room, just lists options") and replaced it with a decline. The reader lost
the ranking, the question and any way to answer it.

1. A phrase several spaces' names carry, with no room id in it, names a KIND of space: a ranking is
   scoped to those spaces, and the reading is stated as an assumption.
2. The relevance gate does not judge a turn that asks the reader a question.
3. When the gate does replace an answer and no read was counted, the decline says only what the
   gate knows -- never that the records lack the answer (BUG-1689).
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import clarification as clar
from orchestrator.services.deliberation.candidates import enumerate_candidates
from orchestrator.services.deliberation.capability_schema import (
    ADMIT,
    CLARIFY,
    BuildingCapabilitySchema,
    validate,
)
from orchestrator.services.deliberation.coverage_audit import STATUS_PRESENT, SpaceCoverage
from orchestrator.services.deliberation.cqir import (
    CQIR,
    Constraint,
    DecisionKind,
    Direction,
    SpatialQualifier,
    SpatialRelation,
)

pytestmark = pytest.mark.unit

NS = "http://example.org/anybldg#"


def _space(local, label, floor="floor1"):
    sc = SpaceCoverage(space_iri=f"{NS}{local}", label=label, floor=floor)
    sc.modalities = {
        "co2": {"status": STATUS_PRESENT, "sensor": "", "uuid": local, "stored_at": "t"}
    }
    return sc


def _schema():
    return BuildingCapabilitySchema(
        building_id="anybldg",
        namespace=NS,
        spaces=[
            _space("RM101", "Room 1.01 — Meeting Room"),
            _space("RM102", "Room 1.02 — Meeting Room"),
            _space("RM103", "Room 1.03 — Open Office"),
            _space("RM201", "Room 2.01 — Meeting Room", floor="floor2"),
        ],
        amenities=[],
    )


def _ir(anchor, relation=SpatialRelation.IN_SPACE, decision=DecisionKind.SELECT_ONE):
    return CQIR(
        decision=decision,
        constraints=[Constraint(modality="co2", direction=Direction.MINIMIZE)],
        spatial=[SpatialQualifier(relation=relation, anchor=anchor)],
        signals=[],
    )


@pytest.mark.parametrize("anchor", ["Meeting Room", "meeting room"])
def test_a_kind_phrase_is_admitted_as_a_scope_not_asked_about(anchor):
    res = validate(_ir(anchor), _schema())
    assert res.verdict == ADMIT
    assert res.space_anchor is None
    assert res.kind_spaces == sorted([f"{NS}RM101", f"{NS}RM102", f"{NS}RM201"])
    assert res.kind_phrase == anchor


def test_the_ranking_considers_only_the_spaces_of_that_kind():
    schema = _schema()
    ir = _ir("Meeting Room")
    cands, ledger = enumerate_candidates(ir, validate(ir, schema), schema)
    assert sorted(c.space_iri for c in cands) == [f"{NS}RM101", f"{NS}RM102", f"{NS}RM201"]
    assert ledger.in_scope == 3


def test_a_kind_and_a_floor_together_scope_to_both():
    schema = _schema()
    ir = _ir("Meeting Room")
    ir.spatial.append(SpatialQualifier(relation=SpatialRelation.ON_FLOOR, anchor="floor1"))
    cands, _ = enumerate_candidates(ir, validate(ir, schema), schema)
    assert sorted(c.space_iri for c in cands) == [f"{NS}RM101", f"{NS}RM102"]


def test_one_match_is_still_one_space():
    res = validate(_ir("Open Office"), _schema())
    assert res.space_anchor == f"{NS}RM103"
    assert res.kind_spaces == []


def test_a_room_id_is_never_a_kind():
    res = validate(_ir("1.01"), _schema())
    assert res.space_anchor == f"{NS}RM101"
    assert res.kind_spaces == []


def test_next_to_a_phrase_several_spaces_carry_still_asks():
    """ "next to the meeting room" names ONE place; with three candidates, asking is right."""
    res = validate(_ir("Meeting Room", relation=SpatialRelation.ADJACENT_TO), _schema())
    assert res.verdict == CLARIFY
    assert res.kind_spaces == []


def test_an_unknown_phrase_still_asks():
    assert validate(_ir("Ballroom"), _schema()).verdict == CLARIFY


def test_the_answer_states_the_reading_as_an_assumption():
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch)
    assert "read as a kind of space: ranked the" in src


# ── the gate does not judge a question back to the reader ───────────────────────────────────


def test_the_relevance_gate_skips_a_turn_that_asks_the_reader_a_question():
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch._relevance_gated)
    skip = src.index('"needs_clarification_payload"')
    judge = src.index("gate.relevance_verdict(")
    assert skip < judge, "the skip must run before the gate spends a call judging"


# ── BUG-1689: what the replacement may say ──────────────────────────────────────────────────


def _abstract(**kw):
    return clar.compose_abstract("Some Building", "how warm is it in here?", (), (), (), (), **kw)


def test_a_replacement_with_no_counted_read_does_not_claim_the_records_lack_it():
    text = _abstract(drafted_off_topic=True)
    assert text.startswith("I couldn't put an answer together")
    assert "I couldn't answer that from" not in text
    assert "not a finding that Some Building's records lack the answer" in text


def test_a_counted_read_keeps_its_own_lead():
    text = _abstract(read_but_off_topic=True, drafted_off_topic=True)
    assert "I did read them" in text


def test_no_replacement_keeps_the_plain_decline():
    assert _abstract().startswith("I couldn't answer that from Some Building's records.")


def test_the_response_node_passes_the_flag_only_when_the_gate_replaced():
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch._unanswered_response)
    assert "drafted_off_topic=_gate_replaced and not _rows_read" in src


# ── BUG-1685: a named criterion the compile left unmapped is kept, not declared "not sensed" ──


def _compiled(decision, unmapped, query):
    import json

    from orchestrator.services.deliberation.compiler import _parse_compiled

    raw = json.dumps(
        {
            "decision": decision,
            "constraints": [{"modality": "co2", "direction": "minimize", "phrase": "CO2"}],
            "unmapped": unmapped,
            "spatial": [],
        }
    )
    return _parse_compiled(raw, query, {"co2", "temperature", "humidity", "noise"})


def test_named_sensed_criteria_beside_a_mapped_one_are_kept():
    c = _compiled(
        "select_one", ["temperature", "humidity", "noise", "good vibes"], "best place to work"
    )
    got = {x.modality: x.direction.value for x in c.constraints}
    assert got == {
        "co2": "minimize",
        "temperature": "near_value",
        "humidity": "near_value",
        "noise": "minimize",
    }
    assert [s.phrase for s in c.signals] == ["good vibes"]


def test_a_ranking_by_temperature_still_has_no_guessed_end():
    c = _compiled("rank_all", ["temperature"], "rank the rooms by co2 and temperature")
    assert [x.modality for x in c.constraints] == ["co2"]
    assert [s.phrase for s in c.signals] == ["temperature"]


def test_a_long_clause_beside_a_mapped_criterion_is_not_mined_for_a_word():
    c = _compiled("select_one", ["somewhere my colleague will not overheat at all"], "q")
    assert [x.modality for x in c.constraints] == ["co2"]


# ── CAVEAT-1708: a decline's evidence panel claims nothing ──────────────────────────────────


def _record():
    return {
        "status": "observed",
        "operation": "observation",
        "source_tier": "measurement",
        "sources": [{"source_id": "u1", "label": "Noise Data", "kind": "sensor"}],
    }


def test_a_declined_turn_is_not_called_an_instrument_reading():
    from orchestrator.services.answer_provenance import render

    out = render(_record(), inline=True, declined=True)
    assert "not_assessable" in out
    assert "read from an instrument" not in out
    assert "Kind of source that led" not in out
    assert "Looked at while answering (1)" in out


def test_an_answer_keeps_its_observed_panel():
    from orchestrator.services.answer_provenance import render

    out = render(_record(), inline=True)
    assert "observed — read from an instrument" in out
    assert "Sources (1)" in out


def test_the_response_node_marks_a_decline_only_when_it_states_no_figure():
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch)
    assert "is_decline(final_response) or _first_sentence_declines(final_response)" in src
    assert "and not has_quantitative_claim(final_response)" in src


@pytest.mark.parametrize(
    "text,declines",
    [
        ("I’m sorry, but there is no air‑pressure sensor data available for Room 2.01.", True),
        ("There is no noise sensor in Room 1.04, so I can't chart it.", True),
        ("No fault is recorded as standing right now in the building's records.", False),
        ("The latest temperature in Room 2.01 is 23.4 °C.", False),
    ],
)
def test_a_decline_in_the_models_own_words_is_recognised(text, declines):
    from orchestrator.workflow._orchestrator import _first_sentence_declines

    assert _first_sentence_declines(text) is declines
