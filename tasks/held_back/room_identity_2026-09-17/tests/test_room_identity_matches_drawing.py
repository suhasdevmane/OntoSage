# -*- coding: utf-8 -*-
"""A room is what the architect's drawing says it is (BUG-671 follow-up, 2026-09-17).

The building owner ruled the drawings authoritative for room identity. Before that ruling the
graph typed 132 of bldg1's 225 drawn rooms against the drawing: ten-square-metre cellular
offices as "Computer Laboratory", the 120-person lecture theatre 0.01 as "Main Reception", the
96-person lecture theatre 0.34 as a telecom room, PhD offices as restrooms. A stakeholder asking
"is Room 1.06 ready for my class?" was answered about a laboratory that is one person's office.

Three rules, each checked against the measured drawing fixture
(``tests/fixtures/floor_plans/<id>_drawing_rooms.json``) and the building's own TTLs:

* a room the drawing names as an office, store or plant room carries no teaching, meeting or
  laboratory type -- and more generally, every specific Brick type is one the drawing allows;
* the room's label names the same kind of room the drawing does;
* the label and the type agree with each other.

Rooms whose drawing text does not settle what they are ("IT Hub", "Project Rm", "Magic Room",
"Cyber Security") are not judged. Reads committed files only.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest
import yaml

rdflib = pytest.importorskip("rdflib")
from rdflib.namespace import RDF, RDFS  # noqa: E402

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "floor_plans"
BRICK = "https://brickschema.org/schema/Brick#"
SPACE_FUNCTION = rdflib.URIRef("http://ontosage.org/hbco#spaceFunction")

#: Brick 1.4 types each kind of room may carry. Brick 1.4 declares no lecture-hall or classroom
#: class (checked against Brick_v1.4.ttl): a lecture theatre is an Auditorium, a seminar or
#: teaching room a Conference_Room, a computer teaching room a Laboratory.
ALLOWED: Dict[str, Set[str]] = {
    "office": {
        "Office",
        "Enclosed_Office",
        "Private_Office",
        "Shared_Office",
        "Open_Office",
        "Team_Room",
    },
    "store": {"Storage_Room", "Waste_Storage"},
    "plant": {
        "Electrical_Room",
        "Telecom_Room",
        "Server_Room",
        "Service_Room",
        "Mechanical_Room",
        "Battery_Room",
        "Switch_Room",
        "Equipment_Room",
    },
    "lecture": {"Auditorium"},
    "teaching": {"Conference_Room", "Laboratory"},
    "meeting": {"Conference_Room"},
    "lab": {"Laboratory"},
    "workshop": {"Workshop"},
    "breakout": {"Break_Room", "Breakroom", "Office_Kitchen"},
}
GENERIC = {"Room", "Space", "Location", "NamedIndividual"}
#: Kinds nobody teaches, meets or experiments in.
NOT_TAUGHT = {"office", "store", "plant"}
TAUGHT_TYPES = {"Laboratory", "Conference_Room", "Auditorium", "Workshop"}

_COUNT = re.compile(r"^\s*\d+(?:\s*-\s*\d+)?\s*(?:P\b|S\b|Persons?\b|(?=\s+[A-Za-z]))", re.I)


def drawing_kind(label: str) -> Optional[str]:
    """What kind of room a drawing label names, or None when it does not settle it."""
    body = _COUNT.sub("", label or "").strip().lower()
    body = re.sub(r"^erson\s+", "", body)
    rules: List[Tuple[str, str]] = [
        ("lecture", r"\blecture\b"),
        ("teaching", r"\b(computer room|seminar|teaching)\b"),
        ("meeting", r"\b(meeting|meet rm)\b"),
        ("breakout", r"^staff room$"),
        ("lab", r"\blab\b"),
        ("workshop", r"\b(workshop|maker rm)\b"),
        ("plant", r"\b(db room|switch room|ups|lan|server|meter)\b"),
        ("store", r"\b(store|storage)\b"),
        (
            "office",
            r"^(office|research|small research|visiting staff|exec pa|finance)$|"
            r"\b(research office|phd research|phd students|prof serv)\b",
        ),
    ]
    for kind, rx in rules:
        if re.search(rx, body):
            return kind
    return None


def label_kind(text: str) -> Optional[str]:
    """What kind of room a graph label or space function names."""
    t = (text or "").split("—", 1)[-1].lower()
    rules: List[Tuple[str, str]] = [
        ("lecture", r"lecture|theatre|auditorium"),
        ("teaching", r"seminar|teaching|classroom|computer room|computer lab"),
        ("meeting", r"meeting|conference"),
        ("lab", r"laborator|\blab\b"),
        ("store", r"\bstore\b|storage"),
        (
            "plant",
            r"plant|mechanical|telecom|server|service room|electrical|switch|ups\b|\blan\b|meter|board room",
        ),
        ("common", r"reception|atrium|common area|lobby|foyer|restroom"),
        ("breakout", r"staff room|break|kitchen"),
        ("workshop", r"workshop|maker"),
        ("office", r"office"),
    ]
    for kind, rx in rules:
        if re.search(rx, t):
            return kind
    return None


def _compatible(kind_a: Optional[str], kind_b: Optional[str]) -> bool:
    if kind_a == kind_b:
        return True
    # a seminar room described as a meeting room, or the reverse, names the same use
    return {kind_a, kind_b} == {"teaching", "meeting"}


def _buildings() -> List[Tuple[str, str, Path]]:
    out = []
    for folder in [REPO / "input"] + sorted(REPO.glob("bldg*")):
        cfg = folder / "building.yaml"
        if not folder.is_dir() or not cfg.exists():
            continue
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        if data.get("building_id") and data.get("ontology_namespace"):
            out.append((str(data["building_id"]), str(data["ontology_namespace"]), folder))
    return out


#: A file that says what a room IS: a room subject followed by a type other than a bare
#: owl:NamedIndividual, a label, or a space function. The multi-megabyte vocabulary exports that
#: only declare rooms as individuals are not parsed, which keeps this a unit test.
_IDENTITY_TEXT = re.compile(
    r"Room\d\.\d\d>?\s+(?:(?:rdf:type|a)\s+(?!owl:NamedIndividual\s*\.)|rdfs:label\s|hbco:spaceFunction\s)"
)


def _identity_graph(folder: Path) -> rdflib.Graph:
    g = rdflib.Graph()
    for path in sorted(folder.glob("*.ttl")):
        if path.name.startswith("Brick"):
            continue
        if _IDENTITY_TEXT.search(path.read_text(encoding="utf-8", errors="replace")):
            g.parse(str(path), format="turtle")
    return g


class Room:
    def __init__(self, iri: str, drawing_label: str, g: rdflib.Graph):
        node = rdflib.URIRef(iri)
        self.name = iri.rsplit("#", 1)[-1]
        self.drawing_label = drawing_label
        self.kind = drawing_kind(drawing_label)
        self.types = {
            str(t)[len(BRICK) :] if str(t).startswith(BRICK) else str(t).rsplit("#", 1)[-1]
            for t in g.objects(node, RDF.type)
        }
        self.labels = [str(x) for x in g.objects(node, RDFS.label)]
        self.functions = [str(x) for x in g.objects(node, SPACE_FUNCTION)]

    @property
    def specific(self) -> Set[str]:
        return self.types - GENERIC


@pytest.fixture(scope="module")
def rooms() -> List[Room]:
    out: List[Room] = []
    for bid, ns, folder in _buildings():
        path = FIXTURES / f"{bid}_drawing_rooms.json"
        if not path.exists():
            continue
        g = _identity_graph(folder)
        for row in json.loads(path.read_text(encoding="utf-8")).get("rooms") or []:
            iri = row.get("ontology_iri")
            if iri and str(iri).startswith(ns):
                out.append(Room(str(iri), str(row.get("label") or ""), g))
    if not out:
        pytest.skip("no building folder has a measured drawing fixture")
    return out


# ── the classifiers are not vacuous ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,kind",
    [
        ("Office", "office"),
        ("8P PHD Research", "office"),
        ("6P Prof Serv- IT", "office"),
        ("3 Person Prof Serv & Post", "office"),
        ("120 Person Lecture Theatre", "lecture"),
        ("96P Lecture", "lecture"),
        ("30P Seminar Room", "teaching"),
        ("42P Computer Room 14SD cap.", "teaching"),
        ("16-20P Meeting", "meeting"),
        ("8-12P Meet Rm", "meeting"),
        ("DB Room", "plant"),
        ("Gas Meter & Tank", "plant"),
        ("ICT LAN", "plant"),
        ("Records Storage", "store"),
        ("I.T. Store", "store"),
        ("Financial Lab", "lab"),
        ("Maker Rm", "workshop"),
        ("IT Hub", None),
        ("Project Rm - 1", None),
        ("Magic Room", None),
        ("Cyber Security", None),
    ],
)
def test_drawing_labels_are_classified(label, kind):
    assert drawing_kind(label) == kind


@pytest.mark.parametrize(
    "label,kind",
    [
        ("Room 1.06 — Computer Laboratory", "teaching"),
        ("Room 2.03 — Research Laboratory", "lab"),
        ("Room 0.01 — Main Reception", "common"),
        ("Room 1.06 — Office", "office"),
        ("Room 0.34 — Lecture Theatre (96 people)", "lecture"),
        ("Room 2.15 — Distribution Board Room", "plant"),
        ("Room 5.15 — Seminar / Conference Room", "teaching"),
    ],
)
def test_graph_labels_are_classified(label, kind):
    assert label_kind(label) == kind


# ── the building ─────────────────────────────────────────────────────────────────────────────


def test_the_fixture_and_the_graph_cover_the_same_rooms(rooms):
    unasserted = [r.name for r in rooms if not r.labels and not r.specific]
    assert len(rooms) > 150
    assert not unasserted, f"drawn rooms the graph says nothing about: {unasserted[:10]}"


def test_no_office_store_or_plant_room_carries_a_teaching_or_lab_type(rooms):
    wrong = [
        f"{r.name} drawing '{r.drawing_label}' typed {sorted(r.specific & TAUGHT_TYPES)}"
        for r in rooms
        if r.kind in NOT_TAUGHT and r.specific & TAUGHT_TYPES
    ]
    assert not wrong, "\n".join(wrong)


def test_every_settled_room_is_typed_as_the_drawing_allows(rooms):
    wrong = []
    for r in rooms:
        if r.kind is None:
            continue
        allowed = ALLOWED[r.kind]
        if not r.specific or not r.specific <= allowed:
            wrong.append(
                f"{r.name} drawing '{r.drawing_label}' ({r.kind}) typed {sorted(r.specific)}"
            )
    assert not wrong, "\n".join(wrong)


def test_every_settled_room_is_labelled_as_the_drawing_names_it(rooms):
    wrong = []
    for r in rooms:
        if r.kind is None:
            continue
        for text in r.labels + r.functions:
            if not _compatible(label_kind(text), r.kind):
                wrong.append(f"{r.name} drawing '{r.drawing_label}' ({r.kind}) but says '{text}'")
    assert not wrong, "\n".join(wrong)


def test_the_label_and_the_type_agree(rooms):
    """Checked for every drawn room, settled or not: a label naming one kind of room over a type
    naming another is wrong whichever of the two is right."""
    wrong = []
    for r in rooms:
        for text in r.labels:
            kind = label_kind(text)
            if kind is None or kind == "common" or not r.specific:
                continue
            allowed = set(ALLOWED.get(kind, set()))
            if kind in ("teaching", "meeting"):
                allowed |= ALLOWED["teaching"] | ALLOWED["meeting"]
            if not r.specific & allowed:
                wrong.append(f"{r.name} labelled '{text}' but typed {sorted(r.specific)}")
    assert not wrong, "\n".join(wrong)


def test_a_lecture_theatre_is_still_a_room(rooms):
    """brick:Auditorium is a Common_Space, not a Room; everything selecting brick:Room would lose
    it (CAVEAT-301)."""
    wrong = [r.name for r in rooms if "Auditorium" in r.types and "Room" not in r.types]
    assert not wrong, f"lecture theatres not typed brick:Room: {wrong}"
