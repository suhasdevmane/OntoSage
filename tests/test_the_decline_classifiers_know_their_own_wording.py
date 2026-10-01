# -*- coding: utf-8 -*-
"""A decline classifier must recognise the declines this system itself emits.

WHY THIS FILE DERIVES ITS FIXTURES INSTEAD OF WRITING THEM DOWN
---------------------------------------------------------------
Four modules in this repository decide, from prose, whether a reply is a decline, and each
is a list of literal markers. CAVEAT-887 records what that costs: one question produced
THREE honest decline wordings in a single day, each needing its own marker, each found only
when a gate reported a false regression. A test that restates the markers cannot catch the
next wording, because it is written from the same list.

So the fixtures here are not written. They are **produced by calling the functions that
emit the declines** -- ``clarification.compose_abstract`` and
``fallback_wording.compose_unanswered`` -- with both shapes of input each supports. Change
the wording in either emitter and these fixtures change with it; the assertion below then
fails without anyone having to remember to update a list. That is the difference between a
test of the markers and a test of the contract.

WHAT IS PINNED, AND WHAT IS EXPECTED TO FAIL
--------------------------------------------
* ``regression_answerability.classify`` must call every emitted decline a decline. It is
  the gate protecting the 73-question evidence pack, and a decline it scores as an answer
  hides a regression -- the direction that matters (BUG-876).
* ``publication_gate.is_decline`` must call every emitted decline a decline too. It was
  marked ``xfail`` against **CAVEAT-952** while it did not recognise the commonest of
  them; that row is now closed (BUG-992) and the marker is gone. The plan written here
  said the non-strict marker would "report XPASS rather than breaking the suite" — it
  did, for six parameters, and XPASS is a state nobody reads: a green run looked the same
  before and after the fix. A marker left on a passing test is a fix nobody recorded.
  Do not restore it by loosening the assertion.
* The 73 stored pack answers must classify exactly as recorded. CLAUDE.md's standing rule
  (lessons #141): every change to a marker list is verified against all 73, because an
  intermediate broader pattern moved two of them and was rejected for it.

Building-agnostic: the building name is a fixture argument, and nothing here asserts on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
BUILDING = "Test Building"


# ── the fixtures, produced by the emitters rather than transcribed ────────────────────


def emitted_declines() -> List[Tuple[str, str]]:
    """(where it came from, the text) for every decline the fallback lanes can emit.

    Each emitter is called with the inputs that select each of its branches, so the
    returned list holds every surface form those branches produce -- including the one
    where a referent is interpolated into the middle of the lead, which is the shape a
    fixed marker cannot span (BUG-876).
    """
    from orchestrator.services.clarification import compose_abstract
    from orchestrator.services.fallback_wording import compose_unanswered

    out: List[Tuple[str, str]] = []

    # clarification.compose_abstract: with and without a resolved entity, and with and
    # without nearby holdings to offer.
    for entities in ((), ("Room 2.01",)):
        for measured in ((), ("Air Temperature",)):
            label = f"compose_abstract(entities={len(entities)}, measured={len(measured)})"
            out.append(
                (
                    label,
                    compose_abstract(
                        BUILDING,
                        "What is the air pressure in room 2.01 right now?",
                        unmatched=(),
                        measured=measured,
                        records=(),
                        entities=entities,
                    ),
                )
            )

    # fallback_wording.compose_unanswered: the same two lead branches.
    for entities in ((), ("Room 2.01",)):
        out.append(
            (
                f"compose_unanswered(entities={len(entities)})",
                compose_unanswered(
                    building=BUILDING,
                    question="What is the air pressure in room 2.01 right now?",
                    entities=entities,
                ),
            )
        )
    return out


def test_the_emitters_are_callable_and_produce_distinct_wordings():
    """If this fails, every assertion below is vacuous and must not be trusted."""
    produced = emitted_declines()
    assert len(produced) >= 4, produced
    texts = {text for _, text in produced}
    assert len(texts) >= 2, "the emitters produced one wording; the branches did not vary"
    for label, text in produced:
        assert text.strip(), label
        assert "{" not in text, f"{label} leaked a format placeholder: {text[:80]}"


# ── the gate that protects the evidence pack ──────────────────────────────────────────


@pytest.mark.parametrize("label,text", emitted_declines(), ids=lambda v: str(v)[:48])
def test_the_answerability_gate_calls_every_emitted_decline_a_decline(label, text):
    """A decline scored as an answer hides a regression, which is the worse direction."""
    from scripts.regression_answerability import classify

    assert classify(text) in ("declined", "refused"), f"{label}: {text[:120]!r}"


# ── the shared classifier, which is known to be wrong here ────────────────────────────


@pytest.mark.parametrize("label,text", emitted_declines(), ids=lambda v: str(v)[:48])
def test_the_shared_classifier_calls_every_emitted_decline_a_decline(label, text):
    """CAVEAT-952 is CLOSED (by BUG-992), and the xfail that marked it is gone with it.

    All six of these parameters were XPASSing — passing under a marker that said they
    could not. The marker carried ``strict=False``, which is exactly why nobody noticed:
    a non-strict xfail reports an unexpected pass as ``xpassed``, a state that is neither
    a failure nor counted among the passes, so a green run looked identical before and
    after the fix landed. Verified directly before removing it: ``is_decline`` now returns
    True for both leads the caveat named.
    """
    from orchestrator.services.publication_gate import is_decline

    assert is_decline(text), f"{label}: {text[:120]!r}"


def test_the_shared_classifier_still_recognises_what_it_was_written_for():
    """The xfail above must not be read as "this classifier is broken". It is not.

    These are the wordings ``_DECLINE_MARKERS`` was written against. Pinning them here
    means a repair for CAVEAT-952 that widens the list cannot quietly drop one.
    """
    from orchestrator.services.publication_gate import is_decline

    for text in (
        "I don't have readings for that room.",
        "I do not have that information.",
        "No data is held for that period.",
        "That is not measured in this building.",
        "There are no readings for that sensor.",
        "I couldn't verify that against the model.",
        "Unable to answer from the records held.",
    ):
        assert is_decline(text), text


def test_the_shared_classifier_does_not_call_an_answer_a_decline():
    """The direction that would turn a clear answer into a vague one."""
    from orchestrator.services.publication_gate import is_decline

    for text in (
        "CO2 averages 792 ppm across 50 sensors on floor 3.",
        "**Best match: Room 3.50** (score 0.3761 out of 1).",
        "The peak was 1240 ppm at 14:00 yesterday.",
    ):
        assert not is_decline(text), text


# ── the 73-answer guard (lessons #141) ────────────────────────────────────────────────


def _pack_rows() -> List[dict]:
    pack = REPO / "docs" / "supervisor_evidence_pack" / "answers.jsonl"
    if not pack.is_file():
        pytest.skip("evidence pack not present")
    return [
        json.loads(line) for line in pack.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_every_decline_classifier_splits_the_73_stored_answers_as_recorded():
    """One corpus, three classifiers, three different answers -- pinned, not endorsed.

    Measured 2026-09-30 over the 73 stored pack answers: the shared classifier called 6 of them
    declines, the grader's called 11, and the pack gate's called 16. That spread is the evidence
    for CAVEAT-887 and it is pinned here so a change to any one list is a deliberate decision with
    a number attached, not a side effect discovered later.

    UPDATED THE SAME DAY, and the update is the point of the test working. BUG-992 added
    "i couldn't answer that" / "i could not answer that" to `publication_gate._DECLINE_MARKERS`,
    because `clarification.compose_abstract` emits exactly that and `is_decline` returned False
    for all three of its surface forms. The miss was inert inside `evaluate` — the next guard
    catches a decline anyway, since a decline carries no figure — but LIVE in
    `session_summary.outcome_of`, where a turn ending in that decline was remembered as
    `answered` and fed into the classification prompt on every `/v1` turn.

    **The shared classifier moves 6 -> 11, giving it the same TOTAL as the grader.**

    THE SENTENCE THAT USED TO BE HERE WAS WRONG, AND CORRECTING IT IS WORTH MORE THAN THE
    TEST. It read: "Two of the three now split the same corpus the same way, which is the
    first time that has been true." Measured 2026-09-30 at the row level, the two decline
    SETS overlap on THREE rows out of nineteen -- 16 of the 73 are a decline to exactly one
    of them. Equal totals are the weakest available evidence of agreement, and concluding
    agreement from them is lessons #160 (a metric arithmetically correct and structurally
    blind) happening inside the test written to prevent that class of error. The sets, and
    the reason each family disagrees, are pinned in
    `tests/test_the_decline_classifiers_do_not_share_a_core.py`; this test still pins the
    counts, which is a different and weaker guarantee and should be read as one.

    The pack gate's 16 remains the outlier and CAVEAT-887 stays open on it. The five rows
    that moved are
    pack indexes 1, 4, 27, 37 and 51, and every one OPENS with that decline — checked, per
    CLAUDE.md's rule that any change to a marker list is verified against all 73 because an
    intermediate broader pattern moved two of them and was rejected for it (lessons #141).
    `"answer that from"` was tried and rejected: it also captures "I can answer that from the
    building's records: the mean is 22.9 C", which is an answer.
    """
    from orchestrator.services.publication_gate import is_decline as shared
    from scripts.grade_answers_rubric import is_decline as grader
    from scripts.regression_answerability import classify

    rows = _pack_rows()
    assert len(rows) == 73, len(rows)
    counts = {
        "publication_gate": sum(1 for r in rows if shared(r.get("answer") or "")),
        "grade_answers_rubric": sum(1 for r in rows if grader(r.get("answer") or "")),
        "regression_answerability": sum(
            1 for r in rows if classify(r.get("answer") or "") in ("declined", "refused")
        ),
    }
    assert counts == {
        # 6 before BUG-992; now equal to the grader's count, which is the improvement.
        "publication_gate": 11,
        "grade_answers_rubric": 11,
        "regression_answerability": 16,
    }, counts


def test_the_derivation_finds_the_leads_the_tracker_rows_name():
    """The audit script's AST derivation must still see the modules CAVEAT-952 names.

    A refactor that moves or renames a lead is fine; one that makes the derivation blind
    to it is not, because the audit would then report a clean sheet it has not earned.
    """
    from scripts.audit_decline_markers import derive_leads

    leads = derive_leads(REPO, ["orchestrator"])
    modules = {lead.module for lead in leads}
    for required in (
        "orchestrator/services/clarification.py",
        "orchestrator/services/fallback_wording.py",
        "orchestrator/agents/capability_agent.py",
    ):
        assert required in modules, f"{required} contributed no lead; modules={len(modules)}"
    assert len(leads) >= 40, f"only {len(leads)} leads derived; the rule may have broken"
