# -*- coding: utf-8 -*-
"""The evidence record answers "how do you know that?" (V7-T74).

V6 built a machine-readable record for every consequential answer — sources and their
owners, the operation performed, when the evidence was observed and when it was retrieved,
the checks that fired — assembled at one chokepoint and carried on every turn.

Nothing reached it by asking. Measured on the stakeholder probe: an auditor's "can every
extraction, join, filter and chart be rerun from authorised inputs?" got a document
search, and "how do you know that?" was answered as a question about the system's own
capabilities. The record was in the previous turn's state the whole time — the twelfth
instance of a capability built, correct, tested, and with no invoker.
"""

from __future__ import annotations

import pytest

from orchestrator.services.answer_provenance import is_provenance_question, render

pytestmark = pytest.mark.unit

RECORD = {
    "status": "observed",
    "operation": "authoritative_lookup",
    "sources": [
        {
            "source_id": "ontosage:Permit",
            "kind": "document_derived",
            "owner": "Estates Compliance Team",
            "record_version": "4.1",
            "simulated": True,
        },
        {"source_id": "uuid-1", "kind": "sensor", "simulated": None},
    ],
    "latest_evidence_at": "2026-08-31T09:00:00",
    "retrieved_at": "2026-08-31T09:05:00",
    "completeness": 0.92,
    "analysis_method": "count over the register",
    "gates_applied": ["freshness", "spatial_adequacy"],
    "conflicts": ["sensor says empty, booking says occupied"],
}


@pytest.mark.parametrize(
    "query",
    [
        "How do you know that?",
        "Where did that number come from?",
        "What are your sources?",
        "Can that be rerun from authorised inputs?",
        "How was that calculated?",
        "Show me your working",
        "What was that based on?",
    ],
)
def test_a_provenance_question_is_recognised(query):
    assert is_provenance_question(query), query


@pytest.mark.parametrize(
    "query",
    [
        "Where is the nearest toilet?",  # wayfinding, not provenance
        "How many permits are open?",
        "What is the temperature in room 5.04?",
        "How do I get to level 3?",
        "Who owns the lift contract?",
    ],
)
def test_ordinary_questions_are_not_taken(query):
    assert not is_provenance_question(query), query


def test_the_record_is_read_back_not_reconstructed():
    text = render(RECORD)
    assert "observed" in text
    assert "authoritative lookup" in text
    assert "Estates Compliance Team" in text
    assert "version 4.1" in text
    assert "count over the register" in text


def test_the_two_times_are_reported_separately():
    """Stale evidence is not current status, and collapsing them hides that."""
    text = render(RECORD)
    assert "newest evidence 2026-08-31 09:00" in text
    assert "retrieved 2026-08-31 09:05" in text


def test_a_declared_synthetic_source_says_so():
    assert "declared synthetic" in render(RECORD)


def test_an_undeclared_source_is_not_called_real():
    """simulated is tri-state: None means nobody said, which is not the same as real."""
    text = render({"sources": [{"source_id": "uuid-1", "kind": "sensor", "simulated": None}]})
    assert "synthetic" not in text.lower()
    assert "real" not in text.lower()


def test_conflicts_are_reported_never_averaged():
    assert "sensor says empty, booking says occupied" in render(RECORD)


def test_no_record_returns_none_rather_than_a_placeholder():
    """The caller says so in its own words; inventing one here would be a reconstruction."""
    assert render(None) is None
    assert render({}) is None


def test_the_rule_fires_before_every_other_parse_rule():
    from orchestrator.services import routing_contract as rc

    assert rc.PARSE_STAGE_RULES[0].name == "answer_provenance"


def test_the_capability_lane_reads_the_PREVIOUS_turn():
    """ "How do you know that" refers to the answer just given, not to this question."""
    import inspect

    from orchestrator.agents import capability_agent

    source = inspect.getsource(capability_agent)
    assert "load_state(state.conversation_id)" in source
    assert 'intermediate_results.get("evidence_record")' in source


def test_a_register_lookup_is_not_described_as_an_instrument_reading():
    """Both are OBSERVED, and only one of them read a sensor.

    Live, before this: "Kind of claim: observed — read from an instrument" was printed
    over a permit-register lookup. The catalogues separate a lookup from an observation
    for precisely this reason, and the gloss has to follow the operation.
    """
    text = render({"status": "observed", "operation": "authoritative_lookup"})
    assert "system of record" in text
    assert "read from an instrument" not in text


def test_a_sensor_reading_is_still_described_as_one():
    text = render({"status": "observed", "operation": "observation"})
    assert "read from an instrument" in text
