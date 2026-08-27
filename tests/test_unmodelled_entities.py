# -*- coding: utf-8 -*-
""""Zero" and "not modelled" are different answers (CAVEAT-309, 2026-08-27).

*"How many desks are available in the building?"* answered **"0 desks
available"**. This model has no desk or workspace entity at all -- no class, no
instances -- so "0 available" reads as *every desk is taken*: a specific claim
about a specific building, made about something nobody ever recorded.

The rule carries no word list, because the distinction is not about desks:

* the ontology **defines the class** and holds none -> "none" is a real answer;
* the ontology **defines no such class** -> the concept was never modelled, and
  any count of it is invented.

It fails open everywhere it is unsure. A guard that edits answers on a failed
query is worse than the defect it corrects.
"""

import pytest

from orchestrator.services.unmodelled_entities import (
    _class_forms,
    correction_text,
    detect_zero_entity_claim,
    guard_answer,
)

pytestmark = pytest.mark.unit


async def _modelled(_q):
    return {"rows": [{"n": "1"}]}


async def _not_modelled(_q):
    return {"rows": [{"n": "0"}]}


async def _broken(_q):
    raise RuntimeError("graphdb unreachable")


# -- reading a zero-claim ----------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("There are 0 desks available in the building.", "desks"),
        ("0 desks are available.", "desks"),
        ("No hot desks are free on floor 3.", "hot desks"),
        ("Zero lockers are available.", "lockers"),
        ("There are 3 desks available.", None),
    ],
)
def test_zero_claims_are_read_and_others_are_not(text, expected):
    assert detect_zero_entity_claim(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "No data is available for 9am.",  # a windowing statement
        "No readings were found in that window.",  # an empty result set
        "The lab is at 22 degrees.",  # not a count at all
    ],
)
def test_an_empty_result_set_is_not_an_unmodelled_entity(text):
    assert detect_zero_entity_claim(text) is None


# -- and only rewriting when the ontology agrees -----------------------------
@pytest.mark.asyncio
async def test_a_zero_over_an_undefined_class_is_rewritten():
    text = "There are 0 desks available in the building."
    out, violation = await guard_answer(text, _not_modelled)
    assert out != text
    assert "does not include" in out and "desks" in out
    assert violation["entity"] == "desks"


@pytest.mark.asyncio
async def test_a_zero_over_a_DEFINED_class_is_left_alone():
    """A building with a defined bike-rack class and none of them genuinely has
    none. Rewriting that would replace a true answer with a hedge."""
    text = "There are 0 bicycle racks available in the building."
    out, violation = await guard_answer(text, _modelled)
    assert out == text and violation is None


@pytest.mark.asyncio
async def test_an_unverifiable_lookup_changes_nothing():
    text = "There are 0 desks available in the building."
    out, violation = await guard_answer(text, _broken)
    assert out == text and violation is None


@pytest.mark.asyncio
async def test_an_answer_with_no_zero_claim_is_never_touched():
    text = "Room 5.01 is at 21.4 degrees."
    assert await guard_answer(text, _not_modelled) == (text, None)


# -- the correction says what would fix it -----------------------------------
def test_the_correction_distinguishes_itself_from_none_and_says_what_to_do():
    out = correction_text("desks", "0 desks available")
    assert "not the same as there being none" in out
    assert "TTL" in out


# -- class-name forms --------------------------------------------------------
@pytest.mark.parametrize(
    "noun,expected",
    [
        ("desks", ("Desk", "Desks")),
        ("hot desks", ("Hot_Desk", "Hot_Desks")),
        ("bicycle racks", ("Bicycle_Rack", "Bicycle_Racks")),
        ("facilities", ("Facilities", "Facility")),
    ],
)
def test_singular_and_plural_class_names_are_both_tried(noun, expected):
    """A building may model the class as Desk or as Desks; missing one spelling
    would report a modelled thing as unmodelled."""
    assert _class_forms(noun) == expected


# -- and it runs on real answers ---------------------------------------------
def test_the_guard_is_called_in_the_response_node():
    """The recurring defect in this codebase is the capability with no invoker."""
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "_unmodelled_guard(final_response, _sx)" in src
