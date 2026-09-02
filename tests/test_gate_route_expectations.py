# -*- coding: utf-8 -*-
"""The regression gate can attribute a LANE change, not just observe one (CAVEAT-379).

The gate could already attribute a *tightening*, because a tightening names the gate that
fired. A lane change had no equivalent: every move landed in one bucket and nothing blocked,
so a question moving into the register lane (the intended V7 behaviour) and a question
falling out of it looked identical in the report.

These tests pin the asymmetry that makes the addition safe to rely on:

* into a declared lane  -> attributable, does not block
* out of a declared lane -> BLOCKS
* nothing declared      -> exactly the old behaviour

That third case is the important one. It is what guarantees this change cannot manufacture
a PASS, which is the direction this project's measurement apparatus has failed in before.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_GATE = Path(__file__).resolve().parent.parent / "scripts" / "baseline_regression_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("baseline_regression_gate", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


gate = _load()


def _row(answer="Twelve permits are current.", intent="register", question="", gates=""):
    return {
        "answer": answer,
        "answer_sha": "",
        "intent": intent,
        "question": question,
        "gates": gates,
        "status": "OK",
    }


# --------------------------------------------------------------------------------------
# The expectations file must actually load and actually match. An entry that never fires is
# worse than no entry: it looks like coverage and provides none.
# --------------------------------------------------------------------------------------


def test_expectations_file_loads_with_entries():
    entries = gate._expectations()
    assert entries, "config/routing_expectations.yaml produced no usable entries"
    assert all(e["lanes"] for e in entries)


@pytest.mark.parametrize(
    "question, lane",
    [
        ("Which contracts expire in the next six months?", "register"),
        ("Are all the roof access permits still valid?", "register"),
        ("What warranties are still running on the plant?", "register"),
        ("Show me the risk assessments for the labs", "register"),
        ("Where is the nearest toilet?", "floor_plan"),
        ("Where's the closest fire exit?", "spatial_query"),
        ("How do you know that?", "capability"),
    ],
)
def test_declared_questions_match_their_lane(question, lane):
    """Each shape the file claims to cover must really resolve to the lane it names."""
    lanes, rule = gate.expected_lanes(question)
    assert lanes, f"no expectation matched {question!r}"
    assert lane in lanes, f"{question!r} -> {lanes} (rule {rule}), expected {lane!r} among them"


def test_yaml_line_folding_does_not_break_the_patterns():
    """A folded YAML scalar inserts a space at each fold; unstripped, alternations die.

    This is not hypothetical — the patterns in the file are folded across several lines, and
    a literal space inside `(a|b\n|c)` makes every branch after the fold unmatchable. The
    entry would still load and still look active.
    """
    lanes, _ = gate.expected_lanes("Are the competency records up to date?")
    assert "register" in lanes, "a term after a line fold failed to match — folding not stripped"


# --------------------------------------------------------------------------------------
# The asymmetry.
# --------------------------------------------------------------------------------------


def test_moving_into_a_declared_lane_is_attributable_and_does_not_block():
    q = "Which contracts expire in the next six months?"
    verdict, reason = gate.classify(
        _row(intent="capability", question=q), _row(intent="register", question=q)
    )
    assert verdict == gate.ROUTE_INTENDED
    assert "declared by" in reason
    assert verdict not in gate.BLOCKING


def test_moving_out_of_a_declared_lane_blocks():
    q = "Which contracts expire in the next six months?"
    verdict, reason = gate.classify(
        _row(intent="register", question=q), _row(intent="capability", question=q)
    )
    assert verdict == gate.ROUTE_REGRESSION
    assert verdict in gate.BLOCKING, "a lane abandoning the questions it owns must fail the gate"
    assert "left the lane declared for it" in reason


def test_wayfinding_falling_into_the_register_blocks():
    """The exact shape of BUG-372/374, which reached production three separate times."""
    q = "Where is the nearest toilet?"
    verdict, _ = gate.classify(
        _row(intent="floor_plan", question=q), _row(intent="register", question=q)
    )
    assert verdict == gate.ROUTE_REGRESSION


def test_move_between_two_acceptable_lanes_does_not_block():
    """floor_plan <-> spatial_query are both right for wayfinding; neither is a regression."""
    q = "Where is the nearest toilet?"
    verdict, _ = gate.classify(
        _row(intent="floor_plan", question=q), _row(intent="spatial_query", question=q)
    )
    assert verdict not in gate.BLOCKING


def test_undeclared_route_change_keeps_the_old_non_blocking_verdict():
    """The safety property: no expectation, no change in behaviour."""
    q = "What is the CO2 level in the seminar room?"
    verdict, _ = gate.classify(
        _row(intent="sensor_data", question=q), _row(intent="analytics", question=q)
    )
    assert verdict == gate.ROUTE_CHANGED
    assert verdict not in gate.BLOCKING


# --------------------------------------------------------------------------------------
# The property that lets me rely on this on the very run it was written for.
# --------------------------------------------------------------------------------------


def test_expectations_can_only_add_blocking_never_remove_it(monkeypatch):
    """With the file emptied, nothing that blocked before stops blocking.

    Stated as a property rather than a case list: for a spread of transitions, the verdict
    with expectations loaded must block whenever the verdict without them blocked.
    """
    cases = [
        ("Which contracts expire soon?", "register", "capability", "Ten contracts.", ""),
        ("Where is the nearest toilet?", "floor_plan", "register", "Room 1.2.", ""),
        ("What is the CO2 in the lab?", "sensor_data", "analytics", "612 ppm.", ""),
        ("Which permits are current?", "capability", "register", "Fifteen permits.", ""),
        ("What is the CO2 in the lab?", "sensor_data", "sensor_data", "I cannot answer", "gate_x"),
    ]

    gate._expectations.cache_clear()
    loaded = list(gate._expectations())
    assert loaded, "no expectations loaded — the comparison below would be vacuous"

    def verdicts(entries):
        # Swap the loaded list, not the cached function: replacing `_expectations` with a
        # plain lambda leaves no `.cache_clear`, and the first draft of this test crashed on
        # exactly that.
        monkeypatch.setattr(gate, "_expectations", lambda: entries)
        return [
            gate.classify(
                _row(answer="Some answer.", intent=bi, question=q),
                _row(answer=ans, intent=ci, question=q, gates=g),
            )[0]
            for q, bi, ci, ans, g in cases
        ]

    without, with_file = verdicts([]), verdicts(loaded)

    assert any(
        a != b for a, b in zip(without, with_file)
    ), "expectations changed nothing at all — the property below would pass vacuously"

    for (q, *_), before, after in zip(cases, without, with_file):
        if before in gate.BLOCKING:
            assert after in gate.BLOCKING, (
                f"expectations turned a blocking {before!r} into a non-blocking {after!r} "
                f"for {q!r} — the file must only ever make the gate stricter"
            )


def test_missing_expectations_file_is_not_an_error(monkeypatch, tmp_path):
    """The gate predates this file and must still run where it is absent."""
    gate._expectations.cache_clear()
    monkeypatch.setattr(gate, "_EXPECTATIONS_PATH", tmp_path / "nope.yaml")
    assert gate._expectations() == []
    gate._expectations.cache_clear()
