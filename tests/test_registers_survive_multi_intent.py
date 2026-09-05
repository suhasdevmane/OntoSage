# -*- coding: utf-8 -*-
"""A correct routing decision must survive the stage after it (BUG-425).

`dialogue_agent` resolves a question naming a record class the building HOLDS straight to
`metadata`, skipping the LLM intent call entirely — V7-T21 added that precisely so lifting a
register would change what the system can answer. Multi-intent decomposition then ran on the
result and discarded it.

Measured live on bldg1:

    Q: "Who is my contact for a fault with the network, and what is their response target?"
    [ttl-route]     metadata via held record class: Department (20 instances)
    [multi-intent]  Decomposed into 2 sub-intents: ['capability', 'capability']

The department register holds the contact route AND the response target in one row. Both
clauses were instead answered from prose, and the answer named the wrong contacts.

**A compound question is the case where a register is most useful**, not least: one SPARQL
returns every column at once, while two capability probes return two partial prose answers
that then have to be stitched together. So the guard is not "decompose more carefully" — it
is "do not decompose what a register already answers".

This is the fourth defect in this project of the same shape: something built, correct and
tested, whose result a later stage quietly overwrote.
"""

import inspect
import re

import pytest

pytestmark = pytest.mark.unit


def _dialogue_block() -> str:
    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    start = src.find("# ── Multi-intent decomposition")
    assert start > 0, "the multi-intent block has moved or gone"
    return src[start : start + 3500]


def test_the_register_check_runs_before_decomposition():
    block = _dialogue_block()
    check_at = block.find("held_record_class")
    detect_at = block.find("MultiIntentDetector")
    assert check_at > 0, "nothing checks for a held record class before decomposing"
    assert detect_at > 0, "the detector import has moved"
    assert check_at < detect_at, (
        "the record check must run BEFORE the detector is constructed, or the routing "
        "decision it protects has already been thrown away"
    )


def test_decomposition_is_gated_on_the_register_check():
    """The flag must actually gate the branch, not merely be computed and logged."""
    block = _dialogue_block()
    assert "_register_answerable" in block
    gate = re.search(r"and not _register_answerable", block)
    assert gate, (
        "_register_answerable is computed but does not gate the decomposition branch — "
        "which is the same defect with an extra log line"
    )


def test_the_check_cannot_block_routing_when_the_graph_is_unavailable():
    """A record-registry failure must degrade to the old behaviour, never to an error.

    Routing runs on every single turn. A graph hiccup here would take the whole pipeline
    down rather than lose one optimisation.
    """
    block = _dialogue_block()
    seg = block[block.find("held_record_class") : block.find("MultiIntentDetector")]
    assert "except Exception" in seg, "the record check is not wrapped"
    assert "_register_answerable = False" in block, (
        "the flag must default to False so a failed check falls back to decomposing, "
        "which is the previous behaviour"
    )


def test_the_skip_set_still_excludes_the_conversational_intents():
    """The pre-existing guard must survive this change."""
    block = _dialogue_block()
    for intent in ("clarification", "greeting", "unknown"):
        assert f'"{intent}"' in block, f"{intent} is no longer skipped"
