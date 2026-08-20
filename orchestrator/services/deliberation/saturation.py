"""
saturation.py — SATURATE provisioner: turn the coverage gap matrix into TTL (V4-T08).

For every (space × modality) the audit marks ``missing`` or ``unbacked``, emit a
simulated sensor individual with BOTH halves of the connect-data contract (#8):
the Brick point triples AND a ``ref:TimeseriesReference`` (deterministic uuid5 +
``ref:storedAt`` the modality's narrow table key). Every generated sensor carries
``ontosage:isSimulated true`` — the epistemic label that flows through to
per-answer provenance — plus an ``rdfs:comment`` marker for greppability.

Also emits the canonical ``ontosage:zoneId`` literal per discovered space — the
join key that repairs the manifest↔ontology bridge (BUG-147 / V4-T13).

Deliberate choices:
  * TTL is emitted here rather than via sensor_ttl_generator.generate_timeseries_ttl,
    because that generator links sensors with ``brick:isPartOf`` (wrong idiom for
    location-based discovery — sensors are found via ``brick:hasLocation``) and
    cannot carry ``ontosage:isSimulated``. The ``ref:`` block conventions are kept
    byte-compatible with it.
  * Full IRIs (``<ns+local>``) are used instead of prefixed names so space locals
    containing dots ('Room_5.28') can never produce invalid Turtle PN_LOCAL names.
  * Output is deterministically ordered and timestamp-free: re-running on the same
    graph state yields byte-identical files (idempotency = the acceptance test).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from orchestrator.services.datasource_registry import derive_point_uuid
from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    ModalitySpec,
    SpaceCoverage,
    _local,
)
from shared.utils import get_logger

logger = get_logger(__name__)

_COMMENT_MARKER = "synthetic-saturation-v4"

_PREFIXES = (
    "@prefix brick: <https://brickschema.org/schema/Brick#> .\n"
    "@prefix ref:   <https://brickschema.org/schema/Brick/ref#> .\n"
    "@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .\n"
    "@prefix ontosage: <http://ontosage.org/capabilities#> .\n"
)

# zone-id heuristic: a dotted number anywhere in the label ('HVAC Zone 5.28' -> '5.28')
_DOTTED_ID_RE = re.compile(r"\b(\d+\.\d+[A-Za-z]?)\b")


def _qualify_class(brick_class: str) -> str:
    """Render a configured class name as a prefixed IRI.

    A bare name means Brick (the overwhelmingly common case). An explicitly
    prefixed name is emitted verbatim, which is how a modality Brick does not
    cover declares itself in OntoSage's own namespace instead. Before V5-T10
    every name was minted as ``brick:<name>`` unconditionally, which is how 52
    ``brick:Sound_Level_Sensor`` instances came to exist for a class Brick does
    not define (BUG-179) — a term invented inside someone else's namespace.
    """
    return brick_class if ":" in brick_class else f"brick:{brick_class}"


@dataclass
class SaturationItem:
    """One simulated sensor to provision."""

    space_iri: str
    space_label: str
    modality: str
    sensor_iri: str
    uuid: str
    brick_class: str
    table: str
    unit: str


def plan_saturation(
    building_id: str,
    namespace: str,
    spaces: List[SpaceCoverage],
    modalities: List[ModalitySpec],
    building_iri: Optional[str] = None,
) -> Dict[str, List[SaturationItem]]:
    """Gap matrix -> {modality: [SaturationItem]} for every non-present cell.

    ``unbacked`` cells are provisioned too: the modeled-but-dataless original stays
    untouched, and the new simulated sensor supplies the answerable point (this is
    how legacy placeholder-UUID sensors get superseded rather than repaired).
    """
    plan: Dict[str, List[SaturationItem]] = {}
    for spec in modalities:
        sat = spec.sat or {}
        if not sat.get("table") or not sat.get("brick_class"):
            logger.warning(f"[saturation] modality '{spec.name}' has no sat config — skipped")
            continue

        # V5-T09: scoped modalities anchor to floors / the building instead of
        # rooms. Emission is deterministic and named-graph-replacing, so scoped
        # sets are always emitted in full — idempotent by construction.
        scope = str(sat.get("scope", "room")).lower()
        if scope in ("floor", "building"):
            anchors: List[tuple] = []
            if scope == "floor":
                seen = set()
                for sc in sorted(spaces, key=lambda s: s.space_iri):
                    fl = (sc.floor or "").strip()
                    if fl and fl not in seen:
                        seen.add(fl)
                        anchors.append((f"{namespace}{fl}", fl))
            else:
                anchors.append((building_iri or f"{namespace}Building", "building"))
            items = [
                SaturationItem(
                    space_iri=a_iri,
                    space_label=a_local,
                    modality=spec.name,
                    sensor_iri=f"{namespace}{a_local}_sat_{spec.name}",
                    uuid=derive_point_uuid(building_id, f"sat_{spec.name}", a_local),
                    brick_class=sat["brick_class"],
                    table=sat["table"],
                    unit=sat.get("unit", ""),
                )
                for a_iri, a_local in anchors
            ]
            if items:
                plan[spec.name] = items
            continue

        items: List[SaturationItem] = []
        for sc in sorted(spaces, key=lambda s: s.space_iri):
            entry = sc.modalities.get(spec.name)
            if entry is None or entry["status"] == STATUS_PRESENT:
                continue
            space_local = _local(sc.space_iri)
            sensor_local = f"{space_local}_sat_{spec.name}"
            items.append(
                SaturationItem(
                    space_iri=sc.space_iri,
                    space_label=sc.label or space_local,
                    modality=spec.name,
                    sensor_iri=f"{namespace}{sensor_local}",
                    uuid=derive_point_uuid(building_id, f"sat_{spec.name}", space_local),
                    brick_class=sat["brick_class"],
                    table=sat["table"],
                    unit=sat.get("unit", ""),
                )
            )
        if items:
            plan[spec.name] = items
    return plan


def build_saturation_ttl(namespace: str, modality: str, items: List[SaturationItem]) -> str:
    """Turtle for one modality's simulated sensors (one file = one named graph = one switch)."""
    if not items:
        return ""
    table = items[0].table
    parts: List[str] = [
        f"# SATURATE (V4-T08): simulated {modality} sensors for spaces the coverage",
        f"# audit found uninstrumented. Every sensor is labeled ontosage:isSimulated.",
        f"# Rows live in the narrow table '{table}' (database_registry.yaml key).",
        _PREFIXES
        # the TTL validator requires every <id>_*.ttl to declare the building
        # prefix matching ontology_namespace, even though we emit full IRIs
        + f"@prefix bldg:  <{namespace}> .\n",
    ]
    parts += [
        f"<{namespace}{table}>",
        "    a ref:Database ;",
        f'    rdfs:label "{table.replace("_", " ").title()}" .',
        "",
    ]
    for item in items:
        unit_suffix = f" [{item.unit}]" if item.unit and item.unit != "binary" else ""
        parts += [
            f"<{item.sensor_iri}>",
            f"    a {_qualify_class(item.brick_class)} ;",
            f'    rdfs:label "{item.space_label} {modality} (simulated){unit_suffix}"@en ;',
            f"    brick:hasLocation <{item.space_iri}> ;",
            '    ontosage:isSimulated "true"^^xsd:boolean ;',
            f'    rdfs:comment "{_COMMENT_MARKER}" ;',
            "    ref:hasExternalReference [",
            "        a ref:TimeseriesReference ;",
            f'        ref:hasTimeseriesId "{item.uuid}" ;',
            f"        ref:storedAt <{namespace}{item.table}> ;",
            "    ] .",
            "",
        ]
    return "\n".join(parts)


def zone_id_for(space_iri: str, label: str) -> str:
    """Canonical zoneId: dotted id from the label when present, else the local name."""
    m = _DOTTED_ID_RE.search(label or "")
    if m:
        return m.group(1)
    return _local(space_iri)


def build_zoneid_ttl(namespace: str, spaces: List[SpaceCoverage]) -> str:
    """Turtle asserting ontosage:zoneId for every discovered space (BUG-147 join key)."""
    if not spaces:
        return ""
    parts: List[str] = [
        "# SATURATE (V4-T08): canonical ontosage:zoneId per space — the manifest join",
        "# key the floor-plan linker matches FIRST (label matching stays as fallback).",
        _PREFIXES + f"@prefix bldg:  <{namespace}> .\n",
    ]
    for sc in sorted(spaces, key=lambda s: s.space_iri):
        parts.append(f'<{sc.space_iri}> ontosage:zoneId "{zone_id_for(sc.space_iri, sc.label)}" .')
    parts.append("")
    return "\n".join(parts)
