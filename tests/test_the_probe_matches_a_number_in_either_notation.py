"""CAVEAT-600: the probe judged notation rather than the answer.

"Which stakeholder groups does DEP-13 serve?" answered "3 stakeholder groups" and named
SH-36/37/38 — every one correct — and the case failed for missing the word "three". The same
weakness passes a case for the wrong reason: a marker "9" was satisfied by "4.9" in a table.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent


def _probe():
    spec = importlib.util.spec_from_file_location("_probe", REPO / "scripts" / "regression_probe.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "answer,marker",
    [
        ("3 stakeholder groups: SH-36, SH-37, SH-38", "three"),
        ("three groups are served", "3"),
        ("there are 9 floor pairs", "nine"),
        ("nine floor pairs", "9"),
    ],
)
def test_a_number_matches_in_either_notation(answer, marker):
    assert _probe()._matches(answer, marker)


@pytest.mark.parametrize(
    "answer,marker",
    [
        ("23 teaching sessions", "3"),      # not inside a larger number
        ("the 3rd floor", "3"),             # not inside a word
        ("4.9 minutes step-free", "9"),     # not a decimal's tail — the CAVEAT-600 false pass
        ("no sessions at all", "3"),
    ],
)
def test_a_number_does_not_match_a_coincidence(answer, marker):
    assert not _probe()._matches(answer, marker)


def test_a_marker_with_words_keeps_its_exact_wording():
    p = _probe()
    assert p._matches("there are 3 open work orders", "3 open work orders")
    assert not p._matches("three open work orders", "3 open work orders")


def test_the_separator_tolerance_still_holds():
    assert _probe()._matches("2,728 sensors carry a cadence", "2728")
