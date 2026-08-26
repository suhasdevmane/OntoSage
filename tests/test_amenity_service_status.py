# -*- coding: utf-8 -*-
"""An out-of-service amenity must be excluded, not caveated (V6-T45, 2026-08-26).

The OCBV schema declared `ontosage:amenityStatus` and said plainly why it matters:

    An amenity whose status is out_of_service must be EXCLUDED from recommendations
    rather than listed with a caveat: somebody who walks to a broken fountain has been
    given a wrong answer, however well hedged.

Nothing read the property. An audit of all 213 declared `ontosage:` terms against the
codebase found that every term in the module — amenityStatus, PotabilityStatement,
potabilityValue, potabilityAuthority, potabilityIssuedOn, appliesToOutlet — had zero
readers, and the word "potability" appeared nowhere in the code. The task was marked done.
"""

import pytest

from orchestrator.services.capability_graph_resolver import (
    CapabilityGraphResolver,
    _is_out_of_service,
)

pytestmark = pytest.mark.unit


def _rows(*amenities):
    """SPARQL bindings for the resolver's amenity query."""
    return {"results": {"bindings": [{k: {"value": v} for k, v in a.items()} for a in amenities]}}


def _resolver(*amenities):
    async def _exec(_q):
        return _rows(*amenities)

    return CapabilityGraphResolver(sparql_exec=_exec)


_WORKING = {
    "a": "urn:f1",
    "label": "Drinking fountain, floor 1",
    "lay": "water fountain,drinking water",
}
_BROKEN = {
    "a": "urn:f2",
    "label": "Drinking fountain, floor 2",
    "lay": "water fountain,drinking water",
    "svc": "out_of_service",
}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("out_of_service", True),
        ("out of service", True),
        ("out-of-service", True),
        ("broken", True),
        ("closed", True),
        ("operational", False),
        ("", False),
        (None, False),
    ],
)
def test_out_of_service_detection(value, expected):
    """An empty status means 'nobody published one', not 'broken' — defaulting the other
    way would empty every answer on the many buildings that publish no status at all."""
    assert _is_out_of_service(value) is expected


@pytest.mark.asyncio
async def test_a_broken_amenity_is_not_offered():
    facts = await _resolver(_WORKING, _BROKEN).resolve("where is the water fountain?")
    labels = [f.label for f in facts]
    assert "Drinking fountain, floor 1" in labels
    assert "Drinking fountain, floor 2" not in labels


@pytest.mark.asyncio
async def test_when_everything_matched_is_broken_the_answer_says_so():
    """ "No drinking fountains here" sends someone away; "the ones here are not working"
    tells them what is wrong. The second is both truer and more useful."""
    facts = await _resolver(_BROKEN).resolve("where is the water fountain?")
    assert facts, "an all-broken match must not look like an empty building"
    text = " ".join(f.answer for f in facts).lower()
    assert "out of service" in text


@pytest.mark.asyncio
async def test_an_amenity_with_no_status_is_still_offered():
    facts = await _resolver(_WORKING).resolve("where is the water fountain?")
    assert [f.label for f in facts] == ["Drinking fountain, floor 1"]


@pytest.mark.asyncio
async def test_the_query_actually_asks_for_the_status():
    """The property was declared for a year and never read; assert the join is present."""
    captured = {}

    async def _exec(q):
        captured["q"] = q
        return _rows(_WORKING)

    await CapabilityGraphResolver(sparql_exec=_exec).resolve("water fountain")
    assert "ontosage:amenityStatus" in captured["q"]
    assert "ontosage:statusValue" in captured["q"]


# ── silence is more dangerous than a broken entry, for some categories ───────
_BROKEN_AED = {
    "a": "urn:aed",
    "label": "Defibrillator (AED) and first aid",
    "lay": "defibrillator,aed,first aid",
    "cat": "EMERGENCY",
    "svc": "out_of_service",
}


@pytest.mark.asyncio
async def test_a_broken_defibrillator_is_reported_never_hidden():
    """Excluding an out-of-service AED tells somebody asking in an emergency that the
    building has none. The exclusion rule was written for a drinking fountain, where a
    wasted trip is the whole cost."""
    facts = await _resolver(_BROKEN_AED).resolve("where is the defibrillator?")
    assert facts, "a safety-critical amenity must never be silently withheld"
    blob = " ".join(f"{f.label} {f.note}" for f in facts).lower()
    assert "defibrillator" in blob
    assert "out of service" in blob


@pytest.mark.asyncio
async def test_a_broken_fountain_is_still_excluded():
    """The carve-out is scoped: an ordinary amenity keeps the exclusion rule."""
    facts = await _resolver(_WORKING, _BROKEN).resolve("where is the water fountain?")
    assert [f.label for f in facts] == ["Drinking fountain, floor 1"]


@pytest.mark.parametrize(
    "category,expected",
    [
        ("EMERGENCY", True),
        ("Safety", True),
        ("ACCESSIBILITY", True),
        ("AMENITIES", False),
        ("", False),
    ],
)
def test_safety_categories(category, expected):
    from orchestrator.services.capability_graph_resolver import _is_safety_critical

    assert _is_safety_critical(category) is expected
