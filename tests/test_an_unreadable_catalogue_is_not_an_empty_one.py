# -*- coding: utf-8 -*-
"""CAVEAT-951: a sensor catalogue that could not be read is not a building with no sensors.

Observed 2026-09-29 while verifying BUG-950. The FIRST question after ``docker compose
restart`` declined with:

    "The nearest things I can answer are the Interval record, Timetabled session and Access
     event records."

— records only, not one measurand. The identical question thirty seconds later, container
warm, ended "…and the readings of pm25, air quality, carbon monoxide and co2." Nothing in the
cold answer said the catalogue could not be read. The list simply looked shorter, and a reader
takes a shorter list as a smaller building.

This is the *four kinds of nothing* lesson at the wording layer: a RETRIEVAL FAILURE was
published as an ABSENCE. The two need different words because they need different actions —
try again, versus this building does not measure it.

**The information is not missing; it is discarded.** ``_measured_modality_counts`` documents
and honours the distinction — "None when nothing could be read (graph down, no modalities
declared, timeout) … Neither is ever zero" — and ``_measured_names`` then turns that None into
``[]``, after which no caller can tell the two apart. The tests below pin both halves: that
the distinction is real at the source, and that it is gone one call later.

The wording itself already existed, for the reach lane's own cold case, so this file's job is
to stop a SECOND one being written: ``observability.catalogue_unreadable`` is the single
sentence, and the response node's literal is parsed back out of its source and compared.
"""

import asyncio
import inspect
import re
from pathlib import Path

import pytest

from orchestrator.services.observability import catalogue_unreadable

pytestmark = pytest.mark.unit

_ORCHESTRATOR = (
    Path(__file__).resolve().parents[1] / "orchestrator" / "workflow" / "_orchestrator.py"
)


def _response_node_wording() -> str:
    """The cold-catalogue sentence as the response node emits it, read from its source.

    Derived, never restated. CLAUDE.md's rule for decline wording is that the marker set comes
    from the code that EMITS it (lessons #141); the same rule applies to a sentence two lanes
    now share.
    """
    src = _ORCHESTRATOR.read_text(encoding="utf-8")
    found = re.search(
        r'f"\*\*I couldn\'t read \{_bname\}\'s sensor catalogue just now,\*\* so I can\'t "\s*'
        r'"([^"]*)"\s*"([^"]*)"',
        src,
    )
    assert found, "the response node no longer carries the cold-catalogue sentence"
    return (
        "**I couldn't read {b}'s sensor catalogue just now,** so I can't "
        + found.group(1)
        + found.group(2)
    )


def test_one_sentence_serves_both_lanes():
    """Reuse the wording rather than inventing a second one — the row's own prescription."""
    assert catalogue_unreadable("Abacws Building") == _response_node_wording().format(
        b="Abacws Building"
    )


def test_it_names_the_building_it_is_asked_about():
    assert "Abacws Building's sensor catalogue" in catalogue_unreadable("Abacws Building")
    assert "Other Tower's sensor catalogue" in catalogue_unreadable("Other Tower")


def test_a_building_with_no_name_still_reads_as_a_sentence():
    text = catalogue_unreadable("")
    assert "this building's sensor catalogue" in text
    assert "{" not in text and "None" not in text


def test_it_says_unreadable_and_never_says_absent():
    """The whole point: nothing here may be read as the building measuring nothing."""
    text = catalogue_unreadable("Abacws Building").lower()
    assert "couldn't read" in text
    assert "try again" in text
    for absence in ("no sensors", "does not measure", "nothing is measured", "none"):
        assert absence not in text


def test_the_sentence_carries_no_building_literal():
    """Design contract 3: portable, so the building is an argument and never a constant."""
    src = inspect.getsource(catalogue_unreadable)
    for literal in ("Abacws", "bldg1", "bldg2", "bldg3"):
        assert literal not in src


# ── the premise the handover rests on ────────────────────────────────────────────────────────


def test_an_unreadable_catalogue_is_None_at_the_source_and_not_an_empty_dict():
    """`_measured_modality_counts` keeps the distinction. This is where it still exists."""
    from orchestrator.workflow._orchestrator import _measured_modality_counts

    class _Spec:
        def __init__(self, name):
            self.name = name

    async def _dead(*_args, **_kwargs):
        raise RuntimeError("graphdb cold")

    got = asyncio.run(
        _measured_modality_counts(
            timeout_s=5.0,
            building_id="probe-bldg",
            namespace="http://example.org/probe#",
            sparql_exec=_dead,
            specs=[_Spec("temperature"), _Spec("co2")],
        )
    )
    assert got is None, "an unreadable catalogue must not come back as a readable empty one"


def test_the_distinction_is_carried_not_lost_one_call_later():
    """`_measured_names(None)` and `_measured_names({})` are the same empty list — so DON'T ASK IT.

    NOT a complaint about `_measured_names`, whose job is names. It records WHERE the fact used
    to be dropped, so the fix stayed at the one line that has both values in hand rather than
    being guessed at further downstream. `_closest_holdings` is the caller that holds them.

    THIS TEST USED TO ASSERT THE OPPOSITE, and its failure message said to flip it once the
    handover landed. It has landed: `_closest_holdings` now returns `Optional[List[str]]` and
    decides None-vs-names BEFORE calling `_measured_names`, so the unreadable case can no
    longer be laundered into "this building measures nothing" by a function whose only job is
    to format names.
    """
    from orchestrator.workflow._orchestrator import _closest_holdings, _measured_names

    assert _measured_names(None) == []
    assert _measured_names({"temperature": 0}) == []
    src = inspect.getsource(_closest_holdings)
    assert "_measured_names(" in src
    assert "-> Tuple[Optional[List[str]], List[Any]]" in src, (
        "the unreadable/empty distinction must survive the return (CAVEAT-951); a plain "
        "List[str] here cannot express 'the catalogue could not be read'"
    )
    # the decision has to happen before the formatter, not inside it
    assert "None if _counts is None else _measured_names(" in src, (
        "None-vs-names must be decided at the call site that still has the counts; passing "
        "the counts straight into _measured_names is exactly how the fact was lost before"
    )
