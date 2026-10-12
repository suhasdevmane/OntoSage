"""A bound point whose recorded class names no quantity has its classes looked up (2026-10-11).

The template returns one row per inferred type and the metadata kept the last ("Building_Meter"),
so the building's water meter was refused with measurand=None while its Water_Meter class names
the water quantity.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services import aggregate_lane as al

pytestmark = pytest.mark.unit

U = "ec82da0d-dd27-5565-9851-e950bade85e8"
B = "https://brickschema.org/schema/Brick#"


def _exec(classes):
    async def run(_query):
        return {
            "results": {
                "bindings": [{"uuid": {"value": U}, "cls": {"value": B + c}} for c in classes]
            }
        }

    return run


def test_a_class_that_names_no_quantity_is_replaced_by_one_that_does():
    meta = {U: {"label": "Building-Level Water Meter", "brick_class": B + "Building_Meter"}}
    out = asyncio.run(
        al.fill_missing_classes([U], meta, _exec(["Building_Meter", "Meter", "Water_Meter"]))
    )
    assert out[U]["brick_class"] == B + "Water_Meter"
    assert al.measurand_from_classes([out[U]["brick_class"]]) is not None


def test_a_class_that_already_names_a_quantity_is_not_asked_about():
    meta = {U: {"label": "x", "brick_class": B + "Water_Meter"}}

    async def never(_q):
        raise AssertionError("no lookup expected")

    assert asyncio.run(al.fill_missing_classes([U], meta, never)) == meta
