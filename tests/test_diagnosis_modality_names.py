# -*- coding: utf-8 -*-
"""A why-question may name the quantity outright (BUG-354).

Graded 'wrong' in bldg1's certification: "Why dose the temperature keep changing?" came
back "I processed your request, but couldn't generate a response."

The typo is NOT the cause -- the correctly spelled version failed identically. WHY_RE
matched both; the modality lookup matched neither, because it held only LAY vocabulary
(cold, hot, stuffy, loud, dark, dusty, busy) and none of the modality names. Measured:
"temperature", "illuminance" and "occupancy" appeared nowhere in it, and ``\bhumid\b``
does not match "humidity" -- the trailing word boundary stops it.

So an occupant asking "why is it stuffy" was served, and a facility manager or researcher
asking "why is the humidity high" was not. Design contract 6 requires one system to serve
lay users AND experts; this was the expert half missing.
"""

import pytest

from orchestrator.services.anomaly.diagnosis import is_why_question

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question,expected",
    [
        # the graded failure, with and without its typo
        ("Why dose the temperature keep changing?", ("temperature", "high")),
        ("Why does the temperature keep changing?", ("temperature", "high")),
        # the word boundary that swallowed humidity
        ("why is the humidity high?", ("humidity", "high")),
        ("why is relative humidity so high in the lab?", ("humidity", "high")),
        # names that appeared nowhere at all
        ("why is the illuminance low in room 2.14?", ("illuminance", "low")),
        ("why is occupancy so high today?", ("occupancy", "high")),
        ("why is the lux level dropping?", ("illuminance", "low")),
        ("why is CO2 rising in the seminar room?", ("co2", "high")),
    ],
)
def test_a_question_naming_the_modality_is_diagnosable(question, expected):
    assert is_why_question(question) == expected


@pytest.mark.parametrize(
    "question,expected",
    [
        ("why is it so warm in here?", ("temperature", "high")),
        ("why is it chilly?", ("temperature", "low")),
        ("why is it stuffy?", ("co2", "high")),
        ("why is it so dark?", ("illuminance", "low")),
    ],
)
def test_the_lay_vocabulary_still_wins_and_keeps_its_direction(question, expected):
    """A lay word carries a direction of its own — 'chilly' is not merely 'temperature' —
    so it must be read before the bare names, or 'why is it chilly' would come back high."""
    assert is_why_question(question) == expected


def test_an_explicit_direction_overrides_the_default():
    assert is_why_question("why is the temperature so low?") == ("temperature", "low")
    assert is_why_question("why is the temperature above target?") == ("temperature", "high")


@pytest.mark.parametrize(
    "question",
    [
        "what is the temperature?",
        "why is the lift broken?",
        "why do I need a badge?",
        "temperature in room 2.14",
    ],
)
def test_things_that_are_not_diagnosable_why_questions_stay_out(question):
    """Widening the vocabulary must not make every mention of a quantity a diagnosis."""
    assert is_why_question(question) is None


# -- comparatives, the form people actually use (BUG-354, second half) --------
@pytest.mark.parametrize(
    "question,expected",
    [
        # the single 'wrong' answer in bldg1's clean certification
        ("Why is it so much warmer in the corner than by the windows?", ("temperature", "high")),
        ("why is it colder upstairs?", ("temperature", "low")),
        ("why is it noisier today?", ("noise", "high")),
        ("why is it darker in here?", ("illuminance", "low")),
        ("why is it busier than usual?", ("occupancy", "high")),
        ("why is it stuffier after lunch?", ("co2", "high")),
        ("why is it the hottest room?", ("temperature", "high")),
        ("why is it dimmer on this side?", ("illuminance", "low")),
    ],
)
def test_a_comparative_is_the_normal_way_to_ask(question, expected):
    """Nobody asks "why is it warm here" — they ask "why is it WARMER in the corner".

    ``\bwarm\b`` does not match "warmer"; the word boundary stops it, exactly as
    ``\bhumid\b`` did not match "humidity". I closed BUG-354 on two examples that
    happened to use base forms, and the very next certification run produced this one.
    """
    assert is_why_question(question) == expected


def test_the_base_forms_still_work():
    """Widening to comparatives must not cost the plain adjectives."""
    assert is_why_question("why is it warm?") == ("temperature", "high")
    assert is_why_question("why is it chilly?") == ("temperature", "low")
    assert is_why_question("why is it stuffy?") == ("co2", "high")
