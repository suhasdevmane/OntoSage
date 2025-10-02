"""
Provenance copy of the script used to add timeseries references.

Used on: 2025-10-01
Input TTL:  bldg2/trial/dataset/bldg2.ttl
Output TTL: bldg2/trial/dataset/bldg2_timeseries.ttl
Invocation example:
  python tools/sensors/add_timeseries_refs.py bldg2/trial/dataset/bldg2.ttl bldg2/trial/dataset/bldg2_timeseries.ttl

Note: This file is a copy of tools/sensors/add_timeseries_refs.py at the time of use,
kept here so readers know exactly what was used to generate the refs for this TTL.
"""

import uuid
import re
from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS, Literal, BNode
from rdflib.namespace import OWL

BRICK = Namespace("https://brickschema.org/schema/Brick#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

# Default building namespace (will be overridden by detected 'bldg:' prefix in input TTL if present)
BLDG = Namespace("http://buildsys.org/ontologies/bldg2#")

TURTLE_HEADER = None  # no manual header; we'll bind prefixes on the graph


def _parse_turtle_with_fallback(src_ttl: Path) -> Graph:
    """Parse a Turtle file; if it fails, auto-declare undeclared prefixes and
    sanitize illegal prefixed names (like pfx:local with '/') into full IRIs,
    then parse from the sanitized data."""
    g = Graph()
    # Bind core prefixes in case input is missing them
    g.bind("brick", BRICK)
    g.bind("ref", REF)
    try:
        g.parse(src_ttl.as_posix(), format="turtle")
        return g
    except Exception:
        # Read raw text for fallback sanitation
        text = src_ttl.read_text(encoding="utf-8")

        # 1) Collect declared prefixes from the document
        declared = dict(re.findall(r"@prefix\s+([A-Za-z][\w-]*):\s*<([^>]+)>\s*\.\s*", text))

        # Try to detect a canonical building namespace (often 'bldg')
        bldg_base = declared.get("bldg")

        # 2) Find all used prefixed names not inside <...>
        #    Capture prefix and local parts
        usage_pattern = re.compile(r"(?<!<)\b([A-Za-z][\w-]*):([^\s;,)\]\}>]+)")
        used_matches = list(usage_pattern.finditer(text))
        used_prefixes = {m.group(1) for m in used_matches}

        # 3) Build a mapping of prefix -> base IRI, auto-adding undeclared ones
        prefix_bases = {**declared}
        added_prefixes = {}
        for pfx in sorted(used_prefixes):
            if pfx in prefix_bases:
                continue
            # For bldg-like prefixes (e.g., bldg1, bldg2), reuse the detected 'bldg' base if present
            if pfx.startswith("bldg") and bldg_base:
                prefix_bases[pfx] = bldg_base
            else:
                # Fallback to a generated URN namespace
                prefix_bases[pfx] = f"urn:auto/{pfx}#"
            added_prefixes[pfx] = prefix_bases[pfx]

        # 4) Prepend synthetic @prefix declarations for any added prefixes to avoid 'not bound' errors
        preamble = "".join(f"@prefix {pfx}: <{iri}> .\n" for pfx, iri in added_prefixes.items())

        # 5) Replace any prefixed name whose local contains '/' with a full IRI using the resolved base
        def sanitize_prefixed(match: re.Match) -> str:
            pfx, local = match.group(1), match.group(2)
            # If inside an angle IRI, skip (already handled by negative lookbehind)
            base = prefix_bases.get(pfx)
            if base and "/" in local:
                return f"<{base}{local}>"
            return match.group(0)

        sanitized_body = usage_pattern.sub(sanitize_prefixed, text)
        sanitized = preamble + sanitized_body

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
    for row in g.query(q):
        s = row[0]
        # Skip if already annotated
        if (s, REF.hasExternalReference, None) in g:
            continue
        # Attach a TimeseriesReference blank node
        ts_id = str(uuid.uuid4())
        bn = BNode()  # create a blank node
        g.add((bn, RDF.type, REF.TimeseriesReference))
        g.add((bn, REF.hasTimeseriesId, Literal(ts_id)))
        # Ensure database1 exists as a node in bldg namespace
        g.add((BLDG_USED.database1, RDF.type, BRICK.Database))
        g.add((bn, REF.storedAt, BLDG_USED.database1))
        g.add((s, REF.hasExternalReference, bn))
        changed += 1

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
        # Skip if already annotated
        if (c, REF.hasExternalReference, None) in g:
            continue
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
