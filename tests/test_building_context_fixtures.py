# -*- coding: utf-8 -*-
"""Context data for every building, so portability can be tested at all (2026-08-27).

Several capabilities were built and verified on bldg1 and had NO DATA on the other
buildings. Measured before this landed:

    knowledge topics    bldg1 45   bldg2 10   bldg3  9
    AssetStatus         bldg1 64   bldg2  0   bldg3  0
    PotabilityStatement bldg1  1   bldg2  0   bldg3  0

The out-of-service exclusion, the drinkability claim and the asset-state lane could
not be exercised on bldg2 or bldg3 at all. That is not a portability result; it is
an absence of one.

Three properties this file guards:

* **Discovered, not assumed.** bldg1 names floors `Floor0` and rooms `Room5.01`;
  bldg2 and bldg3 use `floor0` and `RM001A_room`. A generator written against
  either shape would prove only that it had been told the answer.
* **Different, not copied.** Cloning bldg1's topics into bldg2 would make them
  answer identically for the wrong reason.
* **No health claim about a real building.** Potability is authored only where
  building.yaml declares the building synthetic.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[1]
_SYNTHETIC = ("bldg2", "bldg3", "bldg4")


@pytest.fixture(scope="module")
def gen():
    path = _REPO / "scripts" / "generate_building_context.py"
    spec = importlib.util.spec_from_file_location("_genctx", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctx(b: str) -> Path:
    return _REPO / b / f"{b}_context.ttl"


def _text(b: str) -> str:
    return _ctx(b).read_text(encoding="utf-8")


# -- the files exist and parse ------------------------------------------------
@pytest.mark.parametrize("building", _SYNTHETIC)
def test_every_synthetic_building_has_context(building):
    if not (_REPO / building).is_dir():
        pytest.skip(f"{building} not present")
    assert _ctx(building).is_file()
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(str(_ctx(building)), format="turtle")
    assert len(g) > 0


# -- the behaviours are now exercisable everywhere ----------------------------
@pytest.mark.parametrize("building", _SYNTHETIC)
def test_a_drinking_water_point_is_out_of_service(building):
    """The "broken fountain is hidden" behaviour was built and verified on bldg1 and
    could not be exercised anywhere else. A flat probability produced one
    out-of-service amenity per building and never a water point, so the choice is
    designed rather than rolled."""
    if not (_REPO / building).is_dir():
        pytest.skip(f"{building} not present")
    text = _text(building)
    statuses = [ln for ln in text.splitlines() if "statusOf" in ln]
    assert any("DrinkingWater" in ln for ln in statuses), statuses


@pytest.mark.parametrize("building", _SYNTHETIC)
def test_every_out_of_service_entry_says_why(building):
    """ "Out of service" with no cause is unactionable, and this data exists to
    exercise a lane that is supposed to tell somebody something useful."""
    if not (_REPO / building).is_dir():
        pytest.skip(f"{building} not present")
    text = _text(building)
    assert text.count("statusOf") == text.count("statusReason")


@pytest.mark.parametrize("building", _SYNTHETIC)
def test_every_authored_subject_declares_itself_simulated(building):
    if not (_REPO / building).is_dir():
        pytest.skip(f"{building} not present")
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(str(_ctx(building)), format="turtle")
    onto = rdflib.Namespace("http://ontosage.org/capabilities#")
    subjects = {s for s in g.subjects() if isinstance(s, rdflib.URIRef)}
    declared = {s for s, _p, _o in g.triples((None, onto.isSimulated, None))}
    typed = {s for s in subjects if (s, rdflib.RDF.type, None) in g}
    assert typed <= declared, sorted(str(s) for s in (typed - declared))[:5]


# -- different, not copied ----------------------------------------------------
def test_the_buildings_do_not_share_their_topics():
    """A portability test that passes because the fixtures are the same file tests
    nothing."""
    present = [b for b in ("bldg2", "bldg3") if (_REPO / b).is_dir() and _ctx(b).is_file()]
    if len(present) < 2:
        pytest.skip("need two buildings to compare")
    import re

    sets = []
    for b in present:
        sets.append(set(re.findall(r"bldg:Topic_(\w+)", _text(b))))
    a, c = sets[0], sets[1]
    assert a != c, "two buildings have identical topic sets"
    assert (a - c) and (c - a), "neither building has a topic the other lacks"


def test_each_building_names_its_own_operator():
    present = [b for b in ("bldg2", "bldg3") if (_REPO / b).is_dir() and _ctx(b).is_file()]
    if len(present) < 2:
        pytest.skip("need two buildings to compare")
    authorities = [
        [ln for ln in _text(b).splitlines() if "potabilityAuthority" in ln] for b in present
    ]
    if all(authorities):
        assert authorities[0] != authorities[1]


# -- and no health claim about a real building --------------------------------
def test_potability_is_refused_for_a_building_that_is_not_synthetic(gen, tmp_path):
    """bldg1 is real, and five simulated drinkability statements about it had to be
    removed from this repository once already."""
    info = {
        "namespace": "http://example.org/x#",
        "floors": ["f0"],
        "rooms": [],
        "amenities": [
            {"local": "Amenity_DrinkingWater_f0", "label": "Water", "floor": "f0", "space": ""}
        ],
    }
    prof = {
        "operator": "X",
        "email": "x@example.org",
        "phone": "",
        "hours": "",
        "helpdesk": "X",
        "topics": [],
    }
    ttl_real, _b, _s = gen.render("bldgreal", info, prof, "real")
    ttl_synth, _b2, _s2 = gen.render("bldgsynth", info, prof, "synthetic")
    assert "PotabilityStatement" not in ttl_real
    assert "false health claim" in ttl_real
    assert "PotabilityStatement" in ttl_synth


def test_an_unlocatable_amenity_gets_no_service_state(gen):
    """An amenity nobody can find cannot be walked to, so calling it broken helps
    no one."""
    info = {
        "namespace": "http://example.org/x#",
        "floors": [],
        "rooms": [],
        "amenities": [
            {"local": "Amenity_Ghost_a", "label": "", "floor": "", "space": ""},
            {"local": "Amenity_Ghost_b", "label": "", "floor": "", "space": ""},
        ],
    }
    prof = {
        "operator": "X",
        "email": "x@example.org",
        "phone": "",
        "hours": "",
        "helpdesk": "X",
        "topics": [],
    }
    ttl, broken, _sk = gen.render("bx", info, prof, "synthetic")
    assert broken == 0
    assert "AssetStatus" not in ttl


def test_locatable_means_located_not_floor_tagged(gen):
    """Only 9 of bldg2's 22 amenities carry onFloor; many more name a room through
    locatedIn. Testing for the floor string alone called two thirds of a building's
    amenities unlocatable."""
    info = {
        "namespace": "http://example.org/x#",
        "floors": [],
        "rooms": [],
        "amenities": [
            {"local": "Amenity_Water_a", "label": "", "floor": "", "space": "RM001"},
            {"local": "Amenity_Water_b", "label": "", "floor": "", "space": "RM002"},
        ],
    }
    prof = {
        "operator": "X",
        "email": "x@example.org",
        "phone": "",
        "hours": "",
        "helpdesk": "X",
        "topics": [],
    }
    _ttl, broken, _sk = gen.render("bx", info, prof, "synthetic")
    assert broken == 1
