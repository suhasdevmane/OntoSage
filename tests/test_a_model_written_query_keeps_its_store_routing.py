# -*- coding: utf-8 -*-
"""A sensor's store is found whichever name the query bound it to.

Live, unscripted, 2026-09-18: "How many people are in the building at the moment?" found 250
occupancy sensors and answered "no readings from any of them are available to me"; every one was
logged `(Storage: N/A)`. The SPARQL prompt instructs the model to write `ref:storedAt ?database`;
the map that routes each UUID to its store recognised only a variable containing "storage".
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.workflow import _orchestrator as orch

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name", ["storage", "Storage", "sensorStorage", "storage_location", "database", "DATABASE"])
def test_the_names_a_store_arrives_under_are_recognised(name):
    assert orch._is_storage_variable(name), name


@pytest.mark.parametrize("name", ["sensor", "uuid", "timeseriesID", "label", "unit", "type", "databaseName", "", None])
def test_other_variables_are_never_mistaken_for_a_store(name):
    assert not orch._is_storage_variable(name), name


def test_the_prompt_and_the_map_agree_on_the_name():
    """The prompt teaches the model `?database`; the map must read what the prompt teaches."""
    from orchestrator.agents import sparql_agent

    assert "ref:storedAt ?database" in inspect.getsource(sparql_agent)
    assert orch._is_storage_variable("database")


def test_the_extraction_uses_the_helper():
    src = inspect.getsource(orch.WorkflowOrchestrator)
    assert "_is_storage_variable(var)" in src
    assert '"storage" in var.lower()' not in src, "the old inline test must not come back"
