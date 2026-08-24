# -*- coding: utf-8 -*-
"""Omitted-criteria reporting (V6-T39).

Rule R-9: *"[criterion] was omitted because [missing / stale / restricted] source"*.

The failure this prevents is not a missing courtesy. Asked for the quietest, warmest room with
a free socket, a system that silently drops "quietest" has answered a different question and
looks complete doing it -- the user sees a confident ranking with no way to tell that a third
of their request was discarded.

Two things are asserted beyond the obvious:

* **the reason is specific**, because *restricted* and *missing* look identical to a user and
  lead to opposite actions -- one has a governance route, the other does not;
* **the notice survives the causal guard**, which matters because the template's own wording
  contains "because". T33 and T39 were built in the same session and would otherwise have
  collided in production rather than here.
"""

import pytest

from orchestrator.services.evidence.causal_guard import qualify
from orchestrator.services.evidence.omissions import (
    CriterionFacts,
    classify,
    collect,
    facts_from_ranking,
    omission_for,
    render,
    summarise,
)
from shared.models import CausalSupport, OmissionReason

pytestmark = pytest.mark.unit


# -- classifying the gap -----------------------------------------------------


def test_a_usable_criterion_is_not_an_omission():
    assert classify(CriterionFacts("warm", "temperature")) is None
    assert omission_for(CriterionFacts("warm", "temperature")) is None


def test_an_uninstrumented_modality_is_reported_as_such():
    """The whole truth, and the only real remedy."""
    facts = CriterionFacts("quiet", "noise", instrumented=False)
    assert classify(facts) is OmissionReason.NOT_INSTRUMENTED


def test_an_unresolved_term_is_treated_as_uninstrumented():
    """A criterion that resolved to no modality cannot have been scored."""
    assert classify(CriterionFacts("cosy", "")) is OmissionReason.NOT_INSTRUMENTED


def test_a_permission_failure_is_never_reported_as_missing_data():
    """The distinction the enum exists for.

    Telling someone the data does not exist, when they are simply not cleared to see it, is
    false AND a dead end: it hides the governance route that would get them the answer.
    """
    facts = CriterionFacts("who used it", "occupancy_identity", permitted=False, has_readings=False)
    assert classify(facts) is OmissionReason.RESTRICTED


def test_no_readings_is_missing():
    assert classify(CriterionFacts("warm", "temperature", has_readings=False)) is (
        OmissionReason.MISSING
    )


def test_readings_that_are_too_old_are_stale_not_missing():
    """Different remedy, different conversation: the sensor exists but stopped reporting."""
    assert classify(CriterionFacts("fresh air", "co2", is_stale=True)) is OmissionReason.STALE


def test_proxy_only_coverage_is_an_omission_not_a_silent_substitution():
    """Master 8: a corridor value is not a room value, even when it is current."""
    facts = CriterionFacts("bright", "illuminance", proxy_only=True)
    assert classify(facts) is OmissionReason.INADEQUATE_COVERAGE


def test_an_uninstrumented_modality_outranks_a_permission_flag():
    """Reporting "restricted" here sends the user to an owner with nothing to release."""
    facts = CriterionFacts("quiet", "noise", instrumented=False, permitted=False)
    assert classify(facts) is OmissionReason.NOT_INSTRUMENTED


# -- rendering ---------------------------------------------------------------


def test_the_template_shape_is_the_catalogues():
    text = render(collect([CriterionFacts("quietest", "noise", has_readings=False)]))
    assert "**quietest** was omitted because of a missing source" in text


def test_the_user_s_own_words_are_used_not_the_modality():
    """ "quietest" is what they asked for; "noise" is our internal name for it."""
    text = render(collect([CriterionFacts("quietest", "noise", has_readings=False)]))
    assert "quietest" in text
    assert "noise" not in text


def test_every_omission_carries_a_remedy():
    """A stated gap with no route out reads as an excuse."""
    for facts in (
        CriterionFacts("a", "noise", instrumented=False),
        CriterionFacts("b", "temperature", has_readings=False),
        CriterionFacts("c", "co2", is_stale=True),
        CriterionFacts("d", "x", permitted=False),
        CriterionFacts("e", "illuminance", proxy_only=True),
    ):
        omission = omission_for(facts)
        assert omission is not None and omission.detail.strip()


def test_caller_detail_overrides_the_generic_remedy():
    facts = CriterionFacts("warm", "temperature", has_readings=False, detail="Sensor removed.")
    assert omission_for(facts).detail == "Sensor removed."


def test_nothing_omitted_renders_nothing():
    """A reassurance printed on every answer is noise, and noise hides the line that matters."""
    assert render(collect([CriterionFacts("warm", "temperature")])) == ""
    assert summarise([]) == ""


def test_request_order_is_preserved():
    """The user's own sequence is the one they can check their question against."""
    facts = [
        CriterionFacts("quiet", "noise", instrumented=False),
        CriterionFacts("warm", "temperature", has_readings=False),
    ]
    got = [o.criterion for o in collect(facts)]
    assert got == ["quiet", "warm"]


def test_the_singular_heading_differs_from_the_plural():
    one = render(collect([CriterionFacts("quiet", "noise", instrumented=False)]))
    two = render(
        collect(
            [
                CriterionFacts("quiet", "noise", instrumented=False),
                CriterionFacts("warm", "temperature", has_readings=False),
            ]
        )
    )
    assert "One requested criterion" in one
    assert "Not included in this answer" in two


# -- reading what a ranking lane already tracks ------------------------------


def test_a_criterion_that_was_scored_is_not_reported():
    facts = facts_from_ranking(
        requested=[{"phrase": "warmest", "modality": "temperature"}],
        scored_modalities=["temperature"],
    )
    assert collect(facts) == []


def test_a_requested_criterion_that_was_not_scored_is_reported():
    facts = facts_from_ranking(
        requested=[
            {"phrase": "warmest", "modality": "temperature"},
            {"phrase": "quietest", "modality": "noise"},
        ],
        scored_modalities=["temperature"],
        declared_modalities=["temperature", "noise"],
    )
    omissions = collect(facts)
    assert [o.criterion for o in omissions] == ["quietest"]
    assert omissions[0].reason is OmissionReason.MISSING


def test_an_undeclared_modality_reads_as_not_instrumented():
    facts = facts_from_ranking(
        requested=[{"phrase": "has a free socket", "modality": "socket_power"}],
        scored_modalities=[],
        declared_modalities=["temperature", "co2"],
    )
    assert collect(facts)[0].reason is OmissionReason.NOT_INSTRUMENTED


def test_an_unstated_modality_list_does_not_condemn_every_criterion():
    """The dangerous default.

    Treating "no modality list supplied" as "nothing is instrumented" would report every
    criterion as uninstrumented on any caller that has not wired the list yet -- a confident,
    wrong claim about the BUILDING made on the basis of a missing argument.
    """
    facts = facts_from_ranking(
        requested=[{"phrase": "quietest", "modality": "noise"}],
        scored_modalities=[],
        declared_modalities=[],  # not stated
    )
    assert collect(facts)[0].reason is OmissionReason.MISSING


def test_a_scored_but_proxy_only_criterion_is_still_reported():
    facts = facts_from_ranking(
        requested=[{"phrase": "quietest", "modality": "noise"}],
        scored_modalities=["noise"],
        declared_modalities=["noise"],
        proxy_modalities=["noise"],
    )
    assert collect(facts)[0].reason is OmissionReason.INADEQUATE_COVERAGE


def test_a_restricted_modality_is_reported_as_restricted():
    facts = facts_from_ranking(
        requested=[{"phrase": "who was in there", "modality": "occupancy_identity"}],
        scored_modalities=[],
        declared_modalities=["occupancy_identity"],
        restricted_modalities=["occupancy_identity"],
    )
    assert collect(facts)[0].reason is OmissionReason.RESTRICTED


# -- the two guards must not collide -----------------------------------------


def test_the_omission_notice_survives_the_causal_guard():
    """The template says "because", which makes every line a causal sentence syntactically.

    T33 rewrites unlicensed causal claims. Without the meta-cause exclusion it would rewrite
    these -- turning the system's clearest statement about its own limits into a paragraph
    about two things co-occurring. Asserted here rather than discovered in production.
    """
    text = render(
        collect(
            [
                CriterionFacts("quietest", "noise", instrumented=False),
                CriterionFacts("warmest", "temperature", has_readings=False),
                CriterionFacts("who used it", "occupancy_identity", permitted=False),
                CriterionFacts("fresh air", "co2", is_stale=True),
                CriterionFacts("bright", "illuminance", proxy_only=True),
            ]
        )
    )
    assert qualify(text, CausalSupport.NONE) == text
    assert qualify(text, CausalSupport.CORRELATIONAL) == text


# -- building agnosticism ----------------------------------------------------


def test_the_module_carries_no_building_literal():
    from pathlib import Path

    from scripts.check_building_literals import _prose_lines

    path = (
        Path(__file__).resolve().parent.parent
        / "orchestrator"
        / "services"
        / "evidence"
        / "omissions.py"
    )
    src = path.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff"):
        assert literal not in code
