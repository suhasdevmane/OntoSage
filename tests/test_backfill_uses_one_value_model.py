# -*- coding: utf-8 -*-
"""One series must not carry two value models (BUG-1139).

WHAT WENT WRONG
---------------
``scripts/backfill_narrow_gap.py`` had its own ``_shape``: a diurnal sine plus a jitter of 6%
of the range, applied to every point and then rounded. For a 0/1 flag with a swing of 0.9 the
jitter is far too small to move ``int(round())`` except at the crossing, so the value was 0
whenever the centre sat below 0.5 and 1 whenever it sat above -- a perfect square wave
switching at exactly 07:00 and 19:00, identical for all 234 presence flags because the only
per-sensor term moved the value by at most 0.06.

Measured in the store: over the backfilled days 2026-09-25..28 the hourly mean of those flags
was 0.00 from 20:00 to 05:00 and 1.00 from 08:00 to 17:00, pooled range 1.000. Over the live
days either side the same flags sat at 0.45..0.56. The same series answered "was room X
occupied last Friday" from a tidy working day and "is room X occupied now" from a coin.

The fix is not a second copy of the live generator's branch -- two near-identical range and
diurnal tables are how the two writers came to disagree in the first place. The backfill now
imports ``sensor_signal`` and calls the same function the publisher calls.

These tests pin that there is ONE model (a source check, because a reintroduced local model
would otherwise pass every behavioural test it was tuned for), and that a backfilled binary
point is neither a square wave nor a clockless coin.
"""

import importlib.util
import random
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "backfill_narrow_gap.py"
_PUBLISHER_DIR = _REPO / "mysql-dummy-publish-dev"
if str(_PUBLISHER_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISHER_DIR))

sensor_signal = pytest.importorskip("sensor_signal")


def _load():
    """Import the script by path — `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location("backfill_narrow_gap", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backfill = _load()

_DAY = datetime(2026, 9, 3, 0, 0, 0)
_STEP_S = 900.0


def _walk(point, days=3, step_s=_STEP_S):
    sensor_signal.reset_state()
    by_hour = {h: [] for h in range(24)}
    when = _DAY
    while when < _DAY + timedelta(days=days):
        by_hour[when.hour].append(float(backfill._value_from(point, when, step_s)))
        when += timedelta(seconds=step_s)
    return {h: statistics.mean(v) for h, v in by_hour.items()}


def _flag(i):
    return {"uuid": f"flag-{i}", "value_col": "occupancy", "lo": 0.0, "hi": 1.0, "dec": 0}


# ── there is exactly one value model ───────────────────────────────────────────────────


def test_the_backfill_has_no_value_model_of_its_own():
    """A source check, deliberately.

    A reintroduced local `_shape` would satisfy every behavioural test below if it were tuned
    to -- the failure mode here is not a wrong curve, it is a SECOND curve that drifts from
    the first. The only durable statement is that there is one.
    """
    import re

    src = _SCRIPT.read_text(encoding="utf-8")
    assert "import sensor_signal" in src, "the backfill must use the publisher's generator"
    # An ASSIGNMENT, not a mention: the file names both of these in comments explaining why
    # they are gone, and a substring check would fail on its own tombstone.
    assert not re.search(
        r"^\s*def\s+_shape\s*\(", src, re.M
    ), "a local value model has come back — that is BUG-1139"
    assert not re.search(
        r"^\s*_DIURNAL\s*[:=]", src, re.M
    ), "a second diurnal table has come back — that is BUG-1139"


def test_the_backfill_and_the_publisher_produce_the_same_reading():
    """Same point, same instant, same interval — the two writers must not diverge."""
    point = {"uuid": "same-1", "value_col": "temp_c", "lo": 18.0, "hi": 26.0, "dec": 1}
    random.seed(1234)
    sensor_signal.reset_state()
    theirs = sensor_signal.next_value(
        "same-1", "temp_c", 18.0, 26.0, 1, _DAY.replace(hour=13), step_s=_STEP_S
    )[0]
    random.seed(1234)
    sensor_signal.reset_state()
    ours = backfill._value_from(point, _DAY.replace(hour=13), _STEP_S)
    assert ours == theirs


def test_a_point_without_a_declared_band_still_falls_back_to_the_range_table():
    """The narrow map leaves `lo`/`hi` off some entries; that path must survive the rewrite."""
    lo, hi, dec, col = backfill._point_range({"uuid": "x", "value_col": "noise_db"})
    assert (lo, hi, dec, col) == (30.0, 70.0, 1, "noise_db")


# ── a backfilled binary point is not a square wave ─────────────────────────────────────


def test_a_backfilled_flag_is_not_the_same_value_for_every_sensor_at_every_hour():
    """The tell: every backfilled timestamp carried all 234 flags at the SAME value."""
    per_sensor = [_walk(_flag(i)) for i in range(10)]
    identical_hours = sum(1 for h in range(24) if len({round(m[h], 6) for m in per_sensor}) == 1)
    assert identical_hours < 12, (
        f"{identical_hours} of 24 hours have all ten sensors reading identically — "
        f"that is the square wave, not a building"
    )


def test_a_backfilled_flag_is_not_saturated_at_both_ends():
    """0.00 overnight and 1.00 all afternoon, with a pooled range of exactly 1.000."""
    pooled = [
        statistics.mean(m[h] for m in (_walk(_flag(i)) for i in range(10))) for h in range(24)
    ]
    assert max(pooled) < 0.999, f"pooled hourly max {max(pooled):.4f} — every sensor on at once"
    assert min(pooled) > 0.001, f"pooled hourly min {min(pooled):.4f} — every sensor off at once"


def test_a_backfilled_flag_still_follows_the_day():
    """Not a square wave must not become not a cycle — the live series has one."""
    pooled = {
        h: statistics.mean(m[h] for m in (_walk(_flag(i)) for i in range(10))) for h in range(24)
    }
    day = statistics.mean(pooled[h] for h in (11, 12, 13, 14, 15))
    night = statistics.mean(pooled[h] for h in (0, 1, 2, 3, 4))
    assert day > night + 0.3, f"daytime {day:.3f} vs overnight {night:.3f}"


def test_a_backfilled_flag_never_exceeds_one():
    for i in range(4):
        means = _walk(_flag(i))
        assert max(means.values()) <= 1.0


def test_a_backfilled_door_contact_has_no_daily_cycle():
    """`contact` has a diurnal of 0.0; the old `_shape` turned that into a 50/50 coin decided
    by phase, which made a door's whole history a function of its position in a list."""
    per_sensor = [
        _walk({"uuid": f"door-{i}", "value_col": "contact", "lo": 0.0, "hi": 1.0, "dec": 0})
        for i in range(12)
    ]
    pooled = {h: statistics.mean(m[h] for m in per_sensor) for h in range(24)}
    spread = max(pooled.values()) - min(pooled.values())
    assert spread < 0.35, f"a door acquired an hourly swing of {spread:.3f}"


def test_the_backfill_tells_the_generator_its_own_interval():
    """It steps 15 minutes, not the modality's 60-second cadence.

    Without `step_s` the hold-and-flip rate is tuned for writes fifteen times closer together,
    the chain mixes far too slowly, and the daily swing comes out muted rather than absent —
    a quieter version of the same defect.
    """
    src = _SCRIPT.read_text(encoding="utf-8")
    assert "step_s=step_s" in src or "step_s=" in src
    assert "step.total_seconds()" in src
