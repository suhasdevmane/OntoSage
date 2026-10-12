# -*- coding: utf-8 -*-
"""CAVEAT-1619: "what about room 2.53?" asks the previous question again about another place.

The model's rewrite kept the quantity and dropped the judgement ("Is it too humid in room 2.52?"
then "what about room 2.53?" gave values and no verdict). The resolver swaps only the place.
"""

from __future__ import annotations

import pytest

from orchestrator.services.context_switch import resolve_place_swap

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "earlier, latest, expected",
    [
        (
            ["Is it too humid in room 2.52?"],
            "what about room 2.53?",
            "Is it too humid in room 2.53?",
        ),
        (
            ["How much electricity did floor 3 use yesterday?"],
            "and floor 4?",
            "How much electricity did floor 4 use yesterday?",
        ),
        (
            ["What's the temperature in office 4.07?"],
            "how about office 4.08?",
            "What's the temperature in office 4.08?",
        ),
        (
            ["Is it too humid in room 2.52?", "what about room 2.53?"],
            "and room 2.54?",
            "Is it too humid in room 2.54?",
        ),
    ],
)
def test_only_the_place_changes(earlier, latest, expected):
    assert resolve_place_swap(latest, earlier) == expected


@pytest.mark.parametrize(
    "earlier, latest",
    [
        (["Compare room 2.13 and room 3.15"], "what about room 4.11?"),  # two places before
        (["Is it too humid in room 2.52?"], "and the CO2?"),  # not a place
        (["Is it too humid in room 2.52?"], "what about floor 3?"),  # another kind of place
        (["Is it too humid in room 2.52?"], "what about tomorrow?"),
        (["What's the temperature in office 4.07?", "and the CO2?"], "what about room 2.53?"),
        ([], "what about room 2.53?"),
    ],
)
def test_anything_else_is_left_to_the_rewrite(earlier, latest):
    assert resolve_place_swap(latest, earlier) is None


def test_the_resolver_runs_in_the_deterministic_loop():
    import inspect

    from orchestrator.agents import dialogue_agent as da

    src = inspect.getsource(da.DialogueAgent.rewrite_to_standalone)
    assert "(resolve_place_swap, _earlier_user)" in src
