# -*- coding: utf-8 -*-
"""BUG-718 — advice that contradicts the building it is addressed to.

Measured on the 2026-09-17 stakeholder read, class C22. The recommend lane produced
general consultancy and attached it to a building that already had what it advised buying:

* "install daylight sensors" — in a building that models 269 illuminance points;
* run-3 row 128: "install sensors that capture comfort parameters before adjusting the
  schedule" — where temperature, CO2 and humidity are instrumented on every floor;
* run-3 row 145: "install occupancy-based lighting controls" — where occupancy is a
  measured modality and the answer's own list says so two lines earlier;
* run-3 row 132 answered a student asking whether tap water is free with five capital
  projects, the first of them "install on-site water-filtration stations".

That is the most damaging shape of wrong answer this lane can produce: it reads as
expertise, and it tells a reader to buy what they already own. The fix hands the prompt
the quantities this building declares, from the modality CONFIG rather than from any list
written here — so a building that adds a quantity is covered with no edit to the code, and
no building's name appears in the lane.
"""

import inspect

import pytest

pytestmark = pytest.mark.unit


def _src():
    from orchestrator.workflow._orchestrator import WorkflowOrchestrator

    return inspect.getsource(WorkflowOrchestrator._recommend_node)


def test_the_prompt_is_told_what_the_building_already_measures():
    src = _src()
    assert "WHAT THIS BUILDING ALREADY MEASURES" in src
    assert "load_modalities" in src


def test_installing_what_the_building_has_is_forbidden_in_words():
    src = _src()
    for verb in ("installing", "adding", "fitting", "deploying", "retrofitting"):
        assert verb in src, f"the prohibition must name '{verb}'"
    assert "it is already" in src and "instrumented" in src


def test_the_prompt_asks_for_the_measured_quantity_to_be_used_instead():
    """A prohibition alone leaves the model with nothing to say. The replacement is the
    point: a threshold to watch, a schedule to change, a reading to check."""
    src = _src()
    assert "recommend USING it" in src


def test_every_recommendation_must_act_on_something_named():
    src = _src()
    assert "Generic best practice that could be written about any building" in src


def test_a_question_about_what_exists_is_answered_before_any_improvement():
    """Row 132 asked "is tap water free somewhere, or do I have to buy bottles?" and was
    given a capital-works table. The answer to that question is yes or no."""
    assert "a list of improvements is not an answer to" in _src()


def test_the_modality_list_is_read_from_config_not_written_here():
    """The list must not become a second hand-maintained table that is wrong for every
    building except the one it was written on."""
    src = _src()
    # The grounding block itself — from its heading to the prompt it feeds — names no
    # quantity of its own. Scoped to that block on purpose: the prompt below it carries
    # generic instructions that legitimately mention measurands ("a sensor count is not
    # occupancy"), and a whole-function scan would flag those and teach the next reader
    # to delete a true sentence to make a test pass.
    head = src.index("WHAT THIS BUILDING ALREADY MEASURES")
    block = src[head : src.index("prompt = f", head)].lower()
    for quantity in ("illuminance", "daylight", "occupancy", "pm25", "co2", "humidity"):
        assert quantity not in block, f"'{quantity}' is hardcoded in the grounding block"
    assert "building_id" in block  # asked per building, not once for all of them
    # and it degrades rather than failing: a building with no config still gets an answer
    assert "must not cost the answer" in src


def test_the_declared_modalities_load_offline_and_read_as_english():
    """The names reach a prompt, so they must be words rather than column names."""
    from orchestrator.services.deliberation.coverage_audit import load_modalities

    names = {str(spec.name).replace("_", " ") for spec in load_modalities(None)}
    assert names, "no modality set loaded — the prompt would carry no grounding at all"
    assert not any("_" in n for n in names)
