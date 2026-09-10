# -*- coding: utf-8 -*-
"""A synthetic stream must carry the quantity its sensor measures (BUG-439).

WHAT WENT WRONG
---------------
On 2026-09-06 this building answered:

    "Floor 1's average CO2 (157 ppm) is higher than Floor 3's (111 ppm). Both averages are
     well below the 800 ppm guideline for healthy indoor air, so overall air quality is
     compliant. Actionable recommendation: install or verify adequate ventilation..."

Outdoor air is about 420 ppm. Neither figure is a low reading; neither is a reading.

`input/<building>_extended_narrow_uuids.json` -- the file that tells the publisher what to
generate -- typed 174 sensors as `Air_Quality_Sensor` with range 0-150. In the graph those
sensors are `brick:CO2_Sensor`. `Air_Quality_Sensor` is Brick's SUPERTYPE for CO2, TVOC and
particulate sensors alike, and 0-150 is an air-quality-INDEX scale, so every floor 0-4 CO2
reading for seven weeks was an index presented as a concentration. 4,470,907 rows.

The file had **no generator**. It was written once, by hand, and the building changed around
it. That is the same shape as the fourteen dangling asset statuses fixed the same day: an
artefact with no producer drifts from the thing it describes, and nothing compares them.

WHAT THESE TESTS PIN
--------------------
1. Every quantity with a typical (generation) band has a physical (possibility) band, and
   the typical band sits INSIDE it. Two bands that disagree are worse than one.

2. No SUPERTYPE declares a measurand. `Air_Quality_Sensor`, `Gas_Sensor`, `Sensor`, `Point`
   and `Equipment` each sit above instruments measuring different quantities in different
   units, so a band on any of them reaches all of them. This is the defect, stated as a rule.

3. Every entry in a building's publish map matches the band the ontology declares for the
   class it names -- so a hand edit, or a stale file, fails here instead of in an answer.

4. No publish-map entry is typed by a supertype.

Offline: TTL and JSON only. Runs in the parked state, and over every building present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
KINDS = REPO / "ontology" / "measurand_kinds.ttl"
O = "http://ontosage.org/capabilities#"
BRICK = "https://brickschema.org/schema/Brick#"

#: Classes that sit above instruments measuring DIFFERENT quantities. A band on any of
#: these is applied to all of them, which is exactly how 174 CO2 sensors came to generate
#: an air-quality index.
SUPERTYPES = {
    "Air_Quality_Sensor",
    "Gas_Sensor",
    "Sensor",
    "Point",
    "Equipment",
    "Sensor_Equipment",
    "ICT_Equipment",
    "Meter",
    "Class",
    "Entity",
}


def _graph():
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(str(KINDS), format="turtle")
    return g, rdflib


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _bands() -> Dict[str, Tuple[float, float]]:
    """Brick/OntoSage class local name -> (typicalMin, typicalMax)."""
    g, rdflib = _graph()
    ns = rdflib.Namespace(O)
    out: Dict[str, Tuple[float, float]] = {}
    for cls, kind in g.subject_objects(ns.measuresQuantityKind):
        lo = g.value(kind, ns.typicalMin)
        hi = g.value(kind, ns.typicalMax)
        if lo is None or hi is None:
            continue
        out[_local(cls)] = (float(lo), float(hi))
    return out


def _publish_maps() -> List[Path]:
    # Buildings only -- a `*_source/` staging folder is not one. See
    # test_a_relation_points_at_something_declared.py for what that cost.
    dirs = [p for p in REPO.glob("bldg*") if p.is_dir() and (p / "building.yaml").exists()]
    active = REPO / "input"
    if (active / "building.yaml").exists():
        dirs.append(active)
    out: List[Path] = []
    for d in dirs:
        out += sorted(d.glob("*_extended_narrow_uuids.json"))
    return out


# ── property 1: the two bands agree ───────────────────────────────────────────


def test_every_typical_band_sits_inside_its_physical_band():
    g, rdflib = _graph()
    ns = rdflib.Namespace(O)
    problems: List[str] = []
    checked = 0
    for kind, lo in g.subject_objects(ns.typicalMin):
        hi = g.value(kind, ns.typicalMax)
        plo = g.value(kind, ns.physicalMin)
        phi = g.value(kind, ns.physicalMax)
        name = _local(kind)
        if plo is None or phi is None:
            problems.append(f"{name} has a generation band and no possibility band")
            continue
        checked += 1
        if not (float(plo) <= float(lo) <= float(hi) <= float(phi)):
            problems.append(
                f"{name}: typical {lo}..{hi} is not inside physical {plo}..{phi} — "
                f"the generator would produce values the guard rejects"
            )
    assert checked > 10, f"only {checked} bands checked; the parse is wrong"
    assert not problems, "\n".join(problems)


def test_every_band_states_its_unit_and_where_it_came_from():
    """A number in an ontology with no provenance becomes a fact by being copied."""
    g, rdflib = _graph()
    ns = rdflib.Namespace(O)
    missing: List[str] = []
    for kind, _lo in g.subject_objects(ns.physicalMin):
        if g.value(kind, ns.physicalUnit) is None:
            missing.append(f"{_local(kind)} has no physicalUnit")
        if g.value(kind, ns.bandSource) is None:
            missing.append(f"{_local(kind)} has no bandSource")
    assert not missing, "\n".join(missing)


# ── property 2: no supertype carries a band ───────────────────────────────────


def test_no_supertype_declares_a_measurand():
    """The defect, stated as a rule.

    Brick's own definition of Air_Quality_Sensor is "detects pollutants in the ambient
    air", which legitimately covers CO2, TVOC and particulates. That is what makes it
    unusable as a band key: the three share no unit and no scale.
    """
    g, rdflib = _graph()
    ns = rdflib.Namespace(O)
    offenders = sorted(
        _local(c) for c in g.subjects(ns.measuresQuantityKind) if _local(c) in SUPERTYPES
    )
    assert not offenders, (
        f"{offenders} are supertypes and now carry a measurand band. Every instrument "
        f"beneath them inherits it, whatever it actually measures."
    )


# ── properties 3 and 4: the publish maps match the ontology ───────────────────


@pytest.mark.parametrize("path", _publish_maps(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_publish_map_ranges_match_the_declared_band(path: Path):
    bands = _bands()
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = list(data.values()) if isinstance(data, dict) else list(data)
    wrong: List[str] = []
    unknown: List[str] = []
    for e in entries:
        cls = str(e.get("class", ""))
        band = bands.get(cls)
        if band is None:
            unknown.append(cls)
            continue
        lo, hi = float(e.get("lo", 0)), float(e.get("hi", 0))
        if (lo, hi) != band:
            wrong.append(f"{cls}: map says {lo:g}..{hi:g}, ontology says {band[0]:g}..{band[1]:g}")
    assert not wrong, (
        f"{path.name} disagrees with the ontology about what these sensors measure:\n"
        + "\n".join(sorted(set(wrong)))
        + "\n\nRegenerate with: python scripts/generate_publish_map.py"
    )
    assert not unknown, (
        f"{path.name} names class(es) the ontology declares no measurand for: "
        f"{sorted(set(unknown))}. A range with no declared quantity behind it is a guess."
    )


@pytest.mark.parametrize("path", _publish_maps(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_publish_map_never_types_a_sensor_by_a_supertype(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = list(data.values()) if isinstance(data, dict) else list(data)
    bad = sorted({str(e.get("class", "")) for e in entries} & SUPERTYPES)
    assert not bad, (
        f"{path.name} types sensors by supertype(s) {bad}. This is the BUG-439 shape "
        f"exactly: 174 CO2 sensors typed Air_Quality_Sensor and generating 0-150."
    )


def test_there_is_a_publish_map_to_check():
    """A glob matching nothing passes every parametrised test above it."""
    assert _publish_maps(), "no *_extended_narrow_uuids.json found; the discovery is wrong"
