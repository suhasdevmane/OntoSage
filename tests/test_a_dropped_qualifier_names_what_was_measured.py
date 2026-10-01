# -*- coding: utf-8 -*-
"""When the reader's qualifier is not true of the bound sensors, name what IS (BUG-1403).

THE DEFECT, live, facility01 on /v1, caches flushed:

    Q  "What is the barometric pressure in the building?"
    A  "**Across the building pressure is averaging 19.1 Pa**, ranging from 0.0 to 51.5 Pa"
       with a per-floor table.

The six bound sensors are all "Air Handling Unit — Floor N filter differential pressure", typed
`Filter_Differential_Pressure_Sensor` -- the pressure drop across an AHU filter, which indicates
a clogged filter. **Barometric pressure is ~101,325 Pa.** This building holds no barometric
sensor at all, so the honest answer is that it cannot be given.

The lane KNEW and said nothing to the reader:

    [aggregate] qualifier 'barometric' not carried by all 6 bound sensor names — keeping 'pressure'

Dropping to the coarse name was deliberate -- "at least not a claim about a quantity nobody
measured" -- and it is not enough: it answers a question about one physical quantity with
readings of another. Naming the qualifier the SENSORS carry hands the reader the discrepancy.

This is wording only: no figure, grouping or decision-to-answer changes. The remaining half --
that a question naming a quantity the building does not measure should be DECLINED rather than
answered about a cousin -- is not fixed here and is stated on the row.
"""

import pytest

from orchestrator.services.aggregate_lane import _shared_qualifier, asked_quantity_name

pytestmark = pytest.mark.unit

#: The six labels, as the graph spells them.
AHU_FILTER = ["Air Handling Unit — Floor %d filter differential pressure" % i for i in range(6)]


class TestTheSensorsQualifierIsUsed:
    def test_a_barometric_ask_is_named_for_what_was_measured(self):
        assert (
            asked_quantity_name(
                "What is the barometric pressure in the building?", "pressure", AHU_FILTER
            )
            == "filter differential pressure"
        )

    def test_the_shared_run_is_read_from_the_labels(self):
        assert _shared_qualifier(AHU_FILTER, "pressure") == "filter differential"

    def test_an_outside_air_ask_over_room_sensors_names_air_temperature(self):
        """The docstring's own example: the labels do not carry "outside", and do carry "air"."""
        labels = ["Room %d air temperature" % i for i in range(3)]
        assert (
            asked_quantity_name("What is the outside air temperature?", "temperature", labels)
            == "air temperature"
        )


class TestWhatMustNotChange:
    def test_no_qualifier_asked_keeps_the_coarse_name(self):
        assert (
            asked_quantity_name("What is the pressure in the building?", "pressure", AHU_FILTER)
            == "pressure"
        )

    def test_a_qualifier_that_HOLDS_is_still_used(self):
        assert (
            asked_quantity_name("What is the filter differential pressure?", "pressure", AHU_FILTER)
            == "filter differential pressure"
        )

    def test_labels_that_disagree_fall_back_to_the_coarse_name(self):
        """A qualifier true of SOME sensors and not others is the defect, one level down."""
        mixed = [
            "Floor 1 filter differential pressure",
            "Floor 2 duct static pressure",
        ]
        assert asked_quantity_name("barometric pressure?", "pressure", mixed) == "pressure"
        assert _shared_qualifier(mixed, "pressure") == ""

    def test_no_labels_falls_back(self):
        assert asked_quantity_name("barometric pressure?", "pressure", []) == "pressure"
        assert _shared_qualifier([], "pressure") == ""

    def test_a_label_without_the_quantity_word_falls_back(self):
        assert _shared_qualifier(["Floor 1 humidity"], "pressure") == ""


class TestItCannotInvent:
    """Every word must come from every label — that is what makes this safe."""

    def test_the_qualifier_words_all_appear_in_every_label(self):
        q = _shared_qualifier(AHU_FILTER, "pressure")
        assert q
        for word in q.split():
            for label in AHU_FILTER:
                assert word in label.lower(), (word, label)

    def test_the_readers_word_is_never_returned_when_unsupported(self):
        out = asked_quantity_name(
            "What is the barometric pressure in the building?", "pressure", AHU_FILTER
        )
        assert (
            "barometric" not in out
        ), "the reader's unsupported qualifier was echoed back as though the sensors carried it"


#: How the six reach the lane LIVE — short display names in which "differential pressure" is
#: abbreviated, so there is no "pressure" to read leftwards from. Measured from the log line:
#: `(from labels ['AHU F5 Filter DP', 'AHU F2 Filter DP', ...])`.
AHU_SHORT = ["AHU F%d Filter DP" % i for i in range(6)]


class TestLabelsThatDoNotCarryTheQuantityWord:
    """The live case, and the reason the first version of this fix did nothing.

    `_shared_qualifier` read leftwards from the quantity word. These labels do not contain it,
    so it returned "" and the answer still called AHU filter differential pressure "pressure".
    """

    def test_the_shared_words_are_used_when_no_label_carries_the_anchor(self):
        out = asked_quantity_name(
            "What is the barometric pressure in the building?", "pressure", AHU_SHORT
        )
        assert "Filter" in out and "DP" in out, out
        assert "barometric" not in out.lower()

    def test_the_shared_words_come_from_every_label(self):
        q = _shared_qualifier(AHU_SHORT, "pressure")
        assert q, "no shared qualifier derived from abbreviated labels"
        for word in q.split():
            for label in AHU_SHORT:
                assert word.lower() in label.lower(), (word, label)

    def test_the_per_sensor_token_is_dropped(self):
        """F0..F5 differ per sensor, so they cannot name the quantity."""
        q = _shared_qualifier(AHU_SHORT, "pressure")
        for tok in ("F0", "F1", "F2", "F3", "F4", "F5"):
            assert tok.lower() not in q.lower().split(), q

    def test_abbreviated_labels_that_disagree_still_fall_back(self):
        assert (
            asked_quantity_name(
                "barometric pressure?", "pressure", ["AHU F1 Filter DP", "VAV Duct Static"]
            )
            == "pressure"
        )

    def test_no_qualifier_asked_is_unaffected_by_abbreviated_labels(self):
        assert (
            asked_quantity_name("What is the pressure in the building?", "pressure", AHU_SHORT)
            == "pressure"
        )
