# -*- coding: utf-8 -*-
"""A probe expectation that moves with the clock is a scheduled false alarm (TODO-484).

"How many sensors are overdue for calibration?" was pinned at 201 — itself a re-baseline
from 194 — and failed on 2026-09-08 because the true answer had become 206.
`ontosage:calibrationDueOn` dates pass as real time advances, so five more sensors fell
overdue and the system reported them correctly. Nothing was broken except the expectation,
and it chose to break the morning before a planned test.

THE AUDIT, MEASURED RATHER THAN REASONED
----------------------------------------
Ten of the fifty cases expect a bare number. Each was checked against the graph for
whether its value depends on the current time:

    24, 8        SLA hours on a department record            stored literal
    3.1, 2.4     design duty of an air handling unit         stored literal
    4            refuge points with working comms            EvacuationProvision records
    3            permits open                                `recordStatus "open"`, NOT a date
    23           teaching sessions in Room 1.06              timetable records
    60           CO2 reporting cadence                       stored literal
    280          CO2 sensor count                            graph count
    9.99         a room that does not exist (honesty case)   not a count at all
    26           lab recovery minutes                        `ontosage:recoveryMinutes 26.0`

`recoveryMinutes` looked like the dangerous one — "how long to recover after a full class"
reads as something computed from live readings, and the data publisher adds a row every 30
seconds. It is a stored value. So is the permit count: "open" is a status literal, not a
date comparison.

The calibration case was the ONLY expectation compared against `NOW()`, and it is now
computed from the graph at probe time via `expect_sparql`.

WHAT THIS TEST DOES
-------------------
Stops the next one being written. A question asking what is overdue, due, expired or
current cannot have its answer frozen in a file — the answer is a function of when you
ask. Such a case must use `expect_sparql`, which recomputes it, or `expect_any` /
`forbid`, which do not assert a moving figure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CASES = Path("scripts/regression_cases.json")

#: Words that make an answer a function of WHEN it is asked.
#:
#: Deliberately narrow. "open" is not here — a permit's `recordStatus` is a stored literal,
#: and treating every status word as time-relative would flag cases that cannot decay,
#: which trains whoever runs this to ignore it.
_TIME_RELATIVE = (
    "overdue",
    "due",
    "expired",
    "expiring",
    "out of date",
    "so far this",
    "remaining",
    "still outstanding",
    "past its",
    "behind schedule",
)

_BARE_NUMBER = re.compile(r"^[0-9][0-9,]*(?:\.[0-9]+)?$")


def _cases():
    return json.loads(CASES.read_text(encoding="utf-8"))


def test_no_time_relative_question_freezes_its_answer():
    offenders = []
    for c in _cases():
        q = (c.get("question") or "").lower()
        if not any(w in q for w in _TIME_RELATIVE):
            continue
        frozen = [m for m in c.get("expect", []) or [] if _BARE_NUMBER.match(str(m).strip())]
        if frozen and not c.get("expect_sparql"):
            offenders.append(f"{c.get('question')!r} expects {frozen}")

    assert not offenders, (
        "these ask what is overdue/due/expired — the answer is a function of WHEN you ask, "
        "so a number written down here will fail on a day nobody chose. Use "
        "`expect_sparql` so the expectation is recomputed from the graph:\n  "
        + "\n  ".join(offenders)
    )


def test_the_calibration_case_computes_its_own_expectation():
    """The case that taught us this must not quietly revert to a literal."""
    hits = [c for c in _cases() if "overdue for calibration" in (c.get("question") or "").lower()]
    assert hits, "the overdue-calibration case is gone"
    for c in hits:
        assert c.get("expect_sparql"), "it is pinned to a number again"
        assert not c.get("expect"), "a frozen marker is back alongside the computed one"


def test_every_expect_sparql_is_a_select_returning_one_value():
    """A query returning rows-of-many would inject a nonsense marker."""
    for c in _cases():
        for q in c.get("expect_sparql", []) or []:
            low = q.lower()
            assert "select" in low, f"not a SELECT: {q[:60]}"
            assert "count(" in low or "limit" in low, (
                "an expectation query must reduce to a single value — either aggregate it "
                f"or LIMIT it: {q[:80]}"
            )


def test_a_failed_expectation_query_fails_the_case():
    """A check that could not run must never be reported as green."""
    src = Path("scripts/regression_probe.py").read_text(encoding="utf-8")
    assert "expectation not evaluated" in src, (
        "a graph query that fails no longer produces a failing marker, so the case would "
        "silently pass without being checked"
    )
