# -*- coding: utf-8 -*-
"""BUG-950 — a decline's "nearest things I can answer" must not be the alphabetical head.

Measured on the held-out tail M against the 2026-09-29 build:

    "why is pl 2.5 increasing"
    -> "I couldn't answer that about **PM2.5** from Abacws Building's records.
        The nearest things I can answer are the Interval record, Timetabled session and Access
        event records and the readings of air quality, carbon monoxide, co2 and damper
        position."

Read those four measurands: they are the first four modalities ALPHABETICALLY. Nothing in the
question overlapped anything, every score tied, and `nearest_holdings` breaks ties on the
building's own order. **This building holds 210 PM2.5 sensors** — so the one modality that was
the answer was the only one the list could not reach, and the decline reads as though PM2.5
were unavailable.

The resolver had already done its job: the same sentence prints **PM2.5** in bold. Two things
kept that from reaching the ranking.

1.  `_close("pm2.5", "pm25")` was False. Neither is equal to the other and neither prefixes the
    other, so punctuation alone made a measurand unrecognisable as itself.
2.  `nearest_holdings` was only ever given the question's raw words. "why is pl 2.5 increasing"
    carries the content terms {'2.5', 'increas'}, which match nothing — the building's name for
    the thing is not the asker's name for it, which is the whole reason a resolver exists.
"""

from __future__ import annotations

import pytest

from orchestrator.services.clarification import compose_abstract
from orchestrator.services.fallback_wording import _close, nearest_holdings

pytestmark = pytest.mark.unit

# Alphabetical, as the building's own order supplies them — which is what made the defect
# visible: the old answer returned exactly the first four.
MEASURED = [
    "air quality",
    "carbon monoxide",
    "co2",
    "damper position",
    "door contact",
    "electric power",
    "humidity",
    "noise",
    "occupancy",
    "pm1",
    "pm10",
    "pm25",
    "temperature",
    "tvoc",
]


# ── punctuation must not make a measurand unrecognisable ──────────────────────────────


@pytest.mark.parametrize("written", ["pm2.5", "pm 2.5", "pm-2.5", "pm25"])
def test_every_way_people_write_it_is_the_same_measurand(written):
    assert _close(written, "pm25") is True, written


def test_pm1_still_cannot_match_pm10():
    """The `len >= 4` guard on the prefix test is load-bearing and is untouched: squashed "pm1"
    is three characters. Answering a PM1 question about PM10 would be worse than not answering."""
    assert _close("pm1", "pm10") is False
    assert _close("pm10", "pm1") is False


def test_unrelated_terms_are_still_unrelated():
    for a, b in (("noise", "occupancy"), ("co2", "co"), ("temperature", "humidity")):
        assert _close(a, b) is False, (a, b)


def test_the_existing_prefix_case_still_works():
    assert _close("humid", "humidity") is True


# ── the resolved name must reach the ranking ──────────────────────────────────────────


def test_the_question_alone_cannot_find_the_right_modality():
    """The premise. The asker's words are not the building's, which is why the resolver's
    output has to be passed in rather than re-derived from the question."""
    names, _ = nearest_holdings("why is pl 2.5 increasing", MEASURED, [])
    assert names[0] != "pm25"


def test_the_resolved_name_puts_the_right_modality_first():
    names, _ = nearest_holdings("why is pl 2.5 increasing", MEASURED, [], resolved=["PM2.5"])
    assert names[0] == "pm25"


def test_the_decline_names_it_where_it_used_to_name_the_alphabet():
    text = compose_abstract(
        "Abacws Building", "why is pl 2.5 increasing", ["pl"], MEASURED, [], ["PM2.5"]
    )
    assert "pm25" in text
    # and it must not lead with the alphabetical head any more
    assert "the readings of air quality, carbon monoxide, co2 and damper position" not in text


def test_passing_no_resolved_name_behaves_exactly_as_before():
    """Every other caller must be unaffected — `resolved` defaults to empty."""
    a = nearest_holdings("why is pl 2.5 increasing", MEASURED, [])
    b = nearest_holdings("why is pl 2.5 increasing", MEASURED, [], resolved=())
    assert a == b


def test_the_caller_that_has_the_resolved_names_passes_them():
    """`compose_abstract` computes `named` for the bold text one line above the list. If a
    refactor stops forwarding it, the list silently goes back to being alphabetical."""
    import inspect

    src = inspect.getsource(compose_abstract)
    assert "resolved=named" in src
