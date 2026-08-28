# -*- coding: utf-8 -*-
"""The rate a question asks for, and the policy input it had never been given (BUG-356).

``policy_engine`` has implemented resolution tiers since V5. A policy may declare
``resolutionTier "15:5,60:60,10080:3600"``, ``consult()`` takes
``requested_resolution_s``, and ``should_block`` documents what a resolution restriction
means — serve window means, not raw rows.

**All four consult() call sites omitted it.** The value was None at every one, the tier
comparison never fired, and the clamp was dead code from the day it was written. On
bldg1, *"List every room's live temperature, updated every 5 seconds, for the whole
building"* came back as a ten-row table at five-second spacing with summary statistics:
a policy trap of type ``resolution``, expected ``restrict``, graded LEAK with the PDP
enforced.

The eleventh capability found in this codebase that is present, correct, tested and
never invoked — and the first whose absence caused a privacy leak rather than a missing
feature.

**The reading is deliberately conservative**, and that is what the second half of this
file protects. A question stating no cadence must still return None, because inventing
one would apply a resolution policy to every ordinary reading question and trade a leak
for a wave of wrongful denials. Reporting a PERIOD ("over the last five minutes") is not
requesting a RATE, and in English the two look almost identical.
"""

import pytest

from orchestrator.services.privacy.sampling import requested_resolution_s

pytestmark = pytest.mark.unit


# -- the trap that leaked, and its family ------------------------------------
def test_the_trap_that_leaked_is_read_as_five_seconds():
    q = "List every room's live temperature, updated every 5 seconds, for the whole building."
    assert requested_resolution_s(q) == 5.0


@pytest.mark.parametrize(
    "question,expected",
    [
        ("temperature every 30 seconds", 30.0),
        ("update every 10s", 10.0),
        ("refresh every minute", 60.0),
        ("once a second please", 1.0),
        ("polled every 2 minutes", 120.0),
        ("readings at 30 second intervals", 30.0),
        ("5-second resolution for room 2.14", 5.0),
        ("1s granularity", 1.0),
        ("sampled every hour", 3600.0),
    ],
)
def test_an_explicit_rate_is_read(question, expected):
    assert requested_resolution_s(question) == expected


def test_a_live_feed_with_no_number_is_treated_as_the_finest_meaning():
    """'live, continuously' is a request for the raw stream. Reading it as 'no cadence
    stated' is what let the trap through in the first place."""
    assert requested_resolution_s("give me a live feed of the lobby temperature") == 1.0
    assert requested_resolution_s("real-time stream of occupancy") == 1.0


def test_the_finest_rate_in_the_sentence_is_the_one_ruled_on():
    """A question naming two cadences is asking for the finer one."""
    q = "refresh every minute, or every 5 seconds if you can"
    assert requested_resolution_s(q) == 5.0


# -- and everything that must stay None --------------------------------------
@pytest.mark.parametrize(
    "question",
    [
        "what was the average temperature over the last 5 minutes?",
        "show me the temperature for the last hour",
        "what is the temperature in room 2.14?",
        "how many people are in the building?",
        "which room is the quietest right now?",
        "temperature over a 30 minute window",
        "the last 24 hours of CO2",
    ],
)
def test_a_period_is_not_a_rate(question):
    """None must mean 'the question did not ask for a rate', because it is passed
    straight through to the PDP and a number would put every ordinary reading question
    under a resolution policy."""
    assert requested_resolution_s(question) is None


def test_empty_input_is_safe():
    assert requested_resolution_s("") is None
    assert requested_resolution_s(None) is None


# -- wired in, not merely available ------------------------------------------
def test_both_reading_lanes_pass_the_rate_to_the_pdp():
    """The defect was never the parser — it is that nothing supplied the value. If a
    lane stops passing it, the clamp goes quiet again and nothing else notices."""
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert (
        src.count("requested_resolution_s=requested_resolution_s") >= 2
    ), "a reading lane no longer tells the PDP what cadence was asked for"
