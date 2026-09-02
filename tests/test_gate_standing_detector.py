# -*- coding: utf-8 -*-
"""The gate must tell a refusal from an answer, in both directions (2026-09-01).

The V7 regression gate reported THREE blocking regressions. Two were decline -> decline:

* baseline "No **valid** data available for morning warm-up comparison" — the inserted
  adjective broke the `no data available` alternation;
* baseline "I **couldn't find** any sensor or data source" — a phrasing with no entry.

The current run phrased the same refusals differently, matched, and so a pair of identical
refusals scored as an answer that had become one. That is the fifth time in this project's
history that the measurement apparatus was wrong rather than the system.

Both directions are tested, and the SECOND matters more. A missed refusal invents a
regression, which is loud and gets investigated. A refusal pattern that swallows real
answers HIDES regressions, which is silent — and the first draft of the widened regex did
exactly that to "There is no data loss in this series; completeness is 100%".
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_GATE = Path(__file__).resolve().parent.parent / "scripts" / "baseline_regression_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("baseline_regression_gate", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


gate = _load()


@pytest.mark.parametrize(
    "text",
    [
        "**No valid data available for morning warm-up comparison**",
        "I couldn't find any sensor or data source in the building ontology that records lift trips",
        "The ontology data you provided does not contain any information about lift usage",
        "Therefore, there is no data available to determine whether lift trips dropped",
        "**No data available for morning warm-up time comparison.**",
        "I don't have that specific information.",
        "That is not on record for this building.",
        "I cannot answer that from the data I hold.",
        "The analysis could not retrieve any temperature or occupancy readings",
    ],
)
def test_a_refusal_is_recognised_however_it_is_phrased(text):
    assert gate.standing(text) == gate.DECLINED, f"missed refusal: {text[:60]}"


@pytest.mark.parametrize(
    "text",
    [
        # The one that broke. "no data loss" is a QUALITY statement inside a real answer.
        "There is no data loss in this series; completeness is 100%.",
        "I could not find any anomalies in the last 24 hours — all readings were in range.",
        "The CO2 in Room 5.15 is 612 ppm, measured 3 minutes ago.",
        "Floor 3 averaged 21.4 C, which is 1.8 C warmer than floor 5.",
        "No faults were recorded this week, and all 12 units reported normally.",
        "Twelve permits are current; three expire within 60 days.",
    ],
)
def test_a_real_answer_is_never_read_as_a_refusal(text):
    """The dangerous direction: this is how a widened pattern hides a regression."""
    assert gate.standing(text) == gate.ANSWERED, f"answer swallowed as refusal: {text[:60]}"


def test_empty_is_neither():
    assert gate.standing("") == gate.EMPTY
    assert gate.standing("   ") == gate.EMPTY


def test_an_advisory_gate_attributes_a_decline_without_blocking():
    """LT-029: the explanation was in `gates_advisory`, a column classify() never read."""
    base = {"answer": "The light level is 241.7 lux.", "intent": "sensor_data", "status": "OK"}
    cur = {
        "answer": "No data available for this space.",
        "intent": "sensor_data",
        "status": "OK",
        "gates": "",
        "gates_advisory": "freshness: no illuminance observation is available for this space",
    }
    verdict, reason = gate.classify(base, cur)
    assert verdict == gate.TIGHTENED_ADVISORY
    assert verdict not in gate.BLOCKING
    assert "freshness" in reason


def test_a_decline_with_no_gate_at_all_is_still_a_regression():
    """The core rule must survive: attribution is what separates the two."""
    base = {"answer": "The light level is 241.7 lux.", "intent": "sensor_data", "status": "OK"}
    cur = {
        "answer": "No data available for this space.",
        "intent": "sensor_data",
        "status": "OK",
        "gates": "",
        "gates_advisory": "",
    }
    verdict, _ = gate.classify(base, cur)
    assert verdict == gate.REGRESSION
    assert verdict in gate.BLOCKING


def test_an_enforcing_gate_still_outranks_an_advisory_one():
    cur = {
        "answer": "I cannot answer that.",
        "intent": "sensor_data",
        "status": "OK",
        "gates": "referent_existence",
        "gates_advisory": "freshness: stale",
    }
    base = {"answer": "It is 21 C.", "intent": "sensor_data", "status": "OK"}
    verdict, reason = gate.classify(base, cur)
    assert verdict == gate.TIGHTENED
    assert "referent_existence" in reason


def test_a_thorough_answer_that_mentions_a_gap_is_not_a_refusal():
    """Q658 — the best answer in the V7 run, scored as a refusal.

    It checked all nine handover records, gave a definitive negative, and tabled the records
    consulted. Thirty words in it added "there is no information about whether any such
    failures were later fixed" — a caveat inside a real answer — and a substring match over
    the whole text turned that into a refusal, manufacturing a regression out of the register
    lane working exactly as intended.
    """
    answer = (
        "I've checked all nine handover records you provided, and none of them mention a "
        "damper that failed its stroke test at handover. In other words:\n"
        "- **No dampers were recorded as having failed a stroke test** in any of the "
        "handover documents.\n"
        "- Consequently, there is no information about whether any such failures were later "
        "fixed.\n\n**Quick recap of the records we looked at**\n"
        "| Record ID | Covered Scope | Status |\n| HO-AHU01-OM | AHU-01 roof plant | held |"
    )
    assert gate.standing(answer) == gate.ANSWERED


def test_a_refusal_in_the_opening_is_still_caught_after_a_header():
    """Refusals announce themselves, but often after a '**Answer**' heading."""
    assert (
        gate.standing("**Answer**\n\nThere is no information in the provided ontology about bins.")
        == gate.DECLINED
    )
