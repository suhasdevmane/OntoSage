# -*- coding: utf-8 -*-
"""The gate-deletion counter parses exactly the line `_response_node` writes (QA-trial plan 1.4).

The two are pinned against each other: if the log line's wording changes, the counter's regex
must change in the same commit, or the weekly count silently reads zero.
"""

import importlib.util
import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location(
        "count_gate_deletions", REPO / "scripts" / "count_gate_deletions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LOG = """2026-10-02 12:40:01,100 - orchestrator.workflow._orchestrator - INFO - [response] relevance gate replaced a sensor_data answer: OFF_TOPIC (rows_read=1000)
2026-10-02 12:41:01,100 - orchestrator.workflow._orchestrator - INFO - [response] relevance gate replaced a analytics answer: OFF_TOPIC
2026-10-03 09:00:00,000 - orchestrator.workflow._orchestrator - INFO - [response] relevance gate replaced a sensor_data answer: WRONG_QUANTITY
2026-10-03 09:00:01,000 - orchestrator.workflow._orchestrator - INFO - [response] something else entirely
"""


def test_counts_by_day_lane_and_verdict():
    by_day_lane, by_verdict, lines = _mod().tabulate(LOG)
    assert len(lines) == 3
    assert by_day_lane[("2026-10-02", "sensor_data")] == 1
    assert by_day_lane[("2026-10-02", "analytics")] == 1
    assert by_day_lane[("2026-10-03", "sensor_data")] == 1
    assert by_verdict == {"OFF_TOPIC": 2, "WRONG_QUANTITY": 1}


def test_the_regex_matches_the_line_the_orchestrator_writes():
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert "relevance gate replaced a {lane} answer: {verdict.label}" in src
