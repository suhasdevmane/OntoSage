# -*- coding: utf-8 -*-
"""Three things a reader may not be shown, and one thing they should be (2026-09-17).

From a hand read of 147 live answers as a non-admin facility manager:

* **our own component names.** "The ontology lane, the time-series lane ran" was on six
  answers. A lane is a thing inside this program; to the person asking it names nothing.
* **instructions to edit the model.** "You would need to extend the ontology with
  `hasLifecycleEvent`…" is `enablement_hint` in the LLM's own words, and that hint is
  already withheld from anyone without `system:admin`. A rule enforced on our deterministic
  text and not on generated text is enforced on the half that never broke it.
* **stemmer artefacts.** "authorised" folds to "authoris"; printing that back is worse
  than printing nothing.

And the thing they should be shown: the part of their request the building has no
vocabulary for, which is what the deliberation compiler says as "I couldn't map part of
your request (…)" and what no other lane could say at all.
"""

import pytest

from orchestrator.services.grounding_guard import (
    names_internal_vocabulary,
    schema_remediation_reason,
    strip_schema_remediation,
    unmatched_terms,
)

pytestmark = pytest.mark.unit

_VOCAB = ["temperature", "CO2", "occupancy", "work order", "room booking", "cleaning task"]


# ── internal vocabulary ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "The ontology lane, the time-series lane ran, but returned nothing to report.",
        "The document lane ran, but returned nothing to report.",
        "No data lane produced a result for it.",
        "That is a gap on my side, not a statement about the building.",
        "Rephrasing often reaches a lane that can answer.",
        "the floor-plan lane returned nothing",
    ],
)
def test_component_names_are_caught(text):
    assert names_internal_vocabulary(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Room 5.01 CO2 is 812 ppm, measured 4 minutes ago.",
        "This building has no lifts recorded in its model.",
        # "lane" as the reader would ever mean it.
        "The delivery lane behind the building is closed on Tuesday.",
        "",
    ],
)
def test_ordinary_english_is_not_caught(text):
    assert names_internal_vocabulary(text) is None


def test_emphasis_does_not_hide_a_component_name():
    assert names_internal_vocabulary("**The ontology lane** ran.") is not None


# ── remediation ──────────────────────────────────────────────────────────────


def test_an_instruction_to_extend_the_model_is_found():
    assert schema_remediation_reason(
        "You would need to extend the ontology with properties that capture lifecycle events."
    )
    assert schema_remediation_reason("You might consider adding a new sensor type to the ontology.")


def test_a_sentence_about_the_building_is_not():
    assert schema_remediation_reason("The chiller was added to the plant room in 2019.") is None


def test_only_the_instruction_is_removed():
    out = strip_schema_remediation(
        "The records hold 12 approvals.\n\nIf you need lifecycle tracking, you would need to "
        "extend the ontology with new properties.\n\nAsk me for the approvals and I'll list them."
    )
    assert "12 approvals" in out
    assert "extend the ontology" not in out
    assert "Ask me for the approvals" in out


def test_a_bullet_that_is_an_instruction_goes_whole():
    out = strip_schema_remediation(
        "- Check the maintenance logs.\n- Consider adding a new sensor type to the ontology.\n"
    )
    assert "maintenance logs" in out
    assert "sensor type" not in out


def test_clean_text_is_returned_identical():
    clean = "Floor 1's average CO2 (612 ppm) is higher than Floor 3's (540 ppm)."
    assert strip_schema_remediation(clean) is clean


# ── the unmapped part ────────────────────────────────────────────────────────


def test_it_names_the_part_the_building_has_no_word_for():
    out = unmatched_terms(
        "Whats the best empty room to convert into two phone booths, by demand?", _VOCAB
    )
    assert out
    assert all(w in ("convert", "demand", "booths", "phone", "empty") for w in out), out


def test_a_fully_covered_question_yields_nothing():
    assert unmatched_terms("show me the work orders for this room", _VOCAB) == []


def test_an_unreadable_building_yields_nothing():
    """An empty vocabulary means we know nothing, not that nothing matched."""
    assert unmatched_terms("anything at all", []) == []


def test_the_user_s_own_spelling_is_returned_not_the_stem():
    out = unmatched_terms("which rooms have authorised control states?", _VOCAB)
    assert "authoris" not in out
    assert "authorised" in out


def test_adverbs_and_talk_about_the_question_are_dropped():
    out = unmatched_terms(
        "What evidence is too weak for the building to answer my question responsibly?", _VOCAB
    )
    assert "responsibly" not in out
    assert "question" not in out


def test_it_is_deterministic():
    q = "Which electrical and ventilation capacities are adequate for the proposal?"
    assert unmatched_terms(q, _VOCAB) == unmatched_terms(q, _VOCAB)
