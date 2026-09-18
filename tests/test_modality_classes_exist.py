# -*- coding: utf-8 -*-
"""BUG-676: every class the modality config names must exist.

``config/saturation_modalities.yaml`` named ``People_Count_Sensor``, ``Level_Sensor``,
``Fill_Level_Sensor`` and ``Weight_Sensor``, none of which Brick 1.4 or the OCBV schema
declares, and none of which any point in any building was typed with. A name that cannot
match anything makes a modality LOOK broader than it is -- BUG-648's ``Elevator_Status``
made the lift modality look as though it covered lifts while it resolved to nothing.

Two rules, because the file carries two kinds of name:

* ``brick_classes`` are LOCAL NAMES. ``coverage_audit.ModalitySpec.matches`` compares them to
  the local name of a point's class, and ``modality_repair.build_modality_query`` appends them
  to ``#``. A prefixed entry (``ontosage:Soil_Moisture_Sensor``) can therefore never match,
  however real the class is. Each must be declared as an ``owl:Class`` in Brick or in OCBV.
* ``sat.brick_class`` is what the provisioner MINTS: bare means ``brick:<name>`` and must be
  declared in Brick; ``ontosage:<name>`` must be declared in OCBV (BUG-179).

Reads committed files only -- the Brick TTL shipped in every building folder and the OCBV
schema -- so it runs with no building active and makes no live call.
"""

from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest
import yaml

rdflib = pytest.importorskip("rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "saturation_modalities.yaml"
SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
BRICK_NS = "https://brickschema.org/schema/Brick#"
ONTO_NS = "http://ontosage.org/capabilities#"


def _brick_ttl() -> Path:
    candidates = [REPO / "input" / "Brick_v1.4.ttl"] + sorted(REPO.glob("bldg*/Brick_v1.4.ttl"))
    for c in candidates:
        if c.exists():
            return c
    pytest.fail(
        "Brick_v1.4.ttl is committed in every bldg*/ folder and none was found, so there is "
        "nothing to check the modality classes against."
    )


def _declared_locals(path: Path, namespace: str) -> Set[str]:
    g = rdflib.Graph()
    g.parse(str(path), format="turtle")
    out: Set[str] = set()
    for kind in (OWL.Class, RDFS.Class):
        for cls in g.subjects(RDF.type, kind):
            iri = str(cls)
            if iri.startswith(namespace):
                out.add(iri[len(namespace) :])
    return out


@pytest.fixture(scope="module")
def brick() -> Set[str]:
    return _declared_locals(_brick_ttl(), BRICK_NS)


@pytest.fixture(scope="module")
def ocbv() -> Set[str]:
    return _declared_locals(SCHEMA, ONTO_NS)


def _config_files() -> List[Path]:
    """The shared config plus every committed or active per-building overlay."""
    overlays = [REPO / "input" / "saturation_modalities.yaml"]
    overlays += sorted(REPO.glob("bldg*/saturation_modalities.yaml"))
    return [CONFIG] + [p for p in overlays if p.exists()]


def _names(path: Path) -> List[Tuple[str, str, str]]:
    """(modality, field, name) for every class name one config file carries."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: List[Tuple[str, str, str]] = []
    for modality, spec in (raw.get("modalities") or {}).items():
        spec = spec or {}
        for name in spec.get("brick_classes") or []:
            out.append((str(modality), "brick_classes", str(name)))
        sat_class = (spec.get("sat") or {}).get("brick_class")
        if sat_class:
            out.append((str(modality), "sat.brick_class", str(sat_class)))
    return out


def _problem(field: str, name: str, brick: Set[str], ocbv: Set[str]) -> str:
    """Why this name is wrong for this field, or "" when it is fine."""
    if field == "brick_classes":
        if ":" in name:
            return "is prefixed, but brick_classes are compared as LOCAL names and never match"
        if name not in brick and name not in ocbv:
            return "is declared in neither Brick nor OCBV"
        return ""
    prefix, _, local = name.rpartition(":")
    if prefix == "":
        return "" if local in brick else "is minted as brick: but Brick does not declare it"
    if prefix == "ontosage":
        return "" if local in ocbv else "is minted as ontosage: but OCBV does not declare it"
    return f"uses an unknown prefix {prefix!r}"


# ── the checker is not vacuous ───────────────────────────────────────────────────────────────


def test_the_brick_snapshot_actually_parsed(brick, ocbv):
    """An empty set would make every name 'undeclared'; a tiny one would hide a bad parse."""
    assert len(brick) > 1000
    assert {"CO2_Level_Sensor", "Occupancy_Count_Sensor", "Availability_Status"} <= brick
    assert {"Sound_Level_Sensor", "Waste_Fill_Sensor", "Soil_Moisture_Sensor"} <= ocbv


@pytest.mark.parametrize(
    "field,name",
    [
        ("brick_classes", "Elevator_Status"),  # BUG-648
        ("brick_classes", "People_Count_Sensor"),
        ("brick_classes", "Level_Sensor"),
        ("brick_classes", "Fill_Level_Sensor"),
        ("brick_classes", "Weight_Sensor"),
        ("brick_classes", "ontosage:Soil_Moisture_Sensor"),  # real class, unmatchable form
        ("sat.brick_class", "Sound_Level_Sensor"),  # BUG-179: not Brick's to mint
        ("sat.brick_class", "ontosage:People_Count_Sensor"),
        ("sat.brick_class", "rec:Room"),
    ],
)
def test_the_checker_rejects_names_that_cannot_match(brick, ocbv, field, name):
    assert _problem(field, name, brick, ocbv)


@pytest.mark.parametrize(
    "field,name",
    [
        ("brick_classes", "CO2_Level_Sensor"),
        ("brick_classes", "Sound_Level_Sensor"),  # OCBV, matched by local name
        ("sat.brick_class", "Availability_Status"),
        ("sat.brick_class", "ontosage:Waste_Fill_Sensor"),
    ],
)
def test_the_checker_accepts_real_classes(brick, ocbv, field, name):
    assert _problem(field, name, brick, ocbv) == ""


# ── the config ───────────────────────────────────────────────────────────────────────────────


def test_every_modality_class_is_declared_in_brick_or_ocbv(brick, ocbv):
    bad: Dict[str, List[str]] = {}
    checked = 0
    for path in _config_files():
        for modality, field, name in _names(path):
            checked += 1
            why = _problem(field, name, brick, ocbv)
            if why:
                bad.setdefault(path.relative_to(REPO).as_posix(), []).append(
                    f"{modality}.{field}: {name} {why}"
                )
    assert checked > 50, f"only {checked} names read -- the config shape changed"
    assert not bad, (
        "modality config names classes that cannot match any point. Replace each with the "
        "real class (verify it in the TBox) or remove it, recording the measurement inline:\n"
        + "\n".join(f"{f}:\n  " + "\n  ".join(v) for f, v in bad.items())
    )
