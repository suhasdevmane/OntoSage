"""What a metered total COST: consumption x the tariff in force, per the building's own method.

TODO-1646 (2026-10-11): "How much did the building's water cost last week?" had metered litres
and a water tariff and nothing joined them. The tariff document's rule is followed: the tariff in
force for the period, consumption in the rate's unit, standing charge per day, no figure when no
single tariff covers the period.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from orchestrator.services import utility_cost as uc

pytestmark = pytest.mark.unit


def _b(**kw):
    return {k: {"value": str(v)} for k, v in kw.items()}


TARIFFS = [
    _b(
        t="x/TAR-WATER-2026",
        id="TAR-WATER-2026",
        kind="Water",
        rate=1.945,
        unit="m3",
        standing=0.0,
        currency="GBP",
        **{"from": "2025-12-31", "to": "2026-12-31"},
        provider="Dwr Cymru Welsh Water",
    ),
    _b(
        t="x/TAR-ELEC-2026",
        id="TAR-ELEC-2026",
        kind="Electricity",
        rate=0.2847,
        unit="kWh",
        standing=0.612,
        currency="GBP",
        **{"from": "2025-12-31", "to": "2026-12-31"},
    ),
    _b(
        t="x/TAR-ELEC-2025",
        id="TAR-ELEC-2025",
        kind="Electricity",
        rate=0.3102,
        unit="kWh",
        standing=0.588,
        currency="GBP",
        **{"from": "2024-12-31", "to": "2025-12-30"},
    ),
]


def test_water_litres_are_priced_per_cubic_metre():
    t = uc.pick_tariff(TARIFFS, "water", datetime(2026, 10, 5), datetime(2026, 10, 11))
    text = uc.cost_sentence(66882.0, "L", 7, t)
    assert "£1.945 per m³" in text and "about £130.09" in text  # 66.882 m3 x 1.945
    assert "exclude VAT" in text


def test_electricity_adds_the_standing_charge_per_day():
    t = uc.pick_tariff(TARIFFS, "electricity", datetime(2026, 10, 5), datetime(2026, 10, 11))
    got = uc.cost_of(1000.0, "kWh", 7, t)
    assert round(got["total"], 2) == round(1000 * 0.2847 + 7 * 0.612, 2)


def test_a_period_no_single_tariff_covers_gets_no_figure():
    assert (
        uc.pick_tariff(TARIFFS, "electricity", datetime(2025, 12, 20), datetime(2026, 1, 5)) is None
    )


def test_an_unconvertible_unit_gets_no_figure():
    t = uc.pick_tariff(TARIFFS, "water", datetime(2026, 10, 5), datetime(2026, 10, 11))
    assert uc.cost_sentence(10.0, "kW", 1, t) == ""


@pytest.mark.parametrize(
    "q, asks",
    [
        ("How much did the building's water cost last week?", True),
        ("What was our electricity bill yesterday?", True),
        ("How much water did the building use yesterday?", False),
    ],
)
def test_a_cost_question_is_recognised(q, asks):
    assert uc.asks_for_cost(q) is asks


def test_the_answer_gains_the_cost_line_only_when_asked():
    answer = {
        "formatted_response": "**66,882 L (66.9 m³) was used in the building**, last week.",
        "aggregate": {"unit": "L"},
        "figures": {"total": 66882.0},
    }

    async def sparql(_q):
        return {"results": {"bindings": TARIFFS}}

    got = asyncio.run(
        uc.append_cost(
            answer,
            "What did the water cost last week?",
            "water usage",
            "2026-10-04 23:00:00",
            "2026-10-11 22:59:59",
            "Europe/London",
            sparql,
        )
    )
    assert "about £130.09" in got["formatted_response"]
    same = asyncio.run(
        uc.append_cost(
            answer,
            "How much water was used last week?",
            "water usage",
            "2026-10-04 23:00:00",
            "2026-10-11 22:59:59",
            "Europe/London",
            sparql,
        )
    )
    assert same is answer


def _ctx(intent, query, concept_id):
    from orchestrator.services import routing_contract as rc

    concepts = (
        [{"concept_id": concept_id, "brick_classes": ["brick:Water_Meter"]}] if concept_id else []
    )
    return rc._Ctx(
        query=query, ql=query.lower(), normalized={"intent": intent, "concepts": concepts}, sr=None
    )


@pytest.mark.parametrize(
    "intent, q, concept, want",
    [
        (
            "metadata",
            "How much did the building's water cost last week?",
            "water_usage",
            "analytics",
        ),
        ("metadata", "What did the water cost in August?", "water_usage", None),
        ("metadata", "How much did the security contract cost last week?", None, None),
        ("analytics", "How much did the water cost last week?", "water_usage", None),
    ],
)
def test_only_a_day_or_week_cost_of_a_metered_utility_is_computed(intent, q, concept, want):
    from orchestrator.services import routing_contract as rc

    assert rc._r_metered_cost_is_computed(_ctx(intent, q, concept)) == want


def test_an_energy_total_is_claimed_for_a_cost_only():
    from orchestrator.services import aggregate_lane as al

    q = "What did the building's electricity cost yesterday?"
    assert al.wants_lane(q, 6, False, False, ["energy"]).stat == "total"
    # an energy total with no cost over a period still RUNNING stays with the period summary
    # (BUG-936's partial weeks); a completed one is claimed since 2026-10-11 (see
    # test_a_completed_energy_period_is_summed_with_its_own_dates.py)
    assert (
        al.wants_lane(
            "How much electricity has the building used this week?", 6, False, False, ["energy"]
        )
        is None
    )


def test_the_export_document_states_the_total_for_an_additive_unit():
    from orchestrator.agents.data_export_agent import _additive_total

    rows = [{"value": 1.5, "unit": "kWh"}, {"value": 2.5, "unit": "kWh"}]
    assert "Total over the period: 4.0 kWh" in _additive_total(rows)
    assert _additive_total([{"value": 21.0, "unit": "°C"}]) == ""
