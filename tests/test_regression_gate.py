# -*- coding: utf-8 -*-
"""The regression gate that every later V6 task is measured against (V6-T54).

The tracker's verify step is explicit: *"capture the baseline, then break something on purpose
and confirm the gate reports it as a regression rather than a tightening."* That is what the
middle section does -- deliberate damage of each kind, asserted to be caught.

The gate's own failure modes are what the rest guards:

* **failing open** -- calling a silent degradation a tightening. Guarded by requiring a named
  gate before any worsening is excused;
* **failing closed** -- calling a live building's moving numbers a change. Guarded by the
  skeleton comparison, without which the gate reports ~1,500 findings on an unmodified system
  and gets switched off within a day;
* **shrinking silently** -- a run that asks fewer questions scoring clean because the missing
  ones were never compared. Guarded by treating a dropped question as blocking.
"""

import csv
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "baseline_regression_gate.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("baseline_regression_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIELDS = [
    "qid",
    "question",
    "intent",
    "answer",
    "answer_sha",
    "answer_status",
    "gates",
    "status",
]


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            base = {k: "" for k in FIELDS}
            base.update({"status": "OK"})
            base.update(r)
            base.setdefault("answer_sha", str(abs(hash(base["answer"]))))
            base["answer_sha"] = str(abs(hash(base["answer"])))
            w.writerow(base)
    return path


ANSWER = "The CO2 in room 2.15 is 780 ppm, measured at 14:02."
DECLINE = "I don't have that specific information on record for room 2.15."


@pytest.fixture
def pair(tmp_path):
    """A baseline and a helper that writes a mutated 'current' beside it."""
    b = write(
        tmp_path / "baseline.csv",
        [
            {"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER},
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ],
    )

    def current(rows):
        return write(tmp_path / "current.csv", rows)

    return b, current


# -- an unchanged system must come back clean --------------------------------


def test_an_identical_run_passes_with_nothing_flagged(gate, pair):
    b, current = pair
    c = current(
        [
            {"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER},
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    out = gate.compare(b, c)
    assert out["passed"]
    assert out["counts"][gate.UNCHANGED] == 2
    assert out["identity_rate"] == pytest.approx(1.0)


def test_a_live_building_moving_its_numbers_is_not_a_change(gate, pair):
    """Without this the gate reports ~1,500 findings on an unmodified system and is ignored."""
    b, current = pair
    moved = ANSWER.replace("780", "812").replace("14:02", "15:47")
    c = current(
        [
            {"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": moved},
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    out = gate.compare(b, c)
    assert out["passed"]
    assert out["counts"][gate.LIVE_DRIFT] == 1


# -- deliberate damage must be caught (the tracker's verify step) -------------


def test_an_answer_that_became_a_decline_with_no_gate_is_a_regression(gate, pair):
    """The core rule. Something made it worse and nothing owns the change."""
    b, current = pair
    c = current(
        [
            {"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": DECLINE},
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    out = gate.compare(b, c)
    assert not out["passed"]
    assert out["counts"][gate.REGRESSION] == 1
    assert "NO gate" in out["blocking"][0]["reason"]


def test_the_same_change_WITH_a_gate_is_a_tightening_not_a_regression(gate, pair):
    """The distinction the whole design rests on: attributable versus silent."""
    b, current = pair
    c = current(
        [
            {
                "qid": "Q1",
                "question": "co2 in 2.15",
                "intent": "sensor_data",
                "answer": DECLINE,
                "gates": "freshness",
            },
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    out = gate.compare(b, c)
    assert out["passed"]
    assert out["counts"][gate.TIGHTENED] == 1


def test_the_tightening_names_the_gate_responsible(gate, pair):
    b, current = pair
    c = current(
        [
            {
                "qid": "Q1",
                "question": "co2 in 2.15",
                "intent": "sensor_data",
                "answer": DECLINE,
                "gates": "spatial_adequacy",
            },
        ]
    )
    out = gate.compare(b, c)
    row = [r for r in out["results"] if r["qid"] == "Q1"][0]
    assert "spatial_adequacy" in row["reason"]


def test_an_answer_going_empty_is_a_regression(gate, pair):
    b, current = pair
    c = current([{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ""}])
    out = gate.compare(b, c)
    assert not out["passed"]


def test_a_question_that_silently_changed_lane_is_reported(gate, pair):
    """Invisible in the prose, and one of the more informative things that can go wrong."""
    b, current = pair
    c = current(
        [
            {
                "qid": "Q1",
                "question": "co2 in 2.15",
                "intent": "analytics",
                "answer": ANSWER + " Fine.",
            }
        ]
    )
    out = gate.compare(b, c)
    row = [r for r in out["results"] if r["qid"] == "Q1"][0]
    assert row["verdict"] == gate.ROUTE_CHANGED
    assert "sensor_data" in row["reason"] and "analytics" in row["reason"]


def test_a_shrinking_run_cannot_score_clean(gate, pair):
    """A question the baseline answered and this run never asked is a hole, not a pass."""
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER}]
    )
    out = gate.compare(b, c)
    assert not out["passed"]
    assert out["counts"][gate.DROPPED] == 1


# -- the fabrication direction ------------------------------------------------


def test_a_decline_that_became_an_answer_is_surfaced_for_review(gate, pair):
    """Looks like progress. Also exactly how BUG-189 and BUG-218 arrived.

    Not blocking -- it often IS progress -- but never counted as a win without someone
    checking the evidence behind it.
    """
    b, current = pair
    c = current(
        [
            {"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER},
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": "Alice and Bob were in room 2.15 at 14:00.",
            },
        ]
    )
    out = gate.compare(b, c)
    assert out["counts"][gate.LOOSENED] == 1
    assert out["passed"]  # reported, not blocked
    assert "Declines that became answers" in gate.render(out, b, c)


# -- quarantine discipline ----------------------------------------------------


def test_quarantined_rows_are_excluded_from_both_sides(gate, tmp_path):
    """Comparing against an outage marks every later healthy answer as a change.

    That is BUG-176 and BUG-177 restated, and it would make the gate's own output the next
    artefact this project has to retract.
    """
    b = write(
        tmp_path / "b.csv",
        [
            {"qid": "Q1", "question": "q", "answer": "", "status": "TIMEOUT"},
            {"qid": "Q2", "question": "q2", "intent": "sensor_data", "answer": ANSWER},
        ],
    )
    c = write(
        tmp_path / "c.csv",
        [
            {"qid": "Q1", "question": "q", "intent": "sensor_data", "answer": ANSWER},
            {"qid": "Q2", "question": "q2", "intent": "sensor_data", "answer": ANSWER},
        ],
    )
    out = gate.compare(b, c)
    assert out["comparable"] == 1
    assert out["passed"]


def test_a_degraded_current_row_is_not_scored_as_a_regression(gate, pair):
    """An LLM outage during the test run is not a code change."""
    b, current = pair
    c = current(
        [
            {
                "qid": "Q1",
                "question": "co2 in 2.15",
                "intent": "",
                "answer": "",
                "status": "LLM-DEGRADED:empty",
            },
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    out = gate.compare(b, c)
    assert out["counts"][gate.REGRESSION] == 0
    assert out["counts"][gate.DROPPED] == 1  # reported as a hole instead


# -- standing classification --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I don't have that specific information on record.",
        "That is not assessable: the newest reading is three days old.",
        "There is no information on record for that room.",
    ],
)
def test_the_system_s_own_refusals_are_recognised_as_declines(gate, text):
    assert gate.standing(text) == gate.DECLINED


def test_a_substantive_answer_is_recognised(gate):
    assert gate.standing(ANSWER) == gate.ANSWERED


def test_an_empty_answer_is_neither(gate):
    assert gate.standing("") == gate.EMPTY
    assert gate.standing("   ") == gate.EMPTY


# -- the report ---------------------------------------------------------------


def test_the_report_states_that_identity_is_not_the_pass_condition(gate, pair):
    """Anyone reading a low identity rate must not conclude the system broke."""
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER}]
    )
    text = gate.render(gate.compare(b, c), b, c)
    assert "reported, not gated" in text
    assert "temperature 0" in text


def test_the_report_groups_tightenings_by_gate(gate, pair):
    b, current = pair
    c = current(
        [
            {
                "qid": "Q1",
                "question": "co2 in 2.15",
                "intent": "sensor_data",
                "answer": DECLINE,
                "gates": "freshness",
            },
            {
                "qid": "Q2",
                "question": "who was in 2.15",
                "intent": "privacy_refusal",
                "answer": DECLINE,
            },
        ]
    )
    text = gate.render(gate.compare(b, c), b, c)
    assert "by the gate responsible" in text
    assert "freshness" in text


def test_comparing_a_capture_with_itself_is_refused(gate, pair, capsys):
    """It would pass trivially and prove nothing, which is worse than failing."""
    b, _ = pair
    rc = gate.main(["--current", str(b), "--baseline", str(b)])
    assert rc == 2
    assert "REFUSING" in capsys.readouterr().out


def test_the_exit_code_gates_without_anyone_reading_the_output(gate, pair, tmp_path):
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": DECLINE}]
    )
    rc = gate.main(["--current", str(c), "--baseline", str(b), "--md", str(tmp_path / "r.md")])
    assert rc == 1


# -- a deliberately partial run --------------------------------------------------


def test_a_declared_partial_run_does_not_fail_on_absent_questions(gate, pair):
    """Re-running 1,580 questions is not always affordable.

    But absence cannot be INFERRED as deliberate: a capture records only what it asked, so a
    skipped question and one that died before writing a row look identical in the file. The
    operator has to declare it, which keeps the default honest.
    """
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER}]
    )
    assert not gate.compare(b, c)["passed"]  # undeclared: still a hole
    partial = gate.compare(b, c, partial=True)
    assert partial["passed"]
    assert partial["counts"].get(gate.DROPPED, 0) == 0


def test_a_partial_run_still_catches_a_real_regression(gate, pair):
    """Declaring a subset must not become a way to pass while something broke inside it."""
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": DECLINE}]
    )
    out = gate.compare(b, c, partial=True)
    assert not out["passed"]
    assert out["counts"][gate.REGRESSION] == 1


def test_the_report_says_the_run_was_partial(gate, pair):
    """A pass on a subset must not read as a pass on everything."""
    b, current = pair
    c = current(
        [{"qid": "Q1", "question": "co2 in 2.15", "intent": "sensor_data", "answer": ANSWER}]
    )
    text = gate.render(gate.compare(b, c, partial=True), b, c)
    assert "Partial run" in text
    assert "subset only" in text
