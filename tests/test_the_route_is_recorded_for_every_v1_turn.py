# -*- coding: utf-8 -*-
"""W04: a /v1 turn says which rules put it on its lane, not only which lane.

`ontosage_intent` (TODO-657) says WHERE a turn went. Until W04 the reason existed only inside the
server, so a fluent answer from the wrong lane was indistinguishable from a right one. The
record already existed on every turn (`route_decision`); these tests pin that a bounded copy of it
leaves the server on every /v1 body and on the streamed final chunk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

MAIN = Path(__file__).resolve().parent.parent / "orchestrator" / "main.py"


def _record():
    from orchestrator.main import _route_record

    return _route_record


def _state(rd):
    return SimpleNamespace(intermediate_results={"route_decision": rd} if rd is not None else {})


def test_the_record_carries_the_rules_and_the_lane():
    out = _record()(
        _state(
            {
                "intent_from_dialogue": "sensor_data",
                "intent_after_overrides": "register",
                "overrides_applied": ["alarm_history_is_a_record"],
                "final_node": "register",
                "decision_source": "override",
            }
        )
    )
    assert out == {
        "decision_source": "override",
        "intent_from_dialogue": "sensor_data",
        "intent_after_overrides": "register",
        "final_node": "register",
        "overrides_applied": ["alarm_history_is_a_record"],
    }


def test_an_unrouted_turn_records_nothing_rather_than_inventing_a_reason():
    assert _record()(_state(None)) is None
    assert _record()(SimpleNamespace(intermediate_results={"route_decision": "not a dict"})) is None
    assert _record()(SimpleNamespace()) is None


def test_the_override_list_is_bounded_and_the_record_is_json_serialisable():
    many = [f"rule_{i}" for i in range(500)]
    out = _record()(_state({"overrides_applied": many, "decision_source": "override"}))
    assert len(out["overrides_applied"]) == 12
    json.dumps(out)  # would raise on a non-serialisable value


def test_every_v1_response_shape_carries_the_field():
    """Streamed final chunk, the timeout body, and the normal body all name it."""
    src = MAIN.read_text(encoding="utf-8")
    assert src.count('"ontosage_route"') >= 3, "streamed, timeout and normal /v1 bodies"
    # It travels beside the lane it explains, never on its own.
    for m in re.finditer(r'"ontosage_route"', src):
        window = src[max(0, m.start() - 700) : m.end() + 700]
        assert "ontosage_intent" in window, "the route must sit beside the lane it explains"
