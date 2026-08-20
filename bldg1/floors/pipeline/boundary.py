"""
A BOUNDARY / BPOLY equivalent, implemented on the wall network.

AutoCAD's BOUNDARY command takes an internal pick point, rays outward to find
the surrounding linework, and traces the enclosing loop. It needs the AutoCAD
geometry engine, which no Python or JS CAD library reimplements - so this does
the same job a different way:

    1. collect every wall (and optionally door) line as a shapely LineString
    2. union them, which nodes the network at every crossing
    3. polygonize -> the set of enclosed faces, i.e. every region BOUNDARY
       could possibly return
    4. for each room-number TEXT, find the face containing its insertion point

Step 3 traces the *inner* face of the walls automatically: walls drawn as two
parallel lines produce a face bounded by the inner line of each wall, which is
exactly what BOUNDARY returns.

The difference from BOUNDARY that matters: this knows when it failed. A gap in
the wall lines makes a room leak into its neighbour or into the building
exterior, and both are detected and reported rather than approximated.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------

@dataclass
class RoomTrace:
    number: str
    point: tuple[float, float]
    polygon: Polygon | None = None
    area_m2: float | None = None
    islands: int = 0          # enclosed faces inside the room (columns, ducts)
    island_area_m2: float = 0.0
    ok: bool = False
    reason: str = ""


@dataclass
class BoundaryResult:
    traced: list[RoomTrace] = field(default_factory=list)
    failed: list[RoomTrace] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def report(self) -> str:
        lines = [
            f"  traced   {len(self.traced)}",
            f"  failed   {len(self.failed)}",
        ]
        islanded = [t for t in self.traced if t.islands]
        if islanded:
            lines.append("")
            lines.append(
                "  NOTE - traced, but the room encloses island geometry "
                "(columns/ducts/risers).")
            lines.append(
                "  A closed LWPOLYLINE is a single ring, so the island is NOT "
                "subtracted and the")
            lines.append(
                "  area is overstated by that much. AutoCAD BOUNDARY would emit "
                "a second polyline.")
            for trace in sorted(islanded, key=lambda t: t.number):
                lines.append(
                    f"    {trace.number}  {trace.islands} island(s), "
                    f"polyline overstates floor area by "
                    f"{trace.island_area_m2:.2f} m2"
                )

        if self.failed:
            lines.append("")
            lines.append("  FAILURES (not approximated):")
            width = max(len(f.number) for f in self.failed)
            for failure in sorted(self.failed, key=lambda f: f.number):
                lines.append(
                    f"    {failure.number:<{width}}  at "
                    f"({failure.point[0]:.0f}, {failure.point[1]:.0f})  {failure.reason}"
                )
        return "\n".join(lines)


# --------------------------------------------------------------------------
# linework harvesting
# --------------------------------------------------------------------------

def _arc_points(cx, cy, radius, start_deg, end_deg, segments: int = 24):
    start = math.radians(start_deg)
    end = math.radians(end_deg)
    if end <= start:
        end += 2 * math.pi
    step = (end - start) / max(segments, 2)
    return [
        (cx + radius * math.cos(start + step * i), cy + radius * math.sin(start + step * i))
        for i in range(segments + 1)
    ]


def _entity_lines(entity, include_curves: bool) -> Iterator[LineString]:
    """Flatten one DXF entity into LineStrings. Curves are approximated only
    when asked for, because a door swing arc would otherwise slice a curved
    bite out of the room it belongs to."""
    dxftype = entity.dxftype()
    try:
        if dxftype == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            yield LineString([(start.x, start.y), (end.x, end.y)])

        elif dxftype == "LWPOLYLINE":
            points = [(x, y) for x, y, *_ in entity.get_points("xyb")]
            if len(points) >= 2:
                if entity.closed:
                    points = points + [points[0]]
                yield LineString(points)

        elif dxftype == "POLYLINE" and entity.is_2d_polyline:
            points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
            if len(points) >= 2:
                if entity.is_closed:
                    points = points + [points[0]]
                yield LineString(points)

        elif dxftype == "ARC" and include_curves:
            centre = entity.dxf.center
            points = _arc_points(centre.x, centre.y, entity.dxf.radius,
                                 entity.dxf.start_angle, entity.dxf.end_angle)
            yield LineString(points)

        elif dxftype == "CIRCLE" and include_curves:
            centre = entity.dxf.center
            points = _arc_points(centre.x, centre.y, entity.dxf.radius, 0, 360, 48)
            yield LineString(points)
    except Exception:
        return


def _matches(layer: str, patterns: Iterable[str]) -> bool:
    import fnmatch
    lowered = (layer or "").lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


# --------------------------------------------------------------------------
# tracer
# --------------------------------------------------------------------------

class BoundaryTracer:
    def __init__(
        self,
        wall_layers: list[str],
        door_layers: list[str] | None = None,
        room_text_layers: list[str] | None = None,
        room_pattern: str = r"^\d\.\d{2}$",
        units_to_metres: float = 0.001,
        min_area_m2: float = 1.0,
        max_area_m2: float = 2000.0,
        min_inradius_m: float = 0.3,
        include_door_curves: bool = False,
        explode_blocks: bool = True,
    ) -> None:
        self.wall_layers = wall_layers
        self.door_layers = door_layers or []
        self.room_text_layers = room_text_layers or ["A-AREA-IDEN"]
        self.room_re = re.compile(room_pattern)
        self.scale = units_to_metres
        self.min_area = min_area_m2
        self.max_area = max_area_m2
        self.min_inradius_m = min_inradius_m
        self.include_door_curves = include_door_curves
        self.explode_blocks = explode_blocks

    # -- linework ----------------------------------------------------------

    def _iter_entities(self, msp) -> Iterator:
        for entity in msp:
            yield entity
            if self.explode_blocks and entity.dxftype() == "INSERT":
                try:
                    yield from entity.virtual_entities()
                except Exception:
                    continue

    def collect_linework(self, msp) -> list[LineString]:
        lines: list[LineString] = []
        for entity in self._iter_entities(msp):
            layer = entity.dxf.get("layer", "")
            on_wall = _matches(layer, self.wall_layers)
            on_door = _matches(layer, self.door_layers)
            if not (on_wall or on_door):
                continue
            # Door swing arcs are excluded by default: they close the opening
            # but also carve a curved slice out of the room. Door *jamb lines*
            # are kept, which is what actually seals the doorway.
            include_curves = on_wall or (on_door and self.include_door_curves)
            for line in _entity_lines(entity, include_curves):
                if line.length > 0:
                    lines.append(line)
        return lines

    def collect_room_texts(self, msp) -> list[tuple[str, tuple[float, float]]]:
        found: list[tuple[str, tuple[float, float]]] = []
        for entity in self._iter_entities(msp):
            if entity.dxftype() not in ("TEXT", "MTEXT"):
                continue
            if not _matches(entity.dxf.get("layer", ""), self.room_text_layers):
                continue
            text = (
                entity.plain_text(split=False).strip()
                if entity.dxftype() == "MTEXT" else str(entity.dxf.text).strip()
            )
            if not self.room_re.match(text):
                continue
            point = self._text_point(entity)
            if point:
                found.append((text, point))
        return found

    @staticmethod
    def _text_point(entity) -> tuple[float, float] | None:
        for attr in ("insert", "align_point", "location"):
            if entity.dxf.hasattr(attr):
                p = entity.dxf.get(attr)
                return (p.x, p.y)
        return None

    # -- tracing -----------------------------------------------------------

    def trace(self, msp) -> BoundaryResult:
        lines = self.collect_linework(msp)
        texts = self.collect_room_texts(msp)

        result = BoundaryResult()
        result.stats = {
            "wall_segments": len(lines),
            "room_numbers_found": len(texts),
        }
        if not lines:
            for number, point in texts:
                result.failed.append(RoomTrace(
                    number, point, reason="no wall linework found - check wall layer names"))
            return result
        if not texts:
            return result

        # Unioning nodes the network at every intersection; polygonize then
        # yields every enclosed face. This is the whole trick.
        noded = unary_union(lines)
        faces = [f for f in polygonize(noded) if f.is_valid and not f.is_empty]
        result.stats["faces_found"] = len(faces)

        if not faces:
            for number, point in texts:
                result.failed.append(RoomTrace(
                    number, point, reason="wall lines form no closed region"))
            return result

        tree = STRtree(faces)
        scale_sq = self.scale ** 2

        # First pass: which face holds each room number.
        assignments: list[tuple[str, tuple[float, float], int | None]] = []
        for number, point in texts:
            pt = Point(point)
            candidates = [faces[i] for i in tree.query(pt)]
            containing = [f for f in candidates if f.contains(pt)]
            if not containing:
                assignments.append((number, point, None))
                continue
            # Nested faces (a column or duct inside a room) - the room is the
            # smallest face that still contains the point.
            smallest = min(containing, key=lambda f: f.area)
            assignments.append((number, point, faces.index(smallest)))

        # Second pass: a face holding two room numbers means the wall between
        # those rooms has a gap. Report both rather than emitting one merged
        # polygon - "45 correct rooms and a list of 6 failures", as asked.
        occupants: dict[int, list[str]] = {}
        for number, _point, index in assignments:
            if index is not None:
                occupants.setdefault(index, []).append(number)

        for number, point, index in assignments:
            trace = RoomTrace(number=number, point=point)

            if index is None:
                trace.reason = (
                    "no enclosing region - the room leaked to the drawing "
                    "exterior, so the wall lines around it have a gap"
                )
                result.failed.append(trace)
                continue

            face = faces[index]
            area_m2 = face.area * scale_sq
            trace.area_m2 = round(area_m2, 3)

            others = [n for n in occupants[index] if n != number]
            if others:
                trace.reason = (
                    f"region also encloses {', '.join(sorted(others))} - the wall "
                    f"between them has a gap; not merging"
                )
                result.failed.append(trace)
                continue

            if area_m2 < self.min_area:
                trace.reason = (
                    f"traced region is only {area_m2:.2f} m2 - the pick point "
                    f"probably fell inside a wall or a hatch island"
                )
                result.failed.append(trace)
                continue

            inradius = shapely.maximum_inscribed_circle(face).length * self.scale
            if inradius < self.min_inradius_m:
                trace.reason = (
                    f"traced region is only {inradius * 2:.2f} m across at its "
                    f"widest - that is a wall cavity or a gap between lines, "
                    f"not a room"
                )
                result.failed.append(trace)
                continue

            if area_m2 > self.max_area:
                trace.reason = (
                    f"traced region is {area_m2:.0f} m2, over the {self.max_area:.0f} m2 "
                    f"limit - the room leaked into a larger space"
                )
                result.failed.append(trace)
                continue

            # polygonize assigns nested rings as holes, so islands are simply
            # the face's own interior rings - columns, ducts, risers.
            trace.islands = len(face.interiors)
            if trace.islands:
                # The emitted LWPOLYLINE is a single ring and cannot carry a
                # hole, so record how much floor area that ring overstates.
                exterior_area = Polygon(face.exterior).area * scale_sq
                trace.island_area_m2 = round(exterior_area - area_m2, 3)

            trace.polygon = face
            trace.ok = True
            result.traced.append(trace)

        return result


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

XDATA_APPID = "ABACWS_KG"


def write_boundaries(doc, result: BoundaryResult, layer_name: str = "A-AREA-ROOM",
                     color: int = 3, tag_room_number: bool = True) -> int:
    """
    Add one closed LWPOLYLINE per successfully traced room, on a new layer.

    Nothing existing is touched: the layer is created only if absent, and only
    new entities are appended. Coordinates are written back in the drawing's
    own units - no scaling happens on this path, so the origin is preserved.

    Each polyline optionally carries its room number as XDATA, which makes the
    result self-describing without adding any visible entity to the drawing.
    """
    if layer_name not in doc.layers:
        doc.layers.add(name=layer_name, color=color)
    if tag_room_number and XDATA_APPID not in doc.appids:
        doc.appids.add(XDATA_APPID)

    msp = doc.modelspace()
    written = 0
    for trace in result.traced:
        if trace.polygon is None:
            continue
        coords = list(trace.polygon.exterior.coords)
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]          # LWPOLYLINE closes itself
        if len(coords) < 3:
            continue
        polyline = msp.add_lwpolyline(
            coords, format="xy", close=True, dxfattribs={"layer": layer_name})
        if tag_room_number:
            polyline.set_xdata(XDATA_APPID, [(1000, trace.number)])
        written += 1
    return written
