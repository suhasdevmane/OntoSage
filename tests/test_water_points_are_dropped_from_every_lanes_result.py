# -*- coding: utf-8 -*-
"""The medium rule holds on the sparql result rows, whatever lane produced them (BUG-1405, part 2).

MEASURED on tail P, 2026-10-02 (occupant01, /v1), lane `recommend`:

    "Across the building temperature is averaging 25.8 degC, ranging from 6.4 to 71.7 degC"
    | Floor Rooftop | 50.1 | 6.4 | 71.7 | 8 |          <- boiler, chiller and heat-pump WATER

296 sensors, the same eight water points BUG-1405 had removed from the binder's population path
on 2026-10-01. The concept (`setpoint_recommendation`) resolved to the broad Temperature_Sensor
class and the sparql agent fetched every subclass instance directly; the binder's exclusion never
ran because `recommend` is not a binder intent. The rows are now filtered at the seam, before
the intent gate, by LABEL and by class -- the same English medium words the ask regex uses.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services import sensor_binder as sb

pytestmark = pytest.mark.unit


def _row(label, uuid="11111111-1111-4111-8111-111111111111", cls=None):
    row = {
        "sensor": {"value": "http://x#" + label.replace(" ", "_")},
        "label": {"value": label},
        "uuid": {"value": uuid},
    }
    if cls:
        row["type"] = {"value": "https://brickschema.org/schema/Brick#" + cls}
    return row


AIR = [_row("Air Temperature Sensor 5.01"), _row("Room 2.01 zone air temperature")]
WATER = [
    _row("Gas Boiler 1 leaving water temperature"),
    _row("Chiller 1 entering water temperature"),
    _row("Heat Pump 1 return water temperature"),
    _row("Plant point", cls="Water_Temperature_Sensor"),
]


def _result(rows):
    """The shape the sparql lane really returns: a SPARQL document under "results"."""
    return {
        "results": {
            "head": {"vars": ["sensor", "label", "uuid"]},
            "results": {"bindings": list(rows)},
        },
        "standardized": {"results": []},
    }


def _rows_of(out):
    return out["results"]["results"]["bindings"]


class TestTheRowFilter:
    def test_water_rows_are_dropped_from_a_temperature_question(self):
        out = sb.drop_foreign_medium_rows(
            _result(AIR + WATER), "Should the target temperature shift?"
        )
        labels = [r["label"]["value"] for r in _rows_of(out)]
        assert labels == [r["label"]["value"] for r in AIR]

    def test_a_question_naming_the_medium_keeps_them(self):
        out = sb.drop_foreign_medium_rows(
            _result(AIR + WATER), "What is the current temperature of the heat pump water loop?"
        )
        assert len(_rows_of(out)) == len(AIR) + len(WATER)

    def test_a_result_with_only_water_rows_is_left_alone(self):
        """Dropping everything would turn a plant answer into an empty one; the ask decides."""
        out = sb.drop_foreign_medium_rows(_result(WATER), "what is the temperature?")
        assert len(_rows_of(out)) == len(WATER)

    def test_air_rows_are_never_touched(self):
        out = sb.drop_foreign_medium_rows(_result(AIR), "what is the temperature?")
        assert _rows_of(out) == AIR

    def test_a_bare_sparql_document_is_filtered_too(self):
        bare = {"results": {"bindings": list(AIR + WATER)}}
        out = sb.drop_foreign_medium_rows(bare, "what is the temperature?")
        assert len(out["results"]["bindings"]) == len(AIR)

    def test_a_row_with_no_label_is_read_by_its_iri(self):
        """The entity-less template returns no label; the IRI local name says water."""
        rows = [
            {"sensor": {"value": "http://x#Air_Temperature_Sensor_5.01"}, "uuid": {"value": "a"}},
            {
                "sensor": {"value": "http://x#Boiler_1_Entering_Water_Temperature"},
                "uuid": {"value": "b"},
            },
        ]
        out = sb.drop_foreign_medium_rows(_result(rows), "what is the temperature?")
        assert [r["sensor"]["value"] for r in _rows_of(out)] == [
            "http://x#Air_Temperature_Sensor_5.01"
        ]

    def test_a_water_flow_sensor_is_not_a_water_temperature_point(self):
        rows = [
            {
                "sensor": {"value": "http://x#Floor0_sat_water_flow_rate"},
                "label": {"value": "Floor 0 sat water flow rate"},
                "uuid": {"value": "a"},
            },
            {
                "sensor": {"value": "http://x#Water_Flow_Sensor_Main"},
                "label": {"value": "Water Flow Sensor Main"},
                "uuid": {"value": "b"},
            },
        ]
        out = sb.drop_foreign_medium_rows(_result(rows), "what is the flow rate?")
        assert len(_rows_of(out)) == 2

    def test_it_never_raises(self):
        assert sb.drop_foreign_medium_rows({"results": "garbage"}, "x") == {"results": "garbage"}
        assert sb.drop_foreign_medium_rows(None, "x") is None


class TestItRunsBeforeTheIntentGate:
    async def test_a_recommend_turn_is_filtered(self, monkeypatch):
        state = SimpleNamespace(
            current_intent="recommend", intermediate_results={"intent": "recommend"}
        )
        out = await sb.apply_to_result(
            state, _result(AIR + WATER), "Should the target temperature shift?"
        )
        assert len(_rows_of(out)) == len(AIR)

    def test_the_filter_precedes_the_gate_in_source(self):
        import inspect

        src = inspect.getsource(sb.apply_to_result)
        assert src.index("drop_foreign_medium_rows(result, question)") < src.index(
            "if intent not in BINDER_INTENTS"
        )
