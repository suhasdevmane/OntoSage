# -*- coding: utf-8 -*-
"""Computed sensor health (V6-T08) and conflict reporting (V6-T18, acceptance scenario 4).

The failure both of these prevent is quiet. A stale stream keeps answering with its last
value; two disagreeing sensors get averaged into a number neither measured. Neither leaves a
trace in the generated text, so neither is caught by any guard aimed at prose.

Properties pinned here:

* UNKNOWN health is NOT usable -- a sensor we could not assess is not thereby fine;
* drift needs at least two peers, because with one peer nothing says which sensor moved;
* stale beats drifting in precedence -- otherwise someone is sent to recalibrate an
  instrument whose actual problem is that it stopped reporting;
* a conflicting group has NO representative value, so a caller cannot silently take a mean.
"""

from datetime import datetime, timedelta

import pytest

from orchestrator.services.evidence.conflict import Reading, detect, detect_all
from orchestrator.services.evidence.sensor_health import (
    MIN_PEERS_FOR_DRIFT,
    HealthState,
    assess_drift,
    assess_sensor,
    summarise,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 12, 0, 0)


def _recent(n=10, step_min=1, age_min=1):
    newest = NOW - timedelta(minutes=age_min)
    return [newest - timedelta(minutes=i * step_min) for i in range(n)]


# ── health ───────────────────────────────────────────────────────────────────


def test_no_observations_is_no_data_not_healthy():
    h = assess_sensor("s1", [], NOW, max_age_minutes=15)
    assert h.state is HealthState.NO_DATA
    assert not h.usable


def test_old_stream_is_stale_and_says_how_old():
    h = assess_sensor("s1", [NOW - timedelta(hours=8)], NOW, max_age_minutes=15)
    assert h.state is HealthState.STALE
    assert not h.usable
    assert "480" in h.detail or "minutes old" in h.detail


def test_fresh_and_agreeing_is_healthy():
    h = assess_sensor(
        "s1",
        _recent(),
        NOW,
        max_age_minutes=15,
        latest_value=21.0,
        peer_values=[21.2, 20.8, 21.1],
        agreement_tolerance=1.5,
    )
    assert h.state is HealthState.HEALTHY
    assert h.usable


def test_fresh_but_disagreeing_is_drifting():
    h = assess_sensor(
        "s1",
        _recent(),
        NOW,
        max_age_minutes=15,
        latest_value=28.0,
        peer_values=[21.2, 20.8, 21.1],
        agreement_tolerance=1.5,
    )
    assert h.state is HealthState.DRIFTING
    assert not h.usable
    assert "beyond" in h.detail


def test_stale_takes_precedence_over_drift():
    """Otherwise someone recalibrates an instrument that has simply stopped reporting."""
    h = assess_sensor(
        "s1",
        [NOW - timedelta(hours=8)],
        NOW,
        max_age_minutes=15,
        latest_value=99.0,
        peer_values=[21.0, 21.1, 20.9],
        agreement_tolerance=1.5,
    )
    assert h.state is HealthState.STALE


def test_fresh_with_no_peers_is_unknown_not_healthy():
    """The distinction that matters: unassessed is not a clean bill of health."""
    h = assess_sensor("s1", _recent(), NOW, max_age_minutes=15, latest_value=21.0)
    assert h.state is HealthState.UNKNOWN
    assert not h.usable


def test_missing_rate_uses_the_declared_expectation():
    h = assess_sensor("s1", _recent(n=45), NOW, max_age_minutes=15, expected_samples=60)
    assert h.missing_rate == pytest.approx(0.25)


def test_missing_rate_is_none_without_an_expectation():
    assert assess_sensor("s1", _recent(), NOW, max_age_minutes=15).missing_rate is None


# ── drift ────────────────────────────────────────────────────────────────────


def test_one_peer_cannot_establish_drift():
    """With n=1 the disagreement is symmetric - nothing says which sensor moved."""
    v = assess_drift(28.0, [21.0], tolerance=1.5)
    assert v.is_drifting is False
    assert v.judged is False
    assert str(MIN_PEERS_FOR_DRIFT) in v.reason


def test_drift_uses_the_median_so_one_failed_peer_cannot_swing_it():
    """A peer stuck at a rail value would drag a MEAN far enough to invert the verdict."""
    v = assess_drift(21.0, [21.1, 20.9, 0.0], tolerance=1.5)
    assert v.peer_median == pytest.approx(20.9)
    assert v.is_drifting is False


def test_drift_without_a_tolerance_is_unjudged():
    v = assess_drift(28.0, [21.0, 21.1, 20.9], tolerance=None)
    assert v.judged is False
    assert "cannot be judged" in v.reason


def test_no_current_reading_is_not_drift():
    assert assess_drift(None, [21.0, 21.1], tolerance=1.5).is_drifting is False


def test_summarise_counts_every_state():
    healths = [
        assess_sensor("a", [], NOW, 15),
        assess_sensor("b", [NOW - timedelta(hours=9)], NOW, 15),
    ]
    counts = summarise(healths)
    assert counts["no_data"] == 1 and counts["stale"] == 1
    assert set(counts) == {s.value for s in HealthState}


# ── conflict ─────────────────────────────────────────────────────────────────


def test_disagreeing_sensors_are_reported_not_averaged():
    """Acceptance scenario 4. 21 and 27.4 must not become 24.2."""
    rep = detect(
        "http://x/Room2.15",
        "temperature",
        [Reading("s1", 21.0, "north wall", "C"), Reading("s2", 27.4, "south wall", "C")],
        tolerance=1.5,
    )
    assert rep.conflicting
    text = rep.describe()
    assert "21" in text and "27.4" in text
    assert "averaging" in text


def test_a_conflicting_group_offers_no_single_value():
    """A caller must handle the disagreement, not receive a silent average."""
    rep = detect(
        "http://x/R", "temperature", [Reading("s1", 21.0), Reading("s2", 27.4)], tolerance=1.5
    )
    assert rep.representative() is None


def test_agreeing_sensors_yield_a_representative_value():
    rep = detect(
        "http://x/R", "temperature", [Reading("s1", 21.0), Reading("s2", 21.4)], tolerance=1.5
    )
    assert rep.conflicting is False
    assert rep.representative() == pytest.approx(21.2)
    assert rep.describe() == ""  # agreement needs no narration


def test_one_sensor_is_not_a_conflict_but_is_also_not_agreement():
    rep = detect("http://x/R", "temperature", [Reading("s1", 21.0)], tolerance=1.5)
    assert rep.conflicting is False
    assert rep.judged is False
    assert "nothing to cross-check" in rep.reason


def test_no_tolerance_means_unjudged_rather_than_agreeing():
    rep = detect("http://x/R", "exotic", [Reading("s1", 1.0), Reading("s2", 99.0)], tolerance=None)
    assert rep.judged is False
    assert rep.conflicting is False
    assert "cannot be judged" in rep.reason


def test_detect_all_returns_only_real_conflicts():
    """A report per agreeing group would bury the ones that matter."""
    grouped = {
        ("http://x/A", "temperature"): [Reading("a1", 21.0), Reading("a2", 27.0)],
        ("http://x/B", "temperature"): [Reading("b1", 21.0), Reading("b2", 21.2)],
    }
    out = detect_all(grouped, {"temperature": 1.5})
    assert len(out) == 1
    assert out[0].space == "http://x/A"


def test_conflict_module_has_no_notion_of_distance():
    """Co-location comes from the graph, never from geometry - as in spatial adequacy."""
    from pathlib import Path

    from scripts.check_building_literals import _prose_lines

    p = (
        Path(__file__).resolve().parent.parent
        / "orchestrator"
        / "services"
        / "evidence"
        / "conflict.py"
    )
    src = p.read_text(encoding="utf-8")
    prose = _prose_lines(src)
    code = "\n".join(l for n, l in enumerate(src.splitlines(), 1) if n not in prose).lower()
    for banned in ("distance", "proximity", "metres"):
        assert banned not in code
