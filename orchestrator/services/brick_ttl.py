"""
brick_ttl.py — the SINGLE canonical builder for Brick time-series-point TTL.

Every place OntoSage adds a sensor/device to the ontology (synthetic data sources
AND external-DB sensor registration) emits triples through here, so the syntax is
identical to the hand-authored / Protégé-exported bldg1 ontology. Matching that
exact shape is what lets SPARQL resolve new points the same way it resolves the
existing ones.

Canonical shape (mirrors bldg1_expanded_protege_clean.ttl):

    bldg:<local> rdf:type owl:NamedIndividual ,
            brick:Class ,
            brick:Entity ,
            <brick_class> ,
            brick:Point ,
            brick:Sensor ;
        ashrae:hasExternalReference _:ref_<local> ;
        brick:hasLocation bldg:<location> ;
        ref:hasExternalReference _:ref_<local> ;
        rdfs:label "<label>"@en .

    _:ref_<local> rdf:type ashrae:ExternalReference ,
            ref:ExternalReference ,
            ref:TimeseriesReference ;
        ref:hasTimeseriesId "<uuid>" ;
        ref:storedAt bldg:<stored_at> .

Key fidelity points vs. a naive generator:
  * ``rdf:type`` (not the ``a`` shorthand), matching the export.
  * ``brick:Class`` + ``brick:Entity`` included in the type list (bldg1 does this).
  * ONE shared *named* blank node (``_:ref_<local>``) referenced by BOTH
    ``ashrae:hasExternalReference`` and ``ref:hasExternalReference`` — exactly like
    bldg1's ``_:genidNNN`` — NOT two separate inline ``[ … ]`` nodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_PREFIXES = (
    "@prefix bldg:   <{ns}> .\n"
    "@prefix brick:  <https://brickschema.org/schema/Brick#> .\n"
    "@prefix ref:    <https://brickschema.org/schema/Brick/ref#> .\n"
    "@prefix ashrae: <http://data.ashrae.org/standard223#> .\n"
    "@prefix unit:   <http://qudt.org/vocab/unit/> .\n"
    "@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
    "@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:    <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .\n"
)


def _bnode_label(local: str) -> str:
    """Deterministic, Turtle-safe blank-node label for a point's external ref."""
    safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in local)
    return f"_:ref_{safe}"


def _escape_ttl_string(s: str) -> str:
    """Escape a value for a Turtle double-quoted string literal (label / uuid).

    An admin CSV can carry a quote in a label (``Room 5.01 "North"``); unescaped it
    breaks out of the literal and either corrupts the graph or fails the upload.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _safe_local_name(s: str) -> str:
    """Sanitize a Turtle prefixed-name LOCAL part (the piece after ``bldg:``)."""
    return "".join(c if (c.isalnum() or c in "_-.") else "_" for c in s)


def _safe_prefixed_name(s: str) -> str:
    """Sanitize a full prefixed name (``brick:X`` / ``bldg:Y``), keeping the colon."""
    return "".join(c if (c.isalnum() or c in "_-.:") else "_" for c in s)


def point_block(
    local: str,
    brick_class: str,
    location: str,
    uuid: str,
    stored_at: str,
    *,
    unit: Optional[str] = None,
    label: Optional[str] = None,
) -> str:
    """One sensor's two triple blocks (individual + shared external-reference node)."""
    bc = _safe_prefixed_name(brick_class if ":" in brick_class else f"brick:{brick_class}")
    loc = _safe_prefixed_name(location if ":" in location else f"bldg:{location}")
    stored = _safe_prefixed_name(stored_at if ":" in stored_at else f"bldg:{stored_at}")
    lbl = label or local.replace("_", " ")
    genid = _bnode_label(local)

    # owl:NamedIndividual + brick meta-types + the point's class + Point/Sensor,
    # de-duplicated but order-preserving (bldg1 enumerates the hierarchy explicitly
    # because GraphDB runs with no subclass reasoning).
    types = [
        "owl:NamedIndividual",
        "brick:Class",
        "brick:Entity",
        bc,
        "brick:Point",
        "brick:Sensor",
    ]
    seen: set = set()
    tlist = [t for t in types if not (t in seen or seen.add(t))]
    type_str = " ,\n        ".join(tlist)
    unit_line = (
        f"    brick:hasUnit {_safe_prefixed_name(unit)} ;\n" if (unit and ":" in unit) else ""
    )

    return (
        f"bldg:{_safe_local_name(local)} rdf:type {type_str} ;\n"
        f"    ashrae:hasExternalReference {genid} ;\n"
        f"{unit_line}"
        f"    brick:hasLocation {loc} ;\n"
        f"    ref:hasExternalReference {genid} ;\n"
        f'    rdfs:label "{_escape_ttl_string(lbl)}"@en .\n'
        f"\n"
        f"{genid} rdf:type ashrae:ExternalReference ,\n"
        f"        ref:ExternalReference ,\n"
        f"        ref:TimeseriesReference ;\n"
        f'    ref:hasTimeseriesId "{_escape_ttl_string(uuid)}" ;\n'
        f"    ref:storedAt {stored} .\n"
    )


def points_document(
    namespace: str, points: List[Dict[str, Any]], *, header: Optional[str] = None
) -> str:
    """Full Turtle document: prefixes + one canonical block per point.

    Each point dict: {local, brick_class, location, uuid, stored_at, unit?, label?}.
    """
    ns = (namespace or "").rstrip("#/") + "#"
    parts: List[str] = []
    if header:
        parts.append(f"# {header}")
    parts.append(_PREFIXES.format(ns=ns))
    for pt in points:
        parts.append(
            point_block(
                pt["local"],
                pt["brick_class"],
                pt["location"],
                pt["uuid"],
                pt["stored_at"],
                unit=pt.get("unit"),
                label=pt.get("label"),
            )
        )
    return "\n".join(parts)
