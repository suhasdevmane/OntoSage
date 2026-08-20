# -*- coding: utf-8 -*-
"""V5-T27: route finder (hops, metres, step-free, nearest) + recipe formulas."""

from __future__ import annotations

from typing import List

import pytest

from orchestrator.services.recipes_compute import (
    ach_from_co2_decay,
    degree_day_normalized_kwh,
    tariff_cost,
)
from orchestrator.services.route_finder import RouteFinder
from shared.models import FloorPlanManifest, NormalisedPoint, RenderedImage, Space

pytestmark = pytest.mark.unit


def _space(zone_id, label, stype="office", adjacent=None, x=0.0, y=0.0):
    return Space(
        id=f"tb.{zone_id}",
        zone_id=zone_id,
        label=label,
        type=stype,
        adjacent_spaces=adjacent or [],
        centroid=NormalisedPoint(x=x, y=y),
    )


def _manifest(floor: int, spaces: List[Space], width_m=50.0, height_m=20.0):
    return FloorPlanManifest(
        building_id="tb",
        building_name="Test Building",
        floor=floor,
        floor_label=f"Floor {floor}",
        schema_version="2.0",
        source_pdf=f"f{floor}.pdf",
        source_sha256="0" * 64,
        generated_at="2026-01-01T00:00:00",
        rendered_image=RenderedImage(
            png_url=f"/f{floor}.png",
            thumbnail_url=f"/f{floor}_t.png",
            width_px=1000,
            height_px=400,
            dpi=96,
        ),
        pdf_url=f"/f{floor}.pdf",
        spaces=spaces,
        blocks=[],
        bounding_box={"width_m": width_m, "height_m": height_m},
    )


def _two_floor_building():
    # floor 0: office A — corridor C0 — lift L0 — stairs S0 — toilet T0
    f0 = [
        _space("0.01", "Office A", "office", ["0.90"], x=0.1, y=0.5),
        _space("0.90", "Corridor 0", "corridor", ["0.01", "0.80", "0.81", "0.50"], x=0.5, y=0.5),
        _space("0.80", "Lift 0", "lift", ["0.90"], x=0.7, y=0.5),
        _space("0.81", "Stairs 0", "staircase", ["0.90"], x=0.8, y=0.5),
        _space("0.50", "Toilet 0", "toilet", ["0.90"], x=0.3, y=0.5),
    ]
    # floor 1: lift L1 — corridor C1 — office B ; stairs S1 — corridor
    f1 = [
        _space("1.80", "Lift 1", "lift", ["1.90"], x=0.7, y=0.5),
        _space("1.81", "Stairs 1", "staircase", ["1.90"], x=0.8, y=0.5),
        _space("1.90", "Corridor 1", "corridor", ["1.80", "1.81", "1.02"], x=0.5, y=0.5),
        _space("1.02", "Office B", "office", ["1.90"], x=0.1, y=0.5),
    ]
    return [_manifest(0, f0), _manifest(1, f1)]


def test_route_reports_hops_and_metres():
    rf = RouteFinder(_two_floor_building())
    rr = rf.route("0.01", "0.50")
    assert rr is not None
    assert rr.path == ["0.01", "0.90", "0.50"] and rr.hops == 2
    # 0.1→0.5→0.3 of a 50 m floor = 20 + 10 = 30 m
    assert rr.distance_m == pytest.approx(30.0, abs=0.5)


def test_cross_floor_route_uses_aligned_vertical_core():
    rf = RouteFinder(_two_floor_building())
    rr = rf.route("0.01", "1.02")
    assert rr is not None
    assert set(rr.floors) == {0, 1}
    verticals = {"0.80", "0.81", "1.80", "1.81"}
    assert verticals & set(rr.path), "route must pass through a lift or staircase"


def test_step_free_route_avoids_stairs():
    rf = RouteFinder(_two_floor_building())
    rr = rf.route("0.01", "1.02", step_free=True)
    assert rr is not None
    assert not rr.used_stairs
    assert "0.80" in rr.path and "1.80" in rr.path  # via the lift shaft


def test_step_free_declines_when_only_stairs_connect():
    manifests = _two_floor_building()
    # remove the lifts entirely — stairs become the only vertical link
    for m in manifests:
        m.spaces = [s for s in m.spaces if s.type != "lift"]
        for s in m.spaces:
            s.adjacent_spaces = [z for z in s.adjacent_spaces if not z.endswith(".80")]
    rf = RouteFinder(manifests)
    assert rf.route("0.01", "1.02") is not None  # stairs route exists
    assert rf.route("0.01", "1.02", step_free=True) is None  # honest refusal


def test_nearest_by_type_and_distance():
    rf = RouteFinder(_two_floor_building())
    hit = rf.nearest("0.01", space_types={"toilet"})
    assert hit is not None and hit.zone_id == "0.50" and hit.hops == 2
    assert hit.distance_m == pytest.approx(30.0, abs=0.5)
    # nearest lift from Office B is on its own floor
    hit = rf.nearest("1.02", space_types={"lift"})
    assert hit.zone_id == "1.80" and hit.floor == 1


# ── recipe formulas (method citations mandatory) ─────────────────────────────


def test_degree_day_normalization_cites_cibse():
    r = degree_day_normalized_kwh(3200, 160)
    assert r["value"] == 20.0 and r["unit"] == "kWh per degree day"
    assert "CIBSE TM41" in r["citation"] and "160" in r["method"]
    assert "error" in degree_day_normalized_kwh(3200, 0)


def test_ach_decay_formula_and_guards():
    # 1200→810 ppm over 2h with 420 outdoor: ln(780/390)/2 = ln(2)/2 ≈ 0.347
    r = ach_from_co2_decay(1200, 810, 2.0)
    assert r["value"] == pytest.approx(0.347, abs=0.001)
    assert "ASTM D6245" in r["citation"]
    # occupied / at-background windows must refuse, not invent
    assert "error" in ach_from_co2_decay(500, 480, 2.0, c_outdoor_ppm=490)
    assert "error" in ach_from_co2_decay(1200, 810, 0)


def test_tariff_cost_shows_its_arithmetic():
    r = tariff_cost(120.5, 0.28)
    assert r["value"] == pytest.approx(33.74)
    assert "120.5 kWh × 0.28 GBP/kWh" in r["method"]
    r2 = tariff_cost(100, 0.30, standing_charge=0.60)
    assert r2["value"] == pytest.approx(30.60)
    assert "standing charge" in r2["method"]
    assert "error" in tariff_cost(100, 0)


def test_waypoints_resolve_rm_style_labels():
    """V5-T27: 'RM101' must resolve against a manifest label 'RM101_room'."""
    from orchestrator.agents.spatial_agent import SpatialAgent

    spaces = [
        _space("1Z001", "RM101_room", "office", ["1Z090"], x=0.1, y=0.5),
        _space("1Z090", "Corridor 1", "corridor", ["1Z001", "1Z050"], x=0.5, y=0.5),
        _space("1Z050", "RM125_room", "office", ["1Z090"], x=0.9, y=0.5),
    ]
    manifests = [_manifest(1, spaces)]
    agent = SpatialAgent()
    out = agent._answer_wayfinding("Directions to RM125 from RM101", manifests)
    assert "Route to RM125_room" in out
    assert "Distance:" in out and "Method:" in out
