"""Every sensor in the live graph resolves to exactly one timeseries id (V12-34, BUG-531).

The project's fan-out metric (refs / distinct uuids) read 1.00 while 77 sensors answered from
two stores at once, because each reference carries its own uuid. This asks the question
directly, against the live graph, with the same query `certify_building.py` preflight runs.

Integration: skips when GraphDB is not reachable from where the test runs (set
GRAPHDB_URL_HOST). Offline, it pins that the check counts distinct ids per SUBJECT rather
than references per uuid.
"""

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _certify():
    spec = importlib.util.spec_from_file_location(
        "certify_building", REPO / "scripts" / "certify_building.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_the_check_counts_series_per_sensor_not_references_per_uuid():
    q = _certify()._DUAL_REFERENCE_QUERY
    assert "GROUP BY ?s" in q
    assert "COUNT(DISTINCT ?u) > 1" in q


@pytest.mark.integration
def test_no_sensor_in_the_live_graph_has_two_series():
    duals = _certify().sensors_with_two_series()
    if duals is None:
        pytest.skip("GraphDB not reachable from here")
    assert duals == [], f"{len(duals)} sensor(s) with two timeseries ids: {duals[:10]}"
