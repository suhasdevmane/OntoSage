# -*- coding: utf-8 -*-
"""BUG-879 — a named place may mean "group by that place", not "decline".

The aggregate lane vetoed any question naming a place, with a stated and correct reason: a
BUILDING-WIDE summary would then answer a different question. That reasoning is about the
SUMMARY, not about the question. Measured live 2026-09-23:

    "Compare the average CO2 in room 5.01 this week against last week."
    -> [aggregate] not claimed: measurand=co2 place=True per_sensor=False readings=True

Both windows refused, for a comparison whose place scopes them equally. That veto is what left
W1-04 and W2-03 PARTIAL.

THE DANGEROUS HALF, WHICH THESE TESTS EXIST FOR. Lifting the veto while still grouping as
"building" would key every figure "building mean" over one room's sensors — the exact shape of
BUG-883, where one sensor was presented as a floor's and one floor's meter as the building's,
each with every digit correct. So lifting the veto MUST move the grouping to the place, where
`_group_key` names the group after the room or floor and the figure cannot claim a scope it does
not have.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import aggregate_lane
from orchestrator.services.aggregate_lane import _FLOOR_NAMED_RE, _group_key

pytestmark = pytest.mark.unit


# ── the veto is still there for everyone who does not explicitly lift it ─────────────


def test_the_place_veto_is_still_in_the_gate():
    """A refactor that drops it must fail here rather than in front of a user."""
    src = inspect.getsource(aggregate_lane.try_answer)
    gate = src[src.index("summary_ok = bool(") : src.index("profile_ok")]
    assert "_place_named" in gate
    assert "allow_named_place" in gate, "the veto must be liftable only by an explicit flag"


def test_the_flag_defaults_to_off():
    """Every existing caller must behave exactly as before."""
    sig = inspect.signature(aggregate_lane.try_answer)
    assert sig.parameters["allow_named_place"].default is False


def test_the_flag_is_keyword_only_so_it_cannot_be_passed_by_accident():
    sig = inspect.signature(aggregate_lane.try_answer)
    assert sig.parameters["allow_named_place"].kind is inspect.Parameter.KEYWORD_ONLY


# ── and when it IS lifted, the label must follow the scope ───────────────────────────


def test_lifting_the_veto_also_moves_the_grouping():
    """The two must be inseparable: claim the place, group by the place.

    If these ever come apart, a room's mean is published as the building's.
    """
    src = inspect.getsource(aggregate_lane.try_answer)
    assert 'intent.group in ("building", "floor")' in src
    assert "intent.group != _grp" in src
    assert "_FLOOR_NAMED_RE" in src
    # the regrouping must be guarded by BOTH the flag and an actually-named place
    block = src[src.index("and intent.group != _grp") :]
    # Deliberately NOT windowed by character count: this assertion has now been broken twice by
    # the explanatory comment growing, which tells you nothing about the code. What matters is
    # that the regroup happens inside this guard and before anything else reads intent.group.
    body = []
    for line in block.splitlines():
        if body and line.startswith("    if "):
            break  # the next top-level statement — we are past the guard's body
        body.append(line)
    assert any("AggregateIntent(" in line for line in body)
    # `_grp` is computed just above the guard so the condition can compare against it.
    assert '_grp = "floor" if _FLOOR_NAMED_RE.search' in src


@pytest.mark.parametrize(
    "question,expected",
    [
        ("compare the average co2 on floor 2 this week against last week", True),
        ("energy on level 3 yesterday versus a week ago", True),
        ("compare the average co2 in room 5.01 this week against last week", False),
        ("noise level in the atrium this week vs last", False),
        ("the CO2 level is high, compare this week with last", False),
    ],
)
def test_a_floor_groups_by_floor_and_everything_else_by_room(question, expected):
    """ "level" is also the second half of "noise level" and "CO2 level", so it needs a number."""
    assert bool(_FLOOR_NAMED_RE.search(question)) is expected, question


def test_group_key_names_the_place_rather_than_the_building():
    """This is what makes the label honest, and it is existing behaviour we now depend on."""

    class _F:
        floor = "Floor2"
        room = "Room 5.01"
        label = "CO2 Level Sensor 5.01"

    assert _group_key(_F(), "room") == "Room 5.01"
    assert _group_key(_F(), "floor") == "Floor2"
    assert _group_key(_F(), "building") == "building"


def test_a_room_group_key_falls_back_to_the_sensor_label_not_to_the_building():
    """A space with no resolved room name must still not be keyed "building"."""

    class _F:
        floor = "Floor2"
        room = ""
        label = "CO2 Level Sensor 5.01"

    assert _group_key(_F(), "room") == "CO2 Level Sensor 5.01"


# ── the one caller that lifts it, and why only that one ──────────────────────────────


def test_the_comparison_lane_is_the_caller_that_lifts_the_veto():
    from orchestrator.services import comparison_lane

    src = inspect.getsource(comparison_lane.try_compare)
    assert "allow_named_place=True" in src
    assert "BUG-879" in src, "the reason must sit beside the flag, not only in a tracker"


def test_no_other_caller_lifts_it():
    """It is safe only where both windows are the same place. Nothing else knows that."""
    from pathlib import Path

    hits = []
    for p in Path("orchestrator").rglob("*.py"):
        if p.name == "aggregate_lane.py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "allow_named_place=True" in text:
            hits.append(p.name)
    assert hits == ["comparison_lane.py"], hits


# ── the half the first fix missed ────────────────────────────────────────────────────
#
# Lifting the veto made `summary_ok` True and changed nothing: `summary_ok` only feeds
# `wants_lane`'s sixth case, which fires when the question parses to no statistic in particular.
# A question that NAMES its statistic ("the average CO2 ...") parses fine and skips that case
# entirely. Measured 2026-09-29 with the veto already lifted: summary_ok=True, wants_lane=None.


def test_a_question_naming_its_statistic_does_not_reach_the_summary_case():
    """The premise of the second fix. If this ever stops being true, delete the second fix."""
    from orchestrator.services.aggregate_lane import parse_intent, wants_lane

    q = "Compare the average CO2 in room 5.01 this week against last week."
    assert (
        parse_intent(q) is not None
    ), "it parses, so wants_lane's `intent is None` case is skipped"
    assert wants_lane(q, 3, False, True, {"ppm"}, False, True, False) is None


def test_the_caller_flag_claims_a_parsed_intent_wants_lane_declined():
    src = inspect.getsource(aggregate_lane.try_answer)
    assert "if intent is None and allow_named_place and summary_ok:" in src


def test_that_claim_is_gated_on_summary_ok_not_on_the_flag_alone():
    """`summary_ok` carries every honesty test: names the measurand, asks about readings, wants
    no per-sensor detail, is not asking WHICH place. The flag alone would carry none of them."""
    src = inspect.getsource(aggregate_lane.try_answer)
    claim = src[src.index("if intent is None and allow_named_place") :]
    head = claim[: claim.index("\n")]
    assert "summary_ok" in head


def test_the_claim_happens_before_the_decline_and_before_the_regroup():
    """Order is load-bearing twice over: after the decline it is unreachable, and after the
    regroup the intent it produces would keep `group="building"` over one room's sensors."""
    src = inspect.getsource(aggregate_lane.try_answer)
    claim_at = src.index("if intent is None and allow_named_place")
    assert claim_at < src.index("[aggregate] not claimed")
    assert claim_at < src.index("and intent.group != _grp")


def test_no_flag_means_the_decline_is_untouched():
    """Every caller that does not lift the veto must still get None here."""
    src = inspect.getsource(aggregate_lane.try_answer)
    claim = src[src.index("if intent is None and allow_named_place") :]
    assert "allow_named_place and summary_ok" in claim[: claim.index("\n")]


# ── the label is the safety mechanism, so it must not be a bare digit ────────────────
#
# CAVEAT-938, measured live 2026-09-29 the moment BUG-879 started letting room questions
# through: "the temperature in room 5.01 this week compared with last week" labelled every
# figure "5 mean" / "5 peak" / "5 lowest". The figures were right and the basis line said
# "1 sensor, 1 floor", but "5" reads as FLOOR 5 — the scope confusion the regrouping exists to
# prevent, arriving through the label instead of through the grouping.


def test_a_bare_number_is_never_used_as_a_room_name():
    class _F:
        floor = "Floor5"
        room = "5"
        label = "CO2 Level Sensor 5.01"

    assert _group_key(_F(), "room") == "CO2 Level Sensor 5.01"


def test_a_real_room_name_is_still_preferred_over_the_sensor_label():
    class _F:
        floor = "Floor5"
        room = "HVAC Zone 5.01"
        label = "CO2 Level Sensor 5.01"

    assert _group_key(_F(), "room") == "HVAC Zone 5.01"


def test_a_room_name_containing_digits_is_not_mistaken_for_a_bare_one():
    """ "5.01" and "5A" name places; only an all-digit string is the failure mode."""
    for name in ("5.01", "5A", "Room 5", "2.30"):

        class _F:
            floor = "Floor5"
            room = name
            label = "some sensor"

        assert _group_key(_F(), "room") == name, name


def test_whitespace_does_not_smuggle_a_bare_number_through():
    class _F:
        floor = "Floor5"
        room = "  5  "
        label = "CO2 Level Sensor 5.01"

    assert _group_key(_F(), "room") == "CO2 Level Sensor 5.01"


def test_it_never_falls_back_to_the_building():
    """Whatever is missing, the answer must not claim a scope it does not have."""

    class _F:
        floor = "Floor5"
        room = ""
        label = ""

    assert _group_key(_F(), "room") == "this room"


# ── "building" was not the only wrong group ──────────────────────────────────────────
#
# The guard first fired only on `group == "building"`, and the live re-ask showed why that is
# not enough. "How does the temperature in room 5.01 this week compare with last week?" does
# not parse to an intent at all, so it is claimed by the bare-measurand SUMMARY path — which
# hardcodes `group="floor"`. The guard was skipped, `_group_key(f, "floor")` returned the FLOOR
# NUMBER, and every figure came out "5 mean" / "5 peak" / "5 lowest" over a group holding ONE
# sensor. A room's reading wearing a floor's name is BUG-883 exactly, not a cosmetic label.


def test_the_question_that_exposed_the_narrow_guard_does_not_parse_an_intent():
    """The premise. If this ever parses, the summary path is no longer how it is claimed and
    this widening can be re-examined."""
    from orchestrator.services.aggregate_lane import parse_intent

    assert (
        parse_intent("How does the temperature in room 5.01 this week compare with last week?")
        is None
    )


def test_the_summary_path_still_hardcodes_a_floor_group():
    """The other half of the premise: the claim arrives already grouped by floor, which is why
    a guard keyed on "building" could never see it."""
    from orchestrator.services.aggregate_lane import wants_lane

    i = wants_lane("how is the co2 in the building", 3, False, True, {"ppm"}, False, True, False)
    assert i is not None and i.group == "floor"


@pytest.mark.parametrize(
    "group,named,expected",
    [
        ("building", "room", True),  # the original case
        ("floor", "room", True),  # the case that shipped broken
        ("building", "floor", True),
        ("room", "room", False),  # already right — do not churn it
        ("floor", "floor", False),  # already right
        ("room", "floor", False),  # a room grouping is never widened to a floor
    ],
)
def test_the_regroup_fires_only_when_the_group_disagrees_with_the_named_place(
    group, named, expected
):
    """Written as a table because the first attempt used a CHAINED comparison
    (`x in (...) != (...)`), which Python reads as `(x in ...) and ((...) != ...)` — the right
    half is a tuple compared to a bool and so always true. It silently reduced to "any
    building-or-floor group" and regrouped floor->floor."""
    assert (group != named and group in ("building", "floor")) is expected


def test_the_condition_is_not_a_chained_comparison():
    """A regression guard for the shape, not just the outcome."""
    src = inspect.getsource(aggregate_lane.try_answer)
    assert 'in ("building", "floor") != (' not in src
