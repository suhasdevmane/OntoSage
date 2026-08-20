"""
Geometry & semantics extraction, source-agnostic.

Takes a normalised entity list (from either the DWG or DXF reader) and
reconstructs a queryable model of one floor:

    spaces        closed room polygons + code + name + area + centroid
    elements      block references (equipment, furniture, sanitary, doors)
    dimensions    DIMENSION entities with the measurement AutoCAD computed
    adjacency     pairs of spaces whose boundaries run together
    connectivity  door-mediated space-to-space passage

A CAD floor plan is a *drawing*, not a model. Nothing here assumes the file
carries object semantics, because it does not: meaning is recovered from
layer membership, geometric containment and text.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from shapely.geometry import Point, Polygon
from shapely.validation import make_valid

from .entities import NormEntity


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    lowered = (name or "").lower()
    return any(fnmatch.fnmatch(lowered, p.lower()) for p in patterns)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", (text or "").strip())
    return cleaned.strip("_") or "unnamed"


def _polygon_from(entity: NormEntity) -> Polygon | None:
    if not entity.closed or len(entity.points) < 3:
        return None
    polygon = Polygon(entity.points)
    if not polygon.is_valid:
        repaired = make_valid(polygon)
        if repaired.geom_type == "Polygon":
            polygon = repaired
        elif hasattr(repaired, "geoms"):
            parts = [g for g in repaired.geoms if g.geom_type == "Polygon"]
            if not parts:
                return None
            polygon = max(parts, key=lambda g: g.area)
        else:
            return None
    return polygon if polygon.area > 0 else None


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------

@dataclass
class Space:
    id: str
    code: str | None = None
    name: str | None = None
    area_m2: float = 0.0
    perimeter_m: float = 0.0
    centroid: tuple[float, float] = (0.0, 0.0)
    bbox_m: tuple[float, float] = (0.0, 0.0)
    wkt: str = ""
    source_layer: str = ""
    raw_labels: list[str] = field(default_factory=list)


@dataclass
class Element:
    id: str
    kind: str
    brick_class: str
    label: str
    layer: str
    block_name: str | None
    point: tuple[float, float] | None
    attributes: dict[str, str] = field(default_factory=dict)
    in_space: str | None = None


@dataclass
class Dimension:
    """A DIMENSION entity: a measurement the drafter placed on the drawing."""
    id: str
    kind: str                        # linear | aligned | angular | radius | diameter | ordinate
    measurement_m: float | None      # what AutoCAD computed from the geometry
    text_override: str | None        # what the drafter typed, if anything
    layer: str
    point: tuple[float, float] | None
    in_space: str | None = None


@dataclass
class FloorModel:
    building: dict[str, Any]
    storey: dict[str, Any]
    spaces: list[Space]
    elements: list[Element]
    dimensions: list[Dimension]
    adjacency: list[dict[str, Any]]
    connectivity: list[dict[str, Any]]
    stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "building": self.building,
            "storey": self.storey,
            "spaces": [asdict(s) for s in self.spaces],
            "elements": [asdict(e) for e in self.elements],
            "dimensions": [asdict(d) for d in self.dimensions],
            "adjacency": self.adjacency,
            "connectivity": self.connectivity,
            "stats": self.stats,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# DXF dimension type codes (low 4 bits of group 70).
DIMENSION_KINDS = {
    0: "linear", 1: "aligned", 2: "angular", 3: "diameter",
    4: "radius", 5: "angular3point", 6: "ordinate",
}


class FloorPlanExtractor:
    def __init__(self, config: dict[str, Any]) -> None:
        self.cfg = config
        geom = config.get("geometry", {})
        self.room_layers = geom.get("room_boundary_layers", [])
        self.min_area = float(geom.get("min_room_area_m2", 1.0))
        self.min_shared = float(geom.get("min_shared_boundary_m", 0.4))
        self.tol = float(geom.get("tolerance_m", 0.3))
        self.label_layers = config.get("labels", {}).get("layers", [])
        self.code_re = re.compile(config.get("labels", {}).get("code_pattern", r"^$"))
        self.element_rules = config.get("elements", [])
        self.door_cfg = config.get("doors", {})
        self.dimension_cfg = config.get("dimensions", {}) or {}
        self.ignore_layers = {s.lower() for s in config.get("ignore_layers", [])}

    def extract(self, entities: list[NormEntity], meta: dict[str, Any]) -> FloorModel:
        entities = [e for e in entities if not e.paper_space]

        polygons = self._collect_room_polygons(entities)
        spaces = self._build_spaces(polygons)
        self._attach_labels(entities, spaces, polygons)
        elements = self._collect_elements(entities, spaces, polygons)
        dimensions = self._collect_dimensions(entities, spaces, polygons)
        adjacency = self._compute_adjacency(spaces, polygons)
        connectivity = self._compute_connectivity(elements, spaces, polygons)

        measured = [d.measurement_m for d in dimensions if d.measurement_m]
        stats = {
            "source": meta.get("source"),
            "entities_scanned": len(entities),
            "layers_in_drawing": len(meta.get("layers", [])),
            "unknown_entity_count": meta.get("unknown_entity_count", 0),
            "spaces": len(spaces),
            "spaces_with_code": sum(1 for s in spaces if s.code),
            "spaces_with_name": sum(1 for s in spaces if s.name),
            "elements": len(elements),
            "doors": sum(1 for e in elements if e.kind == "door"),
            "dimensions": len(dimensions),
            "dimensions_with_measurement": len(measured),
            "adjacency_edges": len(adjacency),
            "connectivity_edges": len(connectivity),
            "total_area_m2": round(sum(s.area_m2 for s in spaces), 2),
        }

        return FloorModel(
            building=self.cfg.get("building", {}),
            storey=self.cfg.get("storey", {}),
            spaces=spaces, elements=elements, dimensions=dimensions,
            adjacency=adjacency, connectivity=connectivity, stats=stats,
        )

    # -- stages ------------------------------------------------------------

    def _collect_room_polygons(self, entities: list[NormEntity]) -> list[tuple[Polygon, str]]:
        found: list[tuple[Polygon, str]] = []
        for entity in entities:
            if entity.layer.lower() in self.ignore_layers:
                continue
            if not _matches_any(entity.layer, self.room_layers):
                continue
            polygon = _polygon_from(entity)
            if polygon is None or polygon.area < self.min_area:
                continue
            found.append((polygon, entity.layer))

        # Architectural drawings frequently carry the same boundary on two
        # layers (e.g. USABLE over POLYLINES) - keep one.
        deduped: list[tuple[Polygon, str]] = []
        for polygon, layer in sorted(found, key=lambda t: -t[0].area):
            if any(
                polygon.centroid.distance(kept.centroid) < self.tol
                and abs(polygon.area - kept.area) / max(kept.area, 1e-9) < 0.02
                for kept, _ in deduped
            ):
                continue
            deduped.append((polygon, layer))
        return deduped

    def _build_spaces(self, polygons: list[tuple[Polygon, str]]) -> list[Space]:
        spaces: list[Space] = []
        for index, (polygon, layer) in enumerate(polygons, start=1):
            centroid = polygon.representative_point()
            minx, miny, maxx, maxy = polygon.bounds
            spaces.append(Space(
                id=f"Space_{index:04d}",
                area_m2=round(polygon.area, 3),
                perimeter_m=round(polygon.length, 3),
                centroid=(round(centroid.x, 3), round(centroid.y, 3)),
                bbox_m=(round(maxx - minx, 3), round(maxy - miny, 3)),
                wkt=polygon.wkt,
                source_layer=layer,
            ))
        return spaces

    def _attach_labels(self, entities, spaces, polygons) -> None:
        candidates: list[tuple[str, Point, float]] = []
        for entity in entities:
            if not entity.is_text() or entity.point is None or not entity.text:
                continue
            if entity.layer.lower() in self.ignore_layers:
                continue
            if self.label_layers and not _matches_any(entity.layer, self.label_layers):
                continue
            candidates.append((entity.text, Point(entity.point), entity.point[1]))

        for space, (polygon, _) in zip(spaces, polygons):
            inside = [
                (text, y) for text, pt, y in candidates
                if polygon.contains(pt) or polygon.distance(pt) < self.tol
            ]
            if not inside:
                continue
            # The room code is conventionally drawn above the room name.
            inside.sort(key=lambda t: -t[1])
            texts = [t for t, _ in inside]
            space.raw_labels = texts

            name_parts: list[str] = []
            for text in texts:
                if space.code is None and self.code_re.match(text):
                    space.code = text
                else:
                    name_parts.append(text)
            if name_parts:
                space.name = " ".join(name_parts).strip()

        seen: set[str] = set()
        for space in spaces:
            if not space.code:
                continue
            candidate = f"Space_{_slug(space.code)}"
            if candidate in seen:
                continue
            seen.add(candidate)
            space.id = candidate

    def _collect_elements(self, entities, spaces, polygons) -> list[Element]:
        elements: list[Element] = []
        counter = 0
        for entity in entities:
            if entity.type != "INSERT":
                continue
            if entity.layer.lower() in self.ignore_layers:
                continue
            block_name = entity.block_name or ""

            is_door = _matches_any(entity.layer, self.door_cfg.get("layer_patterns", [])) or \
                _matches_any(block_name, self.door_cfg.get("block_name_patterns", []))

            rule = None
            if not is_door:
                for candidate in self.element_rules:
                    if _matches_any(entity.layer, [candidate["pattern"]]):
                        rule = candidate
                        break
                if rule is None:
                    continue

            counter += 1
            elements.append(Element(
                id=f"{'Door' if is_door else 'Element'}_{counter:04d}",
                kind="door" if is_door else "equipment",
                brick_class="Door" if is_door else rule["brick_class"],
                label="Door" if is_door else rule["label"],
                layer=entity.layer,
                block_name=block_name or None,
                point=entity.point,
                attributes=dict(entity.attribs),
            ))

        for element in elements:
            if element.point is None:
                continue
            pt = Point(element.point)
            for space, (polygon, _) in zip(spaces, polygons):
                if polygon.contains(pt):
                    element.in_space = space.id
                    break
        return elements

    def _collect_dimensions(self, entities, spaces, polygons) -> list[Dimension]:
        """
        DIMENSION entities carry a `measurement` computed by AutoCAD from the
        actual geometry - a real number in drawing units, not a drawn label.
        That makes them directly answerable facts ("how wide is the corridor")
        rather than pixels, which is why they are worth lifting into the graph.
        """
        if self.dimension_cfg.get("enabled") is False:
            return []
        include_layers = self.dimension_cfg.get("layers", [])
        min_m = float(self.dimension_cfg.get("min_measurement_m", 0.0))
        max_m = float(self.dimension_cfg.get("max_measurement_m", 1e6))

        dimensions: list[Dimension] = []
        counter = 0
        for entity in entities:
            if entity.type != "DIMENSION":
                continue
            # Dimension layers are usually in ignore_layers (they are visual
            # clutter for room extraction) - but the measurements themselves
            # are wanted, so the ignore list is deliberately not applied here.
            if include_layers and not _matches_any(entity.layer, include_layers):
                continue
            value = entity.measurement
            if value is not None and not (min_m <= abs(value) <= max_m):
                value = None
            if value is None and not entity.text_override:
                continue

            counter += 1
            kind = DIMENSION_KINDS.get(
                (entity.dimension_type or 0) & 0x0F, "linear")
            dimensions.append(Dimension(
                id=f"Dimension_{counter:04d}",
                kind=kind,
                measurement_m=round(value, 4) if value is not None else None,
                text_override=entity.text_override,
                layer=entity.layer,
                point=entity.point,
            ))

        for dimension in dimensions:
            if dimension.point is None:
                continue
            pt = Point(dimension.point)
            for space, (polygon, _) in zip(spaces, polygons):
                if polygon.contains(pt):
                    dimension.in_space = space.id
                    break
        return dimensions

    def _compute_adjacency(self, spaces, polygons) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        count = len(spaces)
        for i in range(count):
            poly_i = polygons[i][0]
            grown_i = poly_i.buffer(self.tol)
            for j in range(i + 1, count):
                poly_j = polygons[j][0]
                if not grown_i.intersects(poly_j):
                    continue
                # The part of j's boundary lying within tolerance of i's. The
                # dilation overshoots by up to `tol` at each end of the run, so
                # subtract 2*tol - this also collapses corner-only touches to
                # ~0, which min_shared then filters out.
                shared = poly_i.boundary.buffer(self.tol).intersection(poly_j.boundary)
                shared_len = max(0.0, shared.length - 2.0 * self.tol) \
                    if not shared.is_empty else 0.0
                if shared_len < self.min_shared:
                    continue
                edges.append({
                    "a": spaces[i].id, "b": spaces[j].id,
                    "shared_boundary_m": round(shared_len, 3),
                })
        return edges

    def _compute_connectivity(self, elements, spaces, polygons) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        for element in elements:
            if element.kind != "door" or element.point is None:
                continue
            pt = Point(element.point).buffer(max(self.tol, 1.0))
            touching = [
                space.id for space, (polygon, _) in zip(spaces, polygons)
                if polygon.intersects(pt)
            ]
            if len(touching) >= 2:
                edges.append({"door": element.id, "spaces": sorted(touching[:2])})
        return edges
