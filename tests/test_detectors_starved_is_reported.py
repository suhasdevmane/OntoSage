# -*- coding: utf-8 -*-
"""A detector that could not run must say so, not return an empty list (BUG-360).

`seasonal_residual` declares ``min_history_hours=48.0``. A sweep fetches ``_PER_UUID_LIMIT``
samples, which at the publisher's 30-second cadence spans nowhere near that — measured live,
the longest series in a sweep spanned **40.9 hours**. So the detector returned ``[]`` for
every point, correctly and in total silence, for as long as this scanner has existed. The
fault-injection harness then scored it 0/1 and the number read as a broken detector.

That is the same shape as CAVEAT-401 — a limit expressed in samples against a requirement
expressed in hours, with nothing connecting them — and this is the fourth time this project
has made it. The fix is not to raise the limit: covering 48 hours at 30 seconds would be
11,520 samples across 1,859 sensors, 21M rows a sweep. The fix is to state the tradeoff.

Requirements are read from each detector's signature BY NAME, so raising a threshold shows
up here instead of quietly becoming a no-op.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.anomaly.scanner import detectors_starved

pytestmark = pytest.mark.unit


def _series(hours: float, n: int = 100):
    end = datetime(2026, 9, 3, 12, 0, 0)
    step = timedelta(hours=hours) / max(1, n - 1)
    return [((end - timedelta(hours=hours) + step * i).isoformat(), 20.0 + i) for i in range(n)]


def test_a_detector_needing_more_history_than_was_fetched_is_named():
    starved = detectors_starved({"u1": _series(24.0)})
    assert "seasonal_residual" in starved
    assert "48" in starved["seasonal_residual"], "the requirement must be quoted, not implied"
    assert "24.0h" in starved["seasonal_residual"], "the span actually fetched must be quoted"


def test_a_detector_that_fits_is_not_named():
    starved = detectors_starved({"u1": _series(24.0)})
    assert "stuck" not in starved, "stuck needs 6h and 24h were fetched"
    assert "spike" not in starved, "spike declares no history minimum"


def test_the_longest_series_decides_not_the_shortest():
    """One point with barely any history must not starve a detector for the whole sweep."""
    starved = detectors_starved({"short": _series(0.5), "long": _series(60.0)})
    assert starved == {}, "a 60h series is enough for every detector; the 0.5h one is noise"


def test_enough_history_starves_nothing():
    assert detectors_starved({"u1": _series(60.0)}) == {}


def test_datetime_stamps_work_as_well_as_iso_strings():
    """Adapters return datetimes; the fetch layer returns strings. Both reach this."""
    end = datetime(2026, 9, 3, 12, 0, 0)
    series = [(end - timedelta(hours=24) + timedelta(minutes=15 * i), 20.0) for i in range(97)]
    assert "seasonal_residual" in detectors_starved({"u1": series})


def test_no_series_reports_nothing_rather_than_everything():
    """An empty sweep is a different failure and must not masquerade as starvation."""
    assert detectors_starved({}) == {}
    assert detectors_starved({"u1": [], "u2": [("2026-09-03T12:00:00", 1.0)]}) == {}


def test_a_malformed_stamp_does_not_take_the_sweep_down():
    starved = detectors_starved({"bad": [("not-a-time", 1.0), ("also-not", 2.0)]})
    assert starved == {}


def test_the_requirement_is_read_from_the_detector_not_restated():
    """Raising a threshold must change this automatically, or the next drift is silent."""
    import inspect

    from orchestrator.services.anomaly import detectors, scanner

    src = inspect.getsource(scanner.detectors_starved)
    assert "inspect.signature" in src
    declared = inspect.signature(detectors.seasonal_residual).parameters["min_history_hours"]
    assert (
        f"{float(declared.default):g}h"
        in detectors_starved({"u1": _series(24.0)})["seasonal_residual"]
    )


def test_the_sweep_summary_carries_the_field():
    """The grader reads it from there; a renamed key would silently restore the old zero."""
    import inspect

    from orchestrator.services.anomaly import scanner

    src = inspect.getsource(scanner.AnomalyScanner.scan_once)
    assert '"detectors_starved"' in src
