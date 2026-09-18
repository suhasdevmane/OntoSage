# -*- coding: utf-8 -*-
"""Tests for the rubric grader and its calibration.

The important ones are at the bottom: the grader's headline claim -- that it agrees with the
human labels better than the old heuristic does -- is asserted against the real 294 labelled
rows, so the claim cannot rot without a test going red.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "grade_answers_rubric", REPO / "scripts" / "grade_answers_rubric.py"
)
G = importlib.util.module_from_spec(_SPEC)
sys.modules["grade_answers_rubric"] = G
_SPEC.loader.exec_module(G)

ASOF = date(2026, 9, 17)
PHASE0 = REPO / "docs" / "phase0"
HAVE_CORPUS = (PHASE0 / "phase0_read.jsonl").exists() and (
    PHASE0 / "phase0_rerun_read.jsonl"
).exists()

pytestmark = pytest.mark.unit


def verdict(question: str, answer: str, asof=ASOF) -> str:
    return G.DeterministicJudge().grade(question, answer, asof=asof).verdict


def codes(question: str, answer: str, asof=ASOF):
    return {s.code for s in G.detect_signals(question, answer, asof=asof)}


# ─────────────────────────────────────────────────────────────────────────────────────────
# Text handling
# ─────────────────────────────────────────────────────────────────────────────────────────


def test_normalise_folds_typography_and_emphasis():
    assert "21 of the 24" in G.normalise("**21 of the 24**")
    assert G.normalise("non‑breaking") == "non-breaking"


def test_body_keeps_a_table_that_sits_under_a_horizontal_rule():
    answer = "The records show 21 of the 24 assets.\n\n---\n\n| Asset |\n|---|\n| AHU-00 |\n"
    assert "AHU-00" in G.body_of(answer)


def test_body_drops_the_sources_and_suggestion_furniture():
    answer = "Delta-T is 10.5 C.\n\n---\n*Sources: `Building Ontology`*"
    assert G.body_of(answer) == "Delta-T is 10.5 C."
    assert "Who owns" not in G.body_of("An answer.\n\n---\n**You might also ask:** Who owns these?")


def test_content_words_fold_hyphens_and_facilities_synonyms():
    assert "book" in G.content_words("room-booking entries")
    assert G.content_words("bins and skips") & G.content_words("waste collection point")


# ─────────────────────────────────────────────────────────────────────────────────────────
# Detectors: each one fires on its own defect and stays quiet on a clean answer
# ─────────────────────────────────────────────────────────────────────────────────────────

CLEAN_ANSWER = (
    "There are 3 open work orders: WO-008 electrical inspection on floor 3, "
    "WO-013 insulation resistance test on floor 3, and WO-015 condensate drain clearance "
    "in room 5.03. All three are recorded as open in the work order register."
)
CLEAN_DECLINE = (
    "The records do not contain any information about whole-life cost. They record cost "
    "line items with budget, actual and committed amounts for each procurement."
)


def test_a_clean_answer_is_good_and_raises_nothing():
    assert codes("How many open work orders are there?", CLEAN_ANSWER) == set()
    assert verdict("How many open work orders are there?", CLEAN_ANSWER) == G.GOOD_ANSWER


def test_a_clean_decline_is_a_good_decline_not_a_failure():
    q = "Which option has the lowest whole-life cost across purchase and running costs?"
    assert codes(q, CLEAN_DECLINE) == set()
    assert verdict(q, CLEAN_DECLINE) == G.GOOD_DECLINE


@pytest.mark.parametrize(
    "code,question,answer",
    [
        (
            "ADD_DATA_INSTRUCTION",
            "Where is the lift?",
            "I don't hold that. You can add it - upload a TTL naming the entity, and I will use it.",
        ),
        (
            "USER_ATTRIBUTION",
            "Are assets moved?",
            "The 32 approval records you provided do not contain any information about asset movement.",
        ),
        (
            "PROVENANCE_LEAK",
            "What is the CO2 level?",
            "The reading is 640 ppm in room 5.01. Environment: simulated = true, so treat with care.",
        ),
        (
            "LANE_JARGON",
            "Is the lighting on schedule?",
            "I understood the question but could not put an answer together for it. The ontology lane ran.",
        ),
        (
            "NON_ANSWER_TEMPLATE",
            "What is tomorrow's plan?",
            "No data was retrieved. 100 sensors were identified for this request but returned no rows.",
        ),
        (
            "FOOTER_MISFIRE",
            "What did submetering cost?",
            "The records do not price submetering.\n\nBoundary: not declared. Evidence time: unknown.",
        ),
        (
            "INTERNAL_TOKEN",
            "What does this building measure?",
            "I have nothing for that zone. What this building measures: air_quality, damper_position, water_flow.",
        ),
        (
            "FRAGMENT",
            "Where do I isolate the water supply on floor 2?",
            "Incoming main stop valve SV-1",
        ),
        (
            "DOCUMENT_CATCHALL",
            "Book me a hotel",
            "The documents do not answer this. I searched the Room Bookings Register; none contains the answer.",
        ),
        (
            "ONTOLOGY_NAMED",
            "Which FCUs are on floor 4?",
            "The ontology data you gave does not contain any information about fan coil units on floor 4.",
        ),
        (
            "PHRASE_NOT_A_PLACE",
            "Is today's noise a brief corridor-related peak?",
            "'brief corridor' does not exist in this building, so there is nothing to report about it.",
        ),
        (
            "DEICTIC_BOUND",
            "Why is it stuffy in this room?",
            "The CO2 Level Sensor installed-node 5.01 reads 700 ppm, so the room is within range.",
        ),
    ],
)
def test_each_detector_fires_on_its_own_defect(code, question, answer):
    assert code in codes(question, answer)
    assert verdict(question, answer) == G.WEIRD


def test_stale_future_date_needs_a_forward_claim_not_a_table_column():
    q = "When is the next collection for the special waste bins?"
    stale = "The next authorised collection is scheduled for 8 September 2026 for every bin."
    assert "STALE_FUTURE_DATE" in codes(q, stale)
    table = "| Asset | Last test | Next due |\n|---|---|---|\n| FSA-002 | 2026-06-16 | 2026-09-08 |"
    assert "STALE_FUTURE_DATE" not in codes(q, table)


def test_stale_future_date_is_not_checked_without_an_asof_date():
    stale = "The next authorised collection is scheduled for 8 September 2026 for every bin."
    assert "STALE_FUTURE_DATE" not in codes("When is the next collection?", stale, asof=None)


def test_breakdown_that_does_not_add_up_is_caught_and_one_that_does_is_not():
    bad = (
        "Summary of the exceptions.\n"
        "- Of those 5, only 3 have a clear justification type recorded:\n"
        "  - 1 override (REG-002)\n"
        "  - 1 specialist service (REG-006)\n"
        "  - 2 overrides (REG-007, REG-009)\n"
    )
    assert "BREAKDOWN_SUM" in codes("Which HVAC assets run beyond their window?", bad)
    good = (
        "They do record the booking status for each of the 16 bookings:\n"
        "- Confirmed: 11\n- Provisional: 3\n- Cancelled: 2\n"
    )
    assert "BREAKDOWN_SUM" not in codes("What share of bookings are ghost meetings?", good)


def test_a_headline_count_its_own_table_contradicts_is_caught():
    bad = (
        "The records show that 21 of the 24 assets have a documented isolation point.\n\n"
        "| Asset | Isolation point |\n|---|---|\n| AHU-00 | LI-00 |\n| AHU-01 | LI-01 |\n| AHU-02 | LI-02 |\n"
    )
    assert "TABLE_COUNT_MISMATCH" in codes("Which isolation details reduce leak consequence?", bad)


def test_repetition_ignores_tables_because_tables_repeat_legitimately():
    table = "| ID | Reason |\n|---|---|\n" + "| CP-00 | No evidenceReference |\n" * 8
    assert "REPETITION" not in codes("Which matters need a management representation?", table)
    prose = "32 approval records - 24 current, 1 due_review, 1 expired. " * 9
    assert "REPETITION" in codes("Which assets moved?", prose)


def test_open_domain_prose_needs_a_question_the_building_cannot_be_the_source_for():
    medical_q = "why does autism happen"
    prose = (
        "Current thinking points to a mix of inherited variation and environmental "
        "factors such as prenatal exposure to certain medications or infections. " * 3
    )
    assert "OPEN_DOMAIN_PROSE" in codes(medical_q, prose)
    # A question about the building's own plant is not open-domain, even with no record ids.
    plant = (
        "Boiler 1's heating circuit delta-T is 10.52 C and Boiler 2 is 10.35 C, a spread "
        "of 0.17 C, so the circuit is operating with a similar lift on each boiler and "
        "the balance between the two is within the usual working range for the plant. " * 2
    )
    assert "OPEN_DOMAIN_PROSE" not in codes("What's the delta-T across the heating circuit?", plant)


ADD_DATA_ANSWER = (
    "I don't have that specific information for the accessible entrance you asked about. "
    "You can add it - upload a TTL naming the entity and I will use it from then on."
)
GROUNDED_ANSWER = (
    "Route RTE-001 runs from the accessible drop-off to room 0.01 reception and is recorded "
    "step free, with the approval status open in the accessible route register. Route "
    "RTE-006 covers the same entrance but is marked restricted."
)


def test_disabled_signals_are_not_raised():
    raised = G.detect_signals("Where is the accessible entrance?", ADD_DATA_ANSWER)
    assert "ADD_DATA_INSTRUCTION" in {s.code for s in raised}
    kept = G.detect_signals(
        "Where is the accessible entrance?",
        ADD_DATA_ANSWER,
        disabled=frozenset({"ADD_DATA_INSTRUCTION"}),
    )
    assert "ADD_DATA_INSTRUCTION" not in {s.code for s in kept}


def test_dimensions_are_reported_for_every_rubric_row():
    res = G.DeterministicJudge().grade("How many work orders are open?", CLEAN_ANSWER, asof=ASOF)
    assert set(res.dimensions) == set(G.DIMENSION_NAMES)
    assert res.dimensions["honest_absence"] == G.NA  # it states no absence
    bad = G.DeterministicJudge().grade(
        "Where is the lift?", "You can add it - upload a TTL.", asof=ASOF
    )
    assert bad.dimensions["answers_question"] == G.FAIL
    assert bad.reason


# ─────────────────────────────────────────────────────────────────────────────────────────
# The LLM judge: structured output, validated, never guessed
# ─────────────────────────────────────────────────────────────────────────────────────────


def _valid_payload(verdict_=G.WEIRD):
    return {
        "verdict": verdict_,
        "dimensions": {n: G.PASS for n in G.DIMENSION_NAMES},
        "reason": "because",
    }


def test_llm_judge_accepts_a_schema_valid_object():
    res = G.LLMJudge.validate(_valid_payload())
    assert res is not None and res.verdict == G.WEIRD and res.judge == "llm"


@pytest.mark.parametrize(
    "payload",
    [
        "not an object",
        {"verdict": "GREAT", "dimensions": {n: G.PASS for n in G.DIMENSION_NAMES}, "reason": "x"},
        {"verdict": G.WEIRD, "reason": "x"},
        {"verdict": G.WEIRD, "dimensions": {"answers_question": G.PASS}, "reason": "x"},
        {"verdict": G.WEIRD, "dimensions": {n: "maybe" for n in G.DIMENSION_NAMES}, "reason": "x"},
    ],
)
def test_llm_judge_rejects_anything_the_schema_does_not_allow(payload):
    assert G.LLMJudge.validate(payload) is None


def test_llm_judge_reports_ungraded_rather_than_guessing(monkeypatch):
    judge = G.LLMJudge(base_url="http://127.0.0.1:1", model="none")
    monkeypatch.setattr(
        judge, "_post", lambda payload: {"message": {"content": "sorry, no JSON here"}}
    )
    res = judge.grade("Q", "A")
    assert res.verdict == G.UNGRADED
    assert res.confidence == "none"
    assert judge.failures == 1


def test_llm_judge_reports_ungraded_when_the_provider_is_unreachable(monkeypatch):
    judge = G.LLMJudge(base_url="http://127.0.0.1:1", model="none", timeout=0.2)

    def boom(payload):
        raise OSError("connection refused")

    monkeypatch.setattr(judge, "_post", boom)
    assert judge.grade("Q", "A").verdict == G.UNGRADED


def test_llm_judge_sends_the_schema_as_the_requested_format(monkeypatch):
    judge = G.LLMJudge()
    seen = {}

    def capture(payload):
        seen.update(payload)
        return {"message": {"content": json.dumps(_valid_payload(G.GOOD_ANSWER))}}

    monkeypatch.setattr(judge, "_post", capture)
    assert judge.grade("Q", "A").verdict == G.GOOD_ANSWER
    assert seen["format"] == G.JUDGE_SCHEMA
    assert seen["options"]["temperature"] == 0


def test_the_deterministic_judge_makes_no_network_call(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the deterministic judge must not open a connection")

    monkeypatch.setattr(G.urllib.request, "urlopen", forbidden)
    assert verdict("How many open work orders are there?", CLEAN_ANSWER) == G.GOOD_ANSWER


# ─────────────────────────────────────────────────────────────────────────────────────────
# Statistics
# ─────────────────────────────────────────────────────────────────────────────────────────


def test_kappa_is_one_for_perfect_agreement_and_zero_for_chance():
    labels = (G.GOOD_ANSWER, G.WEIRD)
    truth = [G.WEIRD] * 5 + [G.GOOD_ANSWER] * 5
    assert G.cohen_kappa(truth, list(truth), labels) == pytest.approx(1.0)
    # Both raters call 5 of 10 weird, but never the same five -> chance agreement.
    pred = [G.GOOD_ANSWER] * 5 + [G.WEIRD] * 5
    assert G.cohen_kappa(truth, pred, labels) == pytest.approx(-1.0)


def test_kappa_is_none_when_it_is_undefined():
    assert G.cohen_kappa([], [], VERDICTS := G.VERDICTS) is None
    assert G.cohen_kappa([G.WEIRD] * 4, [G.WEIRD] * 4, (G.WEIRD, "OK")) is None


def test_weird_precision_and_recall_count_the_right_cells():
    truth = [G.WEIRD, G.WEIRD, G.GOOD_ANSWER, G.GOOD_DECLINE]
    pred = [G.WEIRD, G.GOOD_ANSWER, G.WEIRD, G.GOOD_DECLINE]
    prf = G.weird_prf(truth, pred)
    assert (prf["tp"], prf["fp"], prf["fn"]) == (1, 1, 1)
    assert prf["precision"] == pytest.approx(0.5)
    assert prf["recall"] == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────────────────


def _run_file(tmp_path: Path, name: str, pairs) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps({"q": q, "answer": a, "status": "OK"}) for q, a in pairs) + "\n",
        encoding="utf-8",
    )
    return path


def test_gate_passes_when_the_weird_share_falls(tmp_path):
    q = "Where is the accessible entrance?"
    old = _run_file(tmp_path, "old.jsonl", [(q, ADD_DATA_ANSWER)])
    new = _run_file(tmp_path, "new.jsonl", [(q, GROUNDED_ANSWER)])
    judge = G.DeterministicJudge()
    ok, detail = G.gate(G.grade_run(new, judge, asof=ASOF), G.grade_run(old, judge, asof=ASOF))
    assert ok
    assert len(detail["improved"]) == 1 and not detail["regressed"]


def test_gate_fails_when_the_weird_share_rises(tmp_path):
    q = "Where is the accessible entrance?"
    old = _run_file(tmp_path, "old.jsonl", [(q, GROUNDED_ANSWER)])
    new = _run_file(tmp_path, "new.jsonl", [(q, ADD_DATA_ANSWER)])
    judge = G.DeterministicJudge()
    ok, detail = G.gate(G.grade_run(new, judge, asof=ASOF), G.grade_run(old, judge, asof=ASOF))
    assert not ok
    assert len(detail["regressed"]) == 1
    assert detail["delta"] > 0


def test_gate_exits_non_zero_through_the_cli(tmp_path):
    q = "Where is the accessible entrance?"
    old = _run_file(tmp_path, "old.jsonl", [(q, GROUNDED_ANSWER)])
    new = _run_file(tmp_path, "new.jsonl", [(q, ADD_DATA_ANSWER)])
    rc = G.main(
        [
            "--gate",
            str(new),
            "--baseline",
            str(old),
            "--asof",
            "2026-09-17",
            "--bank",
            "does-not-exist",
        ]
    )
    assert rc == 1


def test_the_gate_never_asks_the_live_system(monkeypatch, tmp_path):
    def forbidden(*a, **k):
        raise AssertionError("the gate must be offline")

    monkeypatch.setattr(G.urllib.request, "urlopen", forbidden)
    run = _run_file(
        tmp_path, "run.jsonl", [("Q", "An answer about room 1.04 from the event register.")]
    )
    assert (
        G.main(
            ["--gate", str(run), "--baseline", str(run), "--asof", "2026-09-17", "--bank", "nope"]
        )
        == 0
    )


# ─────────────────────────────────────────────────────────────────────────────────────────
# The deliverable: agreement with the human labels, measured on the real corpus
# ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not HAVE_CORPUS, reason="the phase0 labelled corpus is not present")
def test_the_labelled_corpus_is_the_size_the_report_claims():
    splits = G.default_splits(ASOF)
    assert [s.name for s in splits] == ["baseline", "rerun"]
    assert sum(len(s.rows) for s in splits) == 294
    for split in splits:
        assert all(r["human"] in G.VERDICTS for r in split.rows)


@pytest.mark.skipif(not HAVE_CORPUS, reason="the phase0 labelled corpus is not present")
def test_the_deterministic_judge_beats_the_old_heuristic_on_the_weird_class():
    result = G.calibrate(G.default_splits(ASOF), {"deterministic": G.DeterministicJudge()})
    old = result["stats"]["old"]["overall"]
    new = result["stats"]["deterministic"]["overall"]
    assert new["kappa_weird"] > old["kappa_weird"]
    assert new["weird"]["recall"] > old["weird"]["recall"]
    # Precision is the thing a louder grader gives away; it must stay high.
    assert new["weird"]["precision"] >= 0.90
    # Recorded so that a drop is a test failure rather than a quiet regression.
    assert new["kappa_weird"] >= 0.40
    assert new["weird"]["recall"] >= 0.60


def test_common_scope_only_counts_rows_every_grader_scored():
    """Ranking a grader measured on 294 rows against one measured on 20 is not a comparison."""
    per_row = [
        {"split": "s", "row": 0, "human": G.WEIRD, "old": G.GOOD_ANSWER, "llm": G.WEIRD},
        {"split": "s", "row": 1, "human": G.WEIRD, "old": G.WEIRD, "llm": G.WEIRD},
        {"split": "s", "row": 2, "human": G.GOOD_ANSWER, "old": G.GOOD_ANSWER},
        {"split": "s", "row": 3, "human": G.WEIRD, "old": G.WEIRD, "llm": G.UNGRADED},
    ]
    result = G.summarise(per_row, ["old", "llm"], ["s"])
    assert result["common_n"] == 2  # row 2 has no llm verdict, row 3 is UNGRADED
    assert result["stats"]["old"]["common"]["n"] == 2
    assert result["stats"]["old"]["overall"]["n"] == 4
    assert result["stats"]["llm"]["overall"]["ungraded"] == 1


def test_recompute_re_summarises_saved_rows_without_grading_anything(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("--recompute must not grade anything")

    monkeypatch.setattr(G.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(G.DeterministicJudge, "grade", forbidden)
    rows = tmp_path / "rows.jsonl"
    rows.write_text(
        "\n".join(
            json.dumps(
                {"split": "s", "row": i, "human": G.WEIRD, "old": G.WEIRD, "deterministic": G.WEIRD}
            )
            for i in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    assert G.main(["--recompute", str(rows), "--asof", "2026-09-17"]) == 0


@pytest.mark.skipif(not HAVE_CORPUS, reason="the phase0 labelled corpus is not present")
def test_no_building_literal_reaches_the_grader():
    source = (REPO / "scripts" / "grade_answers_rubric.py").read_text(encoding="utf-8").lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "cardiff", "senghennydd"):
        assert literal not in source
