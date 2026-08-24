# -*- coding: utf-8 -*-
"""An identifier's digits are not a measurement (found by the V6-T23 live probe).

Reporting a noisy radiator produced:

    "your maintenance request has been logged as REP-571188"
    "WARNING The recorded sound value (571188, 571188) is outside the range this quantity
     normally takes"

`_NUMBER_RE`'s lookbehind rejects a preceding word character but not a hyphen, so every
`PREFIX-123456` in an answer was a candidate reading — and a report acknowledgement is largely
made of one. A confident, wrong warning attached to a correct answer is worse than no warning:
it teaches readers to skip the caveat exactly when it is real.

Third of a family: BUG-191 read the "2" inside "bldg2" as a sensor value and scored refusals
as passes; BUG-230 read a document's threshold table as live readings. The shape recurs
because digits in text are assumed to be measurements unless something proves otherwise, when
the assumption should run the other way.

Note the measurand key is "sound", not "noise". An unknown key makes `implausible_values`
return [] for everything, so a first draft of this file passed every assertion while testing
nothing — the control test below exists to catch exactly that.
"""

import pytest

from orchestrator.services.plausibility import implausible_values

pytestmark = pytest.mark.unit


def test_a_report_id_is_not_a_sound_reading():
    """The exact live failure."""
    text = (
        "Thank you — your maintenance request has been logged as REP-571188. "
        "Category: Maintenance request. We will look into the noise."
    )
    assert (
        implausible_values(text, "sound") == []
    ), "the report ID's digits were judged as a sound level"


@pytest.mark.parametrize(
    "text",
    [
        "Work order WO-4471 has been raised.",
        "See ticket #90210 for the history.",
        "Your reference is REP-8829371.",
    ],
)
def test_no_identifier_shape_is_read_as_a_quantity(text):
    assert implausible_values(text, "sound") == [], text


def test_a_genuinely_implausible_reading_is_still_caught():
    """The control. Without it, a guard disabled outright would pass every test above."""
    hits = implausible_values("The sound level in Room 2.14 is 571188 dB.", "sound")
    assert hits, "the guard no longer catches an impossible reading"


def test_an_ordinary_reading_is_untouched():
    assert implausible_values("The sound level in Room 2.14 is 46 dB.", "sound") == []


def test_a_year_is_still_not_a_reading():
    """The pre-existing exclusion must survive the new one."""
    assert implausible_values("Readings were collected in 2026.", "sound") == []
