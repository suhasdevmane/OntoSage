"""A register's lay terms must not claim a live-conditions question (BUG-623).

Teaching the workspace register the words "focused work" made it answer "which space has the
best conditions for focused work this afternoon?" — a question about CO2, noise and temperature
RIGHT NOW, which the deliberation lane answers with a scored best match. The register knows what
a space is LIKE; it does not know what it is like this afternoon. Two probe cases went from pass
to fail on that one phrase, which is the only reason it was caught.

A register term earns its place by naming the KIND of thing recorded, not a mood or an activity
that a live reading could equally describe.
"""

import pytest

from orchestrator.services.record_registry import RecordClass, held_record_class

pytestmark = pytest.mark.unit

# The phrases the workspace register declares, read from the shared schema rather than copied,
# so this test fails when someone adds a term rather than agreeing with a stale list.
from pathlib import Path
import re


def _workspace_lay_terms():
    text = Path("ontology/ontosage_schema.ttl").read_text(encoding="utf-8")
    start = text.index("ontosage:WorkspaceProfile ontosage:layTerms")
    statement = text[start : text.index(" .\n", start)]
    return [t.lower() for t in re.findall(r'"([^"]+)"', statement)]


def _workspace_class():
    return RecordClass(
        local_name="WorkspaceProfile",
        label="Workspace profile",
        instances=28,
        terms=tuple(_workspace_lay_terms()),
    )


# These are the deliberation lane's own probe cases, verbatim.
_LIVE_CONDITION_QUESTIONS = [
    "Which space has the best conditions for focused work this afternoon?",
    "Which space on Floor 3 has the best conditions for focused work right now?",
]


@pytest.mark.parametrize("question", _LIVE_CONDITION_QUESTIONS)
def test_a_live_conditions_question_is_not_claimed_by_the_register(question):
    held = held_record_class(question, [_workspace_class()])
    assert held is None, (
        f"the workspace register claimed {question!r}; a scored best match from live readings "
        f"is the answer to that, not a list of what spaces are like"
    )


def test_the_register_still_answers_the_question_it_is_for():
    """The guard above must not be satisfied by the register claiming nothing at all."""
    held = held_record_class(
        "Which spaces are suitable for quiet focused work for a group of four?",
        [_workspace_class()],
    )
    assert held is not None
    assert held.local_name == "WorkspaceProfile"


@pytest.mark.parametrize(
    "term",
    ["focused work", "focussed work", "focus work", "deep work", "quiet focused work"],
)
def test_the_terms_that_stole_the_lane_stay_out(term):
    """Named individually: each one describes a WAY OF WORKING, which a live reading describes
    as well as a record does. Re-adding any of them fails the two deliberation probe cases."""
    assert term not in _workspace_lay_terms()
