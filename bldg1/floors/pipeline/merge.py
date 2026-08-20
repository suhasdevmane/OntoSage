"""
Cross-floor reasoning.

A per-floor graph answers questions within a storey. A *building* graph also
has to answer "how do I get from the ground floor to room 3A12" - which needs
vertical circulation. There is nothing in a 2D plan that states a stair on
floor 1 is the same stair as on floor 2, so it is inferred: cores that occupy
the same footprint on adjacent storeys and are labelled as circulation.

This only works if the floor drawings share a coordinate system. They usually
do for one building's DWG set, but it is checked rather than assumed.
"""

from __future__ import annotations

import re
from typing import Any

from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon


DEFAULT_CORE_PATTERNS = [
    r"\bstair", r"\bstairs\b", r"\bstairwell", r"\bstaircase",
    r"\blift\b", r"\blifts\b", r"\belevator", r"\briser\b",
    r"\bcore\b", r"\bshaft\b", r"\bescape\b",
]


def _core_regex(patterns: list[str] | None) -> re.Pattern:
    return re.compile("|".join(patterns or DEFAULT_CORE_PATTERNS), re.IGNORECASE)


def floor_extent(model: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Bounding box across all spaces on a floor, for coordinate-system checks."""
    polygons = [
        shapely_wkt.loads(s["wkt"]) for s in model.get("spaces", []) if s.get("wkt")
    ]
    if not polygons:
        return None
    xs0, ys0, xs1, ys1 = zip(*(p.bounds for p in polygons))
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def check_alignment(models: list[dict[str, Any]], tolerance_m: float = 25.0) -> list[str]:
    """
    Warn if floors do not appear to share an origin.

    Compares bounding-box corners across floors. A building's storeys should
    stack; if one plan was drawn on a different origin, every vertical link
    and every cross-floor spatial query would be quietly wrong.
    """
    warnings: list[str] = []
    extents = [(m.get("storey", {}).get("id", "?"), floor_extent(m)) for m in models]
    known = [(name, ext) for name, ext in extents if ext]
    if len(known) < 2:
        return warnings

    reference_name, reference = known[0]
    for name, extent in known[1:]:
        offset = max(abs(a - b) for a, b in zip(extent, reference))
        if offset > tolerance_m:
            warnings.append(
                f"{name} extent differs from {reference_name} by {offset:.1f} m - "
                f"the floors may not share a coordinate origin, so vertical "
                f"links and cross-floor spatial queries will be unreliable."
            )
    return warnings


def find_vertical_links(
    models: list[dict[str, Any]],
    core_patterns: list[str] | None = None,
    min_overlap_ratio: float = 0.5,
    adjacent_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Link circulation cores that stack across storeys.

    `min_overlap_ratio` is measured against the *smaller* of the two
    footprints, so a small lift shaft still links to the larger stair core it
    sits inside.
    """
    pattern = _core_regex(core_patterns)

    levelled: list[tuple[int, dict[str, Any], list[tuple[str, Polygon]]]] = []
    for model in models:
        level = int(model.get("storey", {}).get("level", 0))
        cores: list[tuple[str, Polygon]] = []
        for space in model.get("spaces", []):
            text = " ".join(filter(None, [space.get("name"), space.get("code")]))
            if not text or not pattern.search(text):
                continue
            if not space.get("wkt"):
                continue
            cores.append((space["id"], shapely_wkt.loads(space["wkt"])))
        levelled.append((level, model, cores))

    levelled.sort(key=lambda t: t[0])
    links: list[dict[str, Any]] = []

    for i in range(len(levelled)):
        for j in range(i + 1, len(levelled)):
            level_a, _, cores_a = levelled[i]
            level_b, _, cores_b = levelled[j]
            if adjacent_only and abs(level_a - level_b) != 1:
                continue
            for id_a, poly_a in cores_a:
                for id_b, poly_b in cores_b:
                    if not poly_a.intersects(poly_b):
                        continue
                    overlap = poly_a.intersection(poly_b).area
                    smaller = min(poly_a.area, poly_b.area)
                    if smaller <= 0:
                        continue
                    ratio = overlap / smaller
                    if ratio < min_overlap_ratio:
                        continue
                    links.append({
                        "a": id_a, "b": id_b,
                        "levels": [level_a, level_b],
                        "overlap_ratio": round(ratio, 3),
                    })
    return links


def building_summary(models: list[dict[str, Any]]) -> dict[str, Any]:
    total_area = sum(
        s.get("area_m2", 0.0) for m in models for s in m.get("spaces", []))
    return {
        "storeys": len(models),
        "spaces": sum(len(m.get("spaces", [])) for m in models),
        "spaces_with_code": sum(
            1 for m in models for s in m.get("spaces", []) if s.get("code")),
        "elements": sum(len(m.get("elements", [])) for m in models),
        "dimensions": sum(len(m.get("dimensions", [])) for m in models),
        "adjacency_edges": sum(len(m.get("adjacency", [])) for m in models),
        "connectivity_edges": sum(len(m.get("connectivity", [])) for m in models),
        "total_area_m2": round(total_area, 2),
    }
