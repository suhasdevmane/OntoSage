# -*- coding: utf-8 -*-
"""A parking question binds the parking point, not the whole occupancy population (BUG-1411).

MEASURED 2026-10-01, occupant01 on /v1. 'Are there any free parking spots available right now?'
answered **"There are no free parking spots available at the moment"** from two EV-charger
status flags reading 0 -- a definite, actionable claim about the car park, drawn from points
whose unit the same answer admitted it did not know. The log holds the chain:

    [dialogue] HBCO concepts: ['parking_availability', 'empty_space']
    [sensor_binder] population bind for the building: 0 retrieved -> 512 bound (occupancy)

Two defects in `detect_quantities`, both in how a resolved CONCEPT is homed on the catalogue:

  1. The home modality was the FIRST catalogue entry sharing any class, so a concept mapped to
     {Occupancy_Count_Sensor, Parking_Occupancy_Sensor} was homed on plain occupancy (one class
     in common) rather than parking (both) -- and the catalogue's label discriminator
     ("parking") was never copied onto the concept's spec, although the docstring said it was.
  2. The bare lay term "available" resolves `empty_space`, which maps to every occupancy class.
     With parking asked for by name, that generic sibling bound the other 511 points.

Both fixes are keyed on the CATALOGUE'S STRUCTURE (a label-split sibling), never on a word or a
building: the specs below are synthetic and no building is assumed to be active.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services import sensor_binder as sb

pytestmark = pytest.mark.unit


def _mod(name, classes, contains=(), excludes=()):
    return SimpleNamespace(
        name=name,
        brick_classes=tuple(classes),
        label_contains=tuple(contains),
        label_excludes=tuple(excludes),
    )


CATALOGUE = [
    _mod("occupancy", ["Occupancy_Count_Sensor"]),
    _mod("occupancy_status", ["Occupancy_Status", "Occupancy_Sensor"]),
    _mod("parking_free", ["Parking_Occupancy_Sensor", "Occupancy_Count_Sensor"], ["parking"]),
    _mod("temperature", ["Temperature_Sensor", "Air_Temperature_Sensor"]),
    _mod("door_contact", ["Contact_Sensor", "Open_Close_Status"], ["door"]),
    _mod("window_contact", ["Contact_Sensor", "Open_Close_Status"], ["window"]),
]
WINDOW = {
    "concept_id": "unexpected_open_window",
    "brick_classes": [
        "https://brickschema.org/schema/Brick#Contact_Sensor",
        "https://brickschema.org/schema/Brick#Open_Close_Status",
    ],
}

PARKING = {
    "concept_id": "parking_availability",
    "brick_classes": [
        "https://brickschema.org/schema/Brick#Occupancy_Count_Sensor",
        "http://ontosage.org/capabilities#Parking_Occupancy_Sensor",
    ],
}
AVAILABLE = {
    "concept_id": "empty_space",
    "brick_classes": [
        "https://brickschema.org/schema/Brick#Motion_Sensor",
        "https://brickschema.org/schema/Brick#Occupancy_Count_Sensor",
        "https://brickschema.org/schema/Brick#Occupancy_Sensor",
        "https://brickschema.org/schema/Brick#Occupancy_Status",
    ],
}
PEOPLE = {
    "concept_id": "people_count",
    "brick_classes": ["https://brickschema.org/schema/Brick#Occupancy_Count_Sensor"],
}


@pytest.fixture(autouse=True)
def _catalogue(monkeypatch):
    monkeypatch.setattr(sb, "_modalities", lambda building_id=None: CATALOGUE)


class TestTheHomeModality:
    def test_a_concept_is_homed_on_the_modality_sharing_most_of_its_classes(self):
        home = sb._home_modality(["Occupancy_Count_Sensor", "Parking_Occupancy_Sensor"], CATALOGUE)
        assert home.name == "parking_free"

    def test_a_tie_goes_to_the_generic_modality(self):
        """'How many people' names only the shared class: that is occupancy, not parking."""
        home = sb._home_modality(["Occupancy_Count_Sensor"], CATALOGUE)
        assert home.name == "occupancy"

    def test_no_shared_class_means_no_home(self):
        assert sb._home_modality(["Wind_Speed_Sensor"], CATALOGUE) is None


class TestTheLiveQuestion:
    def test_the_label_discriminator_travels_with_the_concept(self):
        specs = sb.detect_quantities(
            "Are there any free parking spots available right now?", [PARKING]
        )
        assert len(specs) == 1
        assert specs[0].label_contains == ("parking",)
        assert specs[0].matches(["Occupancy_Count_Sensor"], "building parking_free [bays]")
        assert not specs[0].matches(
            ["Occupancy_Status"], "Charging State Sensor - EV Charger 1 (available/charging/fault)"
        )
        assert not specs[0].matches(["Occupancy_Count_Sensor"], "Room 1.06 occupancy")

    def test_the_generic_sibling_asked_for_by_available_is_dropped(self):
        specs = sb.detect_quantities(
            "Are there any free parking spots available right now?", [PARKING, AVAILABLE]
        )
        assert [s.name for s in specs] == ["parking_availability"]

    def test_the_order_of_the_concepts_does_not_matter(self):
        specs = sb.detect_quantities("free parking available?", [AVAILABLE, PARKING])
        assert [s.name for s in specs] == ["parking_availability"]


class TestAnAmbiguousHomeInheritsNothing:
    def test_a_window_concept_does_not_inherit_the_word_door(self):
        """door_contact and window_contact own the SAME classes; the first must not win."""
        specs = sb.detect_quantities("Is a window open somewhere?", [WINDOW])
        assert len(specs) == 1
        assert specs[0].label_contains == ()
        assert specs[0].matches(["Contact_Sensor"], "Window contact 2.01")
        assert specs[0].matches(["Contact_Sensor"], "Door contact 2.01")

    def test_the_helper_names_the_ambiguity(self):
        assert sb._inherited_discriminator(["Contact_Sensor", "Open_Close_Status"], CATALOGUE) == ()
        assert sb._inherited_discriminator(
            ["Occupancy_Count_Sensor", "Parking_Occupancy_Sensor"], CATALOGUE
        ) == ("parking",)
        assert sb._inherited_discriminator(["Occupancy_Count_Sensor"], CATALOGUE) == ()


class TestNothingElseMoves:
    def test_a_people_question_still_binds_every_count_sensor(self):
        specs = sb.detect_quantities("How many people are in Room 1.06 right now?", [PEOPLE])
        assert len(specs) == 1
        assert specs[0].label_contains == ()
        assert specs[0].matches(["Occupancy_Count_Sensor"], "Room 1.06 occupancy")

    def test_a_people_question_excludes_the_parking_sibling_by_label(self):
        """The catalogue splits the class by label in BOTH directions."""
        specs = sb.detect_quantities("How many people are in Room 1.06 right now?", [PEOPLE])
        assert "parking" in specs[0].label_excludes
        assert not specs[0].matches(["Occupancy_Count_Sensor"], "building parking_free [bays]")

    def test_available_alone_still_binds_occupancy(self):
        """Nothing specific was asked for, so the generic concept stands (BUG-1361 untouched)."""
        specs = sb.detect_quantities("Which rooms are available?", [AVAILABLE])
        assert len(specs) == 1
        assert "Occupancy_Status" in specs[0].classes

    def test_two_unrelated_quantities_both_survive(self):
        specs = sb.detect_quantities(
            "parking and temperature",
            [PARKING, {"concept_id": "temp", "brick_classes": ["Temperature_Sensor"]}],
        )
        assert sorted(s.name for s in specs) == ["parking_availability", "temp"]


class TestTheRuleIsAboutStructure:
    def test_prefer_label_split_drops_only_a_class_sharing_generic(self):
        a = sb.QuantitySpec(name="a", label="a", classes=("X", "Y"), label_contains=("x",))
        g = sb.QuantitySpec(name="g", label="g", classes=("X",))
        other = sb.QuantitySpec(name="o", label="o", classes=("Z",))
        assert [s.name for s in sb._prefer_label_split([g, a, other])] == ["a", "o"]

    def test_without_a_label_split_spec_nothing_is_dropped(self):
        g = sb.QuantitySpec(name="g", label="g", classes=("X",))
        h = sb.QuantitySpec(name="h", label="h", classes=("X", "W"))
        assert sb._prefer_label_split([g, h]) == [g, h]
