# -*- coding: utf-8 -*-
"""The fallback speaks to the reader, not about the pipeline (2D-16, defect class C5).

"I understood the question but could not put an answer together for it. I read it as a question
about **general** ... I could not match **moment** or **empty** to anything this building records"
reached stakeholders on 4 of 147 (2.7%) catalogue answers and 1 of 42 fresh-tail answers. This file
pins the replacement at the module level (`services/fallback_wording`), offline and without a
graph: the caller supplies what the building holds.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import fallback_wording as fw
from orchestrator.services.grounding_guard import names_internal_vocabulary

pytestmark = pytest.mark.unit


def _rec(label, instances=10, terms=()):
    return SimpleNamespace(label=label, instances=instances, terms=tuple(terms))


MEASURED = ["CO2", "humidity", "occupancy", "temperature"]
RECORDS = [
    _rec("Work order", 412, ("work order", "work orders")),
    _rec("Room booking", 88, ("room booking", "bookings")),
    _rec("Cleaning task", 30, ("cleaning task",)),
]


def _text(**kw):
    base = dict(
        building="Example Building", question="anything", measured=MEASURED, records=RECORDS
    )
    base.update(kw)
    return fw.compose_unanswered(**base)


def test_no_lane_intent_or_classifier_vocabulary_is_ever_shown():
    text = _text(question="Which rooms are empty at the moment?", unmatched=["moment", "empty"])
    assert names_internal_vocabulary(text) is None
    for shown in ("I read it as", "question about", "**general**", "**diagnosis**", "what to do"):
        assert shown not in text
    assert "to anything this building records" not in text
    assert "could not put an answer together" not in text


def test_filler_words_are_never_named_back_as_though_they_were_things():
    assert fw.pick_referent([], ["moment", "empty"]) == "empty"
    assert fw.pick_referent([], ["moment", "recently"]) == ""
    text = _text(unmatched=["moment"])
    assert "moment" not in text and text.count("?") == 0


def test_a_real_missing_referent_is_asked_about_exactly_once_as_a_question():
    text = _text(question="Is the phone booth free?", unmatched=["booth", "phone"])
    assert text.count("?") == 1
    assert "Which measurement or record do you mean by **booth**?" in text
    assert "Try asking" not in text, "one question back, not a menu as well"


def test_a_named_place_is_kept_in_the_reader_s_words():
    text = _text(entities=["Room 5.04"])
    assert "Room 5.04" in text and text.startswith("I couldn't answer that about **Room 5.04**")


def test_what_the_building_can_answer_is_ranked_by_closeness_to_the_question():
    names, labels = fw.nearest_holdings("how many bookings are there", MEASURED, RECORDS)
    assert labels[0] == "Room booking"
    names, _ = fw.nearest_holdings("is it humid", ["CO2", "humidity"], [])
    assert names[0] == "humidity"


def test_with_no_overlap_the_building_s_own_order_is_kept():
    names, labels = fw.nearest_holdings("zzz", MEASURED, RECORDS)
    assert names == MEASURED and labels == ["Work order", "Room booking", "Cleaning task"]


def test_an_unreadable_building_is_not_padded_with_a_guess():
    text = _text(measured=[], records=[])
    assert "I can answer about" not in text and "Try asking" not in text
    assert text.startswith("I couldn't answer that from Example Building's records.")


def test_the_text_states_no_figure():
    import re

    assert not re.search(r"(?<![A-Za-z])\d", _text(question="anything")), "digits inside CO2 aside"


def test_a_step_error_appears_only_when_the_caller_passes_it():
    assert "A step reported" not in _text()
    assert "A step reported: sql: timeout" in _text(step_error="sql: timeout")


def test_the_boundary_pointer_names_only_records_near_the_question():
    near = fw.compose_boundary_pointer("Example Building", "how many bookings are held", RECORDS)
    assert "Room booking" in near and "Work order" not in near
    assert fw.compose_boundary_pointer("Example Building", "is there a helipad", RECORDS) == ""
    assert fw.compose_boundary_pointer("Example Building", "bookings", []) == ""


# ── the pointer reaches the capability lane's own boundary ───────────────────


def test_the_capability_boundary_appends_a_pointer_and_never_raises(monkeypatch):
    import orchestrator.agents.capability_agent as cap

    assert cap._boundary_pointer("B", "bookings", RECORDS).startswith(
        "\n\nB does keep Room booking"
    )

    def boom(*_a, **_k):
        raise RuntimeError("wording module gone")

    monkeypatch.setattr(fw, "compose_boundary_pointer", boom)
    assert cap._boundary_pointer("B", "bookings", RECORDS) == ""


# ── general guidance is connected to the workflow node the routing contract uses ──


def test_the_guidance_node_uses_the_writer_and_keeps_the_label_and_pointer(monkeypatch):
    from orchestrator.services import general_guidance as gg
    from orchestrator.services import guidance_node as node

    async def fake_llm(prompt, system_message):
        return "Humidity can shift the readings of some CO2 sensors. Calibration reduces the drift."

    monkeypatch.setattr(gg, "_default_llm", fake_llm)
    state = SimpleNamespace(
        messages=[SimpleNamespace(content="does humidity affect CO2 sensor accuracy?")],
        persona="engineer",
        intermediate_results={},
        current_intent="",
    )
    out = asyncio.run(node.general_guidance_node(state))
    text = out.intermediate_results["dialogue_response"]
    assert text.startswith(node.LABEL) and text.rstrip().endswith(gg.POINTER)
    assert out.intermediate_results["general_guidance"] == {"written": True}
    assert node.LABEL == gg.LABEL, "the two modules must agree on the label"


def test_a_writer_that_declines_leaves_the_node_s_honest_sentence(monkeypatch):
    from orchestrator.services import general_guidance as gg
    from orchestrator.services import guidance_node as node

    async def fake_llm(prompt, system_message):
        return "Keep it under 800 ppm. Room 2.01 is too high."

    monkeypatch.setattr(gg, "_default_llm", fake_llm)
    state = SimpleNamespace(
        messages=[SimpleNamespace(content="how do I control CO2?")],
        persona=None,
        intermediate_results={},
        current_intent="",
    )
    out = asyncio.run(node.general_guidance_node(state))
    assert out.intermediate_results["dialogue_response"] == node.unavailable_text()
    assert out.intermediate_results["general_guidance"] == {"written": False}
