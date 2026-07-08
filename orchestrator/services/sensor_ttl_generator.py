"""
orchestrator/services/sensor_ttl_generator.py — Brick-compliant Turtle generator for sensor registration.

Supports:
  • TimeseriesReference  — SQL/NoSQL UUID-keyed sensors (CSV bulk registration path)
  • BACnetReference      — BACnet object-point sensors (manual TTL via OntologyTab)

Property: ref:hasExternalReference (Brick Schema ref spec, matches existing SPARQL queries)
NOT ashrae:hasExternalReference — that property appears in older Protégé exports; both are
declared as mutual sub-properties in bldg1_expanded_protege_clean.ttl, but SPARQL queries
only look for ref:hasExternalReference so use that for new additions.

Database node: ref:Database with a label only — credentials/routing live in
database_registry.yaml, not in the TTL (TTL is stored in GraphDB and must not expose secrets).

bldg: prefix: caller passes bldg_ns + bldg_prefix from settings.BUILDING_NAMESPACE /
settings.BUILDING_PREFIX so the same namespace is used regardless of which building is active.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Standard prefix block — injected at the top of every generated TTL block
# ---------------------------------------------------------------------------
_PREFIXES = (
    "@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
    "@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:    <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix brick:  <https://brickschema.org/schema/Brick#> .\n"
    "@prefix ref:    <https://brickschema.org/schema/Brick/ref#> .\n"
    "@prefix bacnet: <http://data.ashrae.org/bacnet/> .\n"
    "@prefix unit:   <http://qudt.org/vocab/unit/> .\n"
    "@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .\n"
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
# Bare class name (no colon) → auto-prefix as brick:
_BARE_CLASS_RE = re.compile(r"^[A-Z][A-Za-z0-9_]+$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm_class(raw: str) -> str:
    """Return a prefixed Brick class term, adding brick: when bare."""
    raw = raw.strip()
    if not raw:
        return "brick:Sensor"
    if ":" in raw:
        return raw
    if _BARE_CLASS_RE.match(raw):
        return f"brick:{raw}"
    return raw


def _norm_location(raw: str, bldg_prefix: str) -> Optional[str]:
    """Return a prefixed location term, or None if empty."""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("<") or ":" in raw:
        return raw
    return f"{bldg_prefix}:{raw}"


def _local_to_ref(local_id: str, bldg_prefix: str) -> str:
    """Convert a bare identifier to a bldg:-prefixed node reference."""
    local_id = local_id.strip().replace(" ", "_")
    if ":" in local_id:
        return local_id
    return f"{bldg_prefix}:{local_id}"


# ---------------------------------------------------------------------------
# Public: TimeseriesReference — bulk CSV path
# ---------------------------------------------------------------------------


def parse_sensor_csv(text: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Parse CSV sensor registration text into row dicts.

    Expected header (case-sensitive): local_id,brick_class,location,uuid[,unit,label]
    Lines starting with '#' or blank lines are ignored.

    Returns (rows, parse_warnings).
    """
    warnings: List[str] = []
    clean_lines = [
        ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    if not clean_lines:
        return [], ["CSV is empty"]

    reader = csv.DictReader(io.StringIO("\n".join(clean_lines)))
    fieldnames = [f.strip() for f in (reader.fieldnames or [])]
    required = {"local_id", "brick_class", "location", "uuid"}
    missing = required - set(fieldnames)
    if missing:
        return [], [f"Missing required columns: {', '.join(sorted(missing))}. Got: {fieldnames}"]

    rows: List[Dict[str, str]] = []
    for raw in reader:
        rows.append({k.strip(): (v or "").strip() for k, v in raw.items()})
    return rows, warnings


def generate_timeseries_ttl(
    rows: List[Dict[str, str]],
    db_key: str,
    bldg_ns: str,
    bldg_prefix: str = "bldg",
    db_label: Optional[str] = None,
) -> Tuple[str, List[str], int]:
    """Generate Brick Turtle for SQL/timeseries sensor rows.

    Args:
        rows: Dicts with keys local_id, brick_class, location, uuid; optional unit, label.
        db_key: database_registry.yaml key (e.g. 'database1') → bldg:<db_key>.
        bldg_ns: Building ontology base URI (settings.BUILDING_NAMESPACE).
        bldg_prefix: Short SPARQL prefix (settings.BUILDING_PREFIX, default 'bldg').
        db_label: Human-readable database label; defaults to title-cased db_key.

    Returns:
        (ttl_text, gen_warnings, point_count)
    """
    warnings: List[str] = []
    parts: List[str] = [
        _PREFIXES,
        f"@prefix {bldg_prefix}: <{bldg_ns}> .",
        "",
    ]

    db_ref = f"{bldg_prefix}:{db_key}"
    label = db_label or db_key.replace("-", " ").replace("_", " ").title()

    # Database node — label only; credentials live in database_registry.yaml
    parts += [
        f"# Routing config for this database: database_registry.yaml key '{db_key}'",
        f"# Credentials are NOT stored in the ontology — see database_registry.yaml.",
        f"{db_ref}",
        f"    a ref:Database ;",
        f'    rdfs:label "{label}" .',
        "",
    ]

    point_count = 0
    for i, row in enumerate(rows, start=2):
        local_id = row.get("local_id", "").strip()
        brick_class = _norm_class(row.get("brick_class", ""))
        location = _norm_location(row.get("location", ""), bldg_prefix)
        uuid = row.get("uuid", "").strip()
        unit = row.get("unit", "").strip() or None
        lbl = (row.get("label", "") or local_id).strip()

        if not local_id:
            warnings.append(f"Row {i}: missing local_id — skipped")
            continue
        if not _UUID_RE.match(uuid):
            warnings.append(f"Row {i} ({local_id}): invalid UUID '{uuid}' — skipped")
            continue

        sensor_ref = _local_to_ref(local_id, bldg_prefix)
        block = [f"{sensor_ref}"]
        block.append(f"    a {brick_class} ;")
        if lbl:
            block.append(f'    rdfs:label "{lbl}"@en ;')
        if location:
            block.append(f"    brick:isPartOf {location} ;")
        if unit:
            block.append(f"    brick:hasUnit {unit} ;")
        block += [
            f"    ref:hasExternalReference [",
            f"        a ref:TimeseriesReference ;",
            f'        ref:hasTimeseriesId "{uuid}" ;',
            f"        ref:storedAt {db_ref} ;",
            f"    ] .",
        ]
        parts.append("\n".join(block))
        parts.append("")
        point_count += 1

    return "\n".join(parts), warnings, point_count


# ---------------------------------------------------------------------------
# Public: BACnetReference — used by the manual TTL template in OntologyTab
# ---------------------------------------------------------------------------


def bacnet_device_ttl(
    device_local_id: str,
    device_instance: int,
    ip_hex: str,
    gateway_hex: str,
    bldg_ns: str,
    bldg_prefix: str = "bldg",
) -> str:
    """Return Turtle for a single BACnet device node."""
    ref = _local_to_ref(device_local_id, bldg_prefix)
    return (
        f"{_PREFIXES}"
        f"@prefix {bldg_prefix}: <{bldg_ns}> .\n\n"
        f"{ref}\n"
        f"    a bacnet:BACnetDevice ;\n"
        f"    bacnet:device-instance {device_instance} ;\n"
        f"    bacnet:hasPort [\n"
        f"        a bacnet:Port ;\n"
        f"        bacnet:network-type bacnet:NetworkType.ipv4 ;\n"
        f'        bacnet:ip-address "{ip_hex}"^^xsd:hexBinary ;\n'
        f'        bacnet:ip-default-gateway "{gateway_hex}"^^xsd:hexBinary ;\n'
        f"    ] .\n"
    )


def bacnet_point_ttl(
    local_id: str,
    brick_class: str,
    location: str,
    object_identifier: str,
    object_name: str,
    device_ref: str,
    unit: Optional[str],
    label: Optional[str],
    bldg_ns: str,
    bldg_prefix: str = "bldg",
) -> str:
    """Return Turtle for a single BACnet sensor point (explicit-field style)."""
    sensor_ref = _local_to_ref(local_id, bldg_prefix)
    brick_class = _norm_class(brick_class)
    loc = _norm_location(location, bldg_prefix)
    lbl = label or local_id
    unit_line = f"    brick:hasUnit {unit} ;\n" if unit else ""
    loc_line = f"    brick:isPartOf {loc} ;\n" if loc else ""
    return (
        f"{_PREFIXES}"
        f"@prefix {bldg_prefix}: <{bldg_ns}> .\n\n"
        f"{sensor_ref}\n"
        f"    a {brick_class} ;\n"
        f'    rdfs:label "{lbl}"@en ;\n'
        f"{loc_line}"
        f"{unit_line}"
        f"    ref:hasExternalReference [\n"
        f"        a ref:BACnetReference ;\n"
        f'        bacnet:object-identifier "{object_identifier}"^^bacnet:objectIdentifier ;\n'
        f'        bacnet:object-name "{object_name}" ;\n'
        f"        bacnet:objectOf {device_ref} ;\n"
        f"    ] .\n"
    )
