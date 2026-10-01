# -*- coding: utf-8 -*-
"""BUG-943 — when a deictic is resolved for the user, say which place it was taken to mean.

BUG-940 stopped a co-reference rewrite binding a place the user never named. It did not settle
WHICH of the places they DID name a bare "there" should mean. Measured live 2026-09-29, one
conversation of eight turns:

    T1  "I am looking into air quality in room 5.01 specifically."
    T2-T7  six questions about floor temperatures, the last about floor 1
    T8  "And what is the humidity in there right now?"
        -> rewritten to "What is the current humidity on floor 1?" and answered about floor 1

Floor 1 is a place they named twice, so this is not a fabrication. **Recency is a defensible
reading of "there"** — a human asked that same sequence would very likely answer about floor 1
too — which is exactly why the fix here is NOT to rank the candidates better. Guessing more
confidently is not an improvement.

Saying which one was assumed is. A wrong guess then costs the user one correction instead of a
figure they cannot see is wrong. `build_assumptions` already applies the same reasoning to a
forecast horizon, and states it in a sentence worth keeping: the number is the same; the claim
it makes must not be.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.context_switch import assumed_place_note

pytestmark = pytest.mark.unit


# ── when a note is owed ───────────────────────────────────────────────────────────────


def test_the_measured_case_is_disclosed():
    note = assumed_place_note(
        "And what is the humidity in there right now?",
        "What is the current humidity on floor 1?",
    )
    assert note == 'Taking "there" as floor 1.'


@pytest.mark.parametrize(
    "original,rewritten,expected",
    [
        ("and there?", "What is the temperature in room 5.01?", 'Taking "there" as room 5.01.'),
        ("what about that?", "What is the CO2 in zone 3.10?", 'Taking "that" as zone 3.10.'),
    ],
)
def test_it_names_the_place_the_way_the_question_wrote_it(original, rewritten, expected):
    """ "5.01" alone does not read as a place; "room 5.01" does. The head noun is taken from the
    rewritten text rather than invented, so a building that calls them something else gets the
    bare identifier — thin, but honest."""
    assert assumed_place_note(original, rewritten) == expected


def test_punctuation_does_not_swallow_the_note():
    """The first version matched " there " against " and there? " and found nothing, so the note
    vanished on the commonest phrasing there is. The same shape cost a register its plurals
    (BUG-948) and made "pm2.5" unrecognisable as "pm25" (BUG-950)."""
    assert assumed_place_note("and there?", "What is the temperature in room 5.01?") is not None
    assert assumed_place_note("and there!", "What is the temperature in room 5.01?") is not None


# ── when a note would be noise ────────────────────────────────────────────────────────


def test_no_note_when_the_user_named_the_place_themselves():
    """Nothing was assumed on their behalf, so there is nothing to disclose."""
    assert assumed_place_note("what about room 3.27?", "What is the humidity in room 3.27?") is None


def test_no_note_when_no_place_was_bound():
    """Most rewrites resolve a period or an action, not a place."""
    assert assumed_place_note("and again?", "What is the temperature again?") is None


def test_no_note_when_nothing_deictic_can_be_quoted():
    """A note that cannot say which word it resolved reads as a non-sequitur."""
    assert assumed_place_note("how about floor 2", "What is the temperature on floor 2?") is None


# ── how it is placed ──────────────────────────────────────────────────────────────────


def test_it_is_appended_not_prepended():
    """A footnote about how the question was read must not take the lead sentence, which belongs
    to the answer. This is the opposite placement from BUG-897's declared-capacity statement, and
    the difference is deliberate: that one IS the answer, this one is a caveat on it."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    assert 'final_response = f"{final_response}\\n\\n_{_note}_"' in src


def test_it_is_idempotent():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    assert "_note not in final_response" in src


def test_it_reads_the_rewrite_the_pipeline_already_recorded():
    """`coref_rewrite` is put on the bus by `_dialogue_node`; nothing is recomputed here."""
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    assert 'state.intermediate_results.get("coref_rewrite")' in src


def test_it_never_costs_an_answer():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    src = inspect.getsource(WorkflowOrchestrator._response_node)
    block = src[src.index("BUG-943") :]
    assert "except Exception" in block


def test_the_reason_it_is_disclosure_and_not_ranking_is_recorded():
    """A later session will be tempted to "fix it properly" by ranking the candidates. The reason
    that is not an improvement has to be findable at the code, not only in a tracker."""
    src = inspect.getsource(assumed_place_note)
    assert "Recency is a defensible reading" in src or "recency" in src.lower()
    assert "BUG-943" in src
