# -*- coding: utf-8 -*-
"""General guidance may answer more, but only in ways a reader cannot mistake (owner policy 2026-09-19).

"Does humidity affect CO2 sensor accuracy?" or "how do BREEAM and LEED differ?" ask for knowledge,
not for a reading. The policy is to answer them, labelled as general guidance. What makes that safe
is not the prompt (a model can ignore it) but a checker that runs on the text afterwards, so every
rule is pinned here against a FAKE model that misbehaves on purpose.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services import general_guidance as gg

pytestmark = pytest.mark.unit

LABEL = "General guidance (not from this building's records):"


def _fake(reply: str):
    calls = []

    async def llm(prompt: str, system_message: str) -> str:
        calls.append((prompt, system_message))
        return reply

    llm.calls = calls
    return llm


def _run(question: str, reply: str, persona=None) -> str:
    return asyncio.run(gg.general_guidance(question, persona, llm=_fake(reply)))


def test_the_answer_starts_with_the_label_and_ends_with_a_pointer_to_the_building():
    text = _run(
        "does humidity affect CO2 sensor accuracy?",
        "Yes. Many CO2 sensors drift when humidity is very high because moisture changes how the "
        "infrared light is absorbed. Regular calibration reduces the error.",
    )
    assert text.startswith(LABEL)
    assert text.rstrip().endswith(gg.POINTER)
    assert "Many CO2 sensors drift" in text


def test_a_model_that_writes_its_own_label_is_not_quoted_twice():
    text = _run(
        "how do I control CO2?",
        "General guidance (not from this building's records): Increase fresh air supply.",
    )
    assert text.count("General guidance") == 1
    assert "Increase fresh air supply." in text


def test_the_whole_answer_is_at_most_120_words():
    long_reply = " ".join(
        f"Ventilation removes pollutant number {w} from the air." for w in "abcdefghij" * 4
    )
    text = _run("how do I control CO2?", long_reply)
    assert len(text.split()) <= 120, len(text.split())
    assert text.endswith(gg.POINTER), "truncation cuts whole sentences and keeps the pointer"


# ── no figures the question did not contain ──────────────────────────────────


def test_a_sentence_carrying_a_figure_the_question_did_not_contain_is_dropped():
    text = _run(
        "how do I control CO2?",
        "Ventilate with fresh air. Keep CO2 below 1000 ppm at all times. Open windows if you can.",
    )
    assert "1000" not in text and "ppm" not in text
    assert "Ventilate with fresh air." in text and "Open windows if you can." in text


def test_a_figure_the_question_itself_contained_may_be_discussed():
    text = _run(
        "is 1000 ppm CO2 too high?",
        "Around 1000 ppm indicates the air is not being refreshed quickly enough. Ventilation helps.",
    )
    assert "1000 ppm" in text


def test_digits_inside_a_chemical_name_are_not_figures():
    text = _run("how do I control CO2?", "CO2 builds up when people breathe in a closed space.")
    assert "CO2 builds up" in text


def test_a_percentage_or_a_temperature_is_a_figure():
    text = _run(
        "does humidity affect comfort?",
        "Humidity matters. Most people feel comfortable near 45% relative humidity. "
        "Temperature interacts with it.",
    )
    assert "45%" not in text
    assert "Humidity matters." in text and "Temperature interacts with it." in text


# ── nothing about a particular building ──────────────────────────────────────


@pytest.mark.parametrize(
    "sentence",
    [
        "In this building the chillers are old.",
        "Your building probably has poor airtightness.",
        "Floor 3 is usually the worst.",
        "Room 5.01 needs attention.",
    ],
)
def test_a_building_specific_sentence_is_dropped(sentence):
    text = _run("what does a delta-T mean?", f"Delta-T is a temperature difference. {sentence}")
    assert "Delta-T is a temperature difference." in text
    assert sentence not in text


def test_the_configured_building_name_is_never_spoken():
    out = gg.sanitise(
        "Delta-T is a temperature difference. Abacws Building runs a big chiller.",
        "what does a delta-T mean?",
        building_names=["Abacws Building"],
    )
    assert "Abacws" not in out and out.startswith("Delta-T")


# ── standards ────────────────────────────────────────────────────────────────


def test_a_standard_the_project_holds_may_be_named():
    assert "breeam" in gg.allowed_standards()
    text = _run(
        "how do BREEAM and LEED differ?",
        "BREEAM is a UK-origin assessment method that scores buildings across categories such as "
        "energy and health.",
    )
    assert "BREEAM is a UK-origin" in text


def test_a_standard_the_project_does_not_hold_is_not_cited_unless_the_question_named_it():
    reply = "Follow ISO 14644 for cleanrooms. Good ventilation reduces pollutants."
    text = _run("how do I control CO2?", reply)
    assert "ISO 14644" not in text
    assert "Good ventilation reduces pollutants." in text
    asked = _run("what is ISO 14644?", "ISO 14644 is a family of cleanroom standards.")
    assert "ISO 14644 is a family" in asked


def test_leed_is_discussed_only_because_the_question_named_it():
    text = _run(
        "how do BREEAM and LEED differ?",
        "LEED is a North American rating system. Their scoring weights differ.",
    )
    assert "LEED is a North American rating system." in text
    assert "LEED" not in _run("how do I control CO2?", "LEED credits reward this. Ventilate.")


# ── every failure leaves the caller with an honest empty string ──────────────


def test_a_model_that_fails_returns_nothing_rather_than_something_unchecked():
    async def boom(prompt, system_message):
        raise RuntimeError("provider down")

    assert asyncio.run(gg.general_guidance("how do I control CO2?", None, llm=boom)) == ""


def test_an_empty_reply_returns_nothing():
    assert _run("how do I control CO2?", "   ") == ""


def test_a_reply_made_only_of_forbidden_sentences_returns_nothing():
    assert _run("how do I control CO2?", "Keep it under 800 ppm. Room 2.01 is too high.") == ""


def test_a_question_that_is_not_about_buildings_is_not_answered():
    fake = _fake("Paris is the capital of France.")
    out = asyncio.run(gg.general_guidance("what is the capital of France?", None, llm=fake))
    assert out == "" and fake.calls == [], "the model must not even be asked"


# ── the prompt carries the rules and the persona ─────────────────────────────


def test_the_prompt_states_the_rules_and_lists_only_the_standards_the_project_holds():
    fake = _fake("Ventilate.")
    asyncio.run(gg.general_guidance("how do I control CO2?", "occupant", llm=fake))
    ((_, system),) = fake.calls
    assert "NO access to any building" in system
    assert "BREEAM" in system and "LEED" not in system
    assert "occupant" in system


def test_an_unknown_persona_falls_back_to_a_general_reader():
    assert "general reader" in gg.system_prompt("nobody_knows_this")
    assert "facility manager" in gg.system_prompt("facility_manager")


def test_urls_and_code_fences_are_removed():
    out = gg.sanitise(
        "Ventilate well. See https://example.com/x for more. ```print(1)``` Filters help.",
        "how do I control CO2?",
    )
    assert "http" not in out and "print" not in out
    assert "Ventilate well." in out and "Filters help." in out
