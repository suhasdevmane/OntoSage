"""
Provenance copy of the script used to add timeseries references.

Used on: 2025-10-01
Input TTL:  bldg3/trial/dataset/bldg3.ttl
Output TTL: bldg3/trial/dataset/bldg3_timeseries.ttl
Invocation example:
  python tools/sensors/add_timeseries_refs.py bldg3/trial/dataset/bldg3.ttl bldg3/trial/dataset/bldg3_timeseries.ttl

Note: This file is a copy of tools/sensors/add_timeseries_refs.py at the time of use,
kept here so readers know exactly what was used to generate the refs for this TTL.
"""

import uuid
import re
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, Literal, BNode, URIRef
from rdflib.namespace import OWL

BRICK = Namespace("https://brickschema.org/schema/Brick#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

# Default building namespace (will be overridden by detected 'bldg:' prefix in input TTL if present)
BLDG = Namespace("http://buildsys.org/ontologies/bldg2#")

TURTLE_HEADER = None  # no manual header; we'll bind prefixes on the graph


def _parse_turtle_with_fallback(src_ttl: Path) -> Graph:
    """Parse a Turtle file; if bad CURIEs (like bldg:local with '/') are present,
    sanitize them to full IRIs and parse from data."""
    g = Graph()
    # Bind core prefixes in case input is missing them
    g.bind("brick", BRICK)
    g.bind("ref", REF)
    try:
        g.parse(src_ttl.as_posix(), format="turtle")
        return g
    except Exception:
        # Fallback: sanitize illegal bldg:CURIEs into full IRIs
        text = src_ttl.read_text(encoding="utf-8")
        # Find bldg namespace
        m = re.search(r"@prefix\s+bldg:\s*<([^>]+)>\s*\.", text)
        if not m:
            raise
        bldg_ns = m.group(1)

        # Replace bldg:LOCAL tokens when LOCAL contains '/'
        def repl(match):
            local = match.group(1)
            # If local name contains a '/', it's not a valid PN_LOCAL; turn it into full IRI
            if "/" in local:
                return f"<{bldg_ns}{local}>"
            return match.group(0)

        # Match bldg:LOCAL where LOCAL can include '.' and '/' and other chars; stop at whitespace or ; , ) ] }}
        sanitized = re.sub(r"\bbldg:([^\s;,)\]\}]+)", repl, text)

        g2 = Graph()
        g2.bind("brick", BRICK)
        g2.bind("ref", REF)
        g2.parse(data=sanitized, format="turtle")
        return g2


def add_timeseries_refs(src_ttl: Path, out_ttl: Path):
    g = _parse_turtle_with_fallback(src_ttl)

    # Detect building namespace from input to preserve original 'bldg:' prefix/URI
    detected_bldg_ns = None
    try:
        # build a mapping of prefixes
        ns_map = {p: str(ns) for p, ns in g.namespace_manager.namespaces()}
        if "bldg" in ns_map:
            detected_bldg_ns = Namespace(ns_map["bldg"])
    except Exception:
        detected_bldg_ns = None
    BLDG_USED = detected_bldg_ns or BLDG

    # Use SPARQL with property paths to find all instances of transitive subclasses of brick:Sensor
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?s WHERE {
        ?s a ?c .
        ?c rdfs:subClassOf* brick:Sensor .
    }
    """

    changed = 0

    # First pass: normalize any existing literal references into proper ref nodes
    sensors = [row[0] for row in g.query(q)]
    for s in sensors:
        existing_refs = list(g.objects(s, REF.hasExternalReference))
        if not existing_refs:
            continue
        for obj in existing_refs:
            if isinstance(obj, Literal):
                literal_val = str(obj)
                # Try to find a node <literal_val> that may carry ref:hasTimeseriesId
                candidate_node = URIRef(literal_val)
                ts_uuid = None
                for _uuid in g.objects(candidate_node, REF.hasTimeseriesId):
                    ts_uuid = str(_uuid)
                    break
                # If no UUID found on a candidate node, treat literal as UUID only if it matches UUID pattern
                if not ts_uuid:
                    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", literal_val):
                        ts_uuid = literal_val
                # If still no UUID, generate a new one
                if not ts_uuid:
                    ts_uuid = str(uuid.uuid4())

                # Create a proper blank node reference with storedAt and UUID
                bn = BNode()
                g.add((bn, RDF.type, REF.TimeseriesReference))
                g.add((bn, REF.hasTimeseriesId, Literal(ts_uuid)))
                g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
                g.add((bn, REF.storedAt, BLDG_USED.database1))
                g.add((s, REF.hasExternalReference, bn))

                # Remove the literal reference
                g.remove((s, REF.hasExternalReference, obj))
                changed += 1
            elif isinstance(obj, URIRef):
                # Ensure IRI ref nodes are typed and have storedAt
                if (obj, RDF.type, REF.TimeseriesReference) not in g:
                    g.add((obj, RDF.type, REF.TimeseriesReference))
                if (obj, REF.storedAt, None) not in g:
                    g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
                    g.add((obj, REF.storedAt, BLDG_USED.database1))
                if (obj, REF.hasTimeseriesId, None) not in g:
                    g.add((obj, REF.hasTimeseriesId, Literal(str(uuid.uuid4()))))

    # Second pass: create new references for sensors without any ref
    for s in sensors:
        if (s, REF.hasExternalReference, None) in g:
            continue
        ts_id = str(uuid.uuid4())
        bn = BNode()  # create a blank node
        g.add((bn, RDF.type, REF.TimeseriesReference))
        g.add((bn, REF.hasTimeseriesId, Literal(ts_id)))
        # Ensure database1 exists as a node in bldg namespace
        g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
        g.add((bn, REF.storedAt, BLDG_USED.database1))
        g.add((s, REF.hasExternalReference, bn))
        changed += 1

    # Final pass: ensure ALL reference nodes (IRI or blank) have UUID and storedAt
    for s in sensors:
        for ref_node in g.objects(s, REF.hasExternalReference):
            # Ensure type
            if (ref_node, RDF.type, REF.TimeseriesReference) not in g:
                g.add((ref_node, RDF.type, REF.TimeseriesReference))
            # Ensure storedAt
            if (ref_node, REF.storedAt, None) not in g:
                g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
                g.add((ref_node, REF.storedAt, BLDG_USED.database1))
            # Ensure UUID
            if (ref_node, REF.hasTimeseriesId, None) not in g:
                g.add((ref_node, REF.hasTimeseriesId, Literal(str(uuid.uuid4()))))

    # Also annotate sensor classes themselves (owl:Class that are subclasses of brick:Sensor)
    q_classes = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:   <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?c WHERE {
        ?c a owl:Class .
        ?c rdfs:subClassOf* brick:Sensor .
    }
    """

    for row in g.query(q_classes):
        c = row[0]
        # If already annotated, ensure the node has type/storedAt; if literal, normalize
        existing_refs = list(g.objects(c, REF.hasExternalReference))
        if existing_refs:
            for obj in existing_refs:
                if isinstance(obj, Literal):
                    literal_val = str(obj)
                    candidate_node = URIRef(literal_val)
                    ts_uuid = None
                    for _uuid in g.objects(candidate_node, REF.hasTimeseriesId):
                        ts_uuid = str(_uuid)
                        break
                    if not ts_uuid:
                        if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", literal_val):
                            ts_uuid = literal_val
                    if not ts_uuid:
                        ts_uuid = str(uuid.uuid4())
                    bn = BNode()
                    g.add((bn, RDF.type, REF.TimeseriesReference))
                    g.add((bn, REF.hasTimeseriesId, Literal(ts_uuid)))
                    g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
                    g.add((bn, REF.storedAt, BLDG_USED.database1))
                    g.add((c, REF.hasExternalReference, bn))
                    g.remove((c, REF.hasExternalReference, obj))
                    changed += 1
                elif isinstance(obj, URIRef):
                    if (obj, RDF.type, REF.TimeseriesReference) not in g:
                        g.add((obj, RDF.type, REF.TimeseriesReference))
                    if (obj, REF.storedAt, None) not in g:
                        g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
                        g.add((obj, REF.storedAt, BLDG_USED.database1))
                    if (obj, REF.hasTimeseriesId, None) not in g:
                        g.add((obj, REF.hasTimeseriesId, Literal(str(uuid.uuid4()))))
            # Already had a ref; skip adding a new one
            continue
        # No existing ref: add a new one
        ts_id = str(uuid.uuid4())
        bn = BNode()
        g.add((bn, RDF.type, REF.TimeseriesReference))
        g.add((bn, REF.hasTimeseriesId, Literal(ts_id)))
        g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
        g.add((bn, REF.storedAt, BLDG_USED.database1))
        g.add((c, REF.hasExternalReference, bn))
        changed += 1

    # Write out, relying on bound prefixes
    out_ttl.write_text(g.serialize(format="turtle"), encoding="utf-8")
    return changed


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python add_timeseries_refs_used.py <in_ttl> <out_ttl>")
        raise SystemExit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    count = add_timeseries_refs(src, out)
    print(f"Annotated {count} sensor instances with timeseries references")
