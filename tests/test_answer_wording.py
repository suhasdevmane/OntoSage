# -*- coding: utf-8 -*-
"""Last-pass answer wording: BUG-679 (the building's data is not the user's) and BUG-699 (no
provenance flags in user-visible text).

Every positive case below is a sentence recorded in the phase-0 rerun
(docs/phase0/phase0_rerun.md.jsonl), not an invented example.
"""

import inspect

import pytest

from orchestrator.services.answer_wording import (
    attribute_to_building,
    polish_answer,
    strip_provenance_flags,
)

pytestmark = pytest.mark.unit


# ── BUG-679: recorded sentences ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "before,after",
    [
        (
            "The ontology data you provided does not contain any explicit list of matters.",
            "The building's records do not contain any explicit list of matters.",
        ),
        (
            "The ontology data you provided contains only information about **ApprovalRecord**.",
            "The building's records contain only information about **ApprovalRecord**.",
        ),
        (
            "The operating‑regime records you provided do not contain any information.",
            "The building's operating‑regime records do not contain any information.",
        ),
        (
            "I’m sorry, but the sensor data you provided does not contain any information.",
            "I’m sorry, but the building's sensor data does not contain any information.",
        ),
        (
            "The handover records you provided do **not** contain any information.",
            "The building's handover records do **not** contain any information.",
        ),
        (
            "The records you have show that the compliance checks are being logged.",
            "The building's records show that the compliance checks are being logged.",
        ),
        (
            "The building ontology data you provided does **not contain any information**.",
            "The building's records do **not contain any information**.",
        ),
        (
            "The circulation records you provided only describe walking times between floors.",
            "The building's circulation records only describe walking times between floors.",
        ),
        (
            "Based on the sensor‑count data you provided, the area with the highest count",
            "Based on the building's sensor‑count data, the area with the highest count",
        ),
        (
            "I've checked all nine handover records you provided, and none of them mention it.",
            "I've checked all nine handover records, and none of them mention it.",
        ),
    ],
)
def test_retrieved_data_is_attributed_to_the_building(before, after):
    assert attribute_to_building(before) == after


def test_mid_sentence_lower_case_is_preserved():
    assert (
        attribute_to_building("As noted, the ontology data you provided has no FCUs.")
        == "As noted, the building's records have no FCUs."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Room 2.15 has 14 sensors on record.",
        "The records you have access to are listed below.",
        "If you provided a room name, I would look it up.",
        "Thanks for the data. Here is what the building holds.",
        "The building's records do not contain a tariff.",
        "",
    ],
)
def test_non_matches_are_untouched(text):
    assert attribute_to_building(text) == text


def test_code_is_never_rewritten():
    text = (
        "The ontology data you provided has no FCUs.\n\n"
        "```\nthe data you provided\n```\n"
        "Inline `the records you provided` stays."
    )
    out = attribute_to_building(text)
    assert out.startswith("The building's records have no FCUs.")
    assert "```\nthe data you provided\n```" in out
    assert "`the records you provided`" in out


def test_a_turn_where_the_user_really_pasted_data_is_left_alone():
    pasted = "Here are my readings:\n| room | co2 |\n| 1 | 400 |"
    text = "The data you provided shows one room."
    assert attribute_to_building(text, user_message=pasted) == text
    assert attribute_to_building(text, user_message="what is co2 in room 1?") != text


def test_a_table_row_is_rewritten_only_in_the_phrase():
    text = "| Source | Note |\n|---|---|\n| handover | The handover records you provided |"
    assert attribute_to_building(text) == (
        "| Source | Note |\n|---|---|\n| handover | The building's handover records |"
    )


# ── BUG-699: provenance flags ────────────────────────────────────────────────


def test_the_recorded_environment_flag_line_is_removed():
    """Rerun row 78."""
    text = (
        "**Hazard control register**  \n"
        "- Data source: Hazard Control Register  \n"
        "- Mapping: maps_to: hazard_controls  \n"
        "- Environment: simulated: true  \n"
        "- Model version: not recorded"
    )
    out = strip_provenance_flags(text)
    assert "simulated" not in out.lower()
    assert "- Data source: Hazard Control Register" in out
    assert "- Model version: not recorded" in out
    assert out.count("\n") == text.count("\n") - 1


@pytest.mark.parametrize(
    "line",
    [
        "simulated: true",
        "Simulated: False",
        "isSimulated: true",
        "- isSimulated = false",
        "* **simulated**: true",
        "1. Provenance: `simulated: true`",
        "SIMULATED = TRUE.",
    ],
)
def test_flag_lines_of_every_form_are_removed(line):
    out = strip_provenance_flags(f"Before.\n{line}\nAfter.")
    assert out == "Before.\nAfter."


def test_a_bracketed_inline_flag_is_removed():
    assert (
        strip_provenance_flags("Room 1.06 CO2 is 612 ppm (simulated: true).")
        == "Room 1.06 CO2 is 612 ppm."
    )


def test_a_simulated_table_column_is_removed():
    text = (
        "| sensor | value | isSimulated |\n"
        "|---|---|---|\n"
        "| CO2_1 | 612 | true |\n"
        "| CO2_2 | 598 | false |"
    )
    out = strip_provenance_flags(text)
    assert "simulated" not in out.lower() and "true" not in out and "false" not in out
    assert "| sensor | value |" in out and "| CO2_1 | 612 |" in out


def test_a_key_value_table_row_that_is_only_the_flag_is_removed():
    text = "| field | value |\n|---|---|\n| owner | Estates |\n| simulated | true |"
    out = strip_provenance_flags(text)
    assert "| owner | Estates |" in out and "simulated" not in out


@pytest.mark.parametrize(
    "text",
    [
        "The model simulated the airflow for Floor 2.",
        "A simulated fire drill is scheduled for Friday.",
        "Status: true",
        "```\nsimulated: true\n```",
    ],
)
def test_flag_non_matches_are_untouched(text):
    assert strip_provenance_flags(text) == text


def test_polish_applies_both():
    text = "The ontology data you provided does not list lifts.\n- Environment: simulated: true"
    assert polish_answer(text) == "The building's records do not list lifts."


# ── wiring ───────────────────────────────────────────────────────────────────


def test_the_response_node_polishes_the_final_text_before_it_is_stored():
    """One chokepoint for /chat, the non-streamed and the STREAMED /v1 path: each reads
    messages[-1].content, which only this append writes — and the cache stores the same string."""
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch.WorkflowOrchestrator._response_node)
    polish = src.index("_polish_answer(")
    assert polish < src.index("state.messages.append(")
    assert polish > src.index("_pub_evaluate(")  # after every guard that rewrites the text
    assert polish < src.index("self.response_cache.put(")


def test_a_cached_answer_is_polished_on_the_way_out():
    from orchestrator.workflow import _orchestrator as orch

    src = inspect.getsource(orch.WorkflowOrchestrator._serve_from_cache)
    assert "_polish_answer(" in src


def test_the_narration_prompts_say_the_data_is_the_buildings():
    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent.SPARQLAgent._reason_over_ontology)
    assert "comes from the building's own records, not from the user" in src


# ── where the user really did supply the content ─────────────────────────────


@pytest.mark.parametrize("intent", ["maintenance", "complaint", "feedback", "preference_management"])
def test_a_report_confirmation_keeps_the_users_own_words(intent):
    """'the details you provided have been logged' is true on a report; the building did not
    provide them. The provenance-flag strip still runs there."""
    text = "Thank you — the data you provided has been logged as REP-1.\nsimulated: true"
    out = polish_answer(text, intent=intent)
    assert "the data you provided has been logged" in out
    assert "simulated" not in out


def test_information_is_not_a_rewritten_noun():
    text = "Thank you — the information you provided has been logged."
    assert polish_answer(text) == text


def test_a_data_lane_is_still_rewritten():
    out = polish_answer("The handover records you provided do not list lifts.", intent="metadata")
    assert out.startswith("The building's handover records")


def test_a_parenthetical_that_repeats_the_attribution_is_collapsed():
    """Measured live 2026-09-17: 'The building's records (the building's records) contain …'."""
    text = "The building’s records (the ontology data you provided) contain information about X."
    assert polish_answer(text, intent="metadata") == (
        "The building’s records contain information about X."
    )
    other = "Room 2.01 (the building's largest room) is free."
    assert polish_answer(other, intent="metadata") == other


# ── run 3: two phrasings that got past the first pass ────────────────────────


@pytest.mark.parametrize(
    "before,after",
    [
        (
            "No records of scheduled inspections are present in the ontology.",
            "No records of scheduled inspections are present in the building model.",
        ),
        ("The ontology only defines:", "The building model only defines:"),
        (
            "They may hold documentation not captured in the ontology data.",
            "They may hold documentation not captured in the building model.",
        ),
    ],
)
def test_the_reader_is_never_told_about_an_ontology(before, after):
    """Six answers in run 3 named it. 'Building model' is singular, so the verb still agrees."""
    assert polish_answer(before, intent="metadata") == after


def test_a_negated_reporting_verb_is_still_a_misattribution():
    """Run 3: 'The records you have do not contain …' — the same claim, negated."""
    out = polish_answer(
        "The records you have do not contain any information about exits.", intent="metadata"
    )
    assert out.startswith("The building's records do not contain")


def test_an_ontology_as_a_subject_of_its_own_is_left_alone():
    """A sentence genuinely about the modelling, not about where an answer came from."""
    text = "We model the building with an ontology, which the admin portal can edit."
    assert polish_answer(text, intent="metadata") == text


# ── run 4: "ontology" rose to 9 answers; three shapes the first pattern missed ─


@pytest.mark.parametrize(
    "before,after",
    [
        (
            "matters identified in the building's ontology as needing representation.",
            "matters identified in the building model as needing representation.",
        ),
        (
            "No explicit evidence in the current ontology that controls were transferred.",
            "No explicit evidence in the building model that controls were transferred.",
        ),
        (
            "This is not present in the building’s ontology data, so I cannot say.",
            "This is not present in the building model, so I cannot say.",
        ),
    ],
)
def test_the_possessive_and_adjectival_ontology_phrasings(before, after):
    assert polish_answer(before, intent="metadata") == after


def test_the_passive_misattribution_is_rewritten_too():
    """Run 4: 'The building's records that were provided contain …' — passive voice."""
    out = polish_answer(
        "The building's records that were provided contain information about coordination.",
        intent="metadata",
    )
    assert "that were provided" not in out
    assert out.startswith("The building's records contain")
