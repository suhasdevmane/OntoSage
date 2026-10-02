# -*- coding: utf-8 -*-
"""Boiler water is not room air, however Brick arranges the classes (BUG-1405).

THE DEFECT, live, occupant01 on /v1, tail O #39 ("Do you adjust temperature based on how crowded
it is?"), full answer read from the capture rather than from a terminal:

    **Across the building temperature is averaging 27.6 °C**, ranging from 7.2 to 71.0 °C.

    | Floor | Now °C | Lowest | Highest | Sensors |
    | Floor 0 | 23.9 | 20.2 | 24.6 | 19 |
    ...
    | Floor 5 | 24.4 | 16.2 | 25.1 | 89 |
    | Floor http://abacwsbuilding.cardiff.ac.uk/abacws#Rooftop | 50.6 | 7.2 | 71.0 | 8 |

    Floor http://…#Rooftop is the highest of the 7 floors at 50.6 °C

The eight "Rooftop floor" points are Gas Boiler 1 and 2, Chiller 1 and Heat Pump 1 entering and
leaving WATER temperatures. **71.0 °C is boiler leaving water; 7.2 °C is chilled water.** Brick
puts `Water_Temperature_Sensor` under `Temperature_Sensor`, so a question about temperature bound
them, and the building mean rose from ~23.8 °C to 27.6 °C — BUG-521's shape, which averaged
900 ppm of CO2 with 21.5 °C because the narrow column is called `value`.

MEASURED over the live graph: 296 points bind a temperature question; **8 carry a water class and
288 do not**. The 235 `Lighting_Correlated_Color_Temperature_Sensor` points (Kelvin) were already
excluded and stay excluded.

**I FIRST LOGGED THIS AS "the headline contradicts its own table" AND THAT WAS WRONG** — my own
dump cut the answer at 330 characters and hid the seventh row, so the range 7.2–71.0 looked
unsupported when the table did support it. The real defect is the mixing, not an inconsistency.
Fourth truncation-induced error in one session (lesson #176).
"""

import pytest

from orchestrator.services.sensor_binder import _FOREIGN_MEDIUM, QuantitySpec

pytestmark = pytest.mark.unit

#: An air-temperature quantity as the building's modality catalogue yields it.
AIR = QuantitySpec(
    name="temperature",
    label="temperature",
    classes=("Temperature_Sensor", "Air_Temperature_Sensor", "Zone_Air_Temperature_Sensor"),
)

#: A quantity that IS about water declares such a class itself and must be unaffected.
WATER = QuantitySpec(
    name="water_temperature",
    label="water temperature",
    classes=("Water_Temperature_Sensor", "Leaving_Water_Temperature_Sensor"),
)

#: The eight points, with the classes the graph gives them.
BOILER_LEAVING = [
    "Temperature_Sensor",
    "Water_Temperature_Sensor",
    "Leaving_Water_Temperature_Sensor",
]
CHILLER_ENTERING = [
    "Temperature_Sensor",
    "Water_Temperature_Sensor",
    "Entering_Water_Temperature_Sensor",
]
ROOM_AIR = ["Temperature_Sensor", "Air_Temperature_Sensor"]
ZONE_AIR = ["Zone_Air_Temperature_Sensor"]


class TestAnAirQuestionDoesNotBindWater:
    @pytest.mark.parametrize(
        "classes,label",
        [
            (BOILER_LEAVING, "Gas Boiler 1 — Building Central Plant leaving water"),
            (CHILLER_ENTERING, "Chiller 1 — Building Central Cooling Plant entering water"),
            (
                ["Temperature_Sensor", "Water_Temperature_Sensor"],
                "Heat Pump 1 — Building Heating/Cooling Plant leaving water",
            ),
        ],
    )
    def test_a_water_point_is_not_an_air_temperature(self, classes, label):
        assert not AIR.matches(classes, label), (
            "a water temperature bound to an air-temperature question; this is what put 71.0 °C "
            "into a building air mean"
        )

    @pytest.mark.parametrize(
        "classes,label",
        [(ROOM_AIR, "Room 5.01 temperature"), (ZONE_AIR, "Zone Air Temperature 2.01")],
    )
    def test_air_points_still_bind(self, classes, label):
        assert AIR.matches(classes, label), "the fix must not cost the 288 air points"


class TestAWaterQuantityIsUnaffected:
    """The rule is 'do not mix media', not 'never read water'."""

    @pytest.mark.parametrize("classes", [BOILER_LEAVING, CHILLER_ENTERING])
    def test_a_water_quantity_reads_its_own_points(self, classes):
        assert WATER.matches(classes, "Gas Boiler 1 leaving water")

    def test_a_water_quantity_does_not_claim_air(self):
        assert not WATER.matches(ROOM_AIR, "Room 5.01 temperature")


class TestTheExclusionIsBuildingAgnostic:
    """Design contract #3: core code carries no building literals."""

    def test_every_excluded_name_is_a_brick_class_not_an_instance(self):
        for name in _FOREIGN_MEDIUM:
            assert name == name.lower(), name
            assert name.endswith("_sensor"), "%r is not a Brick sensor class name" % name
            assert "abacws" not in name and "bldg" not in name, name
            assert not any(ch.isdigit() for ch in name), "%r looks like an instance" % name

    def test_the_set_names_water_and_nothing_else(self):
        """A medium exclusion that crept beyond water would start costing air points."""
        for name in _FOREIGN_MEDIUM:
            assert "water" in name, (
                "%r is in the foreign-medium set without naming water; widening this set is how "
                "an air question starts losing air sensors" % name
            )

    def test_air_classes_are_not_in_the_set(self):
        for air in (
            "air_temperature_sensor",
            "zone_air_temperature_sensor",
            "return_air_temperature_sensor",
            "supply_air_temperature_sensor",
            "discharge_air_temperature_sensor",
            "outside_air_temperature_sensor",
            "temperature_sensor",
        ):
            assert air not in _FOREIGN_MEDIUM, air


class TestNamingTheMediumLiftsTheGuard:
    """The rule is "do not MIX media", so a reader who asks for water gets water.

    This is not hypothetical: the first version of this fix had no lift, and
    `test_the_heat_pump_loop_temperature_binds_both_water_points` failed — a test written for
    exactly this capability, doing exactly its job (lesson #153).
    """

    @pytest.mark.parametrize(
        "question",
        [
            "What is the current temperature of the heat pump water loop?",
            "What is the boiler flow temperature?",
            "How cold is the chilled water?",
            "Show me entering and leaving water temperature for Chiller 1",
        ],
    )
    def test_a_question_naming_the_medium_binds_water(self, question):
        from orchestrator.services.sensor_binder import _FOREIGN_MEDIUM_ASK_RE

        assert _FOREIGN_MEDIUM_ASK_RE.search(question), question
        asked = QuantitySpec(
            name="temperature",
            label="temperature",
            classes=("Temperature_Sensor", "Air_Temperature_Sensor"),
            medium_named=True,
        )
        assert asked.matches(BOILER_LEAVING, "Gas Boiler 1 leaving water")

    @pytest.mark.parametrize(
        "question",
        [
            "Do you adjust temperature based on how crowded it is?",
            "What is the temperature in room 5.01 right now?",
            "Is any area overheating right now?",
            "How does indoor humidity vary across different floors?",
        ],
    )
    def test_an_ordinary_question_does_not_lift_it(self, question):
        """The defect's own question must NOT lift the guard, or the fix does nothing."""
        from orchestrator.services.sensor_binder import _FOREIGN_MEDIUM_ASK_RE

        assert not _FOREIGN_MEDIUM_ASK_RE.search(question), question

    def test_the_stamp_is_applied_on_one_path_only(self):
        """A second exit from `detect_quantities` could forget it; there is one helper."""
        import inspect

        from orchestrator.services import sensor_binder as sb

        src = inspect.getsource(sb.detect_quantities)
        returns = [ln for ln in src.splitlines() if ln.strip().startswith("return ")]
        non_empty = [ln for ln in returns if ln.strip() != "return []"]
        assert non_empty, returns
        assert all("_stamp_medium(" in ln for ln in non_empty), (
            "a return path in detect_quantities does not carry the question's medium intent: %r"
            % non_empty
        )


class TestAFloorIsNamedNotIdentified:
    """The same answer printed a bare IRI as a floor name, twice (BUG-1407).

        | Floor http://abacwsbuilding.cardiff.ac.uk/abacws#Rooftop | 50.6 | 7.2 | 71.0 | 8 |
        Floor http://…#Rooftop is the highest of the 7 floors at 50.6 °C

    Nobody saw it until a NAMED location became a group: every other floor keys on a bare
    number, so the render path had only ever been exercised with "3".
    """

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("3", "3"),
            ("0", "0"),
            ("-1", "-1"),
            ("http://abacwsbuilding.cardiff.ac.uk/abacws#Rooftop", "Rooftop"),
            ("https://example.org/any/building#Plant_Room", "Plant Room"),
            ("RooftopPlant", "Rooftop Plant"),
            ("Plant_Room_2", "Plant Room 2"),
            ("", ""),
        ],
    )
    def test_the_label_is_readable(self, key, expected):
        from orchestrator.services.aggregate_lane import _floor_name

        assert _floor_name(key) == expected

    def test_no_render_site_prints_the_raw_key(self):
        """Seven sites printed `Floor {key}`; a new one must not reintroduce the IRI."""
        import inspect
        import re as _re

        from orchestrator.services import aggregate_lane

        src = inspect.getsource(aggregate_lane)
        bad = [
            ln.strip()
            for ln in src.splitlines()
            if _re.search(r"Floor \{(?!_floor_name)[A-Za-z_]", ln)
        ]
        assert not bad, "a floor key is rendered without _floor_name(): %r" % bad[:4]

    def test_a_numeric_floor_is_untouched_so_the_fix_costs_nothing(self):
        from orchestrator.services.aggregate_lane import _floor_name

        for n in range(-2, 12):
            assert _floor_name(str(n)) == str(n)
