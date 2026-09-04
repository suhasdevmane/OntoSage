# -*- coding: utf-8 -*-
"""Generated readings must be a signal, not white noise (CAVEAT-405).

Every value the dev publisher wrote was an independent uniform draw across the modality's
range. A detector keyed on deviation-from-recent-behaviour fires almost everywhere on that,
and it did: measured across five anomaly sweeps on bldg1, stable and unaffected by the
BUG-403 clock fix, ~124,000 spike findings on 1,859 points — about 64 per point — and 8,289
persisted episodes in a single hour. Those episodes feed the anomaly and events lanes, so a
user asking "any anomalies this week" got a number assembled from noise.

The graded scorecard was never wrong (injected spikes still found 2/2, precision 1.0). This
is about the answers users see, and about organic episode counts meaning anything at all.

These tests pin the three properties the old generator lacked — persistence, a daily cycle,
and a stable per-sensor offset — and the per-modality cadence the user asked for.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PUBLISHER_DIR = Path(__file__).resolve().parent.parent / "mysql-dummy-publish-dev"
sys.path.insert(0, str(_PUBLISHER_DIR))

sensor_signal = pytest.importorskip("sensor_signal")


@pytest.fixture(autouse=True)
def _clean_state():
    sensor_signal.reset_state()
    yield
    sensor_signal.reset_state()


def _walk(uuid, col, lo, hi, dec, n=60, when=None):
    when = when or datetime(2026, 9, 3, 11, 0, 0)
    return [sensor_signal.next_value(uuid, col, lo, hi, dec, when)[1] for _ in range(n)]


# ── persistence: the property that makes a real spike stand out ────────────────────────


def test_consecutive_readings_are_close_together():
    """The old generator could jump a third of the range between two samples."""
    series = _walk("u-temp", "temp_c", 18.0, 26.0, 1, n=80)
    span = 26.0 - 18.0
    jumps = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    assert max(jumps) < span * 0.15, f"largest step {max(jumps):.2f} of a {span} range"


def test_the_series_still_moves():
    """Sticky must not mean frozen, or `stuck` fires on every point instead of `spike`."""
    series = _walk("u-co2", "co2_ppm", 400, 1200, 0, n=120)
    assert len(set(round(v, 3) for v in series)) > 20, "the signal is effectively constant"


def test_readings_stay_inside_the_declared_range():
    for col, lo, hi, dec in (
        ("co2_ppm", 400, 1200, 0),
        ("temp_c", 18.0, 26.0, 1),
        ("lux", 0.0, 600.0, 0),
    ):
        for v in _walk(f"u-{col}", col, lo, hi, dec, n=150):
            assert lo <= v <= hi, f"{col} produced {v} outside [{lo}, {hi}]"


# ── a daily cycle ──────────────────────────────────────────────────────────────────────


def test_a_diurnal_modality_peaks_in_the_day_and_troughs_at_night():
    day = sensor_signal.centre("occupancy", 0, 30, datetime(2026, 9, 3, 13, 0), 0.0)
    night = sensor_signal.centre("occupancy", 0, 30, datetime(2026, 9, 3, 2, 0), 0.0)
    assert day > night, f"daytime centre {day} not above overnight {night}"


def test_a_contact_does_not_follow_a_sine_wave():
    noon = sensor_signal.centre("contact", 0, 1, datetime(2026, 9, 3, 13, 0), 0.0)
    night = sensor_signal.centre("contact", 0, 1, datetime(2026, 9, 3, 2, 0), 0.0)
    assert noon == pytest.approx(night), "a door does not track the working day"


# ── per-sensor offset: drift_vs_peers needs peers that differ ──────────────────────────


def test_two_sensors_of_the_same_modality_are_not_identical():
    a = _walk("sensor-a", "temp_c", 18.0, 26.0, 1, n=40)
    b = _walk("sensor-b", "temp_c", 18.0, 26.0, 1, n=40)
    assert a != b


def test_a_sensor_offset_is_stable_across_restarts():
    """Derived from the uuid, not re-randomised — or every restart is a step change."""
    first = sensor_signal.centre(
        "temp_c", 18.0, 26.0, datetime(2026, 9, 3, 11, 0), sensor_signal._phase("sensor-a")
    )
    sensor_signal.reset_state()
    second = sensor_signal.centre(
        "temp_c", 18.0, 26.0, datetime(2026, 9, 3, 11, 0), sensor_signal._phase("sensor-a")
    )
    assert first == second


# ── binary points ──────────────────────────────────────────────────────────────────────


def test_a_binary_point_only_ever_reads_zero_or_one():
    values = [sensor_signal.next_value("u-door", "contact", 0, 1, 0)[0] for _ in range(200)]
    assert set(values) <= {0, 1}


def test_a_binary_point_holds_its_state_rather_than_flipping_every_write():
    values = [sensor_signal.next_value("u-door2", "contact", 0, 1, 0)[0] for _ in range(200)]
    flips = sum(1 for i in range(1, len(values)) if values[i] != values[i - 1])
    assert flips < len(values) * 0.25, f"{flips} flips in {len(values)} writes is not a door"


# ── per-modality cadence (CAVEAT-233: the user asked for varying intervals) ────────────


def test_modalities_report_at_different_intervals():
    assert sensor_signal.cadence_for("co2_ppm") < sensor_signal.cadence_for("kwh")


def test_an_unknown_modality_gets_the_default_rather_than_being_skipped():
    assert sensor_signal.cadence_for("something_new") == 300


def test_a_point_is_written_once_per_its_own_interval():
    assert sensor_signal.due("u1", "kwh", 1000.0) is True, "a new point is always due"
    sensor_signal.mark_written("u1", 1000.0)
    assert sensor_signal.due("u1", "kwh", 1100.0) is False, "900s cadence, 100s elapsed"
    assert sensor_signal.due("u1", "kwh", 1900.0) is True


def test_every_cadence_leaves_enough_samples_for_the_longest_detector_window():
    """Cadence and detector windows are COUPLED, and that has bitten twice already.

    CAVEAT-401 (a sample limit standing in for a window) and again in the fault injector.
    `stuck` needs 6 hours and the detectors need at least 12 samples to judge, so no cadence
    may be so slow that six hours holds fewer than that.
    """
    import inspect

    from orchestrator.services.anomaly import detectors

    min_hours = float(inspect.signature(detectors.stuck).parameters["min_hours"].default)
    for col, seconds in sensor_signal.CADENCE_S.items():
        samples = (min_hours * 3600.0) / seconds
        assert samples >= 12, (
            f"{col} at {seconds}s gives only {samples:.0f} samples in {min_hours:g}h, "
            f"below the 12 the detectors require"
        )


# ── deployment ─────────────────────────────────────────────────────────────────────────


def test_the_image_carries_the_signal_module():
    """Source correct and image broken is this project's BUG-343 pattern."""
    dockerfile = (_PUBLISHER_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY sensor_signal.py" in dockerfile


def test_the_module_is_not_named_signal():
    """`signal.py` in this directory would shadow the stdlib module the publisher uses
    for its SIGTERM handler, and the shadowing is silent."""
    assert not (_PUBLISHER_DIR / "signal.py").exists()
    assert (_PUBLISHER_DIR / "sensor_signal.py").exists()
    src = (_PUBLISHER_DIR / "mysql_dummy_publisher.py").read_text(encoding="utf-8")
    assert "import signal\n" in src, "the stdlib import must survive"
    assert "import sensor_signal as _signal" in src
