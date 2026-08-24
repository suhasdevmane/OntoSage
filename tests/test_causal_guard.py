# -*- coding: utf-8 -*-
"""Causal-claim guard (V6-T33).

Master 12.2's worked example is the whole specification: the system *may* report that
temperature rose after occupancy rose; it *must not* conclude that the occupants caused the
overheating. Two sentences about the same two series, one supportable and one not.

Three properties are asserted here, and each protects against a different way this guard could
go wrong:

* **it acts on the right claims** -- an attribution on correlational evidence is caught;
* **it leaves the right claims alone** -- a mechanism backed by an asserted relation, and the
  system's own honest refusals, which are causal sentences by every syntactic test;
* **its rewrites are grammatical** -- the section at the bottom exists because an earlier
  version emitted "The overheating was." and "The CO2 above 1000 ppm..", each of which is
  worse than the overreaching sentence it replaced.

Fixtures are synthetic on purpose: this is a property of English and of evidence classes, not
of any building, and a test that passed only for bldg1's phrasing would prove nothing.
"""

import pytest
import yaml

from orchestrator.services.evidence import load_policy
from orchestrator.services.evidence.causal_guard import (
    GATE,
    causal_gate,
    find_claims,
    is_already_correlational,
    qualify,
    support_from_evidence,
    unlicensed_claims,
)
from shared.models import CausalSupport

pytestmark = pytest.mark.unit

CORRELATIONAL_ONLY = "The temperature rose because occupancy increased."


@pytest.fixture
def advisory():
    """The shipped default: the guard reports and changes nothing."""
    return load_policy("fixture")


@pytest.fixture
def enforcing(tmp_path):
    (tmp_path / "evidence_policy.yaml").write_text(
        yaml.safe_dump({"gates": {GATE: {"mode": "enforcing"}}}), encoding="utf-8"
    )
    return load_policy("fixture", input_dir=tmp_path)


# -- detecting the claim -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The temperature rose because occupancy increased.",
        "CO2 climbed due to the closed vents.",
        "The overheating was caused by the open window.",
        "High occupancy drove the CO2 above 1000 ppm.",
        "The vent closure resulted in a comfort complaint.",
        "Occupancy is responsible for the afternoon peak.",
        "The plant restart explains the Monday spike.",
    ],
)
def test_causal_wording_is_detected(text):
    assert find_claims(text), f"missed a causal claim in: {text}"


@pytest.mark.parametrize(
    "text",
    [
        "CO2 rose at the same time as occupancy.",
        "Temperature and occupancy both peaked over the same period.",
        "The room reached 1000 ppm for three hours.",
        "Occupancy peaked at 14:00 and CO2 peaked at 14:20.",
    ],
)
def test_co_occurrence_wording_is_not_a_causal_claim(text):
    """The wording the guard is steering answers TOWARD must not itself be flagged."""
    assert not find_claims(text)


def test_the_two_halves_are_separated_the_right_way_round():
    """A rewrite that swapped these would report the effect as the thing that co-occurred."""
    claim = find_claims(CORRELATIONAL_ONLY)[0]
    assert "temperature" in claim.effect.lower()
    assert "occupancy" in claim.cause.lower()


def test_direction_is_read_from_the_connective_not_from_word_order():
    """ "B caused A" puts the cause first; "A because B" puts the effect first."""
    claim = find_claims("High occupancy drove the CO2 above 1000 ppm.")[0]
    assert "occupancy" in claim.cause.lower()
    assert "co2" in claim.effect.lower()


def test_a_longer_connective_wins_over_the_shorter_one_inside_it():
    """Matching "because" inside "because of" leaves a dangling "of" heading the cause."""
    claim = find_claims("pH drifted because of the dosing pump.")[0]
    assert claim.connective == "because of"
    assert not claim.cause.lower().startswith("of ")


def test_word_boundaries_are_respected():
    """Without them "explain" matches inside "explained" and splits at a non-connective."""
    assert not find_claims("The report explained the measurement method.")


# -- what the evidence licenses ----------------------------------------------


def test_correlation_does_not_license_attribution():
    assert unlicensed_claims(CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)


def test_no_evidence_does_not_license_attribution():
    assert unlicensed_claims(CORRELATIONAL_ONLY, CausalSupport.NONE)


def test_an_asserted_relation_licenses_a_mechanism():
    """The anomaly lane's legitimate case: the graph says the AHU serves the room."""
    text = "The room warmed because its air handler was off."
    assert not unlicensed_claims(text, CausalSupport.MECHANISTIC)
    assert qualify(text, CausalSupport.MECHANISTIC) == text


def test_an_intervention_licenses_the_full_claim():
    text = "Raising the setpoint reduced the afternoon peak."
    assert not unlicensed_claims(text, CausalSupport.INTERVENTIONAL)


def test_support_is_graded_from_facts_the_caller_holds():
    assert support_from_evidence() is CausalSupport.NONE
    assert support_from_evidence(series_compared=2) is CausalSupport.CORRELATIONAL
    assert support_from_evidence(has_asserted_relation=True) is CausalSupport.MECHANISTIC
    assert support_from_evidence(has_intervention=True) is CausalSupport.INTERVENTIONAL


def test_an_intervention_outranks_a_mere_correlation():
    got = support_from_evidence(has_intervention=True, series_compared=2)
    assert got is CausalSupport.INTERVENTIONAL


# -- the system's own refusals must survive intact ---------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I cannot answer because no readings are recorded for that room.",
        "The figure is unavailable because the sensor has not reported since Friday.",
        "I have not reported a room-level value because there is no sensor inside it.",
        "That was declined because the combination is restricted by policy.",
    ],
)
def test_honest_refusals_are_never_rewritten(text):
    """Load-bearing.

    Every one of these is a causal sentence syntactically, and every one is exactly the honest
    refusal the V6 plan exists to produce. A guard that mangled them would damage the answers
    it was built to protect -- and it would do so on the system's most careful outputs.
    """
    assert not unlicensed_claims(text, CausalSupport.NONE)
    assert qualify(text, CausalSupport.NONE) == text


# -- the gate ----------------------------------------------------------------


def test_the_gate_fails_an_unlicensed_claim(advisory):
    v = causal_gate(advisory, CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert not v.passed
    assert "correlational" in v.reason


def test_the_gate_ships_advisory(advisory):
    """A guard that rewords answers is the one whose blast radius is measured first."""
    v = causal_gate(advisory, CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert not v.blocks
    assert v.advisory_failure


def test_the_gate_can_be_switched_on_per_building(enforcing):
    v = causal_gate(enforcing, CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert v.blocks


def test_failing_does_not_downgrade_the_measurement(enforcing):
    """The observation is still observed; only its explanation overreached.

    Downgrading the whole answer would throw away a good measurement to punish a bad sentence.
    """
    v = causal_gate(enforcing, CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert v.downgrade_to is None


def test_the_gate_passes_a_licensed_claim(enforcing):
    v = causal_gate(enforcing, CORRELATIONAL_ONLY, CausalSupport.MECHANISTIC)
    assert v.passed and not v.blocks


def test_the_remedy_says_what_would_establish_a_cause(advisory):
    """A remedy that only says "don't" teaches nothing about the evidence that would."""
    v = causal_gate(advisory, CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert "measured response" in v.remedy or "serving relation" in v.remedy


# -- the rewrite must be grammatical -----------------------------------------
#
# Every case below was produced as broken output by an earlier version of restate().


@pytest.mark.parametrize(
    "text",
    [
        "The temperature rose because occupancy increased.",
        "The overheating was caused by the open window.",
        "High occupancy drove the CO2 above 1000 ppm.",
        "The vent closure resulted in a comfort complaint.",
        "pH drifted because of the dosing pump.",
        "CO2 levels climbed due to the closed vents.",
    ],
)
def test_the_rewrite_leaves_no_fragment_or_double_stop(text):
    out = qualify(text, CausalSupport.CORRELATIONAL)
    assert out != text
    assert ".." not in out
    assert " ;" not in out
    for dangling in (" was;", " is;", " were;", " are;", " has;", " had;"):
        assert dangling not in out, f"dangling auxiliary in: {out}"


def test_both_observations_survive_the_rewrite():
    """Refusing the attribution must not discard the evidence behind it."""
    out = qualify(CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert "temperature rose" in out
    assert "occupancy increased" in out


def test_the_rewrite_says_what_was_not_established():
    out = qualify(CORRELATIONAL_ONLY, CausalSupport.CORRELATIONAL)
    assert "does not establish" in out


def test_acronyms_and_units_are_not_lower_cased():
    """Lower-casing a measurand is an error a reader spots instantly."""
    out = qualify("CO2 levels climbed due to the closed vents.", CausalSupport.CORRELATIONAL)
    assert "CO2" in out
    out = qualify("pH drifted because of the dosing pump.", CausalSupport.CORRELATIONAL)
    assert "pH" in out


def test_a_back_reference_is_left_alone_rather_than_half_rewritten():
    """ "This is because X" has its subject in the PREVIOUS sentence.

    No rewrite confined to this sentence can recover it, so the guard records the claim and
    declines to restate it -- "this is" would be worse than the original.
    """
    text = "Energy use is higher on Mondays. This is because the plant restarts."
    assert qualify(text, CausalSupport.CORRELATIONAL) == text
    assert unlicensed_claims(text, CausalSupport.CORRELATIONAL)  # still RECORDED


def test_only_the_offending_sentence_changes():
    text = "Room 2.15 held 900 ppm all morning. The rise was caused by the closed vents."
    out = qualify(text, CausalSupport.CORRELATIONAL)
    assert out.startswith("Room 2.15 held 900 ppm all morning.")


def test_an_already_correlational_answer_is_recognised():
    assert is_already_correlational("CO2 rose at the same time as occupancy.")
    assert not is_already_correlational(CORRELATIONAL_ONLY)


def test_empty_text_is_handled():
    assert qualify("", CausalSupport.NONE) == ""
    assert find_claims("") == []


# -- building agnosticism ----------------------------------------------------


def test_the_guard_carries_no_building_literal():
    """It reasons about English and evidence classes, not about one estate."""
    from pathlib import Path

    from scripts.check_building_literals import _prose_lines

    path = (
        Path(__file__).resolve().parent.parent
        / "orchestrator"
        / "services"
        / "evidence"
        / "causal_guard.py"
    )
    src = path.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff"):
        assert literal not in code, f"causal guard hardcodes {literal}"
