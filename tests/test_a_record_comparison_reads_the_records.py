"""A comparison or trend naming no measured quantity and no place reads the records (2026-10-11).

The compare and trend lanes compare readings; comparisons of records reached them and were
answered "I have no measured series for Contractor_Completion_Record, ...".
"""

from __future__ import annotations

import pytest

from orchestrator.services import routing_contract as rc

pytestmark = pytest.mark.unit

_CO2 = [{"concept_id": "co2", "lay_term": "co2", "brick_classes": ["CO2_Level_Sensor"]}]


def _ctx(intent, query, concepts=None):
    return rc._Ctx(
        query=query,
        ql=query.lower(),
        normalized={"intent": intent, "concepts": concepts or []},
        sr=None,
    )


@pytest.mark.parametrize("intent", ["compare", "trend"])
def test_a_records_comparison_goes_to_metadata(intent):
    q = "Compare the contractor completion records with the observed service states"
    assert rc._r_record_comparison_is_not_a_series(_ctx(intent, q)) == "metadata"


def test_a_measured_quantity_keeps_its_lane():
    q = "Compare the CO2 this week with last week"
    assert rc._r_record_comparison_is_not_a_series(_ctx("compare", q, _CO2)) is None


_WATER = [
    {
        "concept_id": "water_usage",
        "lay_term": "how much water",
        "brick_classes": ["brick:Building_Water_Meter", "brick:Water_Meter"],
    }
]


def test_a_metered_quantity_keeps_its_lane():
    # The first live check sent this to the records lane: meters are measured too.
    q = "How much water did we use last week compared with the week before?"
    assert rc._r_record_comparison_is_not_a_series(_ctx("compare", q, _WATER)) is None


def test_a_named_place_keeps_its_lane():
    assert (
        rc._r_record_comparison_is_not_a_series(_ctx("compare", "Compare floor 3 and floor 4"))
        is None
    )


def test_other_intents_are_untouched():
    q = "Compare the contractor completion records with the observed service states"
    assert rc._r_record_comparison_is_not_a_series(_ctx("register", q)) is None
