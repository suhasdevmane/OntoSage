# -*- coding: utf-8 -*-
"""BUG-1292: the spatial lane's last branch answered everything with all 354 spaces.

Tail N, asked live as an occupant through ``/v1`` on 2026-09-30:

    Can you tell me which areas are currently overcrowded?

    ## Explain how overcrowded areas are identified.
    a step of this request could not be carried out
    ---
    ## Spatial Information
    ## All spaces
    **354** space(s) found: | Floor | Zone | Label | Type | Area (m²) | ...

The ``Unknown agent: deliberate`` leak above that table is BUG-1261 and is already fixed.
The table is not. ``_answer_list`` is the final branch of ``_answer``, so anything that
reaches it and names no space type is answered with the building's entire space inventory.

MEASURED, eight questions through ``SpatialAgent.resolve()`` against the live building: all
eight returned the byte-identical 3,042-character *"## All spaces — **354** space(s) found"*
table, including *"which rooms are the quietest right now?"* and *"which areas are the
warmest?"*, which floor plans cannot answer at all.

This is BUG-377 one level up. That fix stopped a nearest-question whose target the plans do
not label from falling through to the same table — *"wrong in shape, not merely in content:
the user asked where ONE thing is and got a list of everything."* The default branch has the
same hole, and every question that matches no earlier branch goes through it.

BLAST RADIUS, measured before wiring the predicate in: of 7,151 real survey questions and
4,060 catalogue questions, 784 and 743 respectively name a space noun and no space type —
the widest set whose answer could change — and the predicate accepts **zero** of them as
inventory requests. Nobody in either corpus, nor in the 60-case regression probe, nor in the
demo script, asks for a list of every space; the branch that answered 1,527 questions with
one was answering a question nobody asked.
"""

import pytest

from orchestrator.agents.spatial_agent import SpatialAgent

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def agent():
    return SpatialAgent()


# ── the live failure, verbatim, and the two neighbours measured beside it ────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Can you tell me which areas are currently overcrowded?",
        "Explain how overcrowded areas are identified.",
        "which rooms are the quietest right now?",
        "which areas are the warmest?",
        "Are there any rooms currently overcrowded?",
        "are there any areas of this room hotter than others?",
    ],
)
def test_a_question_the_plans_cannot_evaluate_is_not_an_inventory_request(agent, question):
    assert agent._inventory_was_asked_for(question) is False


# ── what must keep working: the branch still exists for the question it is for ───────────


@pytest.mark.parametrize(
    "question",
    [
        "list all the spaces in the building",
        "show me all rooms",
        "what rooms are there?",
        "list the zones",
        "which areas are there",
        "Can you list all the rooms?",
    ],
)
def test_a_plain_inventory_request_still_gets_the_inventory(agent, question):
    assert agent._inventory_was_asked_for(question) is True


def test_an_empty_question_is_not_an_inventory_request(agent):
    assert agent._inventory_was_asked_for("") is False
    assert agent._inventory_was_asked_for("   ") is False


# ── the decline, and the property five consumers depend on ───────────────────────────────


def test_the_decline_opens_with_an_ALREADY_RECOGNISED_lead(agent):
    """Five consumers key on a decline's first sentence (BUG-897, BUG-1252, CAVEAT-1281).

    ``regression_answerability._DECLINE_MARKERS``, ``publication_gate.is_decline``,
    ``scripts/audit_decline_markers.py``, the grader, and ``_orchestrator._decline_leads``
    — the last a ``startswith`` that decides whether a declared-capacity statement REPLACES
    this text or is prepended to it. Reusing an EXISTING lead is why no marker list had to
    change, and therefore why the blast radius over the ~2,985 stored answers is zero by
    construction. A new wording here would be scored as an ANSWER, which is the direction
    that hides a regression.
    """
    text = agent._list_target_unknown("which areas are currently overcrowded?", [])
    assert text.lstrip().lower().startswith("i couldn't answer that")
    assert "i couldn't answer that from" in " ".join(text.lower().split())


def test_the_decline_names_no_building_and_carries_no_count(agent):
    """Contract 3: nothing here may be a building literal, and no figure may be invented."""
    text = agent._list_target_unknown("which areas are currently overcrowded?", [])
    assert "abacws" not in text.lower()
    assert "354" not in text


def test_the_decline_says_what_the_plans_do_hold(agent):
    """A refusal that names nothing usable is worse than one that names what is there."""
    text = agent._list_target_unknown("which areas are currently overcrowded?", [])
    assert "floor plans" in text.lower()
    assert "list the spaces" in text.lower()


# ── CAVEAT-1297: both declines read the WRONG ATTRIBUTE and named nothing ────────────────


class _Space:
    """The two fields these two declines read off ``shared.models.Space``."""

    def __init__(self, type_):
        self.type = type_


class _Manifest:
    def __init__(self, spaces):
        self.spaces = spaces


_MANIFESTS = [_Manifest([_Space("office"), _Space("meeting_room"), _Space("unknown")])]


@pytest.mark.parametrize("method", ["_list_target_unknown", "_nearest_target_unknown"])
def test_a_decline_names_the_kinds_of_space_the_plans_label(agent, method):
    """`Space.type`, not `space_type` — the latter silently returns the getattr default.

    `_nearest_target_unknown` has shipped since BUG-377 reading ``space_type``, so its
    "**I can find the nearest:** ..." sentence has never rendered on any building: the
    decline was honest and withheld the half that makes it useful. Verified live against
    bldg1's manifests after the fix — both declines now name classroom, kitchen, lab,
    lecture, meeting room, office, reception, server room, storage, toilet, utility, zone.
    """
    text = getattr(agent, method)("where is the nearest water refill station?", _MANIFESTS)
    assert "office" in text
    assert "meeting room" in text
    # `SpaceType`'s default for a space the plan never typed. Not a kind of place, and
    # offering it as one would be worse than naming nothing.
    assert "unknown" not in text.lower()
