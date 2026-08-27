# -*- coding: utf-8 -*-
"""The unit reaches the answer (BUG-257, narration half, 2026-08-27).

"152 - 154 units (the exact unit isn't specified)" for a filter differential
pressure whose point carries BOTH `qudt:hasUnit <unit:PA>` and
`brick:hasUnit "Pa"`.

The earlier half of this bug fixed the metadata path -- the config-backed unit
lookup and the QUDT binding. But probing showed the builder ALREADY returned "Pa"
for this exact sensor, so that could not have been the cause, and the row was
deliberately left open rather than closed on a plausible-looking change.

This is the actual cause. `_format_results` built its summary prompt from the raw
rows alone: uuid, value, timestamp. The model was never told the unit or the
label, so "the exact unit isn't specified" was an HONEST answer to a prompt that
had omitted it. The caller had the metadata in state the whole time and simply
never passed it.

The prompt now carries each uuid's label and unit, and says what to do when a unit
is missing -- "say it is not recorded, never invent one" -- because an instruction
to state the unit, with no instruction for the absent case, leaves the model to
choose between them on its own.
"""

import inspect

import pytest

from orchestrator.agents.sql_agent import SQLAgent

pytestmark = pytest.mark.unit

_MD = {
    "11111111-2222-3333-4444-555555555555": {
        "label": "Filter Differential Pressure - AHU F5",
        "unit": "Pa",
    },
    "22222222-0000-0000-0000-000000000000": {"label": "Sound Level 5.01", "unit": ""},
}


# -- the context block --------------------------------------------------------
def test_the_label_and_unit_are_offered_to_the_model():
    out = SQLAgent._sensor_context(_MD)
    assert "Filter Differential Pressure - AHU F5" in out
    assert "measured in Pa" in out


def test_a_sensor_with_no_unit_says_so_rather_than_going_silent():
    """The prompt tells the model to state the unit or say it is not recorded. A
    silent omission would leave it to choose between those on its own."""
    out = SQLAgent._sensor_context(_MD)
    assert "unit NOT RECORDED" in out


def test_no_metadata_adds_nothing_to_the_prompt():
    """Text-to-SQL turns have no metadata; they must be unchanged."""
    assert SQLAgent._sensor_context(None) == ""
    assert SQLAgent._sensor_context({}) == ""


# -- the prompt and the plumbing ---------------------------------------------
def test_the_prompt_instructs_both_cases():
    src = inspect.getsource(SQLAgent._format_results)
    assert "States the UNIT with every figure" in src
    assert "never invent one" in src


def test_the_formatter_accepts_metadata():
    sig = inspect.signature(SQLAgent._format_results)
    assert "sensor_metadata" in sig.parameters


def test_the_fetcher_accepts_and_forwards_it():
    """A parameter that is accepted and then dropped is the same bug one layer in."""
    sig = inspect.signature(SQLAgent.fetch_data_for_uuids)
    assert "sensor_metadata" in sig.parameters
    src = inspect.getsource(SQLAgent.fetch_data_for_uuids)
    assert "sensor_metadata" in src.split("def fetch_data_for_uuids", 1)[1].split("return", 1)[0]


def test_the_orchestrator_actually_passes_it():
    """The metadata sat in state the whole time. Accepting it changes nothing until
    the caller hands it over."""
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    idx = src.index("fetch_data_for_uuids(")
    assert 'state.intermediate_results.get("sensor_metadata")' in src[idx : idx + 700]
