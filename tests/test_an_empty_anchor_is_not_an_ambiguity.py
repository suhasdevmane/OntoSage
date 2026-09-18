# -*- coding: utf-8 -*-
"""A phrase that names no space is the default scope, not an unresolved anchor (BUG-755).

Measured live 2026-09-17, after the row-117 compiler fix had already landed and the question
was STILL refused: "I'm pregnant and overheating - where's the coolest place to work today?"

The compile was right — `constraints=[('temperature','minimize')]`. The refusal came from the
spatial half: the model emitted `in_space` with anchor `""` for the phrase "coolest place to
work today", which became an `unresolved_anchor` signal. Two rules then compounded:

* `CQIR.is_executable()` is false while ANY signal stands, so admission returned CLARIFY;
* `clarify_policy.absorb_unmapped`, whose whole job is to drop an unsensable extra like
  "pregnant" when real constraints mapped, returns early when a non-unmapped signal remains.

So one phantom anchor blocked a ranking the lane can do over every room. The fix distinguishes
"named no space" (default scope) from "named a space I could not resolve" (still ask).
"""

from __future__ import annotations

import json

import pytest

from orchestrator.services.deliberation import compiler as c

pytestmark = pytest.mark.unit

KNOWN = {"temperature", "co2", "noise", "occupancy", "illuminance", "pm25"}

#: The cached compile of the live question, as Redis held it on 2026-09-17.
LIVE_RAW = json.dumps(
    {
        "decision": "select_one",
        "constraints": [
            {
                "phrase": "coolest place to work today",
                "modality": "temperature",
                "direction": "minimize",
                "hardness": "soft",
                "threshold": None,
            }
        ],
        "spatial": [
            {"relation": "in_space", "anchor": "", "phrase": "coolest place to work today"}
        ],
        "time": {"basis": "now", "horizon_hours": None, "window_hours": None},
        "unmapped": ["pregnant"],
    }
)


def test_the_live_question_compiles_to_an_executable_plan():
    ir = c._parse_compiled(LIVE_RAW, "coolest place to work today?", KNOWN)
    assert [(x.modality, x.direction.value) for x in ir.constraints] == [
        ("temperature", "minimize")
    ]
    assert not [s for s in ir.signals if s.kind == "unresolved_anchor"]
    # "pregnant" survives as an unmapped term — absorb_unmapped drops and DECLARES it, which
    # it can only do once no other signal stands.
    from orchestrator.services.deliberation.clarify_policy import absorb_unmapped

    absorbed, dropped, must_decline = absorb_unmapped(ir)
    assert dropped == ["pregnant"]
    assert not must_decline
    assert absorbed.is_executable()


def test_a_named_space_with_no_anchor_still_asks():
    """Widening a question the user scoped to one room is the worse error."""
    raw = json.dumps(
        {
            "decision": "select_one",
            "constraints": [
                {
                    "phrase": "warmest",
                    "modality": "temperature",
                    "direction": "maximize",
                    "hardness": "soft",
                    "threshold": None,
                }
            ],
            "spatial": [{"relation": "in_space", "anchor": "", "phrase": "in Room 2.01"}],
            "time": {"basis": "now", "horizon_hours": None, "window_hours": None},
        }
    )
    ir = c._parse_compiled(raw, "is Room 2.01 warm?", KNOWN)
    assert [s.kind for s in ir.signals] == ["unresolved_anchor"]
    assert not ir.is_executable()


@pytest.mark.parametrize(
    "phrase,named",
    [
        ("coolest place to work today", False),
        ("somewhere quiet to work", False),
        ("a place to sit", False),
        ("in Room 2.01", True),
        ("on floor 3", True),
        ("near the Atrium", True),
    ],
)
def test_what_counts_as_naming_a_space(phrase, named):
    assert c._looks_like_a_named_space(phrase) is named
