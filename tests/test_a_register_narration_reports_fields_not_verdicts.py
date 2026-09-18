# -*- coding: utf-8 -*-
"""The register narration reports what a field says, not a verdict it reasoned to (BUG-709).

The largest class in the 2026-09-17 hand read of 147 live stakeholder answers: 17 answers where
the register was RIGHT and the conclusion was invented. Two measured examples:

* "Which permission groups or zones are orphaned because no current owner, purpose or mapped
  opening can be evidenced?" -> "Each of the 20 records contains a mapped opening and a granted
  role, so none lack the basic evidence of ownership, purpose" — a verdict reasoned from the
  fields that happen to be present.
* "Which water-supply, drainage, containment and isolation details minimise the consequence of
  leaks?" -> "assets list probable containment features that would limit damage from a leak",
  where no field records containment at all.

The instruction is in the narration prompt, so the test pins the prompt: a rule that is deleted
takes its defect class back with it, and nothing else in the suite reads this text.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.agents import sparql_agent

pytestmark = pytest.mark.unit


def _narration_prompt_source() -> str:
    """The function that builds the narration prompt, as the file holds it."""
    for name in dir(sparql_agent.SPARQLAgent):
        if name.startswith("__"):
            continue
        member = getattr(sparql_agent.SPARQLAgent, name, None)
        if not callable(member):
            continue
        try:
            src = inspect.getsource(member)
        except (OSError, TypeError):
            continue
        if "=== USER QUESTION ===" in src and "Generate your response now" in src:
            return src
    raise AssertionError("the narration prompt is no longer built in SPARQLAgent")


@pytest.fixture(scope="module")
def prompt() -> str:
    return _narration_prompt_source()


def test_a_judgement_is_reported_only_when_a_field_records_it(prompt):
    assert "A FIELD IS EVIDENCE OF ITSELF AND NOTHING ELSE" in prompt
    for word in ("orphaned", "adequate", "justified", "viable", "compliant"):
        assert word in prompt, f"the rule no longer names {word}, one of the asked judgements"
    assert "say which field would have recorded it and stop" in prompt


def test_a_missing_field_is_unknown_not_satisfactory(prompt):
    assert "A MISSING FIELD MEANS UNKNOWN, NEVER SATISFACTORY" in prompt


def test_a_record_status_is_not_a_statement_about_the_world(prompt):
    assert "A STATUS DESCRIBES THE RECORD, NOT THE WORLD" in prompt


def test_an_invented_grouping_must_name_the_field_it_grouped_on(prompt):
    assert "DO NOT INVENT A CATEGORY" in prompt


def test_the_earlier_rules_this_prompt_already_carried_are_still_there(prompt):
    """A prompt is a place where rules quietly disappear in an edit."""
    assert "A COUNT OF SENSORS describes how a space is instrumented" in prompt
    assert 'data the user "provided"' in prompt


def test_the_prompt_carries_no_building_literal(prompt):
    import re

    body = prompt[prompt.index("=== IMPORTANT ===") :]
    assert not re.search(r"\bbldg\d", body)
    assert "Abacws" not in body
