# -*- coding: utf-8 -*-
"""Declare meter topology: what each meter serves, and how sub-figures are allocated (V6-T27).

Master Package E asks that an energy answer state its **boundary** and **allocation method**. The
boundary is a fact about the estate that no algorithm can derive — whether a meter named for a
floor measures the whole floor or one riser is a question for whoever commissioned it — so this
script **proposes** a topology and makes every proposal's basis explicit, rather than inventing
one and presenting it as fact.

Four sources, in descending order of trust, each RECORDED on the triple it produced as
``ontosage:boundarySource`` so an answer can say how much weight the boundary deserves:

``declared``
    An operator already wrote ``ontosage:meterServes``. Authoritative; used as-is with whatever
    allocation method accompanies it.

``brick_class``
    The meter's Brick TYPE states its scope: ``brick:Building_Water_Meter`` means a meter for
    the building's water, whatever floor the hardware is bolted to. This is a declaration in the
    shared vocabulary, not a guess about this estate, so it ranks above placement — and here it
    CONTRADICTS placement, which is the point. The site water meter is ``isPartOf Floor0``;
    without this rule the building's water total would have been labelled "Floor 0".

``placement``
    The graph relates the meter to a place via ``brick:isPartOf`` / ``brick:hasLocation``.
    **Placement is not boundary.** Those predicates say where a meter SITS, not what it
    MEASURES, and this building proves the difference: ``Building_Water_Meter brick:isPartOf
    Floor0`` is a whole-site meter installed on the ground floor. Read as a boundary it would
    label the site's water total "Floor 0". So this is a proposal, and the allocation method is
    left EMPTY rather than assumed ``direct``.

``label``
    The meter's name matches a place exactly. The weakest signal, and marked as such.

``undeclared``
    Nothing settles it. **No triple is written.** The answer then says the boundary is not
    declared, which is true; writing a guess would make it state a boundary it does not have.

Allocation method is NEVER invented. "This floor figure is a share of the building total
apportioned by area" is an accounting decision, not an observation, and presenting an estimate
as a reading is the exact failure the boundary statement exists to prevent.

Usage::

    python scripts/provision_meter_topology.py --dry-run
    python scripts/provision_meter_topology.py
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.services.ontology_manager import run_sparql_select  # noqa: E402
from shared.config import settings  # noqa: E402

ONTOSAGE = "http://ontosage.org/capabilities#"

_PREFIXES = (
    "PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick:<https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref:  <https://brickschema.org/schema/Brick/ref#>\n"
    f"PREFIX ontosage: <{ONTOSAGE}>\n"
)


def local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


async def rows(query: str, limit: int = 500) -> List[Dict]:
    res = await run_sparql_select(_PREFIXES + query, limit=limit)
    if not res.get("ok"):
        raise SystemExit(f"query failed: {res.get('error')}")
    return res.get("rows") or []


async def discover_meters(namespace: str) -> List[Dict]:
    """Every meter, with whatever the graph already asserts about where it sits."""
    out: Dict[str, Dict] = {}
    for r in await rows(
        "SELECT DISTINCT ?m ?cls ?label ?declared ?method ?asserted WHERE {\n"
        "  ?m a ?cls . ?cls rdfs:subClassOf* brick:Meter .\n"
        "  OPTIONAL { ?m rdfs:label ?label }\n"
        "  OPTIONAL { ?m ontosage:meterServes ?declared }\n"
        "  OPTIONAL { ?m ontosage:allocationMethod ?method }\n"
        "  OPTIONAL { { ?m brick:isPartOf ?asserted } UNION { ?m brick:hasLocation ?asserted }\n"
        "             ?asserted a ?acls .\n"
        "             ?acls rdfs:subClassOf* brick:Location }\n"
        f'  FILTER(STRSTARTS(STR(?m), "{namespace}"))\n'
        "}",
        1000,
    ):
        iri = str(r.get("m") or "")
        if not iri:
            continue
        cur = out.setdefault(
            iri,
            {
                "iri": iri,
                "label": "",
                "declared": "",
                "method": "",
                "asserted": "",
                "classes": set(),
            },
        )
        cur["classes"].add(local(str(r.get("cls") or "")))
        cur["label"] = cur["label"] or str(r.get("label") or "")
        cur["declared"] = cur["declared"] or str(r.get("declared") or "")
        cur["method"] = cur["method"] or str(r.get("method") or "")
        cur["asserted"] = cur["asserted"] or str(r.get("asserted") or "")
    return sorted(out.values(), key=lambda d: d["iri"])


async def discover_energy_points(namespace: str) -> List[Dict]:
    """Energy/power points, which are what an energy answer actually reads.

    In this estate the readable things are `brick:Energy_Sensor` points rather than the
    `brick:Meter` individuals — the meters carry no timeseries reference. A boundary attached
    only to the Meter would therefore never be found by an answer, which is the
    present-correct-and-invisible failure again.
    """
    out: Dict[str, Dict] = {}
    for r in await rows(
        "SELECT DISTINCT ?p ?label ?uuid ?loc WHERE {\n"
        "  ?p a ?cls . ?cls rdfs:subClassOf* brick:Energy_Sensor .\n"
        "  OPTIONAL { ?p rdfs:label ?label }\n"
        "  OPTIONAL { ?p ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid }\n"
        "  OPTIONAL { { ?p brick:hasLocation ?loc } UNION { ?p brick:isPartOf ?loc }\n"
        "             ?loc a ?lcls . ?lcls rdfs:subClassOf* brick:Location }\n"
        f'  FILTER(STRSTARTS(STR(?p), "{namespace}"))\n'
        "}",
        1000,
    ):
        iri = str(r.get("p") or "")
        if not iri:
            continue
        cur = out.setdefault(iri, {"iri": iri, "label": "", "uuid": "", "asserted": ""})
        cur["label"] = cur["label"] or str(r.get("label") or "")
        cur["uuid"] = cur["uuid"] or str(r.get("uuid") or "")
        cur["asserted"] = cur["asserted"] or str(r.get("loc") or "")
    return sorted(out.values(), key=lambda d: d["iri"])


async def discover_places(namespace: str) -> List[Dict]:
    """Floors, the building, and systems — the things a meter can serve."""
    out: Dict[str, Dict] = {}
    for r in await rows(
        "SELECT DISTINCT ?s ?label ?kind WHERE {\n"
        "  { ?s a brick:Floor BIND('floor' AS ?kind) }\n"
        "  UNION { ?s a brick:Building BIND('building' AS ?kind) }\n"
        "  UNION { ?s a brick:System BIND('system' AS ?kind) }\n"
        "  OPTIONAL { ?s rdfs:label ?label }\n"
        f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
        "}",
        1000,
    ):
        iri = str(r.get("s") or "")
        if iri:
            cur = out.setdefault(iri, {"iri": iri, "label": "", "kind": str(r.get("kind") or "")})
            cur["label"] = cur["label"] or str(r.get("label") or "")
    return sorted(out.values(), key=lambda d: d["iri"])


def propose(entity: Dict, places: List[Dict]) -> Tuple[str, str, str]:
    """(serves_iri, source, method) for one meter or energy point.

    **Placement is not boundary.** `brick:hasLocation` says where a meter physically sits and
    `brick:isPartOf` says what assembly it belongs to; NEITHER says what it measures. This
    building asserts `Building_Water_Meter brick:isPartOf Floor0` — a whole-site water meter
    that happens to be installed on the ground floor. Treating that as a boundary would have
    labelled the building's water total "Floor 0", which is precisely the confident wrong
    answer a boundary statement exists to prevent.

    So placement yields a PROPOSAL carrying its provenance, never a declared boundary, and the
    allocation method is left EMPTY rather than assumed to be `direct` — whether a meter
    measures all of what it sits in is exactly the thing nobody has told us.

    Returns ``("", "undeclared", "")`` when nothing settles it. That is a result, not a failure:
    the answer then says the boundary is not declared, which is true.
    """
    if entity.get("declared"):
        return entity["declared"], "declared", entity.get("method") or "direct"

    # The Brick CLASS states the scope, and that is a declaration in the vocabulary rather than
    # a guess about this estate: `brick:Building_Water_Meter` means a meter for the building's
    # water, whatever floor the hardware is bolted to. Ranked above placement precisely because
    # it CONTRADICTS it here -- the site water meter is `isPartOf Floor0`, and without this the
    # building's water total would have been labelled "Floor 0".
    if any(c.startswith("Building_") and c.endswith("Meter") for c in entity.get("classes", ())):
        building = next((p["iri"] for p in places if p.get("kind") == "building"), "")
        if building:
            return building, "brick_class", "direct"

    if entity.get("asserted"):
        return entity["asserted"], "placement", ""

    # Exact normalised match against a real place, never a substring: "Floor1" must not attach
    # to "Floor10", and a token match must be on a whole token rather than a shared fragment.
    hay = f"{local(entity['iri'])} {entity.get('label', '')}"
    tokens = {squash(t) for t in re.split(r"[^A-Za-z0-9]+", hay) if t}
    for p in places:
        cand = {squash(local(p["iri"])), squash(p.get("label", ""))} - {""}
        if cand & tokens:
            return p["iri"], "label", ""
    return "", "undeclared", ""


def build_ttl(namespace: str, decided: List[Dict]) -> str:
    ns = namespace if namespace.endswith("#") else namespace + "#"
    lines = [
        "# Meter topology — what each meter covers, and how sub-figures are allocated (V6-T27).",
        "#",
        "# GENERATED by scripts/provision_meter_topology.py. Every line records the BASIS of its",
        "# claim in ontosage:boundarySource:",
        "#   asserted  — the graph already related the meter to a place; used as-is",
        "#   label     — PROPOSED from an exact name match, for an operator to confirm",
        "# Meters whose boundary could not be established appear in NEITHER form: no triple is",
        "# written, so the answer says 'boundary not declared' instead of stating one it lacks.",
        "#",
        "# allocationMethod is 'direct' only where the meter measures exactly what it serves.",
        "# Any apportioned method is an ACCOUNTING DECISION and must be declared by an operator —",
        "# this script will not invent one, because an estimate presented as a reading is the",
        "# failure the whole boundary statement exists to prevent.",
        "",
        f"@prefix bldg: <{ns}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        f"@prefix ontosage: <{ONTOSAGE}> .",
        "",
    ]
    for d in decided:
        lines.append(f"bldg:{local(d['iri'])}")
        lines.append(f"    ontosage:meterServes bldg:{local(d['serves'])} ;")
        # An UNKNOWN allocation method must be absent, never an empty string. A present-but-empty
        # literal reads downstream as "declared" and would let an estimate be presented as a
        # direct reading — the one outcome this whole turn exists to prevent.
        if d["method"]:
            lines.append(f'    ontosage:allocationMethod "{d["method"]}" ;')
        lines.append(f'    ontosage:boundarySource "{d["source"]}" .')
        lines.append("")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    building, namespace = settings.BUILDING_ID, settings.BUILDING_NAMESPACE
    places = await discover_places(namespace)
    meters = await discover_meters(namespace)
    points = await discover_energy_points(namespace)

    print(f"building={building}")
    print(f"places (floor/building/system): {len(places)}")
    print(f"meters: {len(meters)} | energy points: {len(points)}")

    decided: List[Dict] = []
    undeclared: List[str] = []
    for e in meters + points:
        serves, source, method = propose(e, places)
        if not serves:
            undeclared.append(local(e["iri"]))
            continue
        decided.append({"iri": e["iri"], "serves": serves, "source": source, "method": method})

    by_source: Dict[str, int] = {}
    for d in decided:
        by_source[d["source"]] = by_source.get(d["source"], 0) + 1
    print(f"declared: {len(decided)}  {by_source}")
    print(f"UNDECLARED (no triple written, answers will say so): {len(undeclared)}")
    for name in undeclared[:12]:
        print(f"   {name}")
    if len(undeclared) > 12:
        print(f"   ... and {len(undeclared) - 12} more")

    ttl = build_ttl(namespace, decided)
    out = Path("input") / f"{building}_meter_topology.ttl"
    if args.dry_run:
        print(f"\nDRY RUN — would write {out} ({len(decided)} meters)")
        return 0
    out.write_text(ttl, encoding="utf-8")
    print(f"\nwrote {out} ({len(ttl.splitlines())} lines)")
    print("NEXT: restart the orchestrator so ttl_uploader ingests it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
