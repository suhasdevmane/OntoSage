"""
Lift extracted floor models into RDF (Brick + BOT + GeoSPARQL).

  BOT  (W3C LBD CG) - topology: Site -> Building -> Storey -> Space,
       bot:adjacentZone, bot:Interface, bot:containsElement. Deliberately
       minimal, and the right vocabulary for "what is next to what".

  Brick (1.3+) - classification: Room, Floor, Door, Equipment, and the
       sensor/point hierarchy your IoT telemetry hangs off.

  GeoSPARQL - geometry: geo:asWKT, so spatial questions stay answerable in
       SPARQL without leaving the triplestore.

Every space is one URI shared by topology, classification and geometry, so a
single query can cross all three. Multiple floors merge into one graph with
distinct storey URIs under a shared building.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from rdflib import Graph, Literal, Namespace, BNode
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD

BOT = Namespace("https://w3id.org/bot#")
BRICK = Namespace("https://brickschema.org/schema/Brick#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
UNIT = Namespace("http://qudt.org/vocab/unit/")

DEFAULT_BASE = "https://abacws.cardiff.ac.uk/kg#"


class GraphBuilder:
    def __init__(self, base: str = DEFAULT_BASE) -> None:
        self.ns = Namespace(base)
        self.graph = Graph()
        for prefix, namespace in [
            ("bot", BOT), ("brick", BRICK), ("geo", GEO), ("unit", UNIT),
            ("dcterms", DCTERMS), ("owl", OWL), ("abx", self.ns),
        ]:
            self.graph.bind(prefix, namespace)
        self._declare_local_terms()
        self._building_done = False

    # -- vocabulary ---------------------------------------------------------

    def _declare_local_terms(self) -> None:
        g, ns = self.graph, self.ns

        def datatype_prop(term, label, comment=None, rng=None):
            g.add((term, RDF.type, OWL.DatatypeProperty))
            g.add((term, RDFS.label, Literal(label)))
            if comment:
                g.add((term, RDFS.comment, Literal(comment)))
            if rng:
                g.add((term, RDFS.range, rng))

        datatype_prop(
            ns.roomCode, "room code",
            "Institutional room identifier as drawn on the floor plan, e.g. "
            "'0Z19'. Stable join key to timetabling and BMS systems.",
            XSD.string)
        datatype_prop(ns.sourceLayer, "source CAD layer",
                      "Provenance: the CAD layer the geometry was recovered from.")
        datatype_prop(ns.blockName, "source block name",
                      "Provenance: the CAD block definition this element came from.")
        datatype_prop(ns.bboxWidth, "bounding box width (m)", None, XSD.double)
        datatype_prop(ns.bboxDepth, "bounding box depth (m)", None, XSD.double)
        datatype_prop(ns.perimeter, "perimeter (m)", None, XSD.double)
        datatype_prop(ns.level, "storey level",
                      "Signed storey index; 0 is ground, negative is below ground.",
                      XSD.integer)
        datatype_prop(
            ns.dimensionKind, "dimension kind",
            "linear | aligned | angular | radius | diameter | ordinate - the "
            "DXF dimension type the drafter used.")
        datatype_prop(
            ns.textOverride, "dimension text override",
            "Text the drafter typed in place of the computed measurement. When "
            "present it should be trusted over the measurement, because the "
            "drafter deliberately replaced it.")

        for term, label, comment in [
            (ns.connectedTo, "connected to",
             "Two spaces are directly passable between one another through a "
             "door. Stronger than bot:adjacentZone, which only asserts that "
             "two spaces share a boundary."),
            (ns.verticallyConnectedTo, "vertically connected to",
             "Two spaces on different storeys are linked by shared vertical "
             "circulation - a stair, lift or riser core occupying the same "
             "footprint on both floors."),
        ]:
            g.add((term, RDF.type, OWL.ObjectProperty))
            g.add((term, RDF.type, OWL.SymmetricProperty))
            g.add((term, RDFS.label, Literal(label)))
            g.add((term, RDFS.comment, Literal(comment)))
            g.add((term, RDFS.domain, BOT.Zone))
            g.add((term, RDFS.range, BOT.Zone))

        g.add((ns.appliesTo, RDF.type, OWL.ObjectProperty))
        g.add((ns.appliesTo, RDFS.label, Literal("applies to")))
        g.add((ns.appliesTo, RDFS.comment, Literal(
            "The space a drawn dimension was placed inside.")))

        g.add((ns.Dimension, RDF.type, OWL.Class))
        g.add((ns.Dimension, RDFS.label, Literal("Dimension")))
        g.add((ns.Dimension, RDFS.comment, Literal(
            "A measurement annotation from the drawing. The value is what the "
            "CAD application computed from the underlying geometry, so it is a "
            "fact about the building rather than a picture of one.")))

        g.add((ns.measurement, RDF.type, OWL.ObjectProperty))
        g.add((ns.measurement, RDFS.label, Literal("measurement")))
        g.add((ns.measurement, RDFS.domain, ns.Dimension))

    # -- construction -------------------------------------------------------

    def build(self, model: dict[str, Any]) -> Graph:
        return self.build_many([model])

    def build_many(self, models: Iterable[dict[str, Any]]) -> Graph:
        for model in models:
            storey = self._add_topology(model)
            self._add_spaces(model, storey)
            self._add_adjacency(model)
            self._add_connectivity(model)
            self._add_elements(model)
            self._add_dimensions(model)
        return self.graph

    def _add_topology(self, model: dict[str, Any]):
        g, ns = self.graph, self.ns
        building_cfg = model.get("building", {})
        storey_cfg = model.get("storey", {})

        building = ns[building_cfg.get("id", "Building")]
        storey = ns[storey_cfg.get("id", "Storey")]

        if not self._building_done:
            site_name = building_cfg.get("site")
            if site_name:
                site = ns[site_name.replace(" ", "_")]
                g.add((site, RDF.type, BOT.Site))
                g.add((site, RDFS.label, Literal(site_name)))
                g.add((site, BOT.hasBuilding, building))
            g.add((building, RDF.type, BOT.Building))
            g.add((building, RDF.type, BRICK.Building))
            g.add((building, RDFS.label, Literal(building_cfg.get("name", "Building"))))
            self._building_done = True

        g.add((building, BOT.hasStorey, storey))
        g.add((storey, RDF.type, BOT.Storey))
        g.add((storey, RDF.type, BRICK.Floor))
        g.add((storey, RDFS.label, Literal(storey_cfg.get("name", "Storey"))))
        if "level" in storey_cfg:
            g.add((storey, ns.level, Literal(int(storey_cfg["level"]))))
        return storey

    def _quantity(self, subject, predicate, value: float, unit) -> None:
        """Brick's quantity pattern: value + unit, never a bare number."""
        node = BNode()
        self.graph.add((subject, predicate, node))
        self.graph.add((node, BRICK.value, Literal(float(value), datatype=XSD.double)))
        self.graph.add((node, BRICK.hasUnit, unit))

    def _add_spaces(self, model: dict[str, Any], storey) -> None:
        g, ns = self.graph, self.ns
        for space in model.get("spaces", []):
            uri = ns[space["id"]]
            g.add((uri, RDF.type, BOT.Space))
            g.add((uri, RDF.type, BRICK.Room))
            g.add((storey, BOT.hasSpace, uri))

            label = space.get("name") or space.get("code") or space["id"]
            g.add((uri, RDFS.label, Literal(label)))

            if space.get("code"):
                # Plain literal, NOT xsd:string-typed. RDF 1.1 says the two are
                # the same term, but rdflib does not equate them, so a typed
                # value here silently breaks FILTER/match on "0Z19".
                g.add((uri, ns.roomCode, Literal(space["code"])))
            if space.get("name"):
                g.add((uri, DCTERMS.title, Literal(space["name"])))
            if space.get("source_layer"):
                g.add((uri, ns.sourceLayer, Literal(space["source_layer"])))
            if space.get("area_m2"):
                self._quantity(uri, BRICK.area, space["area_m2"], UNIT.M2)
            if space.get("perimeter_m"):
                g.add((uri, ns.perimeter,
                       Literal(float(space["perimeter_m"]), datatype=XSD.double)))
            bbox = space.get("bbox_m")
            if bbox:
                g.add((uri, ns.bboxWidth, Literal(float(bbox[0]), datatype=XSD.double)))
                g.add((uri, ns.bboxDepth, Literal(float(bbox[1]), datatype=XSD.double)))

            if space.get("wkt"):
                geometry = ns[f"Geometry_{space['id']}"]
                g.add((uri, GEO.hasGeometry, geometry))
                g.add((geometry, RDF.type, GEO.Polygon))
                g.add((geometry, GEO.asWKT,
                       Literal(space["wkt"], datatype=GEO.wktLiteral)))

            centroid = space.get("centroid")
            if centroid:
                point = ns[f"Centroid_{space['id']}"]
                g.add((uri, GEO.hasCentroid, point))
                g.add((point, RDF.type, GEO.Point))
                g.add((point, GEO.asWKT, Literal(
                    f"POINT({centroid[0]} {centroid[1]})", datatype=GEO.wktLiteral)))

    def _add_adjacency(self, model: dict[str, Any]) -> None:
        g, ns = self.graph, self.ns
        for edge in model.get("adjacency", []):
            a, b = ns[edge["a"]], ns[edge["b"]]
            # bot:adjacentZone is symmetric; assert both directions so naive
            # SPARQL without reasoning still works.
            g.add((a, BOT.adjacentZone, b))
            g.add((b, BOT.adjacentZone, a))

    def _add_connectivity(self, model: dict[str, Any]) -> None:
        g, ns = self.graph, self.ns
        storey_id = model.get("storey", {}).get("id", "S")
        for index, edge in enumerate(model.get("connectivity", []), start=1):
            spaces = edge.get("spaces", [])
            if len(spaces) < 2:
                continue
            a, b = ns[spaces[0]], ns[spaces[1]]
            interface = ns[f"Interface_{storey_id}_{index:04d}"]
            g.add((interface, RDF.type, BOT.Interface))
            g.add((interface, BOT.interfaceOf, a))
            g.add((interface, BOT.interfaceOf, b))
            if edge.get("door"):
                g.add((interface, BOT.interfaceOf, ns[edge["door"]]))
            g.add((a, ns.connectedTo, b))
            g.add((b, ns.connectedTo, a))

    def _add_elements(self, model: dict[str, Any]) -> None:
        g, ns = self.graph, self.ns
        for element in model.get("elements", []):
            uri = ns[element["id"]]
            g.add((uri, RDF.type, BOT.Element))
            g.add((uri, RDF.type, BRICK[element["brick_class"]]))
            g.add((uri, RDFS.label, Literal(element.get("label") or element["id"])))
            if element.get("layer"):
                g.add((uri, ns.sourceLayer, Literal(element["layer"])))
            if element.get("block_name"):
                g.add((uri, ns.blockName, Literal(element["block_name"])))
            if element.get("in_space"):
                g.add((ns[element["in_space"]], BOT.containsElement, uri))
            point = element.get("point")
            if point:
                geometry = ns[f"Geometry_{element['id']}"]
                g.add((uri, GEO.hasGeometry, geometry))
                g.add((geometry, RDF.type, GEO.Point))
                g.add((geometry, GEO.asWKT, Literal(
                    f"POINT({point[0]} {point[1]})", datatype=GEO.wktLiteral)))
            # ATTRIB key/values are the only native semantics a DWG carries;
            # keep them verbatim so nothing is silently discarded.
            for tag, value in (element.get("attributes") or {}).items():
                prop = ns[f"attr_{tag.replace(' ', '_')}"]
                g.add((prop, RDF.type, OWL.DatatypeProperty))
                g.add((uri, prop, Literal(value)))

    def _add_dimensions(self, model: dict[str, Any]) -> None:
        g, ns = self.graph, self.ns
        for dimension in model.get("dimensions", []):
            uri = ns[dimension["id"]]
            g.add((uri, RDF.type, ns.Dimension))
            g.add((uri, ns.dimensionKind, Literal(dimension["kind"])))
            if dimension.get("measurement_m") is not None:
                self._quantity(uri, ns.measurement, dimension["measurement_m"], UNIT.M)
            if dimension.get("text_override"):
                g.add((uri, ns.textOverride, Literal(dimension["text_override"])))
            if dimension.get("layer"):
                g.add((uri, ns.sourceLayer, Literal(dimension["layer"])))
            if dimension.get("in_space"):
                g.add((uri, ns.appliesTo, ns[dimension["in_space"]]))
            point = dimension.get("point")
            if point:
                geometry = ns[f"Geometry_{dimension['id']}"]
                g.add((uri, GEO.hasGeometry, geometry))
                g.add((geometry, RDF.type, GEO.Point))
                g.add((geometry, GEO.asWKT, Literal(
                    f"POINT({point[0]} {point[1]})", datatype=GEO.wktLiteral)))

    # -- post-processing ----------------------------------------------------

    def add_vertical_links(self, links: list[dict[str, Any]]) -> None:
        g, ns = self.graph, self.ns
        for link in links:
            a, b = ns[link["a"]], ns[link["b"]]
            g.add((a, ns.verticallyConnectedTo, b))
            g.add((b, ns.verticallyConnectedTo, a))


def attach_sensors(graph: Graph, csv_path: str | Path, base: str = DEFAULT_BASE) -> int:
    """
    Bind IoT points to rooms - the step that turns a static floor graph into a
    live digital twin.

    Expects a CSV with headers: sensor_id, room_code, brick_class, [label].
    Sensors whose room_code has no matching space are reported, not dropped
    silently.
    """
    import csv as _csv

    ns = Namespace(base)
    code_to_space = {str(o): s for s, o in graph.subject_objects(ns.roomCode)}

    bound = 0
    unmatched: list[str] = []
    with open(csv_path, newline="", encoding="utf-8") as handle:
        for row in _csv.DictReader(handle):
            code = (row.get("room_code") or "").strip()
            space = code_to_space.get(code)
            if space is None:
                unmatched.append(f"{row.get('sensor_id')} -> room {code!r}")
                continue
            sensor = ns[f"Sensor_{row['sensor_id'].strip().replace(' ', '_')}"]
            graph.add((sensor, RDF.type, BRICK[row["brick_class"].strip()]))
            graph.add((sensor, RDFS.label, Literal(row.get("label") or row["sensor_id"])))
            graph.add((space, BRICK.hasPoint, sensor))
            graph.add((sensor, BRICK.isPointOf, space))
            bound += 1

    if unmatched:
        print(f"  ! {len(unmatched)} sensor(s) had no matching room code:")
        for item in unmatched[:10]:
            print(f"      {item}")
    return bound


def load_model(json_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))
