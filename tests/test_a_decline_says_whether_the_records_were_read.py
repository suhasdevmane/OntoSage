# -*- coding: utf-8 -*-
"""BUG-1252 (P1) — the decline that replaces a deleted answer must not deny the read.

MEASURED LIVE, 2026-09-30, four consecutive turns in one container log. Each question routed
correctly, its lane fetched real readings, an answer was produced, and the answer-relevance
gate replaced it with `_unanswered_response`:

    relevance gate replaced a sensor_data answer: OFF_TOPIC
        (Does not address change, only gives current values.)      <- 275 humidity UUIDs
    relevance gate replaced a sensor_data answer: OFF_TOPIC
        (Does not provide return air temperature, ...)             <- 6 AHU points, fresh
    relevance gate replaced a analytics  answer: OFF_TOPIC
        (Provides data, not explanation of monitoring method.)     <- 1,000 water rows
    relevance gate replaced a events     answer: OFF_TOPIC
        (does not address reserved spaces question.)               <- the events lane

The reader then saw "I couldn't answer that from Abacws Building's records", followed one
paragraph later by "the nearest things I can answer are the readings of humidity" — a refusal
naming, as an alternative, the very quantity the turn had just read 275 series of.

WHAT THIS FIX IS NOT
--------------------
It does not stop the gate firing, and it does not widen `_grounded_evidence_behind`. The
gate's VERDICT was right in all four, and in at least two the deleted answer really was about
something else (BUG-1255: a return-air question answered with building averages), so
suppression was protective. A fifth instance arrived the same day — BUG-1271, "what is the
average sound level" answered with a list of eight floors — which makes three independent
cases of the gate correctly rejecting an off-topic answer. The data lanes are where the gate
measures best (sensor_data 17/30 weird flagged, 0/10 good replaced), and disabling its action
there on the evidence of a hand read is the trade CAVEAT-972 and BUG-1073 both refused.

What changes is the SENTENCE. That cannot restore a wrong answer and cannot lose a right one.

WHY THE OPENING IS THE PART THAT NEEDED CARE
--------------------------------------------
Five consumers classify a decline from its text, and a new opening they do not know is read as
an ANSWER — which silently moves every decline-rate measurement in the project (lessons #141:
one question produced three honest decline wordings in a single day). The opening therefore
reuses "I couldn't put an answer together", which `publication_gate` already carried, and the
lists that did not were updated in the same change and measured:

    2,985 stored answers (73-probe pack + every docs/phase0/*.jsonl) — 0 reclassified
    73-probe guard — publication_gate 11, grade_answers_rubric 11, regression 16, unchanged

One candidate addition was REVERTED for failing that measurement, and it is the reason the
measurement is run rather than assumed: the uncontracted "could not put an answer together"
moves 33 stored answers, because the RETIRED `_unanswered_response` text read "I understood the
question but could not put an answer together for it."
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import List

import pytest

from orchestrator.services import clarification as clar
from orchestrator.services.publication_gate import is_decline as pg_is_decline
from orchestrator.workflow import _orchestrator
from orchestrator.workflow._orchestrator import _store_rows_read

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
BUILDING = "Abacws Building"


class _State:
    def __init__(self, results):
        self.intermediate_results = results


class _Record:
    def __init__(self, label, terms=()):
        self.label = label
        self.terms = terms


RECORDS = [_Record("Booking", ("booking",)), _Record("Maintenance", ("work order",))]
MEASURED = ["humidity", "temperature", "co2", "water flow"]


# ── the signal: did this turn count rows out of a store? ─────────────────────────────


@pytest.mark.parametrize(
    "label, results, expected",
    [
        # The three shapes the SQL lane writes, all of which `_count_sql_rows` knows
        # (BUG-508 — reading one level too shallow returned 0 for every real fetch).
        ("#23 humidity, 275 series", {"sql_result": {"results": {"data": [{}] * 275}}}, 275),
        ("#43 return air, 6 points", {"sql_result": {"data": [{}] * 6}}, 6),
        ("#45 water, 1,000 rows", {"sql_result": {"results": [{}] * 1000}}, 1000),
        # The events lane, which writes a list or a total depending on the kind.
        ("#46 reserved spaces", {"events_result": {"success": True, "rows": [{}, {}, {}]}}, 3),
        ("events with a total", {"events_result": {"success": True, "total": 12}}, 12),
    ],
)
def test_a_counted_read_of_a_store_is_visible(label, results, expected):
    assert _store_rows_read(_State(results)) == expected, label


@pytest.mark.parametrize(
    "label, results",
    [
        ("nothing ran", {}),
        ("a lane ran and fetched nothing", {"sql_result": {"results": {"data": []}}}),
        # BUG-1271: eight floor labels for "what is the average sound level". The lane ran and
        # the gate was right to delete the answer, but no store was read, so the stronger
        # sentence must NOT be offered.
        ("sparql only, no readings", {"sparql_result": {"results": [{}] * 8}}),
        (
            "an events DECLINE, which reads nothing",
            {"events_result": {"success": True, "kind": "referent_not_found"}},
        ),
        (
            "an events lane that failed",
            {"events_result": {"success": False, "rows": [{}, {}]}},
        ),
    ],
)
def test_no_counted_read_reports_zero(label, results):
    """Positive-only, like `_grounded_evidence_behind`: 0 means "none visible", never "none"."""
    assert _store_rows_read(_State(results)) == 0, label


def test_a_malformed_state_reports_zero_rather_than_raising():
    """A wording decision must never cost an answer."""
    assert _store_rows_read(object()) == 0
    assert _store_rows_read(_State(None)) == 0
    assert _store_rows_read(_State({"sql_result": "not a dict"})) == 0
    assert _store_rows_read(_State({"events_result": {"success": True, "total": "many"}})) == 0


def test_this_is_not_the_gate_s_own_guard_and_must_not_become_it():
    """`_grounded_evidence_behind` decides whether an answer may be DELETED; this decides only
    what the resulting decline may SAY. BUG-1252 records at length why widening the first is
    unsafe, and `test_the_relevance_gate_gap_tail_n_measured.py` fails if anyone does."""
    guard = inspect.getsource(_orchestrator._grounded_evidence_behind)
    for key in ("sql_result", "analytics_result", "events_result"):
        assert key not in guard, key


# ── the sentence ─────────────────────────────────────────────────────────────────────


def test_the_default_lead_still_says_what_it_always_said():
    """The no-lane-ran case is untouched: there the old sentence is true."""
    text = clar.compose_abstract("Example Building", "tell me things", (), MEASURED, RECORDS)
    assert text.startswith("I couldn't answer that from Example Building's records.")


def test_the_read_lead_does_not_deny_the_read():
    lead = clar.lead_read_but_off_topic(BUILDING)
    low = lead.lower()
    assert "i did read them" in low, lead
    assert "couldn't answer that from" not in low, lead


def test_only_the_lead_changes_and_the_tail_is_untouched():
    """The nearest-holdings tail is derived live and is still the reader's way forward."""
    q = "Has the humidity changed in the past hour?"
    plain = clar.compose_abstract(BUILDING, q, (), MEASURED, RECORDS, ["humidity"])
    read = clar.compose_abstract(BUILDING, q, (), MEASURED, RECORDS, ["humidity"], True)
    assert plain != read
    tail = "\n\n" + plain.split("\n\n", 1)[1]
    assert read.endswith(tail), read
    # The resolved entity is still named, and still AFTER the marker rather than spliced
    # into the middle of it (BUG-876's shape).
    assert "**humidity**" in read
    assert read.lower().index("put an answer together") < read.index("**humidity**")


def test_the_two_shapes_that_do_not_assert_anything_about_the_records_are_unaffected():
    """A weather reply names the outdoor readings it found; a referent reply asks which one is
    meant. Neither says the building could not answer, so neither carries the falsehood."""
    kind, text = clar.compose(
        building=BUILDING,
        question="What caused the incident?",
        records=RECORDS,
        read_but_off_topic=True,
    )
    assert kind == clar.KIND_REFERENT
    assert "put an answer together" not in text.lower()


# ── every consumer that classifies a decline from its text ───────────────────────────


def _regression_module():
    import importlib.util

    path = REPO / "scripts" / "regression_answerability.py"
    spec = importlib.util.spec_from_file_location("_ra_bug1252", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decline_leads_from_source() -> List[str]:
    """Read the tuple the product uses, not a copy of it (lessons #145).

    It is a local inside `_response_node`, so it cannot be imported.
    """
    src = inspect.getsource(_orchestrator)
    block = src[src.index("_decline_leads = (") :]
    block = block[: block.index(")")]
    return [
        line.strip().strip(",").strip('"')
        for line in block.splitlines()[1:]
        if line.strip().startswith('"')
    ]


@pytest.mark.parametrize("entities", [[], ["humidity"]], ids=["bare", "named"])
def test_every_decline_classifier_recognises_the_new_wording(entities):
    """A new opening none of them knows is read as an ANSWER, which moves every decline-rate
    measurement in the project without anything having changed (lessons #141)."""
    from scripts.grade_answers_rubric import is_decline as grader

    ra = _regression_module()
    text = clar.compose_abstract(
        BUILDING, "Has the humidity changed?", (), MEASURED, RECORDS, entities, True
    )
    assert pg_is_decline(text), text[:120]
    assert grader(text), text[:120]
    assert ra.classify(text) == "declined", text[:120]
    leads = _decline_leads_from_source()
    assert any(text.lstrip().lower().startswith(m) for m in leads), leads


def test_the_design_occupancy_path_replaces_this_decline_rather_than_prepending_to_it():
    """Otherwise a declared capacity is stated and then denied in the next sentence (BUG-897)."""
    leads = _decline_leads_from_source()
    assert len(leads) == 4, leads
    assert "i couldn't put an answer together" in leads


def test_the_addition_reclassifies_none_of_the_73_stored_pack_answers():
    """CLAUDE.md's standing rule, and the reason one candidate marker was reverted: the
    uncontracted form moves 33 stored answers from the retired `_unanswered_response` text."""
    pack = REPO / "docs" / "supervisor_evidence_pack" / "answers.jsonl"
    if not pack.is_file():
        pytest.skip("evidence pack not present")
    rows = [
        json.loads(line) for line in pack.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(rows) == 73, len(rows)
    ra = _regression_module()
    marker = "put an answer together"
    assert not [r for r in rows if marker in (r.get("answer") or "").lower()]
    assert sum(1 for r in rows if pg_is_decline(r.get("answer") or "")) == 11
    assert (
        sum(1 for r in rows if ra.classify(r.get("answer") or "") in ("declined", "refused")) == 16
    )


# ── the wiring ───────────────────────────────────────────────────────────────────────


def test_the_stronger_sentence_is_gated_on_the_gate_having_replaced_something():
    """Both halves are required. `relevance_gate.replaced` says a lane's answer was DELETED —
    the only case in which the default sentence is false — and `_store_rows_read` says the
    turn actually read a store, which is what "I did read them" asserts."""
    src = inspect.getsource(_orchestrator._unanswered_response)
    assert "relevance_gate" in src
    assert "_store_rows_read" in src
    assert "read_but_off_topic" in src
    # The row count is only consulted when the gate replaced; otherwise an ordinary
    # no-answer turn that happened to fetch rows would claim a deletion that never happened.
    assert src.index("_gate_replaced") < src.index("_store_rows_read(state)")


def test_the_gate_s_verdict_does_not_outlive_its_turn():
    """A key that is READ on the response path must be cleared between turns.

    `relevance_gate` was written and never read there, so leaving it behind cost nothing.
    Now `_unanswered_response` reads `replaced`, and a stale one would make THIS turn's
    decline say "I did read them" about the PREVIOUS question's read. That is the shape of
    the defect `_PER_TURN_LANE_KEYS` exists to stop — measured once as a deliberative answer
    about the wrong room, floor and modality being served verbatim on the following turn.
    """
    assert "relevance_gate" in _orchestrator._PER_TURN_LANE_KEYS
