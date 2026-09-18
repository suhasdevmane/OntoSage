# -*- coding: utf-8 -*-
"""BUG-671: a declared room capacity must fit the room, and say the same thing everywhere.

``bldg1_enrichment_metadata.ttl`` gave Room1.06 a capacity of 30 in 11.94 m2 and Room5.08 50
in 24.73 m2 -- denser than the 1.0 m2 per person Approved Document B allows even as a
means-of-escape maximum. Asked "does room 1.06 fit my class of 30?", the system had a
confident, unsafe yes to give. ``bldg:maxOccupancy`` said 40 people for a 7.83 m2 distribution
board room, and the capacity provisioner gave six people to a gas-meter room.

It was the capacities, not the areas, that were wrong. Every room number sits inside exactly
one room outline in the architect's DXF, alone, and the text in that outline names what the
room is. The building owner has ruled the drawings authoritative for room identity, so one rule
now sets every capacity: the person count the drawing writes in the outline; else floor(area /
density) with the density chosen from the drawing's name for the room; plant, IT, metering and
storage rooms get none. Three places state capacity -- ``hbco:roomCapacity``,
``<building>:maxOccupancy`` and the provisioner's derived file -- and they must agree.

Reads committed files only, so it runs with no building active: the building's TTLs and
``tests/fixtures/floor_plans/<id>_drawing_rooms.json``, which is measured from the DXFs.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
import yaml

rdflib = pytest.importorskip("rdflib")

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "floor_plans"
SCRIPT = REPO / "scripts" / "provision_event_and_capacity_data.py"
HBCO_CAPACITY = rdflib.URIRef("http://ontosage.org/hbco#roomCapacity")
CAPACITY_BASIS = rdflib.URIRef("http://ontosage.org/capabilities#capacityBasis")

#: Approved Document B's densest planning figure for any occupied room type. Not a comfortable
#: layout -- a MAXIMUM. A capacity implying less floor than this per person is impossible, not
#: merely generous.
MIN_M2_PER_PERSON = 1.0

_BASIS_AREA = re.compile(r"(\d+(?:\.\d+)?)\s*m2\b")


def _load_script():
    spec = importlib.util.spec_from_file_location("_provision_capacity_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


prov = _load_script()


def _buildings() -> List[Tuple[str, str, Path]]:
    """(building_id, namespace, folder) for the active building and every parked one."""
    out = []
    for folder in [REPO / "input"] + sorted(REPO.glob("bldg*")):
        cfg = folder / "building.yaml"
        if not folder.is_dir() or not cfg.exists():
            continue
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        if data.get("building_id") and data.get("ontology_namespace"):
            out.append((str(data["building_id"]), str(data["ontology_namespace"]), folder))
    return out


def _capacity_files(folder: Path) -> List[Path]:
    """TTLs that declare a capacity. The multi-megabyte vocabularies are not read."""
    out = []
    for path in sorted(folder.glob("*.ttl")):
        if path.name.startswith("Brick"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "roomCapacity" in text or re.search(r"maxOccupancy\s+\d", text):
            out.append(path)
    return out


def _graph(folder: Path) -> rdflib.Graph:
    g = rdflib.Graph()
    for path in _capacity_files(folder):
        g.parse(str(path), format="turtle")
    return g


def _drawing(building_id: str) -> List[Dict]:
    path = FIXTURES / f"{building_id}_drawing_rooms.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("rooms") or []


def _local(iri: str, namespace: str) -> Optional[str]:
    return iri[len(namespace) :] if iri.startswith(namespace) else None


def implied_m2_per_person(area_m2: float, persons: int) -> float:
    """Floor area each person gets at the declared capacity."""
    return area_m2 / persons


def _stated_area(basis: str) -> Optional[float]:
    m = _BASIS_AREA.search(basis)
    return float(m.group(1)) if m else None


class Building:
    def __init__(self, bid: str, ns: str, g: rdflib.Graph):
        self.bid, self.ns, self.g = bid, ns, g
        rows = _drawing(bid)
        self.areas: Dict[str, float] = {
            str(r["ontology_iri"]): float(r["area_m2"])
            for r in rows
            if r.get("ontology_iri") and r.get("area_m2") is not None
        }
        self.labels: Dict[str, str] = {
            str(r["ontology_iri"]): str(r.get("label") or "") for r in rows if r.get("ontology_iri")
        }
        self.max_occupancy = rdflib.URIRef(ns + "maxOccupancy")

    def name(self, room) -> str:
        return f"{self.bid} {_local(str(room), self.ns) or room}"


@pytest.fixture(scope="module")
def buildings() -> List[Building]:
    found = [Building(bid, ns, _graph(folder)) for bid, ns, folder in _buildings()]
    if not found:
        pytest.skip("no building folder with a building.yaml is present")
    return found


# ── the arithmetic and the parsing are not vacuous ───────────────────────────────────────────


@pytest.mark.parametrize(
    "area,persons,ok",
    [
        (11.94, 30, False),  # Room1.06 as it was
        (24.73, 50, False),  # Room5.08 as it was
        (7.83, 40, False),  # Room2.15 maxOccupancy as it was
        (11.94, 12, False),  # just past the limit
        (11.94, 11, True),
        (11.94, 1, True),
        (184.46, 120, True),
    ],
)
def test_the_density_check_flags_impossible_capacities(area, persons, ok):
    assert (implied_m2_per_person(area, persons) >= MIN_M2_PER_PERSON) is ok


def test_a_stated_area_is_read_from_a_basis():
    assert _stated_area("Estimated, not certified: 56.8 m2 floor-plan area at 2.0 m2") == 56.8
    assert _stated_area("From the drawing label, no area stated") is None


@pytest.mark.parametrize(
    "label,expected",
    [
        ("8P PHD Research", (8, False)),
        ("30 P Seminar", (30, False)),
        ("120 Person Lecture Theatre", (120, False)),
        ("120S Lecture Theatre - Group Bench seating style 30SD Cap.", (120, False)),
        ("16-20P Meeting", (20, True)),
        ("8-12 Exec Meeting", (12, True)),
        ("Office", None),
        ("Small Research", None),
        ("1650", None),  # a dimension, not a count
        ("", None),
    ],
)
def test_a_drawing_person_count_is_read_from_the_label(label, expected):
    assert prov.drawing_person_count(label) == expected


@pytest.mark.parametrize(
    "label,unoccupied",
    [
        ("DB Room", True),
        ("Gas Meter & Tank", True),
        ("ICT LAN", True),
        ("I.T. Store", True),
        ("Server Rm", True),
        ("Main UPS & Batt", True),
        ("Records Storage", True),
        ("Switch Room", True),
        ("Office", False),
        ("I.T Workshop", False),
        ("Meeting Room", False),
        ("Visiting Staff", False),
    ],
)
def test_the_drawing_names_plant_it_and_storage_rooms(label, unoccupied):
    assert prov.drawing_says_unoccupied(label) is unoccupied


def _room(local, classes, area, label=None, has_capacity=False):
    return prov.Room(
        "http://example.org/b#" + local, frozenset(classes), area, has_capacity, False, label
    )


def _estimate(room):
    est, skipped = prov.capacity_estimates([room])
    return (est[0]["capacity"] if est else None), skipped


def test_the_drawing_outranks_the_graph_room_type():
    """An office the graph typed as a conference room got five people at 2 m2 per person."""
    cap, _ = _estimate(_room("R", {"Conference_Room", "Room"}, 11.21, "Office"))
    assert cap == 1
    cap, _ = _estimate(_room("R", {"Conference_Room", "Room"}, 56.76, "8P Research Office"))
    assert cap == 8


def test_a_room_the_drawing_shows_as_plant_gets_no_capacity_whatever_its_type():
    cap, skipped = _estimate(_room("R", {"Office", "Room"}, 68.01, "Gas Meter & Tank"))
    assert cap is None
    assert skipped["drawing shows a room not laid out for occupants"] == 1


def test_a_drawing_count_that_cannot_fit_its_outline_is_not_used():
    cap, skipped = _estimate(
        _room("R", {"Lecture_Hall", "Room"}, 27.44, "120S Lecture Theatre - Group Bench")
    )
    assert cap is None
    assert skipped["drawing count does not fit its outline"] == 1


def test_a_named_room_with_no_count_takes_a_density_from_its_name():
    assert _estimate(_room("R", {"Room"}, 84.77, "Staff Room"))[0] == 42  # break-out, 2 m2
    assert _estimate(_room("R", {"Room"}, 8.87, "Meeting Room"))[0] == 4  # seated, 2 m2
    assert _estimate(_room("R", {"Room"}, 24.73, "Small Research"))[0] == 2  # workplace, 10 m2


def test_without_a_drawing_record_the_graph_type_still_decides():
    assert _estimate(_room("R", {"Conference_Room", "Room"}, 21.0))[0] == 10
    assert _estimate(_room("R", {"Storage_Room", "Room"}, 30.0))[0] is None


# ── the data ─────────────────────────────────────────────────────────────────────────────────


def _declared(b: Building, prop) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for room, value in b.g.subject_objects(prop):
        out.setdefault(str(room), []).append(int(value))
    return out


def _check_density(buildings: List[Building], prop_of, name: str):
    impossible, checked = [], 0
    for b in buildings:
        for room, values in _declared(b, prop_of(b)).items():
            area = b.areas.get(room)
            if area is None:
                stated = [
                    _stated_area(str(x)) for x in b.g.objects(rdflib.URIRef(room), CAPACITY_BASIS)
                ]
                area = next((a for a in stated if a), None)
            if area is None:
                continue
            for value in values:
                checked += 1
                if value < 1 or implied_m2_per_person(area, value) < MIN_M2_PER_PERSON:
                    impossible.append(f"{b.name(room)}: {name} {value} in {area} m2")
    if not checked:
        pytest.skip(f"no building declares a {name} with a known area")
    assert not impossible, f"{name} denser than 1.0 m2 per person:\n" + "\n".join(impossible)


def test_every_room_capacity_fits_its_floor_plan_area(buildings):
    _check_density(buildings, lambda b: HBCO_CAPACITY, "roomCapacity")


def test_every_max_occupancy_fits_its_floor_plan_area(buildings):
    _check_density(buildings, lambda b: b.max_occupancy, "maxOccupancy")


def test_every_room_capacity_states_its_basis(buildings):
    """The schema's own rule: a capacity with no basis reads as a certified fire limit."""
    missing = []
    for b in buildings:
        for room in set(b.g.subjects(HBCO_CAPACITY, None)):
            if not list(b.g.objects(room, CAPACITY_BASIS)):
                missing.append(b.name(room))
    assert not missing, "hbco:roomCapacity with no ontosage:capacityBasis: " + ", ".join(
        sorted(missing)
    )


def test_a_basis_that_quotes_an_area_quotes_the_drawing(buildings):
    wrong = []
    for b in buildings:
        for room, basis in b.g.subject_objects(CAPACITY_BASIS):
            stated, measured = _stated_area(str(basis)), b.areas.get(str(room))
            if stated is not None and measured is not None and abs(stated - measured) > 0.1:
                wrong.append(f"{b.name(room)}: basis says {stated} m2, drawing measures {measured}")
    assert not wrong, "\n".join(wrong)


def test_one_value_per_room_per_property(buildings):
    """Two files each declaring a capacity leaves the answer to whichever the query hits."""
    conflicts = []
    for b in buildings:
        for prop, name in ((HBCO_CAPACITY, "roomCapacity"), (b.max_occupancy, "maxOccupancy")):
            for room, values in _declared(b, prop).items():
                if len(set(values)) > 1:
                    conflicts.append(f"{b.name(room)} {name}: {sorted(set(values))}")
    assert not conflicts, "\n".join(conflicts)


def test_room_capacity_and_max_occupancy_agree_for_every_room_carrying_both(buildings):
    disagree = []
    for b in buildings:
        caps, maxes = _declared(b, HBCO_CAPACITY), _declared(b, b.max_occupancy)
        for room in set(caps) & set(maxes):
            if set(caps[room]) != set(maxes[room]):
                disagree.append(
                    f"{b.name(room)}: roomCapacity {caps[room]} maxOccupancy {maxes[room]}"
                )
    assert not disagree, "\n".join(disagree)


def test_every_declared_figure_is_what_the_provisioner_rule_gives(buildings):
    """One rule, three places: hand-authored capacities, maxOccupancy and the derived file.

    The provisioner is run over the measured drawing for every room that carries either
    property, as though the room had no capacity yet; a hand-authored figure the rule would not
    produce is a fourth rule nobody wrote down."""
    differ, checked = [], 0
    for b in buildings:
        if not b.labels:
            continue
        declared = {}
        for prop, name in ((HBCO_CAPACITY, "roomCapacity"), (b.max_occupancy, "maxOccupancy")):
            for room, values in _declared(b, prop).items():
                declared.setdefault(room, []).extend((name, v) for v in values)
        rooms = [
            prov.Room(room, frozenset({"Room"}), b.areas.get(room), False, False, b.labels[room])
            for room in declared
            if b.labels.get(room)
        ]
        estimates, _ = prov.capacity_estimates(rooms)
        by_room = {e["room_iri"]: e["capacity"] for e in estimates}
        for room in rooms:
            for name, value in declared[room.iri]:
                checked += 1
                if by_room.get(room.iri) != value:
                    differ.append(
                        f"{b.name(room.iri)} {name}={value}, drawing rule gives "
                        f"{by_room.get(room.iri)} for '{room.drawing_label}'"
                    )
    if not checked:
        pytest.skip("no building has both declared capacities and a measured drawing")
    assert not differ, "\n".join(differ)


def test_no_room_the_drawing_shows_as_plant_declares_occupants(buildings):
    wrong = []
    for b in buildings:
        for prop in (HBCO_CAPACITY, b.max_occupancy):
            for room in set(b.g.subjects(prop, None)):
                label = b.labels.get(str(room), "")
                if prov.drawing_says_unoccupied(label):
                    wrong.append(f"{b.name(room)} ('{label}')")
    assert not wrong, "occupant figures on rooms nobody occupies: " + ", ".join(sorted(wrong))


def test_the_drawing_fixture_is_measured_not_empty():
    rows = _drawing("bldg1")
    if not rows:
        pytest.skip("no drawing fixture for bldg1")
    assert len(rows) > 150
    assert all(r["area_m2"] and r["area_m2"] > 0 for r in rows)
    assert len({r["ontology_iri"] for r in rows if r["ontology_iri"]}) == len(
        [r for r in rows if r["ontology_iri"]]
    ), "two outlines claim one room"
