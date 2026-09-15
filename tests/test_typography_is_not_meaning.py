"""BUG-587: a rewrite that wrote "CO₂" and "room\u202f2.01" was routed to the Working Hours capability."""

import inspect

import pytest

from orchestrator.workflow import _orchestrator as mod

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "typed,plain",
    [
        ("Plot the CO\u2082 in room\u202f2.01 over the last 24 hours.", "Plot the CO2 in room 2.01 over the last 24 hours."),
        ("CO\u2082 in room\u00a05.01", "CO2 in room 5.01"),
        ("What is the CO2 level in room 5.01?", "What is the CO2 level in room 5.01?"),
    ],
)
def test_typographic_forms_fold_to_plain_ones(typed, plain):
    assert mod.normalise_query_text(typed) == plain


def test_the_dialogue_node_folds_the_question_and_the_rewrite():
    src = inspect.getsource(mod)
    assert src.count("normalise_query_text(") >= 3  # definition + question + rewrite
    assert "_standalone = normalise_query_text(_standalone)" in src
