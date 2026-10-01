# -*- coding: utf-8 -*-
"""A binary point must read the same clock the continuous branch reads (BUG-1130).

THE DEFECT THESE PIN
--------------------
``sensor_signal.next_value`` branches on ``dec == 0 and span <= 1.0``. Every one of bldg1's
234 ``Room<N>_sat_occupancy_status`` series is declared ``lo=0 hi=1 dec=0``, so span is
exactly 1.0 and all of them took that branch -- which seeded 1 with a fixed p=0.25, flipped
with a fixed p=0.08, and **never called ``centre()``**. It therefore never read ``when``, and
``DIURNAL["occupancy"] = 0.9`` was declared and never seen.

The 233 ``Room<N>_sat_occupancy`` COUNTERS beside them are ``lo=0 hi=30``, took the continuous
branch, and did follow the day. Measured in the store over ten days: the counter ran 3.9 at
02:00 to 29.3 at 13:00, while the flag sat between 0.41 and 0.59 at every hour with no shape.
One room, one phenomenon, two series, two models, no shared clock -- so "is room X occupied"
and "how many people are in room X" disagreed, and which of them was right depended on the
hour you asked at.

These tests pin the property that was missing (a flag tracks the hour), the properties that
must SURVIVE the fix (it still holds state; it is still 0/1; a door still has no daily cycle),
and the one structural fact behind BUG-1150 (a boolean point may never emit a value above 1).
"""

import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PUBLISHER_DIR = Path(__file__).resolve().parent.parent / "mysql-dummy-publish-dev"
if str(_PUBLISHER_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISHER_DIR))

sensor_signal = pytest.importorskip("sensor_signal")

_DAY = datetime(2026, 9, 3, 0, 0, 0)


@pytest.fixture(autouse=True)
def _clean_state():
    sensor_signal.reset_state()
    yield
    sensor_signal.reset_state()


def _hourly_means(col, lo, hi, dec, step_s, sensors=12, days=3, tag="s"):
    """Mean reading per hour of day, pooled over several sensors and several days."""
    sensor_signal.reset_state()
    by_hour = {h: [] for h in range(24)}
    for i in range(sensors):
        uuid = f"{tag}-{col}-{i}"
        when = _DAY
        end = _DAY + timedelta(days=days)
        while when < end:
            value, _ = sensor_signal.next_value(uuid, col, lo, hi, dec, when, step_s=step_s)
            by_hour[when.hour].append(float(value))
            when += timedelta(seconds=step_s)
    return {h: statistics.mean(v) for h, v in by_hour.items()}


def _pearson(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) ** 0.5) * (sum((b - my) ** 2 for b in ys) ** 0.5)
    return num / den if den else 0.0


# ── the value domain: a status is not a count (BUG-1150) ───────────────────────────────


@pytest.mark.parametrize("col", ["occupancy", "contact", "lux", "generic", "something_new"])
def test_a_boolean_band_never_produces_a_value_above_one(col):
    """A point declared 0..1 with no decimals is a status, whatever modality it belongs to.

    BUG-1150: a booking-status point whose own label reads "(available=0 / booked=1)" held
    values to 189.48. That came from a wider declared band rather than from this branch, but
    the branch is the last line of defence and it must never be the source.
    """
    sensor_signal.reset_state()
    when = _DAY
    for _ in range(600):
        value, raw = sensor_signal.next_value(f"u-{col}", col, 0, 1, 0, when)
        assert value in (0, 1), f"{col} emitted {value!r} from a 0..1 band"
        assert 0.0 <= float(raw) <= 1.0
        when += timedelta(minutes=5)


def test_a_counter_and_a_flag_of_the_same_room_are_not_confused():
    """The 0..30 band must still give a count, or the fix has traded one error for another."""
    counts = [
        sensor_signal.next_value("u-count", "occupancy", 0, 30, 0, _DAY.replace(hour=13))[0]
        for _ in range(200)
    ]
    assert max(counts) > 1, "a 0..30 occupancy point should read like a count"


# ── the missing property: a flag tracks the hour ───────────────────────────────────────


def test_the_binary_branch_reads_the_clock_at_all():
    """The narrowest statement of BUG-1130: `when` must change the answer."""
    phase = sensor_signal._phase("u-any")
    night = sensor_signal.on_probability("occupancy", 0, 1, _DAY.replace(hour=2), phase)
    noon = sensor_signal.on_probability("occupancy", 0, 1, _DAY.replace(hour=13), phase)
    assert noon > night + 0.4, f"midday {noon:.3f} is not meaningfully above 02:00 {night:.3f}"


def test_a_presence_flag_is_more_likely_on_during_the_day_than_at_night():
    means = _hourly_means("occupancy", 0, 1, 0, 60, tag="flag")
    day = statistics.mean(means[h] for h in (11, 12, 13, 14, 15))
    night = statistics.mean(means[h] for h in (0, 1, 2, 3, 4))
    assert day > night + 0.3, f"daytime {day:.3f} vs overnight {night:.3f} — measured 0.41..0.59"


def test_a_presence_flag_correlates_with_the_hour_of_day():
    """Correlation against the modality's own declared diurnal centre, not a hand-drawn curve."""
    means = _hourly_means("occupancy", 0, 1, 0, 60, tag="corr")
    centre = [
        sensor_signal.centre("occupancy", 0.0, 1.0, _DAY.replace(hour=h), 0.0) for h in range(24)
    ]
    r = _pearson([means[h] for h in range(24)], centre)
    assert r > 0.85, f"hourly mean correlates with the declared shape at only r={r:.3f}"


def test_the_flag_and_the_counter_agree_about_the_day():
    """The contradiction BUG-1042 was opened about: one room, two series, two answers."""
    flag = _hourly_means("occupancy", 0, 1, 0, 60, tag="pair-flag")
    count = _hourly_means("occupancy", 0, 30, 0, 60, tag="pair-count")
    r = _pearson([flag[h] for h in range(24)], [count[h] for h in range(24)])
    assert r > 0.9, f"flag and counter of one modality correlate at only r={r:.3f}"


# ── properties that must survive the fix ───────────────────────────────────────────────


def test_a_door_contact_acquires_no_daily_cycle():
    """`DIURNAL['contact'] = 0.0` says a door does not track the working day. Still true."""
    means = _hourly_means("contact", 0, 1, 0, 300, sensors=16, days=4, tag="door")
    spread = max(means.values()) - min(means.values())
    assert spread < 0.25, f"a door acquired an hourly swing of {spread:.3f}"


def test_a_binary_point_still_holds_its_state():
    """Persistence is why a real change stands out. A flag that flips every write is noise."""
    values = [
        sensor_signal.next_value("u-hold", "contact", 0, 1, 0, _DAY.replace(hour=12))[0]
        for _ in range(300)
    ]
    flips = sum(1 for i in range(1, len(values)) if values[i] != values[i - 1])
    assert flips < len(values) * 0.25, f"{flips} flips in {len(values)} writes is not a door"


def test_a_door_keeps_the_flip_rate_it_had_before_the_change():
    """`contact` reports at the reference cadence, so the cadence scaling is exactly 1.0 there.

    This is the guard on the second half of the fix: if someone changes
    `_FLIP_REFERENCE_CADENCE_S` or the contact cadence without thinking, doors change
    behaviour silently.
    """
    assert sensor_signal.flip_rate_for("contact") == pytest.approx(sensor_signal._FLIP_P)


def test_a_faster_modality_gets_a_proportionally_smaller_per_write_flip_probability():
    """_FLIP_P is quoted as 'roughly one change an hour at a 300s cadence'.

    Occupancy reports every 60s. A constant per-write probability therefore made it change
    five times as often as the comment claims — measured live at 0.0743 flips per write.
    """
    fast = sensor_signal.flip_rate_for("occupancy")
    slow = sensor_signal.flip_rate_for("contact")
    ratio = sensor_signal.cadence_for("occupancy") / sensor_signal.cadence_for("contact")
    assert fast == pytest.approx(slow * ratio)


def test_a_caller_writing_at_its_own_interval_can_say_so():
    """The gap backfill steps 15 minutes, not 60 seconds (BUG-1139)."""
    assert sensor_signal.flip_rate_for("occupancy", step_s=900) > sensor_signal.flip_rate_for(
        "occupancy"
    )
    assert sensor_signal.flip_rate_for("occupancy", step_s=10_000) <= 0.5


# ── the source-parsing contract the anomaly scanner depends on ─────────────────────────


def test_the_scanner_can_still_read_the_cadence_table_out_of_this_source():
    """`anomaly/scanner.py` PARSES this file rather than importing it, over a 900-char window.

    A new integer-valued mapping added near `CADENCE_S` would be read as a cadence and could
    silently shrink every detector's fetch window. Pinning a source layout is unpleasant, but
    less unpleasant than the scanner reading a constant that is not a cadence (lessons #151).
    """
    import re

    from orchestrator.services.anomaly import scanner

    block = (_PUBLISHER_DIR / "sensor_signal.py").read_text(encoding="utf-8")
    start = block.index("CADENCE_S")
    parsed = [int(v) for v in re.findall(r":\s*(\d+)\s*,", block[start : start + 900])]
    assert parsed, "the scanner's regex now reads nothing out of this file"
    assert sorted(set(parsed)) == sorted(set(sensor_signal.CADENCE_S.values())), (
        "the scanner's source parse no longer agrees with the CADENCE_S dict — something "
        "integer-valued was added within 900 characters of it"
    )
    assert scanner._FASTEST_CADENCE_S == float(min(sensor_signal.CADENCE_S.values()))
