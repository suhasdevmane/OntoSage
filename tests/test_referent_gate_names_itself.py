# -*- coding: utf-8 -*-
"""A refusal must be recorded as a refusal, by the gate that caused it (CAVEAT-385).

Measured live before this fix: "What is the temperature in Room 99.99?" was correctly refused
— *"I couldn't find 99.99 in Abacws Building"* — and the evidence record said

    status: observed | operation: authoritative_lookup | gates_applied: []

A refusal recorded as an OBSERVATION, with nothing claiming responsibility. Wrong on its own
terms: every consumer of the record inherits it — the provenance answer, the precedence
tiers, any audit.

It also broke the measurement. The regression gate's rule is "worse, and no gate fired = a
REGRESSION", so a correct, deliberate refusal read as silent breakage. That is why four
successive gate runs over ONE unchanged capture reported 3, 19, 22 and 22 blocking findings
while every one of them, read by hand, turned out to be a decline the system meant.

Note what this does NOT require: no change to the regression gate. It already reads
`gates_applied`. The gate could not attribute these refusals because the system never said it
had refused — fixing the honesty fixed the measurement.
"""

import inspect

import pytest

from orchestrator.services.evidence.assemble import build_evidence_record
from shared.models import AnswerStatus

pytestmark = pytest.mark.unit


def _refused_state():
    """The bus as the referent gate leaves it when a named space does not exist."""
    return {
        "intent": "sensor_data",
        "sparql_result": {
            "success": True,
            "analytics_required": False,
            "formatted_response": 'I couldn\'t find "99.99" in Abacws Building.',
            "referent_not_found": "99.99",
        },
        "referent_resolution": "not_found",
        "evidence": {
            "status": "not_assessable",
            "not_assessable_reason": "'99.99' does not exist in this building, so there is "
            "nothing to report about it",
            "gates_applied": ["referent_existence"],
        },
    }


def test_a_refused_referent_is_not_recorded_as_an_observation():
    rec = build_evidence_record(_refused_state())
    assert rec.status is AnswerStatus.NOT_ASSESSABLE
    assert rec.status is not AnswerStatus.OBSERVED


def test_the_gate_names_itself_so_the_refusal_is_attributable():
    """Without this the regression gate reads a deliberate refusal as silent breakage."""
    rec = build_evidence_record(_refused_state())
    assert "referent_existence" in rec.gates_applied


def test_the_reason_names_the_referent_that_was_missing():
    rec = build_evidence_record(_refused_state())
    assert "99.99" in rec.not_assessable_reason


def test_a_real_answer_is_unaffected():
    """The safety property: this must not relabel answers that succeeded."""
    rec = build_evidence_record(
        {
            "intent": "metadata",
            "sparql_result": {"success": True, "results": {"data": [{"n": 288}]}},
        }
    )
    assert rec.status is AnswerStatus.OBSERVED
    assert rec.gates_applied == []


def test_the_gate_declares_itself_at_the_refusal_site():
    """Pinned against the source: the declaration must live where the refusal is written.

    The gate wrote its refusal into `sparql_result` and returned, so everything downstream
    saw a successful lookup. Any future refusal path added here has to do the same, or it
    reintroduces a refusal that nothing owns.
    """
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    idx = src.find('state.intermediate_results["referent_resolution"] = "not_found"')
    assert idx > 0, "the referent-gate refusal path moved; update this test"
    window = src[idx : idx + 2400]
    assert "referent_existence" in window, "the referent gate no longer names itself"
    assert "not_assessable" in window, "the refusal is no longer recorded as a refusal"


def test_a_lane_partial_status_is_coerced_to_the_enum_not_left_a_string():
    """The subtle half of this fix, and the reason a live check was not enough.

    A lane hands up plain JSON, so it says `{"status": "not_assessable"}`. Assigning that raw
    string left the record holding a `str`, which serialises to byte-identical JSON — the API
    response looked correct while `rec.status is AnswerStatus.NOT_ASSESSABLE` was False. A
    refusal that reads as a refusal on the wire and as something else in code.
    """
    rec = build_evidence_record(
        {
            "intent": "sensor_data",
            "sparql_result": {"success": True, "formatted_response": "no"},
            "evidence": {"status": "not_assessable"},
        }
    )
    assert isinstance(rec.status, AnswerStatus)
    assert rec.status is AnswerStatus.NOT_ASSESSABLE


def test_an_unknown_status_from_a_lane_is_ignored_rather_than_stored():
    """A typo must not put a value in the record that no reader can interpret."""
    rec = build_evidence_record(
        {
            "intent": "sensor_data",
            "sparql_result": {"success": True, "results": {"data": [{"n": 1}]}},
            "evidence": {"status": "definitely_not_a_status"},
        }
    )
    assert isinstance(rec.status, AnswerStatus)
    assert rec.status is AnswerStatus.OBSERVED
