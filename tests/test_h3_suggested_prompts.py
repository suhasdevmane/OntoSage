"""H3 (TRIAL_TRACKER, 2026-10-06): suggested_prompts() gives exactly six starting questions that
name no internal lane, and that read the same in any building."""

from __future__ import annotations

import re

import pytest

from orchestrator.services.self_description import (
    _NOT_USER_FACING,
    SUGGESTED_PROMPTS,
    suggested_prompts,
)

pytestmark = pytest.mark.unit


def _live_intent_names():
    from orchestrator.intents.registry import get_intent_registry

    return {i.name for i in get_intent_registry().intents}


def test_exactly_six_strings_are_returned():
    prompts = suggested_prompts()
    assert len(prompts) == 6
    assert all(isinstance(p, str) and p.strip() for p in prompts)
    assert len(set(prompts)) == 6


def test_the_returned_list_is_a_copy_not_the_module_tuple():
    prompts = suggested_prompts()
    prompts.append("extra")
    assert len(suggested_prompts()) == 6
    assert len(SUGGESTED_PROMPTS) == 6


def test_each_suggestion_is_a_question():
    assert all(p.rstrip().endswith("?") for p in suggested_prompts())


def test_no_suggestion_names_an_internal_lane():
    internal = set(_NOT_USER_FACING) | _live_intent_names()
    for prompt in suggested_prompts():
        words = set(re.findall(r"[a-z_]+", prompt.lower()))
        for name in internal:
            # Whole-word, and the underscore form too ("sensor_data", "safety_report").
            assert name not in words, f"{prompt!r} names internal lane {name!r}"
            spaced = name.replace("_", " ")
            if "_" in name:
                assert spaced not in prompt.lower(), f"{prompt!r} names lane {name!r}"


@pytest.mark.parametrize(
    "pattern",
    [
        r"\b(room|floor|level|zone)\s*\d",  # a room number or floor number of one building
        r"abacws",  # a building's name
        r"bldg\d",
    ],
)
def test_no_suggestion_depends_on_one_building(pattern):
    for prompt in suggested_prompts():
        assert re.search(pattern, prompt, re.IGNORECASE) is None, prompt
