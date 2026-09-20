# -*- coding: utf-8 -*-
"""Narration hygiene (2D-09, BUG-832 / CAVEAT-833): the prose around a correct figure.

The figures in a narrated answer were right and the words around them were not: advice nobody
asked for ("Conduct a quick audit of the HVAC airflow ... rule out any blockage" on a 0.2 C
spread), norms with no source ("a delta-T of 10-12 C is typical"), a count that disagrees with
the list beside it ("the 2 ... (Floors 2 and 5 and the parking ventilation)"), a max-minus-min
range presented as a delta, and advice that moves a value the wrong way.

Every positive case below is a sentence recorded in a run under ``docs/phase0/``. The negative
cases matter as much: a validator that eats a policy sentence, a register field, a footer or a
correct count is worse than the defect it removes.
"""

import pytest

from orchestrator.services import narration_validators as nv

pytestmark = pytest.mark.unit

FOOTER = (
    "\n\n---\n**You might also ask:** Plot the comparison? | Export results?"
    "\n\n---\n*Sources: `Building model` `Sensor data`*"
)


def _clean(question, text, intent=None, evidence=None):
    return nv.validate_narration(question, text, intent, evidence).text


# ── (a) advice nobody asked for ──────────────────────────────────────────────

WARMEST = (
    "**Floor 5 is the warmest at 23.4 °C.** The floors span 23.2 to 23.4 °C, a spread of 0.2 °C.\n\n"
    "**Recommendation:** Conduct a quick audit of the HVAC airflow on floors 0, 3, and 4 to ensure "
    "even distribution and rule out any blockage that could be causing the slight elevation."
)


def test_a_recommendation_paragraph_nobody_asked_for_is_removed_and_the_figures_stay():
    out = _clean("Which floor is the warmest right now?", WARMEST + FOOTER, "compare")
    assert "audit" not in out and "Recommendation" not in out
    assert "**Floor 5 is the warmest at 23.4 °C.**" in out
    assert "spread of 0.2 °C" in out
    assert "You might also ask" in out and "Sources" in out, "footers are never edited"


@pytest.mark.parametrize(
    "question",
    [
        "What should I do to cut the energy use on floor 3?",
        "Can you recommend ways to save energy?",
        "How can I reduce the CO2 in room 5.01?",
        "Give me some tips to improve comfort.",
    ],
)
def test_advice_the_question_asks_for_is_left_alone(question):
    assert _clean(question, WARMEST, "compare") == WARMEST


def test_the_recommend_lane_is_never_edited_for_advice():
    assert _clean("Is the atrium ok?", WARMEST, "recommend") == WARMEST


def test_a_recommendations_section_goes_with_its_list_and_stops_at_the_footer():
    text = (
        "CO₂ in room 5.01 averaged 686 ppm yesterday, peaking at 729 ppm.\n\n"
        "**Recommendations**\n"
        "1. **Maintain ventilation** – Ensure the HVAC system keeps CO₂ below the observed maximum.\n"
        "2. **Implement real-time monitoring alerts** – Trigger alerts if CO₂ exceeds 1,100 ppm.\n"
        + FOOTER
    )
    out = _clean("Give me a report on the CO2 in room 5.01 yesterday.", text, "report")
    assert "Recommendations" not in out and "1,100" not in out and "Maintain ventilation" not in out
    assert "averaged 686 ppm" in out and "You might also ask" in out and "Sources" in out


@pytest.mark.parametrize(
    "sentence",
    [
        "To ensure continued accuracy, schedule a calibration check for both sensors.",
        "To promote a more uniform environment, consider fine‑tuning the HVAC setpoints or adding "
        "localized dehumidification in the areas with the highest readings.",
        "Review the equipment and usage patterns on Floor 3 to identify opportunities for energy "
        "savings.",
        "To keep the system balanced, continue to monitor the delta‑T on both boilers and adjust "
        "the flow rate if the difference widens beyond a few degrees.",
        "Continue monitoring to detect any future divergence in temperature readings.",
    ],
)
def test_an_unlabelled_closing_advice_sentence_is_removed(sentence):
    text = f"The average TVOC on Floor 3 is 220 ppb, with a high of 260 ppb. {sentence}"
    out = _clean("What is the average TVOC on floor 3 today?", text, "analytics")
    assert out == "The average TVOC on Floor 3 is 220 ppb, with a high of 260 ppb."


def test_advice_riding_on_the_tail_of_a_data_sentence_is_trimmed_not_dropped():
    text = (
        "The delta-T is 5.4 °C on Boiler 1. The system is functioning, though you might want to "
        "check whether the boilers are running at full capacity during peak demand."
    )
    out = _clean("What is the delta-T?", text, "sensor_data")
    assert out == "The delta-T is 5.4 °C on Boiler 1. The system is functioning."


def test_a_will_help_advice_tail_is_trimmed():
    text = (
        "Overall, the circuit is stable at 5.4 °C, but monitoring the trend will help catch drops."
    )
    assert _clean("Is it stable?", text, "trend") == "Overall, the circuit is stable at 5.4 °C."


@pytest.mark.parametrize(
    "text",
    [
        # a policy sentence in a capability answer is content, not advice
        "Out-of-hours queries should be directed to the security desk. The lab is on level 3, 12 m² "
        "in area.",
        # a caveat about the data, not advice about the building
        "W38 covers only 117 of 168 hours, so totals should not be compared. The rate fell 4.7 % "
        "per day.",
        # a decline naming what it cannot do
        "Naming one room, floor or date usually gives me enough. The floor holds 12 sensors (3 %).",
        # "consider" negated
        "Organisers cannot yet consider the evidence complete; 3 of 9 records (33 %) are "
        "outstanding.",
        # a register field named like the label, no narrated reading beside it
        "**Recommendation:** Replace the pump seal within 2 years.",
    ],
)
def test_sentences_that_are_not_advice_about_a_reading_are_left_alone(text):
    assert _clean("What is the position?", text, "metadata") == text


def test_a_table_row_is_never_edited():
    text = "| Floor | CO₂ |\n|---|---|\n| Consider 3 | 850 ppm |\n"
    assert _clean("What is the CO2?", text, "analytics") == text


def test_an_answer_that_is_only_advice_is_returned_untouched_rather_than_emptied():
    text = "**Recommendation:** Conduct a quick audit of the HVAC airflow at 24 °C."
    assert _clean("What is the position?", text, "analytics") == text


def test_a_dangling_bold_marker_is_not_left_behind():
    text = "Floor 3 averages 23.1 °C. **Recommendation:** review the HVAC setpoint for floor 3.**"
    out = _clean("How has floor 3 changed?", text, "trend")
    assert out.count("**") % 2 == 0 and "review" not in out


# ── (b) norms with no source ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sentence",
    [
        "A ΔT of 8–9 °C is typical for a heating circuit and indicates that heat is being "
        "transferred efficiently.",
        "A ΔT of around 10–12 °C is typical for efficient heating circuits.",
        "A delta‑T of 10–12 degC is typical for a healthy heating circuit, giving good heat transfer.",
        "A ΔT of 8–9 °C is slightly below the typical 10–15 °C target for efficient heating.",
        "*Expected benefit:* Typical buildings see 10 %–20 % lighting savings with this rule.",
        "A 1 °C set-point change typically saves 5-10 % of heating energy.",
        "The heating circuit is operating well; the temperature rise is within the expected healthy range.",
    ],
)
def test_a_norm_with_no_source_is_removed(sentence):
    text = f"The latest ΔT is 10.9 °C on Boiler 1 and 10.8 °C on Boiler 2. {sentence}"
    out = _clean("What is the delta-T?", text, "sensor_data")
    assert out == "The latest ΔT is 10.9 °C on Boiler 1 and 10.8 °C on Boiler 2."


def test_a_norm_that_trails_a_reading_is_cut_and_the_reading_is_kept():
    text = "The latest readings show ΔT values of 10.5–11.1 °C, which fall comfortably within the healthy operating range."
    assert _clean("What is the delta-T?", text, "sensor_data") == (
        "The latest readings show ΔT values of 10.5–11.1 °C."
    )
    text = "The latest readings are 10.5–11.1 °C, in line with the typical 10–12 °C range."
    assert _clean("What is the delta-T?", text, "sensor_data") == (
        "The latest readings are 10.5–11.1 °C."
    )


def test_a_threshold_invented_for_an_alert_is_removed_unless_advice_was_asked_for():
    text = (
        "CO₂ peaked at 1,101 ppm. Schedule a review if temperatures exceed 24.0 °C for more than "
        "two consecutive days."
    )
    assert _clean("How was the CO2?", text, "compare") == "CO₂ peaked at 1,101 ppm."
    # advice was asked for, so the advice stays; the threshold rule is not the one that applies
    assert "24.0" in _clean("What should I do about the temperature?", text, "compare")


@pytest.mark.parametrize(
    "sentence",
    [
        # both numbers are in the project's own standards files (ASHRAE 55 temperature band)
        "The recommended range is 20–26 °C.",
        # a named standard is the prompt's business (BUG-582), not this filter's
        "ASHRAE 55 treats 18–30 °C as tolerable.",
        # a verdict on a reading names no norm number
        "At 665 ppm the level is normal.",
        # the building's own recorded window is data
        "Only 3 records (12 %) run outside the normal operating window.",
        # a comparator with no number is not a norm claim
        "The maximum recorded flow (≈ 280 L min⁻¹) is far above typical tap use.",
        # measured against what the building recorded
        "Both bins are 62 % full, below their approved fill thresholds, so they are within the "
        "normal operating range.",
        # arrival advice is not a sensor norm: no measured quantity
        "A safe rule of thumb is to arrive 15 minutes before the scheduled start.",
    ],
)
def test_claims_that_are_sourced_recorded_or_not_norms_are_kept(sentence):
    text = f"The latest reading is 23.4 °C. {sentence}"
    assert _clean("What is the reading?", text, "sensor_data") == text


def test_evidence_the_caller_passes_makes_a_norm_cited():
    sentence = "A ΔT of 8–9 °C is typical for a heating circuit."
    text = f"The latest ΔT is 5.4 °C. {sentence}"
    assert _clean("What is the delta-T?", text, "sensor_data").endswith("5.4 °C.")
    kept = _clean("What is the delta-T?", text, "sensor_data", evidence="design band 8-9 K")
    assert kept == text


def test_a_typical_claim_built_from_the_answers_own_readings_is_a_summary_not_a_norm():
    text = "The 60 readings average 686 ppm. The typical level in this room is about 686 ppm."
    assert _clean("What is the CO2?", text, "sensor_data") == text


def test_the_narrow_no_break_space_and_non_breaking_hyphen_the_model_emits_do_not_hide_a_norm():
    text = (
        "The latest ΔT is 10.9 °C. A delta‑T of 10–12 °C is "
        "typical for a healthy heating circuit."
    )
    assert _clean("What is the delta-T?", text, "sensor_data") == ("The latest ΔT is 10.9 °C.")


# ── (c) a count that disagrees with the list beside it ───────────────────────


def test_a_count_followed_by_a_longer_list_of_ids_is_recounted_from_the_list():
    text = "There are 2 open permits (PTW‑0416, PTW‑0417 and PTW‑0418)."
    assert nv.check_counts_against_lists(text) == (
        "There are 3 open permits (PTW‑0416, PTW‑0417 and PTW‑0418)."
    )


def test_a_count_that_matches_its_list_is_untouched():
    text = "* **Due for review:** 3 records (APR‑006, APR‑019, APR‑032)"
    assert nv.check_counts_against_lists(text) == text


@pytest.mark.parametrize(
    "text",
    [
        # a partial listing may be right: the count is not the thing to overwrite
        "There are 6 floors (Floor 0, Floor 1, Floor 2).",
        # "e.g." says the list is a sample
        "There are 2 sensors (e.g. CO2, PM2.5 and TVOC).",
        # a label, not a count
        "Floor 2 (Room 2.01, 2.02 and 2.03) is quiet.",
        # a bracketed description, not an enumeration
        "1 (AHU Floor 0 supply air, 3 hours late) is running.",
    ],
)
def test_a_count_is_not_rewritten_when_the_list_may_be_partial_or_is_not_a_list(text):
    assert nv.check_counts_against_lists(text) == text


def test_a_prose_list_that_contradicts_its_count_loses_the_list_and_keeps_the_count():
    text = (
        "Of those 7, 5 have an approved exception, while **2 (the continuous regimes on Floors 2 "
        "and 5 and the parking ventilation) do not have an exception**."
    )
    assert nv.check_counts_against_lists(text) == (
        "Of those 7, 5 have an approved exception, while **2 do not have an exception**."
    )


def test_a_prose_list_that_agrees_with_its_count_is_kept():
    text = "The 2 without an exception (the regimes on Floors 2 and 5) run 24/7."
    assert nv.check_counts_against_lists(text) == text


FLOORS = (
    "- Floor 0: 13 people\n- Floor 1: 13 people\n- Floor 2: 12 people\n- Floor 3: 10 people\n"
    "- Floor 4: 12 people\n- Floor 5: 11 people\n\n**Total:** 71 people\n\n"
)


def test_a_per_floor_average_that_disagrees_with_the_listed_counts_is_dropped():
    text = FLOORS + "* Across the six floors the average occupancy is about 14 people per floor.\n"
    out = nv.check_counts_against_lists(text)
    assert "14 people per floor" not in out and "Floor 3: 10 people" in out


def test_a_per_floor_average_that_agrees_with_the_listed_counts_is_kept():
    text = FLOORS + "* Across the six floors that is about 12 people per floor.\n"
    assert nv.check_counts_against_lists(text) == text


# ── (d) a range presented as a delta ─────────────────────────────────────────

MAX_MINUS_MIN = (
    "Across all 7934 records the ΔT ranged from roughly **0 °C** up to **≈ 53 °C** "
    "(maximum leaving 74.4 °C minus minimum entering 21.7 °C)."
)


def test_max_of_one_stream_minus_min_of_another_is_not_a_delta():
    text = "The latest ΔT is 10.9 °C. " + MAX_MINUS_MIN
    assert nv.no_range_as_delta(text) == "The latest ΔT is 10.9 °C."


def test_the_spread_of_one_quantity_is_a_legitimate_range():
    text = "The spread is 2.1 °C (maximum temperature minus minimum temperature)."
    assert nv.no_range_as_delta(text) == text


# ── (e) advice that moves a value the wrong way ──────────────────────────────

CO2_FLOORS = (
    "The averages per floor are: Floor 0 – 847 ppm, Floor 1 – 846 ppm, Floor 2 – 851 ppm, "
    "Floor 3 – 853 ppm, Floor 4 – 846 ppm, and Floor 5 – 809 ppm."
)


@pytest.mark.parametrize(
    "advice",
    [
        "To balance indoor air quality, consider increasing ventilation on Floor 5 so its average "
        "CO₂ level moves toward the 800‑ppm range observed on the other floors.",
        "Increase ventilation or monitor occupancy on Floor 5 to bring its CO₂ level closer to the "
        "other floors.",
    ],
)
def test_advice_to_ventilate_the_floor_that_already_has_the_lowest_co2_is_removed(advice):
    out = nv.fix_advice_direction(f"{CO2_FLOORS} {advice}")
    assert out == CO2_FLOORS


def test_advice_to_ventilate_the_floor_with_the_highest_co2_stands():
    text = CO2_FLOORS + " Consider increasing ventilation on Floor 3 to bring its CO₂ down."
    assert nv.fix_advice_direction(text) == text


def test_a_raising_action_on_the_hottest_room_is_also_caught():
    text = (
        "Room 1: 21.0 °C, Room 2: 22.0 °C, Room 3: 26.5 °C. Raise the heating in Room 3 to keep "
        "it comfortable."
    )
    assert nv.fix_advice_direction(text).endswith("Room 3: 26.5 °C.")


def test_advice_about_a_different_quantity_is_not_judged_against_the_listed_one():
    # Floor 5 has the lowest CO2, but this advice is about humidity, which the list does not give
    text = CO2_FLOORS + " Consider increasing ventilation on Floor 5 to reduce its humidity."
    assert nv.fix_advice_direction(text) == text


def test_without_a_per_entity_list_the_direction_rule_does_nothing():
    text = "Consider increasing ventilation on Floor 5 so its CO₂ moves toward 800 ppm."
    assert nv.fix_advice_direction(text) == text


# ── the pipeline ─────────────────────────────────────────────────────────────


def test_the_pipeline_cleans_every_defect_in_one_answer_and_reports_each_edit():
    text = (
        "Latest ΔT 5.4 °C. A ΔT of 8–9 °C is typical for a heating circuit. "
        + MAX_MINUS_MIN
        + "\n\n**Recommendation:** Verify that the flow rate through each boiler stays steady."
    )
    res = nv.validate_narration("What is the delta-T?", text, "sensor_data")
    assert res.text == "Latest ΔT 5.4 °C."
    assert {c.validator for c in res.changes} == {
        "no_range_as_delta",
        "strip_uncited_norms",
        "drop_unasked_advice",
    }


def test_the_pipeline_is_idempotent_so_a_cached_answer_polished_twice_is_unchanged():
    text = WARMEST + FOOTER
    once = _clean("Which floor is the warmest?", text, "compare")
    assert _clean("Which floor is the warmest?", once, "compare") == once


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input_is_returned_as_it_came(text):
    assert nv.validate_narration("q", text, "analytics").text == text


def test_code_fences_and_the_dossier_block_are_never_edited():
    text = (
        "CO₂ is 700 ppm.\n\n```\nRecommendation: Conduct an audit at 24 °C\n```\n\n"
        "<details>\n<summary>How I worked this out</summary>\n"
        "Recommendation: Conduct an audit at 24 °C\n</details>"
    )
    assert _clean("What is the CO2?", text, "analytics") == text


def test_a_heading_left_over_an_emptied_block_goes_with_it():
    text = (
        "The latest ΔT is 10.9 °C.\n\n**Key take-away**\n"
        "A ΔT of 8-9 °C is typical for a heating circuit.\n" + FOOTER
    )
    out = _clean("What is the delta-T?", text, "sensor_data")
    assert "Key take-away" not in out and out.startswith("The latest ΔT is 10.9 °C.")
    assert "You might also ask" in out


def test_the_recommend_lane_keeps_its_advice_but_loses_an_invented_saving():
    text = (
        "1. **Target Floor 3.**\n   *Why:* Floor 3 uses 3.64 kWh.\n"
        "   *Expected benefit:* A 1 °C rise in set-point can cut HVAC energy by roughly 5 %-10 %.\n"
        "2. **Tie lighting to occupancy.**\n"
        "   *Expected benefit:* Typical buildings see 10 %-20 % lighting savings with this rule.\n"
    )
    out = _clean("Can you provide energy saving suggestions?", text, "recommend")
    assert "Target Floor 3" in out and "Tie lighting to occupancy" in out
    assert "5 %-10 %" not in out and "10 %-20 %" not in out


def test_a_number_only_the_removed_advice_mentioned_cannot_vouch_for_a_norm():
    # "24 °C" appears in the advice and in the norm; once the advice is gone the norm is uncited.
    text = (
        "**Floor 3 is the warmest, averaging 23.3 °C.**\n"
        "This is within the typical 21 °C – 24 °C comfort band for office spaces.\n\n"
        "**Recommendation:** Keep an eye on the set-point; if the mean rises above 24 °C, consider "
        "tightening the cooling schedule.\n"
    )
    once = _clean("Which floor is the warmest right now?", text, "compare")
    assert "typical" not in once and "Recommendation" not in once
    assert _clean("Which floor is the warmest right now?", once, "compare") == once


def test_a_bold_finding_is_never_mistaken_for_a_heading_over_an_emptied_block():
    text = (
        "**Floor 5 is the warmest at 23.4 °C**\n"
        "This is within the typical 21 °C – 24 °C comfort band for offices.\n"
    )
    out = _clean("Which floor is the warmest?", text, "compare")
    assert out.strip() == "**Floor 5 is the warmest at 23.4 °C**"


def test_an_answer_the_guard_refuses_to_empty_reports_no_edits():
    text = "**Recommendation:** Conduct a quick audit of the HVAC airflow at 24 °C."
    res = nv.validate_narration("What is the position?", text, "analytics")
    assert res.text == text and res.changes == []


def test_advice_whose_only_clause_is_a_subordinate_one_is_dropped_not_left_as_a_fragment():
    text = (
        "Floor 3 is the warmest at 23.3 °C. Because Floor 3 is slightly warmer, consider checking "
        "for localized heat sources and adjusting the HVAC setpoint."
    )
    assert _clean("Which floor is the warmest?", text, "compare") == (
        "Floor 3 is the warmest at 23.3 °C."
    )


def test_a_humidity_range_is_cited_by_the_standards_even_when_the_sentence_never_says_humidity():
    text = (
        "The humidity on Floor 4 is 52 %. The recommended range is 30–60 %, so this is comfortable."
    )
    assert _clean("What's the humidity like on floor 4?", text, "analytics") == text


# ── lanes that are content, not narration ────────────────────────────────────

POLICY = (
    "The ventilation policy sets CO₂ at 1,000 ppm. Consider opening windows when the level "
    "exceeds it, and schedule a calibration check of the sensors every year. A delta-T of 10-12 °C "
    "is typical for a heating circuit."
)


@pytest.mark.parametrize(
    "intent", ["capability", "metadata", "register", "self_description", "diagnosis"]
)
def test_a_lane_that_quotes_content_is_not_judged_for_advice_or_norms(intent):
    assert _clean("What does the policy say?", POLICY, intent) == POLICY


def test_the_same_sentences_are_removed_from_a_narrated_lane():
    out = _clean("What is the CO2?", POLICY, "analytics")
    assert "Consider opening" not in out and "calibration check" not in out
    assert "is typical" not in out and out.startswith(
        "The ventilation policy sets CO₂ at 1,000 ppm."
    )


def test_a_miscount_is_repaired_in_a_register_lane_because_it_is_a_defect_in_any_lane():
    text = "There are 2 open permits (PTW‑0416, PTW‑0417 and PTW‑0418)."
    assert "3 open permits" in _clean("Which permits are open?", text, "metadata")


# ── wiring: answer_wording.polish_answer ─────────────────────────────────────


def test_polish_answer_runs_the_hygiene_on_the_text_the_reader_receives():
    from orchestrator.services.answer_wording import polish_answer

    out = polish_answer(WARMEST + FOOTER, "Which floor is the warmest right now?", "compare")
    assert "audit" not in out and "Recommendation" not in out
    assert "spread of 0.2 " in out and "Sources" in out


def test_polish_answer_leaves_advice_alone_when_the_question_asked_for_it():
    from orchestrator.services.answer_wording import polish_answer

    assert polish_answer(WARMEST, "How can I cool floor 5?", "compare") == WARMEST


@pytest.mark.parametrize("intent", ["maintenance", "complaint", "feedback", "safety_report"])
def test_polish_answer_never_edits_a_lane_whose_content_the_user_supplied(intent):
    from orchestrator.services.answer_wording import polish_answer

    assert polish_answer(WARMEST, "The toilet is leaking at 24 degrees.", intent) == WARMEST
