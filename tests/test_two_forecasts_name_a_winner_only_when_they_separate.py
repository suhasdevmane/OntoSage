# -*- coding: utf-8 -*-
"""W2-03's honesty half: two forecasts, and no winner when their intervals overlap.

WHAT THIS IS FOR
----------------
BUG-946: *"Will floor 3 or floor 4 be warmer TOMORROW?"* answers from CURRENT means and says
so honestly — *"The data reflects current conditions; it does not indicate which floor will be
warmer tomorrow"* — but produces no forecast at all, so there are no intervals to overlap.
W2-03's acceptance is *"the answer names BOTH forecasts and declines to pick a winner when the
intervals overlap"*.

BUG-885 is why the rule is arithmetic rather than a request to the narrator: *"Floor 3 is
warmer than Floor 4"* was asserted twice in bold from a **0.06 °C** gap between two means whose
readings spanned **3.9 °C**.

WHAT IS AND IS NOT COVERED HERE
-------------------------------
This pins the VERDICT: given two bound, aggregated forecasts, what may honestly be said. It
does NOT bind the two sides, and `overlap_verdict`'s docstring says why — a side assigned by
parsing a sensor's LABEL is BUG-884 again, and `data_coverage_audit.py` mis-files about 4,000
of 5,874 sensors that way. The binding has to come through the graph.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.forecasting.overlap_verdict import (  # noqa: E402
    SideForecast,
    compare,
    render,
)


def _side(name, values, half_width, n_sensors=10, how="mean"):
    return SideForecast(
        name=name,
        forecast=list(values),
        lower_95=[v - half_width for v in values],
        upper_95=[v + half_width for v in values],
        n_sensors=n_sensors,
        how=how,
    )


# ── the rule ─────────────────────────────────────────────────────────────────


def test_overlapping_intervals_name_no_winner():
    """The live shape: two floors 0.5 apart with bands of ±2.0."""
    a = _side("Floor 3", [23.0] * 6, 2.0, n_sensors=49)
    b = _side("Floor 4", [22.5] * 6, 2.0, n_sensors=51)
    v = compare(a, b)
    assert v.comparable and not v.separated
    assert v.winner is None
    assert v.reason == "the 95% intervals overlap"


def test_separated_intervals_name_the_higher_one():
    a = _side("Floor 3", [26.0] * 6, 0.5)
    b = _side("Floor 4", [22.0] * 6, 0.5)
    v = compare(a, b)
    assert v.separated and v.winner == "Floor 3"
    assert v.reason == "the 95% intervals do not overlap"


def test_the_lower_side_can_win_too():
    v = compare(_side("A", [10.0] * 4, 0.1), _side("B", [30.0] * 4, 0.1))
    assert v.winner == "B"


def test_a_gap_below_the_reported_precision_is_no_gap():
    """BUG-885 one decimal place down: 0.004 apart is equal to anyone reading two digits."""
    a = _side("Floor 3", [23.0] * 4, 0.0)
    b = _side("Floor 4", [23.004] * 4, 0.0)
    v = compare(a, b)
    assert not v.separated and v.winner is None
    assert "less than the precision" in v.reason


def test_touching_intervals_count_as_overlapping():
    """A band that ends exactly where the other begins has not separated them."""
    a = _side("A", [10.0] * 4, 1.0)  # 9.0 .. 11.0
    b = _side("B", [12.0] * 4, 1.0)  # 11.0 .. 13.0
    assert not compare(a, b).separated


def test_a_missing_interval_is_not_certainty():
    """No band must never read as a narrow band; the pair can then never be separated."""
    a = SideForecast("A", [30.0] * 4, [], [], n_sensors=3)
    b = _side("B", [10.0] * 4, 0.1)
    v = compare(a, b)
    assert not v.separated and v.winner is None
    assert v.intervals[0] == (float("-inf"), float("inf"))


# ── what is compared, and over which steps ───────────────────────────────────


def test_only_the_shared_steps_are_compared():
    a = _side("A", [10.0] * 10, 0.1)
    b = _side("B", [20.0] * 4, 0.1)
    assert compare(a, b).n_steps == 4


def test_a_sub_window_restricts_the_comparison():
    """ "tomorrow afternoon" is a subset of the horizon, and only those steps count."""
    a = _side("A", [0.0, 0.0, 100.0, 100.0], 0.1)
    b = _side("B", [50.0, 50.0, 50.0, 50.0], 0.1)
    early = compare(a, b, steps=[0, 1])
    late = compare(a, b, steps=[2, 3])
    assert early.winner == "B" and late.winner == "A"


def test_steps_outside_the_horizon_are_ignored_and_none_left_means_no_comparison():
    a = _side("A", [1.0, 2.0], 0.1)
    b = _side("B", [3.0, 4.0], 0.1)
    assert compare(a, b, steps=[0, 99]).n_steps == 1
    assert compare(a, b, steps=[50, 99]) is None


def test_two_empty_forecasts_are_not_comparable():
    assert compare(SideForecast("A", [], [], []), SideForecast("B", [], [], [])) is None


def test_a_total_is_summed_and_a_mean_is_averaged():
    """Lesson #139: the reduction comes from the QUANTITY, carried on the side."""
    a = _side("Meters A", [1.0, 2.0, 3.0], 0.0, how="total")
    b = _side("Meters B", [1.0, 1.0, 1.0], 0.0, how="total")
    v = compare(a, b)
    assert v.figures == (6.0, 3.0) and v.winner == "Meters A"
    c = _side("Rooms A", [1.0, 2.0, 3.0], 0.0, how="mean")
    d = _side("Rooms B", [1.0, 1.0, 1.0], 0.0, how="mean")
    assert compare(c, d).figures == (2.0, 1.0)


def test_disagreeing_reductions_fall_back_to_the_mean():
    """Summing one side and averaging the other would compare two different quantities."""
    v = compare(_side("A", [2.0, 2.0], 0.0, how="total"), _side("B", [1.0, 1.0], 0.0, how="mean"))
    assert v.figures == (2.0, 1.0)


# ── the sentence ─────────────────────────────────────────────────────────────


def test_both_forecasts_are_named_when_no_winner_may_be():
    a = _side("Floor 3", [23.0] * 6, 2.0, n_sensors=49)
    b = _side("Floor 4", [22.5] * 6, 2.0, n_sensors=51)
    text = render(a, b, compare(a, b), unit="°C", window_label="tomorrow")
    assert "Neither is forecast higher" in text
    assert "Floor 3 mean 23.00°C" in text and "Floor 4 mean 22.50°C" in text
    assert "95% 21.00 to 25.00°C" in text and "95% 20.50 to 24.50°C" in text
    assert "49 sensor(s)" in text and "51 sensor(s)" in text
    assert "6 predicted step(s)" in text
    assert "warmer" not in text.lower().replace("higher", "")


def test_both_forecasts_are_named_when_a_winner_is():
    a = _side("Floor 3", [26.0] * 6, 0.5, n_sensors=49)
    b = _side("Floor 4", [22.0] * 6, 0.5, n_sensors=51)
    text = render(a, b, compare(a, b), unit="°C", window_label="tomorrow")
    assert text.startswith("**Floor 3 is forecast higher over tomorrow.**")
    assert "Floor 3 mean 26.00°C" in text and "Floor 4 mean 22.00°C" in text
    assert "do not overlap" in text


def test_an_incomparable_pair_says_so_and_states_no_figure():
    text = render(SideForecast("A", [], [], []), SideForecast("B", [], [], []), None, unit="°C")
    assert "No comparison is stated" in text
    assert "0.00" not in text


def test_a_missing_interval_is_named_in_the_sentence():
    a = SideForecast("A", [30.0] * 4, [], [], n_sensors=3)
    b = _side("B", [10.0] * 4, 0.1)
    text = render(a, b, compare(a, b), unit="°C")
    assert "no interval available" in text
    assert "Neither is forecast higher" in text


# ── the boundary this module deliberately does not cross ─────────────────────


def test_the_module_does_not_assign_a_side_from_a_sensor_label():
    """BUG-884's shape: a floor bound to the sensors NAMED for it, not the ones ON it.

    If side assignment ever appears in here it will be doing it from the only thing this
    module has, which is a label — the mistake `data_coverage_audit.py` makes on about 4,000
    of 5,874 sensors. The binding belongs upstream, through the graph.
    """
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1] / "orchestrator/services/forecasting/overlap_verdict.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # It imports nothing that could bind a sensor, and no regex engine to parse a name with.
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    roots = {m.split(".")[0] for m in imported if m}
    assert "re" not in roots, "it imports a regex engine, so it could parse a name"
    for forbidden in ("sparql", "binder", "graph", "sensor_binder"):
        assert not any(forbidden in m for m in imported), f"it imports {forbidden}"

    # And it never reads a sensor's metadata: `window_label` is a caller-supplied phrase, a
    # subscript by the string "label" would be reading a sensor's name.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in ("label", "sensor_label", "uuid"):
            raise AssertionError(f"line {node.lineno} reads a sensor's {node.value}")
