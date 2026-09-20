# -*- coding: utf-8 -*-
"""The regression probe must not fail a right answer over typography (2026-09-19).

"Who is my contact for a fault with the network, and what is their response target?" was marked
FAIL for missing "8" while answering "Response target: **8.0 hours**" from a register recording
respondsWithinHours = 8. The lookahead that stops the marker "3" matching inside a room number
"3.15" also stopped "8" matching "8.0". A whole number written with a zero decimal is the same
fact; a room number is not.

A probe that fails on which notation the model chose trains whoever runs it to ignore it, which is
worse than not having it — and the same failure has now cost two investigations (CAVEAT-834 was the
date-format one).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import regression_probe as rp  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "answer, marker",
    [
        ("- **Response target:** 8.0 hours", "8"),  # the failure this test exists for
        ("206.0 kWh over the window", "206"),
        ("3 open work orders", "3"),
        ("2,728 readings", "2728"),
        ("three stakeholder groups", "3"),  # the word form (CAVEAT-600)
        ("24.00 hours", "24"),
    ],
)
def test_the_same_fact_matches_however_it_is_written(answer, marker):
    assert rp._matches(answer, marker) is True, (marker, answer)


@pytest.mark.parametrize(
    "answer, marker",
    [
        ("the nearest is Room 3.15", "3"),  # a room number is NOT the number three
        ("23 sensors reported", "3"),  # nor is a digit inside a longer number
        ("Room 5.01 — Research Laboratory", "5"),
        ("8.5 hours", "8"),  # a real fractional value is a different figure
    ],
)
def test_a_different_figure_still_fails(answer, marker):
    assert rp._matches(answer, marker) is False, (marker, answer)
