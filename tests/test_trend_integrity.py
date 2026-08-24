# -*- coding: utf-8 -*-
"""Measurement change versus environmental change (V6-T42, rule R-14).

The most persuasive wrong answer available: relocating or recalibrating a sensor puts a step
change in its series, and a step change is exactly what a real building event looks like.
Reported as a trend, the answer is confident, specific, quantified -- and about nothing that
happened.

The verdict is graded on purpose. Refusing every trend that crosses a recalibration would
discard the long-horizon questions the research catalogues care most about, so a change with
long stable stretches either side is reported as two trends rather than none.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.history import ConfigurationPeriod
from orchestrator.services.evidence.trend_integrity import (
    TrendVerdict,
    artefact_kinds,
    assess_trend,
)

pytestmark = pytest.mark.unit

JAN = datetime(2026, 1, 1)
MAR = datetime(2026, 3, 1)
JUN = datetime(2026, 6, 1)
ROOM_A = "http://x/Room2.15"
ROOM_B = "http://x/Room3.20"

STABLE = [ConfigurationPeriod(JAN, None, ROOM_A, "commissioning")]
RELOCATED = [
    ConfigurationPeriod(JAN, MAR, ROOM_A, "commissioning"),
    ConfigurationPeriod(MAR, None, ROOM_B, "relocation"),
]


def test_a_stable_window_is_reportable():
    t = assess_trend(STABLE, datetime(2026, 1, 10), datetime(2026, 2, 10))
    assert t.verdict is TrendVerdict.REPORTABLE
    assert t.may_report_single_trend
    assert t.describe() == ""  # nothing to say when nothing happened


def test_a_change_with_long_sides_is_segmented_not_refused():
    """The judgement that keeps this useful rather than merely safe."""
    t = assess_trend(RELOCATED, MAR - timedelta(days=30), MAR + timedelta(days=30))
    assert t.verdict is TrendVerdict.SEGMENTED
    assert not t.may_report_single_trend
    assert len(t.segments) == 2
    assert "reported separately" in t.describe()


def test_a_change_with_short_sides_supports_no_trend():
    """A fragment either side has no shape to report."""
    t = assess_trend(RELOCATED, MAR - timedelta(hours=6), MAR + timedelta(hours=6))
    assert t.verdict is TrendVerdict.NOT_COMPARABLE
    assert "no trend is reported" in t.describe()


def test_the_caveat_names_what_changed():
    """A relocation invalidates the SPACE; a recalibration invalidates the VALUE.

    'Something changed' leaves the reader unable to tell which of their conclusions survives.
    """
    t = assess_trend(RELOCATED, MAR - timedelta(days=30), MAR + timedelta(days=30))
    assert "relocation" in t.caveat


def test_no_recorded_history_is_reportable_not_suspect():
    """Deliberate.

    Treating unknown history as suspect would make every trend on every building
    unreportable until somebody backfilled metadata -- trading a rare wrong answer for a
    universal useless one. The gap is surfaced by the observability matrix instead, where it
    is actionable.
    """
    assert assess_trend([], JAN, JUN).verdict is TrendVerdict.REPORTABLE


def test_artefact_kinds_are_listed_individually():
    periods = [
        ConfigurationPeriod(JAN, MAR, ROOM_A, "commissioning"),
        ConfigurationPeriod(MAR, JUN, ROOM_A, "recalibration"),
        ConfigurationPeriod(JUN, None, ROOM_B, "relocation"),
    ]
    t = assess_trend(periods, datetime(2026, 2, 1), datetime(2026, 7, 1))
    kinds = artefact_kinds(t.integrity)
    assert kinds == ["recalibration", "relocation"]


def test_a_change_exactly_at_the_window_start_is_not_a_discontinuity():
    """That is the window's own configuration, not a change inside it."""
    assert assess_trend(RELOCATED, MAR, JUN).verdict is TrendVerdict.REPORTABLE


def test_segments_carry_the_location_in_force():
    t = assess_trend(RELOCATED, MAR - timedelta(days=30), MAR + timedelta(days=30))
    locations = [seg[2] for seg in t.segments]
    assert locations == [ROOM_A, ROOM_B]


def test_a_single_trend_number_is_only_permitted_when_nothing_changed():
    """The property every caller must check before quoting one figure."""
    assert assess_trend(STABLE, JAN, JUN).may_report_single_trend is True
    assert assess_trend(RELOCATED, JAN, JUN).may_report_single_trend is False
