"""A hinted class the question names is tried before a rarer class it does not name.

2026-10-11 battery: "is the server room temperature okay?" resolved the thermal-comfort concept,
which hints temperature AND humidity sensors; the resolver tried the class with the fewest
instances first, so the answer was about humidity. Fewest-first stays the rule among classes the
question names equally (the nested outdoor/air/temperature case, CAVEAT-892).
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit

rank = SPARQLAgent._rank_hint_classes


def test_the_named_quantity_is_tried_first():
    counts = {"brick:Temperature_Sensor": 520, "brick:Humidity_Sensor": 281}
    order = [c for _, c in rank(counts, "is the server room temperature okay?")]
    assert order[0] == "brick:Temperature_Sensor"


def test_nested_classes_still_go_fewest_first():
    counts = {
        "brick:Outside_Air_Temperature_Sensor": 1,
        "brick:Air_Temperature_Sensor": 40,
        "brick:Temperature_Sensor": 520,
    }
    order = [c for _, c in rank(counts, "what is the outdoor temperature right now?")]
    assert order[0] == "brick:Outside_Air_Temperature_Sensor"


def test_a_question_naming_neither_keeps_fewest_first():
    counts = {"brick:Temperature_Sensor": 520, "brick:Humidity_Sensor": 281}
    order = [c for _, c in rank(counts, "is it comfortable in here?")]
    assert order[0] == "brick:Humidity_Sensor"


def test_classes_without_readable_instances_are_left_out():
    counts = {"brick:Temperature_Sensor": 0, "brick:Humidity_Sensor": 281}
    assert rank(counts, "temperature?") == [(281, "brick:Humidity_Sensor")]
