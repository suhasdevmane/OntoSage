# -*- coding: utf-8 -*-
"""A planner step that cannot run must say so without naming the lane (BUG-1261).

MEASURED LIVE 2026-09-30. "Can you tell me which areas are currently overcrowded?" returned an
answer whose visible text began:

    ## What threshold defines an area as overcrowded?

    Unknown agent: deliberate

`deliberate` is a real, declared intent -- `intent_definitions.yaml` describes it as a
multi-constraint SPACE RECOMMENDATION, which is precisely what that question is -- but
`PlannerAgent`'s dispatch has no branch for it, so a legitimate plan step fell through to an
`else` that put a debug string in the `error` field. That field is rendered to the reader.

Two separable defects, and only the second is fixed:

  1. the planner can emit a step for a lane it cannot run  -- NOT fixed here, on purpose
  2. its failure text names the lane to the reader          -- fixed

Adding a `deliberate` branch would answer the question by ranking spaces on occupancy against
CAPACITY. Every capacity figure this building holds carries `ontosage:capacityBasis`
"estimated ... Not certified", and BUG-954 (P1, open) has the occupancy count itself wrong by
~190x. A confident "Room X is overcrowded" built on that is a safety-adjacent claim nobody
made, and it is INVISIBLE where the present failure is visible. BUG-1244 pins that decision
separately; this file pins only that the failure stays readable.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLANNER = Path(__file__).resolve().parent.parent / "orchestrator" / "agents" / "planner_agent.py"

#: Words that name an internal lane, node or agent. A reader has no use for any of them.
INTERNAL_NAMES = (
    "deliberate",
    "sparql",
    "sql",
    "analytics",
    "anomaly",
    "capability",
    "floor_plan",
    "spatial_query",
    "report_intake",
    "unknown agent",
    "agent type",
)


def _reader_facing_error_strings(src: str) -> list:
    """Every string literal assigned to an `error` key in a returned dict."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "error"):
                continue
            seg = ast.get_source_segment(src, value) or ""
            out.append(seg)
    return out


def test_a_planner_error_shown_to_a_reader_names_no_internal_lane():
    src = PLANNER.read_text(encoding="utf-8")
    offenders = []
    for seg in _reader_facing_error_strings(src):
        low = seg.lower()
        # `str(exc)` and similar carry whatever the exception said; this test is about
        # literals WE write, which are the ones we control.
        if not (low.startswith('"') or low.startswith("f\"") or low.startswith("'")):
            continue
        for name in INTERNAL_NAMES:
            if name in low:
                offenders.append(seg)
                break
    assert not offenders, (
        "these planner `error` values are rendered to the reader and name an internal lane; "
        f"put the detail in the log and a plain sentence here: {offenders}"
    )


def test_the_unrunnable_step_detail_is_kept_but_not_in_the_error():
    """The lane name is still needed — for the trace and the logs. It must survive SOMEWHERE,
    or this fix trades a leak for a blind spot (the failure mode of every guard in lessons
    #135). It travels under its own key instead."""
    src = PLANNER.read_text(encoding="utf-8")
    assert "unrunnable_agent" in src, (
        "the unrunnable lane name was removed entirely rather than moved off the reader's "
        "path; keep it for the trace"
    )
    assert re.search(r"logger\.warning\([^)]*Unknown agent type", src), (
        "the dispatch no longer logs which lane it could not run; that is the line a "
        "maintainer needs"
    )
