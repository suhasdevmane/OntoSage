# -*- coding: utf-8 -*-
"""Tail N, 2026-09-30: the two false declines a register vocabulary fix could move (BUG-1251).

WHAT THIS PINS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Six of the eight false declines in the live tail-N read were grouped under one heading -- "the
system names the right source in the same sentence as the refusal" -- and measured against the
running build they have FOUR distinct causes, not one (BUG-1251; lessons #158). Only the two
below are register-selector defects, and only those two are pinned here. The other four are
recorded in the tracker against the components that actually produced them:

* #23 humidity, #43 return air temperature, #45 water consumption and #46 reserved spaces were
  all produced by the ANSWER-RELEVANCE GATE replacing a lane's answer with
  `_unanswered_response` (BUG-1252). No register is involved in any of them -- the reading the
  decline names is the MODALITY half of the pointer, which is genuinely close because the
  question named the quantity and the building measures it.
* #45 additionally misses the reach lane on a spelling error in the asker's own text
  ("montored"), which is not a matcher defect at all (CAVEAT-1254).

Each question below is the VERBATIM text a participant typed, including its capitalisation, so
a fix that works only on a tidied paraphrase fails here (lessons #137).

The scoring functions are the router's own, supplied with what they would read from GraphDB by
`scripts/register_reach.py` -- the schema TTL parsed with rdflib, plus the cached instance
snapshot the guard set was derived on. A term declared here is therefore measured without an
upload, and the whole-catalogue measurement behind it is in BUG-1251's row.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
GUARD = REPO / "docs" / "phase0" / "guard_set.jsonl"

#: The two tail-N questions a register vocabulary change moves, verbatim.
N25 = "do the entry and exit logs reconcile for a roll call right now?"
N9 = "Does the server room keep track of who visits the room?"

#: Tail N #46. It reaches Booking now, which is necessary and NOT sufficient: live it routed to
#: the events lane and the relevance gate deleted that lane's answer (BUG-1252). Pinned as a
#: selection, never as an answer.
N46 = "are there any spaces reserved but not currently in use?"


def _harness():
    name = "_test_tail_n_reach_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "register_reach.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    return _harness()


#: THE GUARD SNAPSHOT PREDATES THE ACCESS-EVENT LOAD, and a test written against it would
#: have pinned the wrong thing silently. It was taken 2026-09-17 with `AccessEvent: 0`, so
#: every question below would select nothing however the vocabulary were written — including
#: "who accessed the server room?", which that class has answered since. The live building
#: holds 679 (read from GraphDB 2026-09-19, and the tail-N answer of 2026-09-30 quotes the
#: same figure). `with_counts` exists for exactly this — modelling a load the guard file has
#: not seen — and the override is named here rather than left as an untracked snapshot file,
#: because `scripts/outputs/` is gitignored and CI would resolve it to zero.
LIVE_COUNTS = {"AccessEvent": 679}


@pytest.fixture(scope="module")
def reach(harness):
    """The router's view of the building the guard set was derived on, from files alone."""
    meta, _rows = harness.read_guard(GUARD)
    snapshot = harness.with_counts(meta["snapshot"], LIVE_COUNTS)
    return harness.Reach(harness.load_schema(SCHEMA), snapshot)


# ── the two that are fixed ────────────────────────────────────────────────────────────────


def test_entry_and_exit_logs_reach_the_access_event_register(reach):
    """#25. It selected CoordinationFunction on "roll call" and said so in its refusal.

    Live, 2026-09-30: "The emergency coordination function register (14 records) cannot answer
    this: it records primary system and system state, and nothing about exit, logs and
    reconcile." The register naming the three words it lacks is the system reporting its own
    defect. AccessEvent holds 679 records of exactly those.
    """
    assert reach.register(N25)["held"] == "AccessEvent"


def test_the_coordinated_noun_phrase_is_what_the_old_vocabulary_could_not_match(reach):
    """The PREMISE, so this test cannot pass for an unrelated reason (lessons #146).

    "entry log" and "entry logs" were declared before this fix and neither can match "entry
    AND EXIT logs": a lay term is matched whole, with word boundaries, so a coordinated noun
    phrase reaches only its LAST head. "exit logs" is contiguous in that sentence and "entry
    log" is not. If either of those ever starts matching, the fix below is redundant and this
    test says so.
    """
    registry = _harness().record_registry()
    low = f" {N25.lower()} "
    assert registry._term_score("entry log", low) == 0.0
    assert registry._term_score("entry logs", low) == 0.0
    assert registry._term_score("exit logs", low) > 0.0


def test_the_access_register_outranks_the_roll_call_term_outright(reach):
    """Not by a tie-break. "roll call" scores 18.00; "entry and exit logs" scores 38.00.

    A tie would be decided by the building's own ordering, which is not a reason anyone would
    accept for choosing between two registers (lessons #155).
    """
    registry = _harness().record_registry()
    low = f" {N25.lower()} "
    assert registry._term_score("roll call", low) == pytest.approx(18.0)
    assert registry._term_score("entry and exit logs", low) == pytest.approx(38.0)


def test_who_visits_reaches_the_access_event_register(reach):
    """#9. It reached NO register under either matcher and fell to the document lane.

    Live, 2026-09-30: "Abacws Building's documents do not answer this. I searched Stakeholder
    Group Register". Note what this instance is NOT: the decline's pointer did not name
    AccessEvent either, so this is a plain vocabulary gap and not BUG-970's two-matcher
    disagreement. The tail-N read grouped it with the four that are -- BUG-1073's warning about
    reading a pointer's output as evidence, applied to a hand read (BUG-1251).
    """
    assert reach.register(N9)["held"] == "AccessEvent"


def test_spaces_reserved_reaches_the_booking_register(reach):
    """#46's selector half. The register declared "reservation" and not "reserved".

    This IS BUG-970's disagreement, and the only one of the six that is: `content_terms` stems
    "reserved" to "reserv", which `_close` prefix-matches to "reservation", so the decline's
    pointer printed "Room booking" while the selector could not reach it.
    """
    assert reach.register(N46)["held"] == "Booking"


# ── what the fix must not take ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        # The register whose question #25 was taken FROM keeps its own.
        ("are we ready for an incident", "CoordinationFunction"),
        ("who is on call", "CoordinationFunction"),
        ("what is the roll call procedure", "CoordinationFunction"),
        # AccessEvent's existing questions are unchanged.
        ("who accessed the server room?", "AccessEvent"),
        # Booking's are too, and the events lane still owns this one upstream.
        ("Which meeting rooms are booked this afternoon?", "Booking"),
        # Registers that share no vocabulary with any of it.
        ("when is the recycling collected?", "WasteCollectionPoint"),
        ("what is the escalation route", "Department"),
        ("when was the fire alarm last tested?", "FireSafetyAsset"),
        ("how many permits are open?", "Permit"),
    ],
)
def test_the_registers_these_terms_must_not_take(reach, question, expected):
    assert reach.register(question)["held"] == expected


def test_the_only_other_catalogue_question_with_reserved_does_not_move(reach):
    """LB-063, verbatim. "reserved" there means reserved TO someone, not booked.

    Measured over all 2,960 catalogue questions, "reserved" moves exactly one question and it
    is not this one: CoordinationFunction already outscores a bare eight-character term here.
    The word is irreducibly two-sensed and the catalogue proves it both ways, which is why the
    measurement decides and not the intuition (BUG-971).
    """
    question = (
        "What is the verified impact of the present disruption, and which choices remain "
        "reserved to incident command or accountable service owners?"
    )
    assert reach.register(question)["held"] == "CoordinationFunction"


def test_bare_visitor_is_not_declared_anywhere(harness, reach):
    """MEASURED AND REJECTED, and pinned so it is not added on intuition later (CAVEAT-1253).

    Bare "visitor"/"visitors" on AccessEvent moves 30 of the 2,960 catalogue questions, and
    read by hand most are not access-event questions at all -- "A visitor is joining me. Which
    approved meeting point is easy to find", "How stale are the HR, student, visitor,
    contractor and training feeds used by current access decisions". The same shape CAVEAT-972
    recorded for automatic plural tolerance. Whole phrases only.
    """
    for record in reach.held:
        assert "visitor" not in record.terms, record.local_name
        assert "visitors" not in record.terms, record.local_name
