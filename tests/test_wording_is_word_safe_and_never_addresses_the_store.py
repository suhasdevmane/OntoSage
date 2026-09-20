# -*- coding: utf-8 -*-
"""Mechanical wording defects from the newest unseen set (2D-16 wave 6).

Every text is the LIVE text. The defects share one shape: the wording layer treated a fragment of
the question, or of the store's own addressing, as though it were prose for the reader.
"""

from __future__ import annotations

import glob
import json
import os

import pytest

from orchestrator.services import absence_second_chance as sc
from orchestrator.services import absence_wording as aw
from orchestrator.services import clarification as cl
from orchestrator.services import fallback_wording as fw
from orchestrator.services import plausibility as pl

pytestmark = pytest.mark.unit


# ── (1) a word is never chopped ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "answer,expected",
    [
        (
            "The public event records do not include official text-based check-in or arrival "
            "contact.",
            "official text-based check-in or arrival contact",
        ),
        ("The register does not record ongoing works.", "ongoing works"),
        ("The register does not include total floor area.", "total floor area"),
        ("The register does not include datasets of spills.", "datasets of spills"),
        ("The register does not list entryway doors.", "entryway doors"),
    ],
)
def test_a_missing_thing_keeps_its_first_word_whole(answer, expected):
    shape = sc.detect_absence_shape(answer)
    assert shape is not None and shape.object_text == expected, shape


def test_a_real_preposition_is_still_dropped():
    shape = sc.detect_absence_shape("The register does not record information about spills.")
    assert shape is not None and shape.object_text == "spills"


# ── (2) an article ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "obj,want",
    [
        ("answer", "any answer"),
        ("maintenance schedule", "any maintenance schedule"),
        ("waste volumes", "any waste volumes"),
        ("any evidence", "any evidence"),
        ("Room 5.01", "Room 5.01"),
        ("your booking", "your booking"),
    ],
)
def test_the_missing_thing_reads_as_english(obj, want):
    assert sc._with_a_determiner(obj) == want


def test_the_scoped_sentence_has_its_article():
    shape = sc.AbsenceShape("not_recorded", "x", "answer", True, True)
    assert "I did not find any answer in the records I searched." in sc.scoped_sentence(
        shape, "", []
    )


# ── (4) a spliced clause is not part of the thing that is missing ────────────


def test_the_answers_own_commentary_is_not_spliced_into_the_object():
    answer = "The records do not include waste volumes, so it cannot contribute to the answer."
    shape = sc.detect_absence_shape(answer)
    assert shape.object_text == "waste volumes"
    text = sc.scoped_sentence(shape, "the building's patrol checkpoint records", [])
    assert text == "I did not find any waste volumes in the building's patrol checkpoint records."


# ── (3) no fragment quoted as a topic, no identifier printed ─────────────────


def _abstract(entities=()):
    _, text = cl.compose(
        building="Abacws Building",
        question="Which services keep performance below target and without reducing capacity?",
        unmatched=["performance", "below", "without", "reducing"],
        measured=[],
        records=[],
        outdoor=None,
        entities=list(entities),
    )
    return text


def test_no_arbitrary_pair_of_tokens_is_named_as_the_topic():
    text = _abstract()
    assert "nothing came back about" not in text
    assert "performance below" not in text and "without reducing" not in text


def test_an_ontology_class_name_is_never_printed_to_a_reader():
    text = _abstract(["Motor", "Reactive_Power_Sensor"])
    assert "_" not in text and "Reactive" not in text
    unanswered = fw.compose_unanswered(
        building="Abacws Building",
        question="how is the motor",
        entities=["Motor", "Reactive_Power_Sensor"],
    )
    assert "_" not in unanswered and "**Motor**" in unanswered


def test_readable_names_keeps_a_room_and_drops_identifiers():
    assert cl.readable_names(
        ["Room 5.01", "hasTimeseriesId", "Air_Quality_Sensor", "Room 5.01"]
    ) == ["Room 5.01"]


# ── (5) how the store addresses things is not the reader's business ──────────

URI_TALK = (
    "The lift is on Level 3. Its name is the part after the last '#' in its URI. "
    "It is currently in service."
)
UUID_TALK = "Each sensor has a UUID that can be used to query its data. The sensor reads 21.4 °C."


def test_the_uri_and_uuid_explanations_are_removed_and_the_answer_stays():
    out = aw.strip_store_addressing(URI_TALK, "is the lift working?")
    assert "URI" not in out and "The lift is on Level 3." in out and "in service" in out
    out = aw.strip_store_addressing(UUID_TALK, "what is the temperature?")
    assert "UUID" not in out and "21.4" in out


def test_a_sentence_carrying_a_figure_is_never_dropped():
    text = "The Timeseries ID 8841 has 12 readings today."
    assert aw.strip_store_addressing(text, "how many readings?") == text


def test_the_one_record_phrase_is_reworded_not_deleted():
    out = aw.strip_store_addressing(
        "The query returned a single record: Room 5.01 at 21.4 °C.", "temperature in 5.01?"
    )
    assert "query" not in out.lower() and "Room 5.01 at 21.4" in out


def test_a_reader_who_asks_about_identifiers_is_answered_in_them():
    text = "The Timeseries ID is the key for its data."
    assert aw.strip_store_addressing(text, "what is the timeseries id of this sensor?") == text


def test_a_table_row_is_left_alone():
    text = "| Sensor | Timeseries ID |\n| a | b |"
    assert aw.strip_store_addressing(text, "list the sensors") == text


def test_the_absence_rewrite_applies_it_when_nothing_else_narrates():
    out = aw.rewrite_semantic_absence(URI_TALK, "is the lift working?", "B")
    assert out is not None and "URI" not in out


# ── (6) a figure needs a reason ──────────────────────────────────────────────

MODE_ANSWER = (
    "The HVAC system is currently in mode 3960, which is above the normal set of modes. The "
    "zone temperature is 21.5 °C, and this is high."
)


def test_a_mode_question_is_never_answered_with_a_temperature_warning():
    assert pl.implausibility_note("What mode is the HVAC system in right now?", MODE_ANSWER) is None


def test_a_number_the_answer_never_quotes_as_the_quantity_is_not_judged():
    """The question names no quantity, so the measurand came from the answer's own wording."""
    draft = "The reading is 3960 on this point, and the temperature there is high."
    assert pl.implausibility_note("what is the value on that point?", draft) is None


def test_a_real_impossible_temperature_is_still_flagged():
    note = pl.implausibility_note(
        "is the temperature high in 5.01?", "The temperature is 3960 in 5.01, which is high."
    )
    assert note and "3960" in note


# ── the standard: nothing the hand read called good may change ───────────────

_PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "phase0")


def _recorded():
    for path in sorted(glob.glob(os.path.join(_PH, "*.jsonl"))):
        base = os.path.basename(path)
        if base.endswith("_read.jsonl") or "tail_G" in base or "tail_H" in base:
            continue
        rp = path.replace(".jsonl", "_read.jsonl")
        reads = (
            [json.loads(l) for l in open(rp, encoding="utf-8") if l.strip()]
            if os.path.exists(rp)
            else []
        )
        try:
            rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        except ValueError:
            continue
        for i, row in enumerate(rows):
            verdict = (reads[i].get("verdict") if i < len(reads) else None) or "?"
            yield row.get("q") or "", row.get("answer") or "", verdict


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_no_recorded_good_answer_is_changed_by_the_wave_six_guards():
    changed = []
    for q, a, v in _recorded():
        if not a.strip() or not v.startswith("GOOD"):
            continue
        if aw.strip_store_addressing(a, q) != a or pl.implausibility_note(q, a):
            changed.append((q[:70], a[:100].replace("\n", " ")))
    assert not changed, "\n".join(f"{q} -> {a}" for q, a in changed)
