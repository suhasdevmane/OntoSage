# -*- coding: utf-8 -*-
"""BUG-953: a MAX over readings is never "the maximum occupancy" of a room.

Four live asks, 2026-09-30, after BUG-897 made the declared figure appear:

* *"What is the maximum occupancy of room 2.15?"* — "Room 2.15 — Seminar Room has a design
  occupancy of **40 people**." … "The maximum occupancy recorded for this room is **30.00
  people**." The declared figure and a contradiction of it, four lines apart.
* the same question again — the 30 BOLDED as the key finding, which is the number a reader
  takes as the answer.
* *"What is the design occupancy of room 5.01?"* — the honest deterministic line alone. Good.
* the same question again — "The design occupancy for Room 5.01 is **30 people**", flat. 30 is
  the highest reading in a two-day window.

Whether the narrator denies the declared figure or invents one varied run to run, so this is
generation variance over an unconstrained claim, not arithmetic: ``max(values)`` is right every
time. The additive fix (state the declared figure as well) had reached its limit — it makes
both sentences present rather than removing the wrong one — so the WORDING is constrained at
source instead, which is the row's second candidate and the cheaper one.

Deliberately general. A rated power, a design flow and a setpoint are open to exactly the same
confusion, so the constraint is written about any extreme of any series rather than about
occupancy, and it stays true for a building that declares none of them.
"""

import inspect
from datetime import datetime, timedelta

import pytest

from orchestrator.agents.analytics_agent import AnalyticsAgent
from orchestrator.services.series_summary import OBSERVED_NOT_DECLARED, summarise_series

pytestmark = pytest.mark.unit

META = {"occ-2-15": {"label": "Room 2.15 — Seminar Room occupancy", "unit": "persons"}}


def _readings(peak=30.0, n=24):
    start = datetime(2026, 9, 28, 4, 0)
    rows = []
    for i in range(n):
        rows.append(
            {
                "uuid": "occ-2-15",
                "datetime": (start + timedelta(hours=i)).isoformat(),
                "value": peak if i == 10 else float(i % 12),
            }
        )
    return rows


def test_the_figures_say_they_are_readings_and_not_a_declared_limit():
    text, _ = summarise_series(_readings(), META, "Europe/London")
    assert "max 30" in text  # the figure itself is unchanged
    assert OBSERVED_NOT_DECLARED in text
    assert text.strip().endswith(OBSERVED_NOT_DECLARED)


def test_the_note_names_the_true_phrase_for_a_count_of_people():
    """ "the highest count observed" is the phrase the lane already uses in places."""
    assert "highest count observed" in OBSERVED_NOT_DECLARED


def test_the_note_forbids_the_exact_construction_that_was_produced():
    assert "declared capacity, limit, rating, setpoint or design figure" in OBSERVED_NOT_DECLARED
    assert "the maximum <quantity> of" in OBSERVED_NOT_DECLARED
    assert "do not restate, replace or contradict it" in OBSERVED_NOT_DECLARED


def test_the_note_names_no_building_and_no_single_quantity():
    """Design contract 3: this must read correctly for a building that measures none of this."""
    low = OBSERVED_NOT_DECLARED.lower()
    assert "occupancy" not in low
    assert "abacws" not in low and "bldg" not in low
    assert "room 2.15" not in low


def test_an_empty_series_gains_no_note():
    text, _ = summarise_series([], META, "Europe/London")
    assert text == ""


def test_the_note_carries_no_identifier_into_the_prompt():
    """An existing contract on this function: names, never identifiers."""
    text, _ = summarise_series(_readings(), META, "Europe/London")
    assert "occ-2-15" not in text and "uuid" not in text.lower()


def test_the_analytics_narration_is_told_what_an_extreme_is():
    # The rule is wrapped to the file's line length, so it is read as the model reads it:
    # one run of text. Asserting against the wrapped source would pin the wrap, not the rule.
    flat = " ".join(inspect.getsource(AnalyticsAgent._format_analysis).split())
    assert "AN EXTREME OF A SERIES IS AN OBSERVED VALUE, NEVER A DECLARED ONE" in flat
    assert 'Write "the highest count observed"' in flat
    assert 'never "the maximum occupancy of room X is' in flat
    assert "capacity, rating, limit, permitted maximum or design figure" in flat
    # The two sentences that were actually produced are quoted, so the rule cannot be read as
    # abstract advice (the measured-failure idiom this prompt already uses throughout).
    assert "The maximum occupancy recorded for this room is 30.00 people" in flat
    assert "The design occupancy for Room 5.01 is **30 people**" in flat


def test_the_rule_is_inside_the_narration_prompt_and_not_merely_in_a_comment():
    src = inspect.getsource(AnalyticsAgent._format_analysis)
    start = src.index('summary_prompt = f"""')
    end = src.index('Response:"""')
    assert start < src.index("AN EXTREME OF A SERIES") < end
    assert start < src.index("{declared}") < end


# ── the declared figure, carried into the narration that could contradict it ─────────────────


class _Bus:
    def __init__(self, payload):
        self.intermediate_results = {"design_occupancy": payload} if payload is not None else {}


def test_the_narration_is_told_the_figure_it_must_not_contradict():
    note = AnalyticsAgent._declared_figures_note(
        _Bus(
            {
                "space": "Room 2.15 — Seminar Room",
                "declarations": {"http://hbco#roomCapacity": 40},
                "conflicted": False,
            }
        )
    )
    assert "Room 2.15 — Seminar Room" in note and "roomCapacity = 40" in note
    assert "may restate, replace or contradict it" in note
    assert "highest value observed, never this" in note
    assert "MORE THAN ONE" not in note


def test_two_disagreeing_declarations_are_named_and_not_resolved_by_a_reading():
    note = AnalyticsAgent._declared_figures_note(
        _Bus(
            {
                "space": "Room 5.01 — Research Laboratory",
                "declarations": {"x#maxOccupancy": 25, "x#roomCapacity": 20},
                "conflicted": True,
            }
        )
    )
    assert "maxOccupancy = 25" in note and "roomCapacity = 20" in note
    assert "MORE THAN ONE" in note
    assert "do not offer a reading as the tie-break" in note


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "not a dict",
        {},
        {"space": "Room 1.04"},
        {"space": "", "declarations": {"x#roomCapacity": 20}},
        {"space": "Room 1.04", "declarations": {}},
        {"space": "Room 1.04", "declarations": "not a dict"},
    ],
)
def test_an_unexpected_bus_shape_costs_a_hint_and_never_the_answer(payload):
    """The payload is owned elsewhere and is being changed. This must degrade to silence."""
    assert AnalyticsAgent._declared_figures_note(_Bus(payload)) == ""


def test_no_state_at_all_is_survivable():
    assert AnalyticsAgent._declared_figures_note(None) == ""
    assert AnalyticsAgent._declared_figures_note(object()) == ""


def test_both_call_sites_pass_the_declared_figures():
    """One of the two narration paths is the per-floor shortcut. Half a fix is not a fix."""
    src = inspect.getsource(AnalyticsAgent.analyze)
    assert src.count("declared=self._declared_figures_note(state)") == 2
