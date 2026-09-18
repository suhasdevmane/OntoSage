# -*- coding: utf-8 -*-
"""Waste fill is a sawtooth and weight follows it; a damper follows its fan (BUG-649).

WHY THE SHAPE IS THE POINT
--------------------------
``waste_fill``, ``waste_weight`` and ``damper_position`` were declared in
``config/saturation_modalities.yaml`` and never provisioned — each resolved to zero points,
so the building answered "not measured" to every question about them.

Provisioning them is only half the work, because the questions these modalities exist for
are about their SHAPE, not their level:

  * "Which bins need emptying?" and "how often are they collected?" need fill to ACCUMULATE
    AND RESET. A random walk answers neither, while every individual reading still looks
    like a plausible percentage.
  * "How much did we divert from landfill?" needs weight to track fill through the bin's own
    capacity — and general waste is denser than mixed dry recycling, so one constant across
    both streams makes every recycling weight wrong.
  * A damper that does not follow its air handler is noise with a percent sign.

So these tests assert relationships and shapes. Individual values were plausible in every
broken version this project has shipped; that is precisely why nothing caught them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_PUB_DIR = _REPO / "mysql-dummy-publish-dev"
_WASTE_MAP = _REPO / "input" / "bldg1_waste_publish_map.json"
_PLANT_MAP = _REPO / "input" / "bldg1_plant_publish_map.json"

pytest.importorskip("pymysql", reason="the publisher imports pymysql at module scope")

if str(_PUB_DIR) not in sys.path:
    sys.path.insert(0, str(_PUB_DIR))

publisher = pytest.importorskip("mysql_dummy_publisher")


class _Cursor:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        self.sink.append((sql, list(rows)))


class _Conn:
    def __init__(self):
        self.calls: List[Tuple[str, list]] = []

    def cursor(self):
        return _Cursor(self.calls)


@pytest.fixture(scope="module")
def waste_doc():
    if not _WASTE_MAP.exists():
        pytest.skip("no waste publish map (building not active)")
    return json.loads(_WASTE_MAP.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def waste_series(waste_doc):
    """{uuid: [values]} over many ticks, plus a role index."""
    publisher.load_waste_bins(str(_WASTE_MAP))
    assert publisher.WASTE_BINS, "map loaded no bins"
    out: Dict[str, List[float]] = {}
    conn = _Conn()
    from datetime import datetime, timedelta

    when = datetime(2026, 9, 1, 8, 0)  # a Tuesday morning: occupied
    for _ in range(600):
        conn.calls.clear()
        publisher.publish_waste(conn, now_dt=when)
        for _sql, rows in conn.calls:
            for uuid, value in rows:
                out.setdefault(uuid, []).append(float(value))
        when += timedelta(minutes=5)
    return out


def _roles(waste_doc):
    for b in waste_doc["bins"]:
        yield b, b["roles"]["fill"]["uuid"], b["roles"]["weight"]["uuid"]


# ── fill is a sawtooth ───────────────────────────────────────────────────────


def test_every_bin_both_fills_and_empties(waste_doc, waste_series):
    for b, fill_id, _w in _roles(waste_doc):
        vals = waste_series[fill_id]
        rises = sum(1 for a, c in zip(vals, vals[1:]) if c > a)
        drops = [a - c for a, c in zip(vals, vals[1:]) if c < a - 20]
        assert rises > len(vals) * 0.5, f"{b['bin']}: fill rarely rises"
        assert drops, f"{b['bin']}: fill never dropped — a bin that is never collected"


def test_fill_stays_a_percentage(waste_doc, waste_series):
    for b, fill_id, _w in _roles(waste_doc):
        vals = waste_series[fill_id]
        assert min(vals) >= 0.0 and max(vals) <= 100.0, f"{b['bin']}: {min(vals)}..{max(vals)}"


def test_a_collection_empties_the_bin_rather_than_nudging_it(waste_doc, waste_series):
    """The reset must be a real emptying, not a large random step."""
    for b, fill_id, _w in _roles(waste_doc):
        vals = waste_series[fill_id]
        after = [c for a, c in zip(vals, vals[1:]) if c < a - 20]
        assert after, f"{b['bin']}: no collection observed"
        assert max(after) < 15.0, f"{b['bin']}: 'collected' bin left at {max(after)}%"


# ── weight follows fill, through the stream's own capacity ───────────────────


def test_weight_rises_and_falls_with_fill(waste_doc, waste_series):
    """Compared only where the fill ACTUALLY MOVED.

    The first version of this test compared every consecutive pair and failed at 86%. The
    generator was not at fault there and neither was the instrument: the run spans nights,
    when a bin gains about 0.04 kg per reading while a load cell's own noise is larger than
    that. A real weight sensor on a still bin reads flat with noise, so demanding a matching
    direction from a signal that is not there measures nothing. Below the noise floor the
    right assertion is the next test's — that weight does not WANDER.
    """
    for b, fill_id, weight_id in _roles(waste_doc):
        fills = waste_series[fill_id]
        weights = waste_series[weight_id]
        assert len(fills) == len(weights)
        moved = [
            ((f1 > f0), (w1 > w0))
            for (f0, f1, w0, w1) in zip(fills, fills[1:], weights, weights[1:])
            if abs(f1 - f0) >= 0.3
        ]
        assert len(moved) > 50, f"{b['bin']}: only {len(moved)} readings where fill moved"
        agree = sum(1 for want, got in moved if want == got)
        assert agree > 0.95 * len(moved), (
            f"{b['bin']}: weight followed fill on {agree}/{len(moved)} of the readings "
            f"where the fill actually changed"
        )


def test_weight_does_not_wander_while_a_bin_sits_still(waste_doc, waste_series):
    """The other half: below the signal, weight must be steady, not drifting.

    Together with the test above this pins the real property — weight tracks fill when
    there is fill to track, and stays put when there is not. Either test alone could be
    satisfied by a generator that is wrong in the other direction.
    """
    capacity = waste_doc["capacity_kg"]
    for b, fill_id, weight_id in _roles(waste_doc):
        cap = float(capacity.get(b["stream"], 40.0))
        steady = [
            abs(w1 - w0)
            for (f0, f1, w0, w1) in zip(
                waste_series[fill_id],
                waste_series[fill_id][1:],
                waste_series[weight_id],
                waste_series[weight_id][1:],
            )
            if abs(f1 - f0) < 0.1
        ]
        if steady:
            # A tenth of one percent of the bin's capacity is a generous noise floor.
            assert max(steady) < cap * 0.02, (
                f"{b['bin']}: weight moved {max(steady):.2f} kg while the fill did not"
            )


def test_an_empty_bin_still_weighs_something(waste_doc, waste_series):
    """The container has a tare weight; a bin at 2% does not weigh nothing."""
    for b, fill_id, weight_id in _roles(waste_doc):
        low = [w for f, w in zip(waste_series[fill_id], waste_series[weight_id]) if f < 8.0]
        if low:
            assert min(low) > 0.5, f"{b['bin']}: emptied bin weighed {min(low)} kg"


def test_the_two_streams_do_not_share_one_density(waste_doc, waste_series):
    """Mixed dry recycling is mostly air; general waste is not.

    Without this, a single capacity constant would pass every other test here while making
    every recycling weight wrong.
    """
    capacity = waste_doc["capacity_kg"]
    assert len(set(capacity.values())) > 1, "both streams share a capacity"
    per_stream = {}
    for b, fill_id, weight_id in _roles(waste_doc):
        full = [
            w for f, w in zip(waste_series[fill_id], waste_series[weight_id]) if f > 80.0
        ]
        if full:
            per_stream.setdefault(b["stream"], []).append(max(full))
    if len(per_stream) > 1:
        general = max(per_stream.get("General", [0]))
        recycling = max(per_stream.get("Recycling", [0]))
        assert general > recycling, (
            f"a full general-waste bin ({general} kg) should outweigh a full recycling "
            f"bin ({recycling} kg)"
        )


def test_a_missing_waste_map_disables_publishing_rather_than_raising():
    publisher.load_waste_bins("no/such/waste.json")
    assert publisher.WASTE_BINS == []
    assert publisher.publish_waste(_Conn()) == 0
    publisher.load_waste_bins(str(_WASTE_MAP))


# ── a damper follows its own air handler ─────────────────────────────────────


def test_damper_position_tracks_the_fan_it_belongs_to():
    if not _PLANT_MAP.exists():
        pytest.skip("no plant publish map (building not active)")
    spec = json.loads(_PLANT_MAP.read_text(encoding="utf-8"))
    publisher.load_plant_groups(str(_PLANT_MAP))

    pairs = [
        (g["group"], g["roles"]["damper_position"]["uuid"], g["roles"]["fan_status"]["uuid"])
        for g in spec["groups"]
        if "damper_position" in g["roles"] and "fan_status" in g["roles"]
    ]
    if not pairs:
        pytest.skip("no AHU group carries both a damper and a fan status")

    seen: Dict[str, List[float]] = {}
    conn = _Conn()
    for _ in range(300):
        conn.calls.clear()
        publisher.publish_plant(conn)
        for _sql, rows in conn.calls:
            for uuid, value in rows:
                seen.setdefault(uuid, []).append(float(value))

    for name, damper_id, fan_id in pairs:
        damper = seen[damper_id]
        fan = seen[fan_id]
        shut = [d for d, f in zip(damper, fan) if f == 0.0]
        open_ = [d for d, f in zip(damper, fan) if f == 1.0]
        assert open_, f"{name}: the fan never ran"
        if shut:
            assert max(shut) <= 5.0, f"{name}: damper at {max(shut)}% with the fan stopped"
        assert min(open_) > 5.0, f"{name}: damper at {min(open_)}% with the fan running"
        assert max(open_) <= 100.0
