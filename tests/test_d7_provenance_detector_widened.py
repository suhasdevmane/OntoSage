# -*- coding: utf-8 -*-
"""D7 (QA-trial plan, 2026-10-02): five phrasings a live probe found reaching NEITHER
answer_provenance's detector nor session_recall's were added to `PROVENANCE_RE` only.
"What is the evidence behind your answer?" and "how did you arrive at that?" are
deliberately NOT touched here -- session_recall already owns them (BUG-1397,
VERIFIED_LIVE), and widening PROVENANCE_RE to also match them would re-open that fix
rather than close a gap.

Measured before shipping: exactly 1 move over the 4,060-question bank (a correct one),
0 of the 73 stored pack answers' classification affected (separate from the gate marker
in A6, which is a different module).
"""
import pytest

from orchestrator.services.answer_provenance import is_provenance_question
from orchestrator.services.session_recall import is_recall_question

pytestmark = pytest.mark.unit


class TestTheFiveNewPhrasingsNowReachProvenance:
    @pytest.mark.parametrize(
        "q",
        [
            "which one did you check?",
            "which data sources did you use?",
            "which records did you use?",
            "which sensors did you use?",
            "what data did you use?",
            "what sources did you use?",
            "Which sensors did you use to answer my last question?",
        ],
    )
    def test_matches(self, q):
        assert is_provenance_question(q)


class TestBugFourteenNinetySevensTerritoryIsUntouched:
    """session_recall's own fix (BUG-1397) deliberately gave 'what is the evidence behind
    your answer?' to session_recall; PROVENANCE_RE never matched it and D7 does not add it.
    'how did you arrive at that?' is a PRE-EXISTING dual match (both detectors already
    claimed it before D7, and the routing contract's 'last rule wins' gives it to
    session_recall at index 64 of 65) -- D7 widens neither side of that one."""

    def test_the_evidence_behind_your_answer_is_not_added_to_provenance_re(self):
        assert not is_provenance_question("what is the evidence behind your answer?")

    def test_session_recall_still_claims_both(self):
        assert is_recall_question("what is the evidence behind your answer?")
        assert is_recall_question("how did you arrive at that?")


class TestAnOrdinaryQuestionIsNotTaken:
    @pytest.mark.parametrize(
        "q",
        [
            "which rooms have a projector?",
            "what data does the building record for room 2.01?",
            "which sensors are on floor 3?",
        ],
    )
    def test_does_not_match(self, q):
        assert not is_provenance_question(q)
