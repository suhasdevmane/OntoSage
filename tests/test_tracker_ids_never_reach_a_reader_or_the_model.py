# -*- coding: utf-8 -*-
"""A developer tracker id is never sent to the model and never shown to a reader.

Live, unscripted, 2026-09-18: "How busy is the building right now?" was answered, in full, with
``**BUG-606**``. The analytics narration prompt ended a rule "...and stop (BUG-606)"; the model
echoed the token as the answer. Prompts are built at ~35 call sites and cite the defect behind a
rule by habit, so the defence is at the two boundaries every string crosses.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from orchestrator.services import prompt_hygiene as ph

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent

# The answer as it reached the reader: the tag alone, then the footers a lane always appends.
LEAKED = (
    "**BUG-606**\n\n---\n**You might also ask:** Plot this data? | Check compliance against "
    "ASHRAE? | Compare with another zone?\n\n---\n*Sources: `Building model` "
    "`Occupancy Sensing System` `Analytics Engine`*"
)


def test_the_leaked_answer_becomes_an_honest_fallback_footers_and_all():
    out = ph.scrub_answer(LEAKED)
    assert out == ph.EMPTY_FALLBACK
    assert "BUG" not in out and "You might also ask" not in out and "Sources" not in out


def test_a_real_answer_keeps_its_body_and_loses_only_the_id():
    text = "Floor 3 is the warmest at 24.3 °C (BUG-606).\n\n---\n*Sources: `Building model`*"
    out = ph.scrub_answer(text)
    assert "BUG-606" not in out
    assert "Floor 3 is the warmest at 24.3 °C." in out
    assert "Sources" in out, "footers survive when the body is a real answer"


@pytest.mark.parametrize(
    "text",
    [
        "stop (BUG-606)",
        "stop (BUG-606, CAVEAT-12)",
        "stop (see BUG-606)",
        "stop BUG-606: then continue",
        "stop (CAVEAT-604) and (TODO-012) here",
        "stop (KNOWN-008)",
        "stop (FIX-003)",
    ],
)
def test_every_citation_shape_is_removed(text):
    assert not ph.contains_tracker_id(ph.strip_tracker_ids(text)), text


def test_the_real_prompt_passages_that_caused_it_come_out_clean():
    """The two literal passages the live failure and its sibling were built from."""
    rule_9 = (
        "If the question asks about a property these figures do not carry, say which property they\n"
        "   do carry and stop (BUG-606)\n"
        "10. Is internally consistent"
    )
    rule_b = (
        "- Every recommendation must act on something named above (BUG-718)\n"
        "  unless a reference value is given above (BUG-606)\n"
    )
    for text in (rule_9, rule_b):
        out = ph.strip_tracker_ids(text)
        assert not ph.contains_tracker_id(out)
    assert "and stop" in ph.strip_tracker_ids(rule_9), "the instruction itself must survive"
    assert "10. Is internally consistent" in ph.strip_tracker_ids(rule_9)


def test_text_without_an_id_is_returned_unchanged_and_non_strings_pass_through():
    s = "Floor 3 has 12 rooms."
    assert ph.strip_tracker_ids(s) is s
    assert ph.strip_tracker_ids(None) is None
    assert ph.strip_tracker_ids(42) == 42
    assert ph.scrub_answer("") == ""


def test_no_building_record_id_is_mistaken_for_a_tracker_id():
    """Register ids a building holds must never be stripped from an answer."""
    ids = [
        "AEP-001", "REG-007", "CL-2026-006", "WS-06", "RTE-010", "ACT-0042-2", "CMP-ROOF",
        "WCP-008", "CF-01", "EV-003", "APR-032", "WO-015", "CHK-102", "AV-106-PRJ", "HO-BMS-COMM",
        "REP-7420E1", "RTE-015", "ACT-0043-2", "CL-2026-016",
    ]
    for record_id in ids:
        assert not ph.contains_tracker_id(record_id), record_id
        assert ph.strip_tracker_ids(f"See {record_id}.") == f"See {record_id}."


def test_no_id_the_shipped_ttl_carries_is_mistaken_for_a_tracker_id():
    """Walk the real data: every ID-shaped token a building's graph CARRIES must survive.

    Reads the parsed graph (literal values and IRI local names), not the file text. A first draft
    scanned text and failed on `# BUG-189 ...` — developer COMMENTS in the TTL, which are exactly
    what the tracker pattern is for and never reach a reader. A comment is not data.
    """
    import rdflib

    files = sorted(REPO.glob("input/bldg1_*.ttl")) + sorted(REPO.glob("bldg1/bldg1_*.ttl"))
    files = [f for f in files if f.stat().st_size < 2_000_000]  # the Brick/Protege dumps are not ids
    if not files:
        pytest.skip("no building TTL on disk")
    shape = re.compile(r"\b[A-Z]{2,6}-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
    seen = set()
    for f in files:
        g = rdflib.Graph()
        try:
            g.parse(str(f), format="turtle")
        except Exception:
            continue
        for s, _p, o in g:
            for term in (s, o):
                text = str(term).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                seen.update(shape.findall(text))
    assert len(seen) > 50, f"expected a real spread of ids, found {len(seen)}"
    clashes = sorted(t for t in seen if ph.contains_tracker_id(t))
    assert not clashes, f"a record id looks like a tracker id: {clashes[:10]}"


def test_polish_answer_scrubs_every_reader_facing_answer():
    from orchestrator.services.answer_wording import polish_answer

    assert polish_answer(LEAKED, "How busy is the building right now?", "analytics") == (
        ph.EMPTY_FALLBACK
    )
    assert "BUG-12" not in polish_answer("Floor 2 is fine (BUG-12).", "Is floor 2 fine?", "compare")


def test_all_three_model_entry_points_strip_before_anything_else():
    from orchestrator.llm_manager import LLMManager

    for name in ("generate", "generate_structured", "astream_generate"):
        src = inspect.getsource(getattr(LLMManager, name))
        code = src.split('"""', 2)[-1]  # skip the docstring
        assert "strip_tracker_ids(prompt)" in code, name
        first_use = code.index("strip_tracker_ids(prompt)")
        for later in ("_pick_client", "_breaker", "_structured_provider_kwargs"):
            if later in code:
                assert first_use < code.index(later), f"{name}: strip must precede {later}"


def test_the_narration_rule_no_longer_forbids_a_counting_sensors_own_reading():
    """The root cause under the leak. The rule said "a count of anything is not a measurement of
    it", so 15,000 genuine readings from 250 *Occupancy Count* sensors were, to the model,
    forbidden — and it obeyed "...and stop (BUG-606)" by printing the tag. A sensor count is not
    occupancy; a counting sensor's reading is."""
    src = (REPO / "orchestrator" / "agents" / "analytics_agent.py").read_text(encoding="utf-8")
    assert "a count of anything is not a measurement" not in src
    assert "IS a measurement of that count" in src
    assert "NUMBER OF SENSORS" in src, "the intent of the rule (a sensor tally is not a reading)"
