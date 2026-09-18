# -*- coding: utf-8 -*-
"""A boiler's two water temperatures are one fact measured twice (BUG-664).

WHY THIS TEST EXISTS
--------------------
`plant_data` holds CORRELATED series. A boiler's entering and leaving water temperatures
are one physical fact measured twice, and their difference IS the answer to the demo
question "what's the delta-T across the heating circuit, and is it healthy?".

Publishing them as independent random walks collapsed that answer from 11.08 K to 0.12 K
(BUG-638). The response then was to drop plant_data from the publish map entirely — which
stopped the corruption and also stopped the data: by 2026-09-17 the series had decayed to
ambient and the live answer was **0.04 °C**, with the system recommending "inspect the pump
speed and check for flow restrictions" — a maintenance action invented from a generator
artefact.

So the publisher now derives each equipment group from ONE seed. These tests pin the
property that makes that worth doing. They are deliberately about the RELATIONSHIP between
points, because every individual value was plausible in the broken version too — which is
why nothing caught it.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

pytestmark = pytest.mark.unit

_PUB_DIR = Path(__file__).resolve().parents[1] / "mysql-dummy-publish-dev"
_MAP = Path(__file__).resolve().parents[1] / "input" / "bldg1_plant_publish_map.json"

pytest.importorskip("pymysql", reason="the publisher module imports pymysql at module scope")

if str(_PUB_DIR) not in sys.path:
    sys.path.insert(0, str(_PUB_DIR))

publisher = pytest.importorskip(
    "mysql_dummy_publisher", reason="publisher source not present in this checkout"
)


class _Cursor:
    def __init__(self, sink: List[Tuple[str, float]]):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, _sql, rows):
        self.sink.extend(rows)


class _Conn:
    """Captures what WOULD be written. No database is touched."""

    def __init__(self):
        self.rows: List[Tuple[str, float]] = []

    def cursor(self):
        return _Cursor(self.rows)


@pytest.fixture(scope="module")
def spec():
    if not _MAP.exists():
        pytest.skip("no plant publish map in this checkout (building not active)")
    return json.loads(_MAP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def samples(spec):
    """200 ticks of generated values, keyed by uuid."""
    publisher.load_plant_groups(str(_MAP))
    assert publisher.PLANT_GROUPS, "the map loaded no groups"
    out = {}
    conn = _Conn()
    for _ in range(200):
        conn.rows.clear()
        publisher.publish_plant(conn)
        for uuid, value in conn.rows:
            out.setdefault(uuid, []).append(float(value))
    return out


def _pairs(spec):
    for group in spec["groups"]:
        delta = group.get("delta")
        if delta:
            yield group["group"], group["roles"][delta["lead"]]["uuid"], group["roles"][
                delta["follow"]
            ]["uuid"], delta


# ── the property that was lost ───────────────────────────────────────────────


def test_every_correlated_pair_keeps_the_sign_its_history_had(spec, samples):
    """A boiler must leave hotter than it enters; a chiller must leave colder.

    Sign, not magnitude, is the part a reader would notice instantly: a chiller whose
    leaving water is warmer than its entering water is not a chiller.
    """
    for name, lead_id, follow_id, delta in _pairs(spec):
        want_positive = float(delta["mid"]) > 0
        observed = [a - b for a, b in zip(samples[lead_id], samples[follow_id])]
        wrong = [d for d in observed if (d > 0) != want_positive]
        assert not wrong, (
            f"{name}: {len(wrong)}/{len(observed)} samples have the wrong sign "
            f"(history median {delta['mid']:+.2f})"
        )


def test_no_pair_ever_collapses_to_near_zero(spec, samples):
    """0.04 K across a heating circuit is the defect this guards (BUG-638)."""
    for name, lead_id, follow_id, delta in _pairs(spec):
        observed = [abs(a - b) for a, b in zip(samples[lead_id], samples[follow_id])]
        assert min(observed) > 0.5, f"{name}: a sample collapsed to {min(observed):.3f} K"


def test_each_delta_stays_inside_the_band_its_history_occupied(spec, samples):
    for name, lead_id, follow_id, delta in _pairs(spec):
        lo, hi = sorted((float(delta["lo"]), float(delta["hi"])))
        observed = [a - b for a, b in zip(samples[lead_id], samples[follow_id])]
        out = [d for d in observed if not (lo - 0.5) <= d <= (hi + 0.5)]
        assert not out, f"{name}: {len(out)} samples outside [{lo:+.2f},{hi:+.2f}]: {out[:3]}"


def test_the_typical_delta_resembles_the_history_not_merely_its_range(spec, samples):
    """Staying in range is not the same as continuing the series.

    A uniform draw over a skewed band sits every sample inside the historical range while
    moving the typical value by 2 K, which is what a trend or a health judgement reads.
    """
    for name, lead_id, follow_id, delta in _pairs(spec):
        lo, hi = sorted((float(delta["lo"]), float(delta["hi"])))
        observed = statistics.median(a - b for a, b in zip(samples[lead_id], samples[follow_id]))
        tolerance = max(1.5, 0.35 * (hi - lo))
        assert abs(observed - float(delta["mid"])) <= tolerance, (
            f"{name}: generated median {observed:+.2f} vs history {delta['mid']:+.2f} "
            f"(tolerance {tolerance:.2f})"
        )


# ── what the fan may and may not do ──────────────────────────────────────────


def test_air_temperatures_never_read_zero_when_the_fan_stops(spec, samples):
    """A sensor in a still duct keeps reading the air; it does not report 0 C.

    Roughly half the stored history did exactly that, which is why the supply-air mean
    reads 8 C against a 20 C median of its non-zero rows.
    """
    for group in spec["groups"]:
        for role, entry in group["roles"].items():
            if role not in ("supply_air_temp", "return_air_temp"):
                continue
            vals = samples.get(entry["uuid"]) or []
            if vals:
                assert min(vals) > 5.0, f"{group['group']}/{role} published {min(vals)} C"


def test_flow_does_collapse_with_the_fan(spec, samples):
    """The mirror of the test above: flow SHOULD fall away when the fan is off.

    Without this, 'never publish a low number' would pass by pinning flow high, which
    would be a different falsehood.
    """
    checked = 0
    for group in spec["groups"]:
        roles = group["roles"]
        if "fan_status" not in roles or "supply_air_flow" not in roles:
            continue
        checked += 1
        fan = samples[roles["fan_status"]["uuid"]]
        flow = samples[roles["supply_air_flow"]["uuid"]]
        off = [f for f, s in zip(flow, fan) if s == 0.0]
        if off:
            assert max(off) < 5.0, f"{group['group']}: flow {max(off)} with the fan off"
    if not checked:
        pytest.skip("no AHU group carries both a fan status and a supply air flow")


def test_every_group_writes_every_one_of_its_points_each_tick(spec):
    publisher.load_plant_groups(str(_MAP))
    conn = _Conn()
    publisher.publish_plant(conn)
    expected = sum(len(g["roles"]) for g in spec["groups"])
    assert len(conn.rows) == expected
    assert len({u for u, _ in conn.rows}) == expected, "a uuid was written twice in one tick"


def test_a_missing_map_disables_plant_publishing_rather_than_raising():
    """A publisher that dies on a missing file takes every OTHER modality down with it."""
    publisher.load_plant_groups(os.path.join("does", "not", "exist.json"))
    assert publisher.PLANT_GROUPS == []
    assert publisher.publish_plant(_Conn()) == 0
    publisher.load_plant_groups(str(_MAP))  # restore for any later test
