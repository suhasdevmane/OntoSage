# -*- coding: utf-8 -*-
"""A workflow may not be given less time than one call inside it (BUG-473).

MEASURED 2026-09-07, live. Every `.env` in this repo carried `LLM_TIMEOUT_S=180` and no
`WORKFLOW_TIMEOUT_S`, so the workflow deadline sat at its 120s default. One legal LLM call
outlived the whole workflow containing it by sixty seconds, and `llm_manager` retries each
call on top of that.

The planner-driven report lane makes ~4 sequential calls, so it could never finish:

    2026-09-07 15:25:19  planner  Query: Give me a report on energy use last week.
    2026-09-07 15:27:11  ERROR    Workflow timed out after 120s
    2026-09-07 15:33:54  planner  Query: Give me a report on energy use yesterday.
    2026-09-07 15:35:23  ERROR    Workflow timed out after 120s
    2026-09-07 15:50:43  planner  Query: Give me a report on the CO2 in room 5.01 yesterday.
    2026-09-07 15:52:29  ERROR    Workflow timed out after 120s

Narrowing the question from a building-week to one sensor and one day changed nothing —
the cost is in the sequential calls, not the data. And the turn came back as a DEGRADED
answer, not an error naming the deadline, so the harness quarantined it and every reading
of the result blamed the LLM.

WHY NO TEST COULD HAVE CAUGHT IT
-------------------------------
The two numbers were invisible to each other. `WORKFLOW_TIMEOUT_S` is a Settings field;
`LLM_TIMEOUT_S` is read straight from `os.environ` in `orchestrator/llm_manager.py` and is
not a Settings field at all. Nothing in the codebase ever printed them side by side. The
incoherence lived entirely in the gap between two configuration mechanisms — which is
exactly where a reviewer reading either file alone would never look.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


def _settings(monkeypatch, **env):
    """A fresh Settings built under a controlled environment."""
    import shared.config as cfg

    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    importlib.reload(cfg)
    return cfg.Settings()


def test_the_default_outlasts_a_full_length_llm_call(monkeypatch):
    """The exact configuration that was live: LLM 180s, workflow unset."""
    s = _settings(monkeypatch, LLM_TIMEOUT_S=180, WORKFLOW_TIMEOUT_S=0)
    assert s.WORKFLOW_TIMEOUT_S > 180, (
        "a workflow allowed less time than one LLM call inside it cannot complete any "
        "lane that makes one; this is the BUG-473 configuration exactly"
    )


def test_the_default_leaves_room_for_a_multi_step_lane(monkeypatch):
    """One call's worth of headroom is not enough — the report lane makes about four.

    But four full-length calls is not the answer either: at LLM_TIMEOUT_S=180 that is a
    twelve-minute ceiling before a stuck request is reported, which is a worse deadline
    than the broken one it replaces. The bound is on a HANG, not a budget for the slow
    path — measured live, the report lane needs somewhat over 120s cold and 15s warm.
    """
    s = _settings(monkeypatch, LLM_TIMEOUT_S=180, WORKFLOW_TIMEOUT_S=0)
    assert s.WORKFLOW_TIMEOUT_S >= 2 * 180
    assert s.WORKFLOW_TIMEOUT_S <= 3 * 180, (
        "a ceiling this high stops being a deadline: a genuinely stuck request would be "
        "held for many minutes before anyone is told"
    )


def test_a_short_llm_deadline_does_not_shrink_the_workflow_below_the_old_floor(monkeypatch):
    """Deriving must not make a fast deployment WORSE than the 120s it used to get."""
    s = _settings(monkeypatch, LLM_TIMEOUT_S=10, WORKFLOW_TIMEOUT_S=0)
    assert s.WORKFLOW_TIMEOUT_S >= 120


def test_an_explicit_value_is_kept(monkeypatch):
    """This warns; it does not overrule.

    A deployment may genuinely want to shed slow requests, and silently extending a
    deadline someone chose is its own surprise.
    """
    s = _settings(monkeypatch, LLM_TIMEOUT_S=180, WORKFLOW_TIMEOUT_S=60)
    assert s.WORKFLOW_TIMEOUT_S == 60


def test_an_incoherent_explicit_value_is_reported(monkeypatch, caplog):
    """Kept, but never silently."""
    import logging

    with caplog.at_level(logging.WARNING, logger="shared.config"):
        _settings(monkeypatch, LLM_TIMEOUT_S=180, WORKFLOW_TIMEOUT_S=60)
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "WORKFLOW_TIMEOUT_S" in joined and "LLM_TIMEOUT_S" in joined, (
        "the warning must name BOTH numbers: the whole defect was that they were never "
        "printed side by side"
    )


def test_a_coherent_explicit_value_says_nothing(monkeypatch, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="shared.config"):
        s = _settings(monkeypatch, LLM_TIMEOUT_S=60, WORKFLOW_TIMEOUT_S=600)
    assert s.WORKFLOW_TIMEOUT_S == 600
    assert not [r for r in caplog.records if "WORKFLOW_TIMEOUT_S" in r.getMessage()]


def test_a_garbled_llm_deadline_does_not_break_boot(monkeypatch):
    """`LLM_TIMEOUT_S` is parsed from a raw env string, so it can be anything."""
    s = _settings(monkeypatch, LLM_TIMEOUT_S="not-a-number", WORKFLOW_TIMEOUT_S=0)
    assert s.WORKFLOW_TIMEOUT_S >= 120


def test_nothing_here_names_a_building():
    """The deadline is a property of the model and the lane, never of a building."""
    from pathlib import Path

    src = Path("shared/config.py").read_text(encoding="utf-8")
    block = src.split("_workflow_deadline_must_outlast_one_llm_call", 1)[1][:3000]
    for literal in ("bldg1", "bldg2", "bldg3", "abacws"):
        assert literal not in block.lower()
