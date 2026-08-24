#!/usr/bin/env python3
"""Generate the Question-to-Observability Matrix for the ACTIVE building (V6-T09).

Master 13.1: the artefact that *"prevents the project from claiming capabilities that the
physical deployment cannot support"*. For every question shape the router can emit, it states
what answering that shape requires and whether this building has it — naming the specific
missing element, never an aggregate score.

Read-only. It issues SPARQL and reads config; it never writes to the graph, never edits
`input/`, and can run while other work is in flight.

    python scripts/build_observability_matrix.py                    # print
    python scripts/build_observability_matrix.py --md out.md --csv out.csv

**Why a generator and not a spreadsheet.** A hand-maintained table is stale the moment a
sensor is added or a modality declared, and it becomes a third place — after the intent
registry and the evidence policy — where the system's vocabulary is restated and can drift.
Everything below is derived from what the pipeline already declares, so regenerating after
connecting a source flips exactly the affected rows and nothing else.

**Building-agnostic.** Shapes come from the intent registry including per-building overlays;
thresholds from the evidence policy; modalities from the building's own modality config;
satisfaction from its own graph. No building appears in this file.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ── what the building has ────────────────────────────────────────────────────


async def _run(query: str, limit: int = 5000):
    from orchestrator.services.ontology_manager import run_sparql_select

    return await run_sparql_select(query, limit=limit)


async def gather(namespace: str) -> Dict[str, object]:
    """Everything the assessment needs, in as few round trips as possible."""
    from orchestrator.services.deliberation.coverage_audit import load_modalities

    mods = load_modalities(None)
    facts: Dict[str, object] = {}

    # 1. how many room-like spaces exist
    q_spaces = (
        "PREFIX brick:<https://brickschema.org/schema/Brick#> "
        "PREFIX rdfs:<http://www.w3.org/2000/01/rdf-schema#> "
        "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c . "
        "?c rdfs:subClassOf* brick:Location . "
        f'FILTER(STRSTARTS(STR(?s), "{namespace}")) }}'
    )
    r = await _run(q_spaces, limit=5)
    n_spaces = int(((r.get("rows") or [{}])[0]).get("n") or 0) if r.get("ok") else 0
    facts["n_spaces"] = n_spaces

    # 2. per modality: instrumented at all, and how many DISTINCT spaces have one in-room
    instrumented: List[str] = []
    coverage: Dict[str, float] = {}
    cadence: Dict[str, bool] = {}
    calibration: Dict[str, bool] = {}
    for spec in mods:
        classes = " ".join(f"brick:{c}" for c in spec.brick_classes if c)
        if not classes:
            continue
        q = (
            "PREFIX brick:<https://brickschema.org/schema/Brick#> "
            "PREFIX ref:<https://brickschema.org/schema/Brick/ref#> "
            "PREFIX o:<http://ontosage.org/schema#> "
            "SELECT (COUNT(DISTINCT ?p) AS ?pts) (COUNT(DISTINCT ?loc) AS ?spaces) "
            "(COUNT(DISTINCT ?cad) AS ?cads) (COUNT(DISTINCT ?cal) AS ?cals) WHERE { "
            f"VALUES ?cls {{ {classes} }} ?p a ?cls . "
            f'FILTER(STRSTARTS(STR(?p), "{namespace}")) '
            "OPTIONAL { ?p brick:hasLocation ?loc } "
            "OPTIONAL { ?p o:archivalIntervalS ?c1 BIND(?p AS ?cad) } "
            "OPTIONAL { ?p o:calibratedOn ?c2 BIND(?p AS ?cal) } }"
        )
        rr = await _run(q, limit=5)
        row = (rr.get("rows") or [{}])[0] if rr.get("ok") else {}
        pts = int(row.get("pts") or 0)
        spaces = int(row.get("spaces") or 0)
        if pts:
            instrumented.append(spec.name)
            coverage[spec.name.lower()] = (spaces / n_spaces) if n_spaces else 0.0
            cadence[spec.name.lower()] = int(row.get("cads") or 0) > 0
            # SHARE, not any-of: "one point of this modality is calibrated" would let a
            # single commissioned instrument vouch for a whole building's standards claims,
            # which is the substitution shape this programme keeps meeting. A safety shape
            # needs every contributing instrument calibrated, so the share is what matters.
            calibration[spec.name.lower()] = (int(row.get("cals") or 0) / pts) if pts else 0.0
    facts["instrumented"] = instrumented
    facts["coverage"] = coverage
    facts["cadence"] = cadence
    facts["calibration"] = calibration

    # 3. which non-sensor systems this building has actually DECLARED (V6-T25 closes the
    #    caveat this line carried: it was hardcoded empty, which was true on the day but
    #    would have stayed "true" in the report the moment someone connected a source).
    #    Read from the building's own feeds.yaml, so connecting a timetable flips exactly
    #    the affected rows on the next regeneration and nothing else.
    facts["connected_systems"] = _declared_systems()
    return facts


def _declared_systems() -> List[str]:
    """Non-sensor systems declared in the ACTIVE building's feeds.yaml. [] on any failure —
    an unreadable config is honestly 'nothing declared', not an invented connection."""
    try:
        import yaml

        from orchestrator.services.feeds.base import FeedSpec
        from orchestrator.services.feeds.institutional import declared_systems

        for candidate in (REPO / "input" / "feeds.yaml",):
            if not candidate.exists():
                continue
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            specs = []
            for entry in data.get("feeds") or []:
                try:
                    specs.append(FeedSpec(**entry))
                except Exception:
                    continue
            return declared_systems(specs)
    except Exception as exc:  # pragma: no cover - config is optional
        print(f"(feeds.yaml unreadable: {exc})")
    return []


# ── what each shape needs ────────────────────────────────────────────────────


def shapes_from_registry() -> List[str]:
    """Every intent the router can emit, base registry plus per-building overlays."""
    text = (REPO / "orchestrator/intents/intent_definitions.yaml").read_text(encoding="utf-8")
    for overlay in list(REPO.glob("input/intents.yaml")) + list(REPO.glob("bldg*/intents.yaml")):
        text += overlay.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^\s*-\s*name:\s*(\w+)", text, re.M)))


#: Which modalities a shape reads. Shapes absent from this map read no sensor (a greeting, a
#: policy lookup), which is a legitimate answer to "what does this need" — not a gap.
_SHAPE_MODALITIES: Dict[str, Sequence[str]] = {
    "sensor_data": ("temperature", "co2", "humidity"),
    "analytics": ("temperature", "co2"),
    "trend": ("temperature", "co2"),
    "compare": ("temperature",),
    "anomaly": ("temperature", "co2"),
    "diagnosis": ("temperature", "co2"),
    "compliance": ("co2", "temperature"),
    "deliberate": ("temperature", "co2", "noise"),
    "recommend": ("temperature", "co2"),
    "planner": ("occupancy",),
    "alert": ("temperature", "co2"),
}

_BUILDING_SCOPE = {"discovery", "metadata", "report", "export", "capability", "self_description"}


def requirements(shapes: Sequence[str]) -> List:
    from orchestrator.services.evidence.matrix import (
        AUTHORITATIVE_SYSTEM_BY_SHAPE,
        ShapeRequirement,
    )
    from orchestrator.services.evidence.policy import load_policy

    policy = load_policy()
    out = []
    for shape in shapes:
        cls = policy.consequence_class(shape)
        mods = _SHAPE_MODALITIES.get(shape, ())
        scope = "building" if shape in _BUILDING_SCOPE else "space"
        needs_auth = policy.requires_authoritative_source(cls)
        out.append(
            ShapeRequirement(
                shape=shape,
                modalities=mods,
                spatial_resolution=scope,
                max_age_minutes=(min(policy.max_age_minutes(m) for m in mods) if mods else None),
                min_completeness=policy.min_completeness(cls) if mods else None,
                consequence_class=cls,
                requires_calibration=policy.requires_calibration(cls),
                requires_authoritative_source=needs_auth and shape in AUTHORITATIVE_SYSTEM_BY_SHAPE,
                authoritative_system=AUTHORITATIVE_SYSTEM_BY_SHAPE.get(shape, ""),
                abstention=(
                    "not assessable, naming the missing element"
                    if cls == "safety_or_compliance"
                    else "answer with the gap stated"
                ),
            )
        )
    return out


# ── report ───────────────────────────────────────────────────────────────────


def render(rows, facts, building: str) -> str:
    from orchestrator.services.evidence.matrix import summarise

    s = summarise(rows)
    out = [
        f"# Question-to-Observability Matrix — {building}",
        "",
        "Master 13.1's central artefact: for every question shape the router can emit, what "
        "answering it requires and whether this building has it.",
        "",
        f"**Spaces in the graph:** {facts['n_spaces']}  ",
        f"**Instrumented modalities:** {len(facts['instrumented'])} "
        f"({', '.join(facts['instrumented'][:8])}{'…' if len(facts['instrumented']) > 8 else ''})  ",
        f"**Non-sensor systems connected:** " f"{', '.join(facts['connected_systems']) or 'none'}",
        "",
        "| Shapes | Satisfied | Unsatisfied |",
        "|---:|---:|---:|",
        f"| {s['shapes']} | {s['satisfied']} | {s['unsatisfied']} |",
        "",
        "**Why each unsatisfied shape is unsatisfied** — these are four different jobs for "
        "different people, which is why they are never summed into one score:",
        "",
        "| Cause | Occurrences |",
        "|---|---:|",
        f"| no sensor of that kind exists | {s['no sensor']} |",
        f"| partial spatial coverage | {s['partial coverage']} |",
        f"| no archival cadence declared | {s['no cadence']} |",
        f"| no calibration state declared | {s['no calibration']} |",
        f"| no authoritative system connected | {s['no authoritative system']} |",
        "",
        "## Per shape",
        "",
    ]
    for r in sorted(rows, key=lambda x: (x.satisfied, x.requirement.shape)):
        req = r.requirement
        out.append(f"### `{req.shape}` — **{r.verdict}**")
        out.append("")
        out.append(
            f"- consequence: `{req.consequence_class}` · scope: `{req.spatial_resolution}` · "
            f"abstention: {req.abstention}"
        )
        if req.modalities:
            out.append(
                f"- reads: {', '.join(req.modalities)}"
                + (f" · freshness ≤ {req.max_age_minutes:.0f} min" if req.max_age_minutes else "")
                + (f" · completeness ≥ {req.min_completeness:.0%}" if req.min_completeness else "")
            )
        if req.requires_authoritative_source:
            out.append(f"- requires: **{req.authoritative_system}** (rule R-7/R-8)")
        for m in r.missing:
            out.append(f"- ❌ {m}")
        for n in r.notes:
            out.append(f"- ✓ {n}")
        out.append("")
    return "\n".join(out)


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", default="")
    ap.add_argument("--csv", default="")
    args = ap.parse_args(argv)

    from orchestrator.services.evidence.matrix import assess_shape
    from shared.config import settings

    ns = settings.BUILDING_NAMESPACE
    building = settings.BUILDING_ID
    facts = await gather(ns)
    reqs = requirements(shapes_from_registry())
    rows = [
        assess_shape(
            r,
            instrumented_modalities=facts["instrumented"],
            space_coverage=facts["coverage"],
            cadence_declared=facts["cadence"],
            calibration_declared=facts["calibration"],
            connected_systems=facts["connected_systems"],
        )
        for r in reqs
    ]
    text = render(rows, facts, building)
    print(text[:2500])
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
        print(f"\nwrote {args.md}")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "shape",
                    "verdict",
                    "consequence",
                    "scope",
                    "modalities",
                    "max_age_min",
                    "min_completeness",
                    "authoritative_system",
                    "missing",
                ]
            )
            for r in rows:
                q = r.requirement
                w.writerow(
                    [
                        q.shape,
                        r.verdict,
                        q.consequence_class,
                        q.spatial_resolution,
                        ";".join(q.modalities),
                        q.max_age_minutes or "",
                        q.min_completeness or "",
                        q.authoritative_system,
                        " | ".join(r.missing),
                    ]
                )
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
