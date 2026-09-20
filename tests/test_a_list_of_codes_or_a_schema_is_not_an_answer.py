# -*- coding: utf-8 -*-
"""Codes, schema and system messages are not answers (2D-16 wave 5).

Three independent unseen sets read 38.3%, 38.7% and 43.5% weird, and every wave that fixed the
specific answers it was shown left the rate where it was, because the tail is long. What moves a
rate is a CLASS gate that turns a bad answer into an honest decline. Tail F found seven answers
that the wave-3 guard was too narrow to catch; each is pinned here with its live text, together
with the standard the guard is held to: over ALL 1,845 recorded answers, none the hand read called
good may change.
"""

from __future__ import annotations

import glob
import json
import os
import re
from types import SimpleNamespace

import pytest

from orchestrator.services import absence_wording as aw
from orchestrator.services import answer_shape as ash

pytestmark = pytest.mark.unit

FEEDERS_Q = "Which feeders or boards show sustained loading that warrants detailed cable, protection and capacity checks?"
INCIDENT_Q = (
    "What incident identifier, command status and authoritative information source are "
    "confirmed for this event?"
)
PREREQ_Q = (
    "Which evidence-based prerequisites remain before each area, asset or service can return to "
    "authorised use?"
)
AVAILABLE_Q = "What can the building tell me about entrances?"
REPORT_Q = (
    "Which proposed report facts are directly supported, which require qualification, and what "
    "exact evidence citation belongs with each statement?"
)
ROUTE_Q = (
    "I need to carry approved service or event materials to another floor. Which authorised route "
    "is currently suitable?"
)

FOOTER = "\n\n---\n*From Abacws Building's documents: Asset Engineering Register. For the current version, contact facility management.*"

PROPERTY_DEFINITIONS = (
    "- Current Service Status\n"
    "  - Property: `serviceStatus` (link to an `AssetStatus` record)\n"
    "  - Definition: 'The reported operational state of a lift, door, AV system or other asset.'\n"
    "- Return To Use Approval\n"
    "  - Property: `returnToUseApproval` (link to an `ApprovalRecord`)\n"
    "  - Definition: 'The approval that allows an area or asset to be used again.'"
)
CLASS_NAMES = (
    "I could not find that in the records. What the building does have:\n"
    "- Entrance – the building has a class for the main entrance\n"
    "- ContinuityProvision – a continuity arrangement for a critical service\n"
    "- RefugePoint – a class for an evacuation refuge\n"
)
FIELD_DESCRIPTIONS = (
    "Each entry lists:\n"
    "- **Location** (e.g., “Ceiling voids where asbestos is registered”)\n"
    "- **Note** (a numeric value, e.g., 12, 24, 36)\n"
    "- **Applies‑to role** (e.g., contractor, operator, researcher)\n"
    "- **Covered scope** (e.g., Asbestos awareness, Confined space entry)"
)
SUPPRESSED = (
    "I computed an answer but its narration failed the evidence check — a number in the text "
    "could not be traced back to the underlying data, so I'm not showing it. The structured "
    "result is still available; please try rephrasing."
)
NARRATED_ABSENCE = (
    "I’m sorry, but the information returned only lists the building’s floors (e.g., "
    "“Floor 0 (Ground Floor)”, “Floor 1 (First Floor)”, etc.). It does not "
    "contain any records of authorised routes that would allow you to move approved service or "
    "event materials between floors. The field that would hold that information is not present "
    "in these results."
)

LIVE = [
    ("identifiers", FEEDERS_Q, "GEN-01\nAEP-012" + FOOTER, "only record identifiers"),
    (
        "id and status",
        INCIDENT_Q,
        "RES-EV-2026-0909, Confirmed, RES-EV-2026-0909",
        "only record identifiers",
    ),
    ("properties", PREREQ_Q, PROPERTY_DEFINITIONS, "a list of ontology property definitions"),
    ("class names", AVAILABLE_Q, CLASS_NAMES, "ontology class names offered"),
    ("field list", REPORT_Q, FIELD_DESCRIPTIONS, "a list of field descriptions"),
    ("suppression", "Which check-ins are current?", SUPPRESSED, "an internal suppression message"),
]


@pytest.mark.parametrize("label,question,answer,reason", LIVE, ids=[c[0] for c in LIVE])
def test_each_tail_f_shape_is_caught_and_named(label, question, answer, reason):
    got = ash.non_answer_reason(answer, question)
    assert got and got.startswith(reason), (label, got)


# ── the seven-shaped precision rules ─────────────────────────────────────────


@pytest.mark.parametrize(
    "answer",
    [
        "DR-004",  # one code can be a complete (terse) answer to "which door?"
        "Yes — DR-004 is defective and overdue for test.",
        "The maintenance contract is with Meridian Mechanical Ltd.",
        "GEN-01 is the standby generator on Level 0 and AEP-012 is its engineering profile.",
        "Confirmed",
    ],
)
def test_a_single_code_or_a_sentence_about_a_code_is_left_alone(answer):
    assert not ash.is_identifier_list(answer)


def test_two_codes_with_a_word_between_them_are_an_answer_not_a_list():
    assert not ash.is_identifier_list("GEN-01 and AEP-012")
    assert ash.is_identifier_list("GEN-01, AEP-012")


def test_the_non_breaking_hyphen_models_write_is_read_as_a_hyphen():
    assert ash.is_identifier_list("AEP‑012 GEN‑01")


def test_a_reader_who_asks_what_a_term_means_is_given_the_definition():
    q = "What does the serviceStatus property mean?"
    assert ash.describes_the_schema(PROPERTY_DEFINITIONS, q) is None
    assert (
        ash.describes_the_schema(
            "Each entry lists a name (e.g. a) and a role (e.g. b).",
            "what fields does each record have?",
        )
        is None
    )


def test_a_reader_asking_about_the_schema_is_not_refused_the_schema():
    assert ash.non_answer_reason(FIELD_DESCRIPTIONS, "What columns does the register have?") is None


def test_prose_that_happens_to_say_each_entry_is_not_a_field_list():
    prose = (
        "Each entry lists the room and the date, and 4 of the 12 are overdue. For example, Room "
        "5.01 was last checked on 2026-08-01."
    )
    assert ash.describes_the_schema(prose, REPORT_Q) is None


def test_one_backticked_term_in_a_real_answer_is_not_a_schema_description():
    assert (
        ash.describes_the_schema(
            "The lift record uses `serviceStatus` to say it is closed.", "is the lift working?"
        )
        is None
    )


# ── narration: the wide phrases act only when a register is held ─────────────


def _circulation():
    from orchestrator.services.record_registry import RecordClass, _terms_for

    return RecordClass(
        "CirculationTime",
        "Circulation time",
        23,
        _terms_for("CirculationTime", "Circulation time", "authorised route|carry materials"),
    )


def test_a_false_absence_about_a_held_register_names_the_register_and_claims_no_absence():
    note = aw.false_absence_note(NARRATED_ABSENCE, ROUTE_Q, [_circulation()], "Example Building")
    assert note and "circulation time" in note
    assert "keeps circulation time records" in note
    for banned in ("does not contain", "no records", "information returned", "sorry"):
        assert banned not in note.lower()


def test_a_true_decline_with_the_same_wording_is_left_exactly_as_it_was():
    """'The dataset only lists sensors' for a question no register matches is TRUE, and good."""
    true_decline = (
        "I'm sorry, but the records I have access to do not contain the building's construction "
        "date. The dataset only lists sensors and their details; it does not state whether the "
        "building is older or a new-build."
    )
    assert (
        aw.false_absence_note(true_decline, "are you older or a new-build", [_circulation()])
        is None
    )


def test_an_answer_with_substance_is_never_replaced_by_the_note():
    answer = (
        "Route RTE-015 is step-free between floors 0 and 2 and was surveyed on 2026-08-01, and "
        "RTE-016 is closed for repair. The information returned also lists the building's floors."
    )
    assert aw.false_absence_note(answer, ROUTE_Q, [_circulation()]) is None


def test_no_records_means_no_note_and_no_error():
    assert aw.false_absence_note(NARRATED_ABSENCE, ROUTE_Q, [], "B") is None
    assert aw.false_absence_note(NARRATED_ABSENCE, ROUTE_Q, None, "B") is None


def test_the_wide_phrases_alone_do_not_trigger_the_always_on_strip():
    """Those same words open good declines, so on their own they change nothing."""
    for phrase in (
        "The dataset only lists sensors and their details.",
        "The records you queried do not contain that.",
        "The information returned only lists floors.",
    ):
        assert not aw.describes_retrieval(phrase)
        assert aw.describes_retrieval_wide(phrase)


def test_the_narrow_phrases_are_unchanged_and_do_not_catch_report_prose():
    assert aw.describes_retrieval("The data you received only lists sensor counts.")
    for fine in (
        "No anomalies were detected in the dataset.",
        "Across the entire data set the mean was 21 degrees.",
        "Total records examined: 16",
        "I did not find that in the records I searched.",
        "The target information above says 12.",
    ):
        assert not aw.describes_retrieval(fine), fine


# ── the system's own suppression message ─────────────────────────────────────


def test_the_suppression_message_says_plainly_what_could_not_be_checked():
    from orchestrator.services.numeric_guard import SUPPRESSION_TEXT

    for jargon in ("narration", "evidence check", "structured result", "rephras", "dossier"):
        assert jargon not in SUPPRESSION_TEXT.lower(), jargon
    assert "figure" in SUPPRESSION_TEXT and "could not be checked" in SUPPRESSION_TEXT
    assert "Ask for one" in SUPPRESSION_TEXT, "a reader is told what to ask instead"
    assert ash.non_answer_reason(SUPPRESSION_TEXT, "which check-ins are current?") is None


def test_the_deliberation_lane_uses_the_same_plain_message():
    import inspect

    from orchestrator.workflow import _orchestrator as mod

    src = inspect.getsource(mod.WorkflowOrchestrator)
    assert "narration failed the evidence check" not in src
    assert "see the dossier" not in src


def test_a_lane_still_emitting_the_old_message_is_replaced_by_the_guard():
    assert ash.non_answer_reason(SUPPRESSED, "anything")


# ── wired where a reader meets it ────────────────────────────────────────────


def test_the_response_node_asks_the_register_question_before_it_strips_the_narration():
    import inspect

    from orchestrator.workflow import _orchestrator as mod

    src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    first = src.index("_false_absence_from_a_held_register(state, final_response)")
    second = src.index("_without_retrieval_narration(state, final_response)")
    assert first < second, "a false absence must be named as a register before it is reworded"
    assert "non_answer_reason(final_response, state.user_message" in src


def test_the_node_helper_replaces_a_false_absence_and_leaves_everything_else(monkeypatch):
    from orchestrator.workflow import _orchestrator as mod

    async def _holdings(state, timeout_s=5.0):
        return ([], [_circulation()])

    monkeypatch.setattr(mod, "_closest_holdings", _holdings)
    import asyncio

    state = SimpleNamespace(user_message=ROUTE_Q, intermediate_results={}, messages=[])
    out = asyncio.run(mod._false_absence_from_a_held_register(state, NARRATED_ABSENCE))
    assert "circulation time" in out and state.intermediate_results["false_absence_named_register"]
    fine = "Rooms 5.01 and 5.09 are laboratories."
    assert asyncio.run(mod._false_absence_from_a_held_register(state, fine)) == fine


# ── the standard: nothing the hand read called good may change ───────────────

_PH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "phase0")


def _recorded():
    for path in sorted(glob.glob(os.path.join(_PH, "*.jsonl"))):
        base = os.path.basename(path)
        if base.endswith("_read.jsonl") or "tail_G" in base:
            continue
        rp = path.replace(".jsonl", "_read.jsonl")
        reads = (
            [json.loads(l) for l in open(rp, encoding="utf-8") if l.strip()]
            if os.path.exists(rp)
            else []
        )
        try:
            rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        except ValueError:
            continue
        for i, row in enumerate(rows):
            verdict = (reads[i].get("verdict") if i < len(reads) else None) or "?"
            yield row.get("q") or "", row.get("answer") or "", verdict


def _changes(question: str, answer: str) -> bool:
    return bool(
        ash.non_answer_reason(answer, question)
        or ash.narrates_the_retrieval_only(answer)
        or aw.rewrite_semantic_absence(answer, question, "the building") is not None
    )


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_no_recorded_good_answer_or_good_decline_is_changed_by_any_guard():
    rows = [(q, a, v) for q, a, v in _recorded() if a.strip()]
    assert len(rows) > 1500, "the replay must actually read the recorded runs"
    changed = [
        (q[:70], re.sub(r"\s+", " ", a)[:110])
        for q, a, v in rows
        if v in ("GOOD_ANSWER", "GOOD_DECLINE") and _changes(q, a)
    ]
    assert not changed, "\n".join(f"{q} -> {a}" for q, a in changed)


@pytest.mark.skipif(not os.path.isdir(_PH), reason="the recorded runs are not in this checkout")
def test_the_guards_do_catch_the_weird_answers_they_were_written_for():
    caught = [(q, v) for q, a, v in _recorded() if a.strip() and v == "WEIRD" and _changes(q, a)]
    assert len(caught) >= 20, f"only {len(caught)} recorded WEIRD answers are caught"
