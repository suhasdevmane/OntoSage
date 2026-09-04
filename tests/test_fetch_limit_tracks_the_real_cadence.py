# -*- coding: utf-8 -*-
"""The fetch limit must be derived from the cadence anything actually writes at (CAVEAT-414).

`_PER_UUID_LIMIT` is a sample count standing in for a time window, and the two are joined by
the publish cadence. That join was written as the constant `30.0` with a comment saying to
re-check it whenever the cadence changed.

CAVEAT-405 then changed every cadence: the fastest modality is now 60s and most are at 300s.
Nothing re-checked, because the coupling lived in a comment rather than in code, so the limit
stayed at double what any detector needs. The cost was not theoretical — a sweep fetched
roughly 2.7M rows and took **598 seconds**, and while it ran GraphDB slowed enough that the
capability lane's 15-second SPARQL timeout fired and 52 answers silently left the TTL-first
path (CAVEAT-415).

This is the third time this project has had a limit in one unit against a requirement in
another: CAVEAT-401 (samples vs hours in the scanner), the fault injector (rows vs a run
length), and now this. The fix each time is the same — read it, don't restate it.
"""

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "mysql-dummy-publish-dev"))

from orchestrator.services.anomaly import detectors, scanner  # noqa: E402


def test_the_limit_covers_the_longest_detector_window():
    """The point of the number: a detector must never be handed less than it requires."""
    hours = scanner._PER_UUID_LIMIT * scanner._FASTEST_CADENCE_S / 3600.0
    import inspect

    needed = float(inspect.signature(detectors.stuck).parameters["min_hours"].default)
    assert hours >= needed, f"the fetch spans {hours:.1f}h, stuck needs {needed:g}h"


def test_the_fault_is_a_minority_of_the_fetched_history():
    """A detector that sees only the fault has no baseline to call it a fault against."""
    hours = scanner._PER_UUID_LIMIT * scanner._FASTEST_CADENCE_S / 3600.0
    import inspect

    needed = float(inspect.signature(detectors.stuck).parameters["min_hours"].default)
    assert hours >= needed * 2, "the window must hold the fault and enough contrast around it"


def test_the_cadence_is_read_from_the_publisher_not_restated():
    sensor_signal = pytest.importorskip("sensor_signal")
    assert scanner._FASTEST_CADENCE_S == float(min(sensor_signal.CADENCE_S.values())), (
        "the scanner and the publisher disagree about the fastest cadence, which is exactly "
        "how the limit came to be double what it needed"
    )


def test_a_missing_publisher_falls_back_conservatively():
    """A building whose publisher this cannot see keeps the old value rather than
    silently shrinking every detector's view."""
    assert scanner._fastest_publish_cadence_s(default=30.0) > 0
    import inspect

    src = inspect.getsource(scanner._fastest_publish_cadence_s)
    assert "return default" in src


def test_the_limit_is_not_a_hand_written_constant():
    import inspect

    src = inspect.getsource(scanner)
    idx = src.index("_PER_UUID_LIMIT = ")
    line = src[idx : src.index("\n", idx)]
    assert "_FASTEST_CADENCE_S" in line and "_LONGEST_DETECTOR_WINDOW_H" in line, (
        "the limit must be computed from the two facts it depends on, so changing either "
        "changes it"
    )


def test_slowing_the_cadence_would_lower_the_limit():
    """The arithmetic, not today's numbers: a slower cadence needs fewer samples."""
    at_30 = int((6.0 * 3600.0 / 30.0) * 2)
    at_60 = int((6.0 * 3600.0 / 60.0) * 2)
    assert at_60 < at_30
    assert scanner._PER_UUID_LIMIT <= at_30
