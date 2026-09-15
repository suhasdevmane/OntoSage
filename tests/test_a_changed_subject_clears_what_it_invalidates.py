# -*- coding: utf-8 -*-
"""V12-11 — shared labels and context switches (review A13/A14).

    A13  "An ambiguous label is resolved from authorised context or clarified, never
          silently cross-selected across buildings."
    A14  "Incompatible inherited state is cleared on a context switch, and the co-reference
          rewrite cannot carry a stale referent."

THE TWO PATHS THAT CARRIED STATE ACROSS A TURN, AND WHAT NEITHER CHECKED
------------------------------------------------------------------------
`main.py` injected `forecast_result` and `analytics_result` from the previous turn with an
unconditional `state.intermediate_results.update(carry_forward)`. Ask about room 5.01, then
"what about room 3.27? plot it", and the plot is built from 5.01's analytics under a
question naming 3.27 — every figure real, attributed to the wrong room.

`rewrite_to_standalone` accepted any LLM rewrite that was non-empty, under 500 characters
and not identical to the input. Nothing checked it was about the same place the user had
just named. The rewrite then becomes the query EVERY downstream stage sees, the referent
existence gate included — so a swapped room is not caught later, it is laundered: 5.01
exists, so the gate passes.

BUG-118 was one instance of this class ("floor 2" matched every floor whose name contained
the digit). The class itself had no test until this file.

WHAT THESE TESTS GUARD HARDEST
------------------------------
That the rule stays QUIET. "Now plot that" is why carry-forward exists, and a guard that
cleared state on an ordinary follow-up would break the feature to fix a bug it does not
have. The negative cases outnumber the positive ones.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.context_switch import (  # noqa: E402
    PLACE_BOUND_KEYS,
    place_of,
    prune_inherited,
    rewrite_is_safe,
    switched,
)

FIRST = "what is the CO2 in room 5.01"
SWITCH = "what about room 3.27?"
FOLLOW_UP = "now plot that"

INHERITED = {
    "analytics_result": {"room": "5.01", "mean": 812.4},
    "forecast_result": {"room": "5.01", "next_hour": 830.0},
    "user_preferences": {"units": "metric"},
}


# ── A14, first half: the inherited state ─────────────────────────────────────


def test_a_changed_room_drops_the_results_that_were_about_the_old_one():
    kept, dropped = prune_inherited(INHERITED, FIRST, SWITCH)
    assert set(dropped) == {"analytics_result", "forecast_result"}
    assert "analytics_result" not in kept


def test_state_that_is_not_about_a_place_survives_the_switch():
    """A preference is not a measurement. Clearing it would make the switch guard a worse
    bug than the one it fixes."""
    kept, _ = prune_inherited(INHERITED, FIRST, SWITCH)
    assert kept["user_preferences"] == {"units": "metric"}


def test_an_ordinary_follow_up_keeps_everything():
    """"Now plot that" is the case carry-forward EXISTS for. It names no place, so the
    subject has not changed — it has declined to restate itself."""
    kept, dropped = prune_inherited(INHERITED, FIRST, FOLLOW_UP)
    assert dropped == []
    assert kept == INHERITED


@pytest.mark.parametrize(
    "previous, latest",
    [
        ("what is the CO2 in room 5.01", "what is the temperature in room 5.01"),
        ("what is the CO2 in room 5.01", "and the humidity?"),
        ("show me floor 3", "show me floor 3 again"),
        ("what is the CO2 in room 5.01", "why is it high?"),
        ("how busy is the building", "what about now"),
    ],
)
def test_no_switch_is_detected_when_the_subject_did_not_change(previous, latest):
    assert switched(previous, latest) is None
    kept, dropped = prune_inherited(INHERITED, previous, latest)
    assert dropped == [] and kept == INHERITED


@pytest.mark.parametrize(
    "previous, latest",
    [
        ("what is the CO2 in room 5.01", "what about room 3.27?"),
        ("show me floor 3", "and floor 5?"),
        ("what is the CO2 in room 5.01", "now do room 2.14"),
    ],
)
def test_a_switch_is_detected_when_the_place_really_changed(previous, latest):
    change = switched(previous, latest)
    assert change is not None
    assert change.previous != change.latest
    assert "changed from" in change.describe()


def test_an_empty_inheritance_is_survivable():
    assert prune_inherited({}, FIRST, SWITCH) == ({}, [])
    assert prune_inherited(None, FIRST, SWITCH) == ({}, [])


def test_every_place_bound_key_is_a_real_bus_key():
    """A guard listing keys nothing writes protects nothing. These names are checked
    against the shared-state contract in CLAUDE.md and the code that writes them."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "orchestrator/workflow/_orchestrator.py"
    ).read_text(encoding="utf-8")
    for key in PLACE_BOUND_KEYS:
        assert f'"{key}"' in src, f"{key} is in the drop list but nothing writes it"


# ── A14, second half: the co-reference rewrite ───────────────────────────────


def test_a_rewrite_that_swaps_the_room_the_user_named_is_rejected():
    """The failure this exists for. The rewrite replaces the user's words everywhere
    downstream, so a swapped room passes the existence gate — 5.01 exists."""
    assert rewrite_is_safe(SWITCH, "what is the CO2 in room 5.01?") is False


def test_a_rewrite_that_keeps_the_room_and_adds_context_is_accepted():
    assert rewrite_is_safe(SWITCH, "what is the CO2 in room 3.27 on floor 3?") is True


def test_a_rewrite_that_loses_the_room_the_user_named_is_rejected():
    """A rewrite's job is to make an under-specified question self-contained. Dropping a
    referent the user typed makes it LESS specific, which cannot be an improvement."""
    assert rewrite_is_safe(SWITCH, "what is the CO2 level?") is False


def test_a_follow_up_naming_no_place_is_always_safe_to_rewrite():
    """This is the whole point of the feature; refusing here would disable it."""
    for rewritten in (
        "plot the CO2 in room 5.01",
        "plot the CO2 on floor 3",
        "plot it",
    ):
        assert rewrite_is_safe(FOLLOW_UP, rewritten) is True


def test_the_rewrite_guard_is_actually_called():
    """A guard nothing calls is the V6-T10 failure. This one is only useful at the moment
    the rewrite is about to replace the user's message."""
    import inspect

    from orchestrator.agents.dialogue_agent import DialogueAgent

    src = inspect.getsource(DialogueAgent.rewrite_to_standalone)
    assert "rewrite_is_safe" in src
    assert src.index("rewrite_is_safe") < src.rindex("return rewritten")


def test_the_carry_forward_prune_is_actually_called():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "orchestrator/main.py").read_text(
        encoding="utf-8"
    )
    assert "prune_inherited" in src
    assert src.index("prune_inherited") < src.index(
        "state.intermediate_results.update(carry_forward)"
    ), "the prune runs after the state was already updated"


# ── A13: never silently cross-selected across buildings ──────────────────────


def test_every_existence_query_is_scoped_to_the_active_namespace():
    """A13's core. One building at a time is a design contract, and the gate enforces it
    per QUERY rather than by assuming the process only ever sees one graph: every SPARQL in
    the resolver filters subjects to the namespace it was handed.

    Checked structurally rather than by asserting a result, because a query that forgot the
    filter would still return the right answer on a single-building deployment — and be
    wrong the first time two graphs share a store.
    """
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "orchestrator/services/referent_resolver.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    checked = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.get_source_segment(src, fn) or ""
        if "SELECT" not in body:
            continue
        checked += 1
        assert "STRSTARTS(STR(?s)" in body and "namespace" in body, (
            f"{fn.name} queries the graph without scoping to the active namespace"
        )
    assert checked >= 4, "the scoping check found almost no queries — it is not looking"


def test_a_named_other_building_is_a_referent_that_must_be_validated():
    """"air quality in Building 47" names a site this instance is not connected to. It must
    be treated as a referent and checked, not answered from the connected building."""
    from orchestrator.services.referent_resolver import KIND_LOCATION, detect_typed_referent

    typed = detect_typed_referent("what is the air quality in Building 47")
    assert typed is not None
    assert typed.kind == KIND_LOCATION
    assert "47" in typed.token


@pytest.mark.parametrize("phrase", ["this building", "the building", "our building"])
def test_the_connected_building_is_not_mistaken_for_another_one(phrase):
    """Requiring an identifier is what keeps the ordinary question working."""
    from orchestrator.services.referent_resolver import KIND_LOCATION, detect_typed_referent

    typed = detect_typed_referent(f"how many sensors are in {phrase}")
    assert typed is None or typed.kind != KIND_LOCATION


def test_a_switch_between_two_buildings_is_a_switch():
    """The cross-building case of A14: naming a different site invalidates everything
    inherited about the first."""
    change = switched("air quality in Building 47", "air quality in Building 12")
    assert change is not None


# ── the detector itself ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected_prefix",
    [
        ("what is the CO2 in room 5.01", "loc:"),
        ("show me floor 3", "floor:"),
        ("air quality in Building 47", "location:"),
    ],
)
def test_place_of_reads_the_same_referents_the_existence_gate_reads(text, expected_prefix):
    """Reusing the gate's own detectors, in the gate's own order, so the switch guard and
    the existence check cannot disagree about what a question's subject is."""
    got = place_of(text)
    assert got is not None and got.startswith(expected_prefix)


@pytest.mark.parametrize(
    "text", ["now plot that", "why is it high?", "and the humidity?", "", "   "]
)
def test_a_question_naming_no_place_has_no_place(text):
    assert place_of(text) is None
