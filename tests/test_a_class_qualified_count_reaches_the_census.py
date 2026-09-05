# -*- coding: utf-8 -*-
"""A count of a KIND of device is not a count of all of them (BUG-431).

"How many CO2 sensors are there?" was answered **8**. The graph holds **280**.

The route ran like this. `_INVENTORY_RE` required the noun to follow "how many"
immediately, so a class qualifier broke the match, the question missed the census entirely
and reached the generated-SPARQL path. That returned a LIMITed 72 rows, and the model —
reasoning correctly about the wrong input — divided by RDF-type multiplicity and announced
"8 unique CO2 sensors".

This is the shape CAVEAT-039 already cost this project once: a LIMIT with no DISTINCT and a
count computed from whatever rows arrived rather than by the graph.

The first fix was wrong in a new way. Widening the regex sent the question to the
building-wide metrics snapshot, which reports the building's totals and answered **2,721** —
a different wrong number. The snapshot cannot filter by class; `class_census` can, and holds
CO2_Sensor 280. So the qualified form belongs to the census and the bare form keeps the
snapshot.

A CONDITION qualifier is a third case and belongs to neither: "how many sensors are broken?"
must not be answered with a census of every sensor, which is BUG-427's mistake in a
different field.
"""

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.building_metrics import (  # noqa: E402
    is_inventory_count_question,
    names_a_specific_class,
)


@pytest.mark.parametrize(
    "query",
    [
        "How many CO2 sensors are there?",
        "How many temperature sensors does the building have?",
        "How many air quality sensors are installed?",
        "number of temperature sensors",
    ],
)
def test_a_class_qualified_count_is_recognised(query):
    assert names_a_specific_class(query), (
        f"{query!r} names a kind of device; answering it from the building-wide snapshot "
        f"reports the total for every sensor"
    )


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are there?",
        "How many rooms are there?",
        "How many of the sensors are there?",
        "What is the total floor area?",
    ],
)
def test_an_unqualified_count_keeps_the_snapshot(query):
    assert not names_a_specific_class(query)


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are broken?",
        "How many sensors are offline?",
        "How many sensors are overdue for calibration?",
        "How many meters are out of service?",
    ],
)
def test_a_condition_qualified_count_is_not_a_census(query):
    """The census counts what exists; it cannot filter on state."""
    assert not is_inventory_count_question(query), (
        f"{query!r} asks about a CONDITION. A census answers it with the total, which is "
        f"BUG-427's mistake in a different field."
    )


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are there?",
        "How many CO2 sensors are there?",
        "How many rooms are there?",
    ],
)
def test_ordinary_counts_still_reach_a_counting_path(query):
    assert is_inventory_count_question(query), (
        f"{query!r} no longer reaches a path that counts in the graph, and will be answered "
        f"from whatever rows a generated query happens to return"
    )


def test_the_capability_metrics_path_defers_on_a_class_qualifier():
    import inspect

    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent)
    assert "_class_qualified" in src, (
        "the metrics snapshot no longer defers to the class census, and a question about "
        "one kind of sensor is answered with the building's total"
    )
