# -*- coding: utf-8 -*-
"""A readiness report that cannot reach the stores must not describe an empty building (W3-1).

`check_onboarding.py` answers the question a half-connected building most needs answered:
which capabilities are unlocked, and for the locked ones, exactly which artefact is
missing. It is a good report. It had one way to be badly wrong.

Adapter initialisation was wrapped in `except Exception: pass`, on the reasoning that the
registry is already initialised inside the app process. True there. On the HOST — where
`database_registry.yaml` carries container-internal hostnames — initialisation fails,
every time-series lookup returns nothing, and the report was emitted anyway.

MEASURED on a healthy bldg1, the same minute, two environments:

    from the host        history: 0.0 days · events rows: 0      · adjacency: 0   · 4/11
    inside the container history: 8.0 days · events rows: 98,139 · adjacency: 270 · 10/11

The first was printed, written to `scripts/outputs/`, and exited 0. It reads as
authoritative. Anyone acting on it would open defects against a building that answers
those questions perfectly well — and would be told that predict, detect, bookings,
workorders, access counts and wayfinding were all locked for want of data that is
demonstrably present.

`certify_building.py` already states the principle this needed:

    A run that cannot be trusted is better not started than explained away afterwards.

So the report now refuses, names why, and says where to run it. The same check catches the
quieter route to the same blindness — initialisation that raises nothing and registers no
adapters at all.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path("scripts/check_onboarding.py")


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_a_failed_adapter_init_is_not_swallowed():
    src = _source()
    assert "except Exception:  # already initialised inside the app process" not in src, (
        "the bare pass is back, so a report built with no stores reachable is emitted as "
        "if the building were empty"
    )
    assert "adapters_ok = False" in src


def test_registering_no_adapters_counts_as_failure_too():
    """Initialisation can succeed and register nothing — the same blindness, quieter."""
    src = _source()
    assert "is_available" in src, (
        "only an exception is treated as failure, so an init that quietly registers zero "
        "adapters still produces a table of zeros"
    )


def test_it_refuses_rather_than_reporting():
    src = _source()
    refuse = src.index("REFUSING TO REPORT")
    gather = src.index("gather_facts(")
    assert (
        refuse < gather
    ), "facts are gathered before the trust check, so the report is built anyway"
    assert "return 2" in src


def test_the_refusal_says_where_to_run_it():
    """A refusal that does not say what to do instead just moves the confusion."""
    src = _source()
    assert "docker exec ontosage-orchestrator" in src


def test_the_refusal_quantifies_what_it_would_have_got_wrong():
    """'Could be inaccurate' is ignorable; '4/11 instead of 10/11' is not."""
    src = _source()
    assert "4/11" in src and "10/11" in src


def test_the_docstring_no_longer_recommends_the_host():
    """It used to say 'or on the host with the stack up', which is how this happened."""
    doc = _source().split('"""')[1]
    assert "or on the host with the stack up" not in doc
    assert "refuses" in doc.lower()


def test_it_still_exits_zero_on_a_real_report():
    """This is a REPORT, not a gate: a locked capability must never fail the run."""
    src = _source()
    doc = src.split('"""')[1]
    assert "not a gate" in doc
    # The only non-zero path is the unmeasurable one.
    import re

    returns = set(re.findall(r"^\s+return (\d+)$", src, re.M))
    assert returns <= {"0", "2"}, f"unexpected exit codes: {sorted(returns)}"
