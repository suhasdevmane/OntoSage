# -*- coding: utf-8 -*-
"""CAVEAT-892 — a resolved Brick class must outrank a coincidental word in a label.

Measured live 2026-09-29. "What is the outdoor temperature right now?" resolved its concept
correctly — `outdoor_temperature -> brick:Outside_Air_Temperature_Sensor`, of which this
building has exactly ONE instance, the live Open-Meteo feed — and then bound
`GreenRoof_Ambient_Temp_Sensor` instead. That sensor's label reads:

    "Ambient Temperature Sensor - Green Roof (outdoor reference)"

so the token "outdoor" matched it, while the feed's auto-generated label says "outside". A
synthetic roof sensor answered a question about the weather, and the log carried both facts a
millisecond apart: the class was resolved and then ignored.

`_resolve_entities_by_label` was already being HANDED that class as `class_hints` (added for
BUG-884) and used it only on the floor path. This makes it a preference on the general path too:
tried first, and falling straight through to the label queries when it returns nothing, so a
building whose points are typed differently behaves exactly as before.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def _src() -> str:
    return inspect.getsource(SPARQLAgent._resolve_entities_by_label)


def test_the_class_preference_runs_before_the_label_queries():
    """Order is the whole fix: after the label queries it would never be reached."""
    src = _src()
    typed_at = src.index("_count_readable_instances")
    label_at = src.index("# Timeseries-bearing points first")
    assert typed_at < label_at


def test_it_requires_readable_points():
    """A point with no timeseries reference cannot answer a reading question."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "ref:hasExternalReference" in block


def test_it_is_a_preference_and_not_a_filter():
    """No hits must fall through, not decline.

    A building that types its points differently, or a question whose concept resolved to
    nothing, has to behave exactly as it did before this existed.
    """
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "if _typed_hits:" in block, "the continue must be conditional on actually finding some"


def test_no_hints_means_no_extra_query():
    src = _src()
    assert "if _hint_classes:" in src, "guarded, so an unhinted call costs nothing"


def test_a_failing_class_query_never_costs_the_answer():
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "except Exception" in block
    assert "_typed_hits = []" in block


def test_hits_found_by_class_are_marked_readable():
    """They came from a query that required a timeseries reference, so the SQL stage can read
    them — the same reasoning the label path applies to its own query 0."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "ts_bearing.update(_typed_hits)" in block


def test_the_reason_is_recorded_beside_the_code():
    """A later maintainer must find why this exists without hunting a tracker."""
    src = _src()
    assert "CAVEAT-892" in src
    assert "outdoor" in src.lower() and "label" in src.lower()


def test_prefixed_and_bare_class_names_both_work():
    """`class_hints` arrive as 'brick:X' from the concept register and as 'X' from config."""
    src = _src()
    assert '_c if ":" in _c else f"brick:{_c}"' in src


# ── the first fix made the bug worse, and this is why ────────────────────────────────
#
# Putting every hinted class in one VALUES admitted the broad ones. `class_hints` is every Brick
# class of every resolved concept flattened, so the outdoor question carried
# Outside_Air_Temperature_Sensor AND Air_Temperature_Sensor AND Temperature_Sensor. Verified
# against the live graph 2026-09-29:
#
#   Outside_Air_Temperature_Sensor   -> 1 instance, the Open-Meteo feed
#   GreenRoof_Ambient_Temp_Sensor    -> NOT that class; it is an Air_Temperature_Sensor
#
# so the broad class let the roof sensor in, and the token filter ("outdoor") then threw out the
# correctly typed feed, whose label says "outside". The class was resolved, included, and
# overruled by a word.


def test_classes_are_ranked_by_specificity_not_unioned():
    """A union of a class and its parents is the parent. That is what shipped and failed."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "VALUES ?cls" not in block, "the union is the bug; one class at a time"
    assert "_count_readable_instances" in block
    assert "sorted(" in block and "_ranked" in block


def test_specificity_is_asked_of_the_graph_not_guessed_from_the_name():
    """Brick happens to name subclasses by prefixing the parent, but a building's own classes
    need not, and a class the building never instantiated must rank nowhere rather than first."""
    src = inspect.getsource(SPARQLAgent._count_readable_instances)
    assert "COUNT(DISTINCT ?s)" in src
    assert "ref:hasExternalReference" in src, "rank by what can be READ, not merely what exists"


def test_a_class_with_no_instances_is_never_chosen():
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "if n > 0" in block


def test_a_narrow_class_drops_the_token_filter():
    """The tokens restate the class, so below the cap they can only lose a correctly typed
    point to a vocabulary difference — "outside" vs "outdoor" is exactly that."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "_CLASS_IS_THE_ANSWER_CAP" in block
    # insensitive to how black wraps it; the point is the empty filter under the cap
    assert "_tok_filter" in block
    assert '"" if _n <= self._CLASS_IS_THE_ANSWER_CAP' in " ".join(block.split())


def test_a_broad_class_keeps_the_token_filter_and_the_narrowing():
    """Above the cap the class cannot stand alone: 288 temperature sensors is not an answer."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "_narrow_to_best_match" in block
    assert "if _used_n > self._CLASS_IS_THE_ANSWER_CAP:" in block


def test_the_cap_sits_below_a_floors_worth_of_one_modality():
    """48-56 points is "a place's sensors", not "the sensor for this quantity". If the cap ever
    rises past that, a floor-shaped set starts being returned unfiltered."""
    assert SPARQLAgent._CLASS_IS_THE_ANSWER_CAP < 48


def test_only_a_few_classes_are_tried():
    """Unbounded, a concept resolving to a long ancestor chain would cost a query each."""
    src = _src()
    block = src[src.index("if _hint_classes:") : src.index("# Timeseries-bearing points first")]
    assert "_ranked[:3]" in block


def test_a_failed_ranking_falls_through_rather_than_declining():
    src = inspect.getsource(SPARQLAgent._count_readable_instances)
    assert "return {}" in src, "no ranking means no class preference, not no answer"
