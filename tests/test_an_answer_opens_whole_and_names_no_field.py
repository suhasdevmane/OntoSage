# -*- coding: utf-8 -*-
"""Wording defects left after wave 6 (2D-16 wave 7). Every text is the LIVE text.

An answer must not open with a sentence that points at something the reader was never shown, must
not carry an unmatched quotation mark, must not print a store field name, and must not repeat a
long second sentence on one answer in seven.
"""

from __future__ import annotations

import glob
import inspect
import json
import os

import pytest

from orchestrator.services import absence_second_chance as sc
from orchestrator.services import absence_wording as aw

pytestmark = pytest.mark.unit

Q = "Can settings be changed for the benefit of employee comfort even if they decrease efficiency?"


# ── (1) no orphaned opening ──────────────────────────────────────────────────


def test_a_removal_that_leaves_an_orphan_first_sentence_drops_it():
    before = (
        "The data you received only lists sensors. They only record scheduled closure periods "
        "for floors and the building. The building is closed on public holidays and on 24 "
        "December each year."
    )
    after = (
        "They only record scheduled closure periods for floors and the building. The building is "
        "closed on public holidays and on 24 December each year."
    )
    out = aw.mend_opening(after, before, "when is it closed?")
    assert out.startswith("The building is closed on public holidays")


@pytest.mark.parametrize(
    "orphan",
    [
        "None of those sensor entries contain information about: Current or adjustable settings.",
        "All of them describe the building's parent-child hierarchy (e.g. 'Abacws Building').",
        "These describe the floors.",
        "Those are the rooms.",
        "It only records closures.",
        "Each of them holds a name.",
        "and the building is closed.",
    ],
)
def test_each_orphan_opener_is_removed_when_a_sentence_was_removed(orphan):
    body = "The building keeps a closure register with 12 entries for the year."
    out = aw.mend_opening(f"{orphan} {body}", f"An earlier sentence. {orphan} {body}", Q)
    assert out == body


def test_when_nothing_of_substance_is_left_the_honest_decline_stands_in():
    out = aw.mend_opening(
        "They only record closures.", "Removed sentence. They only record closures.", Q
    )
    assert "does not exist" in out or "I found nothing" in out
    assert "They only" not in out


def test_a_strict_opener_is_an_orphan_even_when_nothing_was_removed():
    text = "None of those sensor entries contain information about settings. The building has a BMS with 12 controllers."
    assert aw.mend_opening(text, text, Q).startswith("The building has a BMS")


def test_an_ordinary_opening_is_never_touched():
    for text in (
        "The lift is in service.",
        "Yes — it is open on Mondays.",
        "**Answer**\n\nRoom 5.01 is a laboratory with 12 desks and a fume cupboard.",
        "- It is a bullet\n- and another",
        "It is open on Mondays.",  # a follow-up answer: 'it' has an antecedent in the chat
    ):
        assert aw.mend_opening(text, text, Q) == text


def test_the_footer_survives():
    before = "Gone. They only list floors. The building has six floors and a roof plant room."
    after = "They only list floors. The building has six floors and a roof plant room.\n\n---\n*Sources: x*"
    out = aw.mend_opening(after, before, Q)
    assert out.startswith("The building has six floors") and out.endswith("*Sources: x*")


def test_the_narration_strip_leaves_no_orphan_through_the_public_entry_point():
    text = (
        "The data you received only lists sensor counts per room. They only record how many "
        "sensors each space has. The building has 234 rooms across six floors in total."
    )
    out = aw.rewrite_semantic_absence(text, "how many rooms?", "B")
    assert out is not None and not out.lower().startswith("they")


def test_the_response_node_calls_the_shared_helper_after_the_last_pass():
    from orchestrator.workflow import _orchestrator as mod

    src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    assert src.index("_before_hygiene = final_response") < src.index("mend_opening(")
    assert src.index("meta-answer check skipped") < src.index("mend_opening(")


# ── (2) quotation marks balance ──────────────────────────────────────────────


def test_a_lone_quotation_mark_is_dropped_and_a_pair_kept():
    assert sc.balance_quotes('bookable room as "reliable') == "bookable room as reliable"
    assert sc.balance_quotes('a "quiet" room') == 'a "quiet" room'
    assert sc.balance_quotes("a “quiet room") == "a quiet room"
    assert sc.balance_quotes("a “quiet” room") == "a “quiet” room"


def test_the_object_phrase_no_longer_keeps_an_opening_quote_it_lost_the_close_of():
    shape = sc.detect_absence_shape(
        'The records do not include any bookable room described as "reliable".'
    )
    assert shape is not None and '"' not in shape.object_text
    sentence = sc.scoped_sentence(shape, "the building's workspace profile records", [])
    assert sentence.count('"') % 2 == 0


# ── (3) no field name, no broken grammar ─────────────────────────────────────


def test_a_field_name_in_bold_or_code_never_reaches_the_reader():
    text = (
        "The building's data only tells us how many sensors each space has (the **sensor_count** "
        "field). It lists 234 rooms in total, and `room_type` is not held."
    )
    out = aw.strip_store_addressing(text, "which rooms are labs?")
    assert "_" not in out and "sensor_count" not in out
    assert "(the" not in out and "room type is not held" in out


def test_a_reader_asking_about_fields_is_told_the_field_names():
    text = "The register has a **sensor_count** field."
    assert aw.strip_store_addressing(text, "what fields does the register have?") == text


def test_a_table_of_fields_is_left_alone():
    text = "| **sensor_count** | 4 |"
    assert aw.strip_store_addressing(text, "which rooms are labs?") == text


@pytest.mark.parametrize(
    "answer,obj",
    [
        (
            "None of the entries contain information about existing signage.",
            "existing signage",
        ),
        (
            "The data does not list; it does not contain any contain information about signage.",
            None,
        ),
    ],
)
def test_the_object_never_starts_with_the_verb_the_pattern_left_behind(answer, obj):
    shape = sc.detect_absence_shape(answer)
    if obj is not None:
        assert shape is not None and shape.object_text == obj
    if shape is not None:
        assert not shape.object_text.lower().startswith(("contain", "include", "list"))


def test_a_leading_verb_is_removed_from_the_object():
    assert sc._without_a_leading_verb("contain information about existing signage") == (
        "existing signage"
    )
    assert sc._without_a_leading_verb("waste volumes") == "waste volumes"
    text = sc.scoped_sentence(
        sc.AbsenceShape("x", "s", "contain information about existing signage", True, True),
        "the records I searched",
        [],
    )
    assert "any contain" not in text


# ── (4) the repeat is one plain clause ───────────────────────────────────────


def test_the_measured_quantity_is_said_in_one_short_clause():
    from types import SimpleNamespace

    shape = sc.AbsenceShape("x", "s", "reliable occupancy", True, True)
    sensor = SimpleNamespace(
        kind="sensor", label="occupancy across the building", score=467.0, shared=()
    )
    text = sc.scoped_sentence(shape, "the building's records", [sensor])
    assert "**does** measure occupancy across the building (467 series); ask for it." in text
    assert "so the limitation" not in text and len(text.split(". ")[-1].split()) <= 14


# ── the standard: nothing the hand read called good may change ───────────────

_PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "phase0")


def _recorded():
    for path in sorted(glob.glob(os.path.join(_PH, "*.jsonl"))):
        base = os.path.basename(path)
        if base.endswith("_read.jsonl") or "tail_I" in base:
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
def test_no_recorded_good_answer_is_changed_by_the_wave_seven_guards():
    changed = []
    for q, a, v in _recorded():
        if not a.strip() or not v.startswith("GOOD"):
            continue
        out = aw.strip_store_addressing(a, q)
        if aw.mend_opening(out, a, q) != a:
            changed.append((q[:70], a[:100].replace("\n", " ")))
    assert not changed, "\n".join(f"{q} -> {a}" for q, a in changed)
