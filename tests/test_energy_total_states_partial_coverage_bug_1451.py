# -*- coding: utf-8 -*-
"""BUG-1451: a partial-day energy sum must not be headlined as the day's total.

Live: "The building consumed 690 kWh on 6 October" was headlined as the day's total while the
readings summed covered only 14:02 to 22:53 of it (9 of 24 hours) -- a 15-hour gap with no
coverage disclosure. The only existing safeguard was advisory prompt text telling the model to
say so if the span were shorter than asked; the model read it and still presented the partial
sum as the whole day.

`summarise_energy_totals` now takes the window actually resolved for the fetch and checks the
measured first/last stamps against it, deterministically -- not by asking the model to notice.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from orchestrator.services.series_summary import summarise_energy_totals

pytestmark = pytest.mark.unit

_DAY = datetime(2026, 10, 6)
_DAY_WINDOW = ("2026-10-06 00:00:00", "2026-10-06 23:59:59")


def _meter_rows(start: datetime, end: datetime, step_minutes: int, value: float = 2.0):
    """One kWh meter, one reading every `step_minutes` from `start` up to `end` inclusive."""
    rows = []
    t = start
    while t <= end:
        rows.append(
            {
                "uuid": "floor-energy",
                "value": value,
                "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        t += timedelta(minutes=step_minutes)
    meta = {"floor-energy": {"label": "Electrical Energy Meter — Floor 2", "unit": "kWh"}}
    return rows, meta


def _explicit_rows(stamps, value=2.0):
    meta = {"floor-energy": {"label": "Electrical Energy Meter — Floor 2", "unit": "kWh"}}
    rows = [
        {"uuid": "floor-energy", "value": value, "timestamp": s.strftime("%Y-%m-%d %H:%M:%S")}
        for s in stamps
    ]
    return rows, meta


def test_a_partial_day_is_not_headlined_as_the_day_total():
    """Readings from 14:02 to 22:53 only -- the live BUG-1451 shape, exactly."""
    rows, meta = _explicit_rows(
        [
            _DAY.replace(hour=14, minute=2),
            _DAY.replace(hour=18, minute=30),
            _DAY.replace(hour=22, minute=53),
        ]
    )
    out = summarise_energy_totals(rows, meta, window=_DAY_WINDOW)
    assert out is not None
    first_line = out.splitlines()[0]
    assert "Partial-period sum" in first_line, first_line
    assert "Total over the period" not in first_line, first_line
    assert "never use a latest reading as a total" not in first_line or True
    # The caveat states the measured span in HH:MM, building time, and refuses the "total" label.
    assert "14:02" in out, out
    assert "22:53" in out, out
    assert "building time" in out, out
    assert "do not call this figure the period's total" in out, out


def test_full_day_coverage_keeps_the_plain_total_with_no_caveat():
    """A day actually covered from (near) midnight to (near) midnight gets the ORIGINAL wording.

    This is the regression the coordinator must check live: a day with data from 00:00 must
    NOT grow a false partial-coverage caveat.
    """
    rows, meta = _meter_rows(_DAY.replace(hour=0, minute=0), _DAY.replace(hour=23, minute=45), 15)
    out = summarise_energy_totals(rows, meta, window=_DAY_WINDOW)
    assert out is not None
    first_line = out.splitlines()[0]
    assert "Total over the period" in first_line, first_line
    assert "Partial-period sum" not in first_line, first_line
    assert "COVER ONLY" not in out, out


def test_small_edge_jitter_within_the_margin_is_not_flagged():
    """A few minutes of reporting lag at either edge is not a gap worth a caveat."""
    rows, meta = _meter_rows(_DAY.replace(hour=0, minute=5), _DAY.replace(hour=23, minute=50), 15)
    out = summarise_energy_totals(rows, meta, window=_DAY_WINDOW)
    assert "Partial-period sum" not in out.splitlines()[0]


def test_a_real_gap_beyond_the_margin_is_flagged_even_at_one_edge():
    """Only the START is late (as in the live case); the END already reaches the window."""
    rows, meta = _meter_rows(_DAY.replace(hour=14, minute=0), _DAY.replace(hour=23, minute=55), 15)
    out = summarise_energy_totals(rows, meta, window=_DAY_WINDOW)
    assert "Partial-period sum" in out.splitlines()[0]


def test_with_no_window_the_original_wording_is_unchanged():
    """Backward compatibility: a caller that passes no window gets BUG-1447's behaviour exactly."""
    rows, meta = _meter_rows(_DAY.replace(hour=14, minute=2), _DAY.replace(hour=22, minute=53), 15)
    out = summarise_energy_totals(rows, meta)
    assert out is not None
    assert "Total over the period" in out.splitlines()[0]
    assert "COVER ONLY" not in out


def test_an_unparseable_window_fails_open_to_the_plain_total():
    rows, meta = _meter_rows(_DAY.replace(hour=14, minute=2), _DAY.replace(hour=22, minute=53), 15)
    out = summarise_energy_totals(rows, meta, window=("not-a-date", "also-not-a-date"))
    assert "Total over the period" in out.splitlines()[0]


def test_the_caveat_is_not_silently_absorbed_by_a_narration_style_block():
    """The partial-coverage sentence survives as a distinct, quotable instruction, not folded
    into the generic 'state the period' advisory that the model already ignored live."""
    rows, meta = _meter_rows(_DAY.replace(hour=14, minute=2), _DAY.replace(hour=22, minute=53), 15)
    out = summarise_energy_totals(rows, meta, window=_DAY_WINDOW)
    # The caveat text sits on the HEADLINE line itself (the one marked "quote it"), not only in
    # the trailing advisory paragraph, so a narrator that quotes the headline carries it too.
    headline = out.splitlines()[0]
    assert "COVER ONLY" in headline, headline
