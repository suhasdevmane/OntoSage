# -*- coding: utf-8 -*-
"""The withheld-figures message names none of the verifier's own vocabulary (2D-16 wave 2).

Wave-1 held-out read, "What is the current load on the system?": "The grounding check did not pass
(grounded=False and confidence=0.20) ... claimed but the data did not support: time_series_data.
... Attempted via the sql path." The decision to withhold is right; the sentence was written for a
developer. The three promises the gate's own tests pin are kept: WITHHELD, not WRONG, and what to
ask instead.
"""

from __future__ import annotations

import re

import pytest

from orchestrator.services import withheld_wording as ww

pytestmark = pytest.mark.unit

INTERNAL = (
    "grounded",
    "confidence",
    "grounding check",
    "time_series_data",
    "ontology_bindings",
    "=False",
    "0.20",
    "path.",
    "_result",
)


def test_none_of_the_verifiers_vocabulary_reaches_the_reader():
    text = ww.withheld_text(["time_series_data", "ontology_bindings"])
    for term in INTERNAL:
        assert term not in text, f"{term!r} reached a reader:\n{text}"
    assert not re.search(r"[a-z]+_[a-z]+", text), "a snake_case identifier reached a reader"


def test_the_three_promises_the_gate_pins_are_kept():
    low = ww.withheld_text(["co2 sensor"]).lower()
    assert "withheld" in low
    assert "not a statement that the figures are wrong" in low
    assert "narrower scope" in low


def test_it_says_plainly_which_source_the_figures_could_not_be_checked_against():
    """Wave-2 live read: 'What I could not back up: the readings behind them' read oddly."""
    text = ww.withheld_text(["time_series_data"])
    assert "I could not check them against the building's stored readings" in text
    assert "What I could not back up" not in text
    assert "the readings behind them" not in text
    assert "figures this answer had worked out" in text


def test_an_unknown_identifier_is_dropped_not_shown():
    assert ww.plain_missing(["some_new_internal_key", "co2 sensor", "sql=0"]) == ["co2 sensor"]


def test_a_second_source_is_named_in_its_own_sentence():
    text = ww.withheld_text(["time_series_data", "ontology_bindings"])
    assert "against the building's stored readings" in text
    assert "against the building's own records either." in text


def test_repeats_collapse_and_the_list_is_short():
    assert ww.plain_missing(["time_series_data", "sql_result"]) == [
        "the building's stored readings"
    ]
    assert len(ww.plain_missing([f"thing {i}" for i in range(9)])) == 3


def test_nothing_missing_falls_back_to_the_general_phrase():
    text = ww.withheld_text([])
    assert "against this building's data" in text and "either." not in text


def test_it_offers_a_concrete_next_question_and_states_no_figure():
    text = ww.withheld_text(["time_series_data"])
    assert "latest reading of one quantity in one named room" in text
    assert not re.search(r"\d", text)
