# -*- coding: utf-8 -*-
"""BUG-940 — a co-reference rewrite may bind only a place the USER named.

Measured live 2026-09-29 on `/v1/chat/completions`, one conversation of eight turns, every
turn genuinely executed (33-51 s each; unique filler, because identical filler is served from
`resp_cache` in 0.0 s and never saves a turn — lessons #149):

    T1  "I am looking into air quality in room 5.01 specifically."   -> answered about 5.01
    T2-T7  six questions about floor temperatures
    T8  "And what is the humidity in there right now?"

    [coref] follow-up rewritten: 'And what is the humidity in there right now?'
            -> 'What is the current humidity in Telecommunications Room 1.34 on Floor 1?'

    -> "The latest reading from the Zone Air Humidity Sensor installed-node 1.34 is 49.03 %...
        across 60 readings... ranged from 48.7 % to 56.1 %, with an average of 51.4 %."

Room 1.34 appears in no message the user wrote. Room 5.01 HAS a humidity sensor of its own
(`bldg:Zone_Air_Humidity_Sensor_5.01`), so this is not an absence handled badly — the building
holds 287 humidity sensors and one was chosen.

WHY NOTHING ELSE CATCHES IT. The rewrite REPLACES the user's message for classification,
entity extraction, SPARQL and the referent existence gate itself, so a room that exists passes
every check. That is the laundering `rewrite_is_safe` exists to prevent — and it arrives
through the door that guard deliberately leaves open, because `rewrite_is_safe` returns True
whenever the user named no place, which is "the case the rewrite exists for". True, and also
the case where the rewrite's choice is completely unopposed.

The prompt asks the model to resolve the reference to "the concrete entity mentioned earlier",
and the six messages it can see are half ASSISTANT replies, which name dozens of rooms. So the
fix is not a better prompt: it is a rule about whose words count.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.context_switch import (
    rewrite_invents_a_place,
    rewrite_is_safe,
)

pytestmark = pytest.mark.unit


# The conversation that produced the defect, in the user's own words only.
USER_SAID = [
    "I am looking into air quality in room 5.01 specifically.",
    "What is the temperature on floor 1? (check 1790702957-6)",
    "And what is the humidity in there right now?",
]

THE_DEICTIC = "And what is the humidity in there right now?"
THE_FABRICATION = "What is the current humidity in Telecommunications Room 1.34 on Floor 1?"


# ── the live failure ─────────────────────────────────────────────────────────────────


def test_the_measured_failure_is_refused():
    assert rewrite_invents_a_place(THE_DEICTIC, THE_FABRICATION, USER_SAID) is True


def test_the_old_guard_let_it_through_which_is_why_this_exists():
    """Not a criticism of `rewrite_is_safe` — it is doing what it documents. This test pins
    that the two guards cover different cases, so neither is later deleted as redundant."""
    assert rewrite_is_safe(THE_DEICTIC, THE_FABRICATION) is True


# ── and it must not disable the feature ──────────────────────────────────────────────


def test_binding_to_the_room_the_user_named_is_allowed():
    assert (
        rewrite_invents_a_place(
            THE_DEICTIC, "What is the current humidity in room 5.01?", USER_SAID
        )
        is False
    )


def test_binding_to_a_floor_the_user_named_is_allowed():
    assert (
        rewrite_invents_a_place("and there?", "What is the temperature on floor 1?", USER_SAID)
        is False
    )


def test_a_rewrite_that_binds_no_place_is_untouched():
    """Most rewrites resolve a period or an action, not a place."""
    assert (
        rewrite_invents_a_place("and again?", "What is the temperature again?", USER_SAID) is False
    )


def test_a_place_the_user_named_in_this_very_message_is_not_invented():
    """`rewrite_is_safe` owns that case; this guard must stand aside rather than double-judge."""
    assert (
        rewrite_invents_a_place(
            "what about room 3.27?", "What is the humidity in room 3.27?", USER_SAID
        )
        is False
    )


def test_with_no_user_text_at_all_any_bound_place_is_invented():
    """The conservative direction: with nothing to check against, refuse rather than allow."""
    assert rewrite_invents_a_place("and there?", "What is the humidity in room 9.99?", []) is True


def test_a_second_place_in_one_message_is_still_the_users_own():
    """`place_of` returns ONE place per text, so a message naming two would hide the second.
    The token fallback is what stops the guard refusing a legitimate binding."""
    said = ["Compare the temperature on floor 3 and floor 4."]
    assert (
        rewrite_invents_a_place("and there?", "What is the temperature on floor 4?", said) is False
    )


# ── whose words count ────────────────────────────────────────────────────────────────


def test_only_user_messages_and_the_session_summary_are_offered_to_the_guard():
    """The assistant's replies are excluded ON PURPOSE: they are where room 1.34 came from.
    If a refactor ever passes the whole history here, the guard becomes a no-op and the
    defect returns silently."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
    assert '_user_texts = [m.content for m in msgs if getattr(m, "role", "") == "user"]' in src
    assert "rewrite_invents_a_place(latest, rewritten, _user_texts)" in src


def test_the_session_summary_counts_as_the_users_words():
    """It is built only from user questions (session_summary.py), which is what makes it
    admissible here — and it is the only record of a turn past the six-message window."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
    assert "_user_texts.append(session_recall)" in src


def test_a_refused_rewrite_returns_none_rather_than_a_repaired_one():
    """Returning the original message is the honest outcome: the pipeline then sees a question
    with an unresolved reference and can ask, which is what the user needed.

    Read from the parsed tree rather than from `block[:400]`. The window was the whole
    remainder of the function anyway, so it bought nothing and cost the assertion its
    stability: one extra line of logging above the return and it slices the `return None`
    off (lessons #151). `return None` is also a common enough statement that a window
    catching an unrelated one would have looked exactly like a pass.
    """
    import ast
    import textwrap

    from orchestrator.agents.dialogue_agent import DialogueAgent

    tree = ast.parse(textwrap.dedent(inspect.getsource(DialogueAgent.rewrite_to_standalone)))
    guards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "rewrite_invents_a_place" in ast.unparse(node.test)
    ]
    assert guards, "the invented-place guard is no longer branched on"
    for guard in guards:
        returns = [
            stmt
            for stmt in guard.body
            if isinstance(stmt, ast.Return)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is None
        ]
        assert returns, (
            "the guard fires but does not return None — a refused rewrite that falls "
            "through hands the pipeline a repaired question instead of an unresolved one"
        )


def test_the_refusal_is_logged_distinguishably_from_the_other_one():
    """Two guards, two reasons. A single shared message would make the live logs unreadable
    at exactly the moment someone is trying to tell which one fired."""
    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
    assert "it changed the referent the user named" in src
    assert "it bound a place the user never named" in src
