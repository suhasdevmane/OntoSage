# -*- coding: utf-8 -*-
"""A6 (QA-trial plan, 2026-10-02): the regression gate's classifier recognises
session_recall's own decline for 'no prior turn in this conversation' -- gate case #37,
'What is the evidence behind your answer about the coolest room?', had been scored
`answered` against that exact wording for as long as the gate has asked it fresh-chat, so
51/51 could not detect either a success or a regression in Wave D's own subject matter.

Verified before shipping: zero of the 73 stored supervisor-evidence-pack answers were
reclassified by adding the marker (57 answered / 2 refused / 14 declined, unchanged).
"""
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _ra():
    spec = importlib.util.spec_from_file_location(
        "regression_answerability", REPO / "scripts" / "regression_answerability.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTheNoPriorTurnDeclineIsRecognised:
    def test_the_exact_live_wording_is_declined_not_answered(self):
        ra = _ra()
        answer = (
            "**Nothing has been asked in this conversation yet**, so there is nothing for "
            "me to recall. This is a record of what you have asked me in this session — it "
            "is not the building's records, and it does not reach back to other sessions."
        )
        assert ra.classify(answer) == "declined"

    def test_gate_case_37_s_live_shape_is_declined(self):
        ra = _ra()
        assert (
            ra.classify(
                "**Nothing has been asked in this conversation yet**, so there is nothing "
                "for me to recall."
            )
            == "declined"
        )


class TestTheAirPressureDeclineWordingDrift:
    """Found running the gate 2026-10-03, unrelated to that day's product changes -- the
    decline text alone, with no evidence panel appended, was already misclassified before
    this marker was added. The live wording for 'what is the air pressure in room 2.01
    right now?' had drifted to 'There is no recorded air-pressure sensor for Room 2.01.'
    sometime after the older marker ('there is no air-pressure sensor data') was written."""

    def test_the_drifted_wording_is_recognised(self):
        ra = _ra()
        assert ra.classify("There is no recorded air‑pressure sensor for Room 2.01.") == "declined"

    def test_the_older_wording_still_works_too(self):
        ra = _ra()
        assert ra.classify("there is no air-pressure sensor data") == "declined"


class TestNoStoredPackAnswerIsReclassified:
    def test_zero_of_the_73_pack_answers_move(self):
        ra = _ra()
        path = REPO / "docs" / "supervisor_evidence_pack" / "answers.jsonl"
        if not path.exists():
            pytest.skip("evidence pack not present on this tree")
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        counts = {}
        for r in rows:
            k = ra.classify(r.get("answer", ""))
            counts[k] = counts.get(k, 0) + 1
        assert counts == {"answered": 57, "refused": 2, "declined": 14}
