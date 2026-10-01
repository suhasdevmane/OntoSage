# -*- coding: utf-8 -*-
"""Why a false decline NAMES the register that holds the answer (BUG-947 / BUG-948).

Hand-reading the held-out tail M on 2026-09-29 found seven false denials in 62 answers
(11.3%), and the tell was that FOUR OF THE SEVEN named the right register in the same
sentence as the refusal. This file pins the mechanism that was found for that, because it is
not the one the parent row assumed: the two halves of that sentence are decided by DIFFERENT
matchers.

* The decline's pointer compares ``grounding_guard.content_terms``, which SINGULARISES.
  ``content_terms("escalation routes") == content_terms("escalation route") ==
  {"escalation", "rout"}``, so the pointer matches the Department register.
* The register selector matches a declared lay term with ``\\b<term>\\b``, which a trailing
  "s" ends. Measured inside the container against the live registry: "what is the escalation
  route" ranked Department at 32.0 and "what are the escalation routes" ranked NOTHING.

So the wording was never accidentally accurate. The decline is composed with the more capable
matcher, which is why it can print the answer's location in the act of refusing.

The fix that was NOT taken, and why it must not be taken later without re-measuring: automatic
plural tolerance on declared lay terms was implemented and measured on the 2,960-question
catalogue, where it moved 79 questions (65 previously-declining questions gained a register,
14 changed) and broke one guard by name. Read, the gains were roughly 30 right against 25
wrong, because the same tolerance that recovers a specific phrase ("escalation route")
captures a generic one — "barriers", "events", "displays" and "eligible alternatives" all read
as ordinary English in the plural. Restricting it to multi-word terms cut the movement to 21
(11 right, 2 partial, 5 wrong) and the guard still failed. See BUG-948.
"""

from types import SimpleNamespace

import pytest

from orchestrator.services.fallback_wording import (
    compose_boundary_pointer,
    pointer_only_registers,
)
from orchestrator.services.grounding_guard import content_terms

pytestmark = pytest.mark.unit


def _register(local_name: str, label: str, instances: int, terms):
    """A held record class, shaped as record_registry hands one over."""
    return SimpleNamespace(
        local_name=local_name,
        label=label,
        instances=instances,
        terms=tuple(terms),
        qualifiers=(),
    )


DEPARTMENT = _register("Department", "Department", 20, ("department", "escalation route"))
PERMIT = _register("Permit", "Permit", 15, ("permit", "permit to work"))

PLURAL = (
    "Are emergency contacts, duty managers and escalation routes current, reachable and "
    "authorised for tonight?"
)
SINGULAR = "What is the escalation route?"


def test_the_two_matchers_disagree_on_a_plural_and_that_is_the_defect():
    """The one-character difference, stated at both matchers."""
    assert content_terms("escalation routes") == content_terms("escalation route")

    from orchestrator.services.record_registry import rank_record_classes

    assert [r.local_name for _s, r in rank_record_classes(SINGULAR, [DEPARTMENT])] == ["Department"]
    assert rank_record_classes(PLURAL, [DEPARTMENT]) == []
    # ...while the decline's pointer reaches it for BOTH wordings.
    for question in (SINGULAR, PLURAL):
        assert "Department" in compose_boundary_pointer("X", question, [DEPARTMENT])


def test_the_gap_is_reported_for_the_plural_and_not_for_the_singular():
    assert pointer_only_registers(PLURAL, [DEPARTMENT]) == ["Department"]
    assert pointer_only_registers(SINGULAR, [DEPARTMENT]) == []


def test_a_register_the_question_does_not_name_is_not_reported():
    """The counter must not become a list of every register the building holds."""
    assert pointer_only_registers("how warm is room 5.04?", [DEPARTMENT, PERMIT]) == []


def test_only_the_registers_the_decline_PRINTS_are_counted():
    """Measured first the other way and rejected: tail M #28 produced fifteen names.

    A long question shares a content term with nearly every register, so counting everything
    the fuzzy matcher touches is a dump. The counter reports the same top-N the pointer
    sentence prints, and nothing beyond it.
    """
    held = [_register(f"Reg{i}", f"Register {i}", 5, (f"term{i}", "service")) for i in range(8)]
    question = "are the approved power, network and ventilation services currently available?"
    named = pointer_only_registers(question, held)
    printed = compose_boundary_pointer("X", question, held)
    assert 0 < len(named) <= 3
    for local in named:
        label = f"Register {local[len('Reg'):]}"
        assert label in printed, (label, printed)


def test_a_name_is_a_disagreement_and_not_evidence_the_register_holds_the_answer():
    """The limit of the counter, pinned so the log line is not read as a verdict (BUG-1073).

    Measured over all 2,960 catalogue questions against the live-shaped held-class snapshot:
    the selector is silent on 1,746 of them and the pointer still names registers on 1,742
    (99.8%), three of them in 1,684 cases. That is structural, not incidental, and this test
    reproduces the structure in memory: ``_near_records`` admits a register on ONE shared
    crude stem, so registers that share nothing but an ordinary English word all clear the
    bar, and ``nearest_holdings`` then returns its top-3 whether or not anything is near.

    So a name here means the two matchers DISAGREED. It is a place to look. It is not on its
    own evidence that the register holds the answer, and BUG-947's tell ("four of seven
    declines named the right register") must be read against a mechanism that names three
    registers on nearly every decline.
    """
    from orchestrator.services.record_registry import rank_record_classes

    # Eight registers whose only common vocabulary is the word every one of them uses.
    held = [_register(f"Reg{i}", f"Register {i}", 5, (f"term{i}", "record")) for i in range(8)]
    question = "what records are kept about the ventilation plant's commissioning?"

    # The selector reaches none of them: no declared term of any register is in the question.
    assert rank_record_classes(question, held) == []
    # The pointer names three all the same, on the bare stem "record".
    named = pointer_only_registers(question, held)
    assert len(named) == 3, named
    # ...and not one of the eight is a register about commissioning, which is the point.
    printed = compose_boundary_pointer("X", question, held)
    assert "which I can read for you" in printed


def test_the_counter_never_raises_into_a_decline():
    """A malformed record must cost a diagnostic, never the decline it sits inside."""
    assert pointer_only_registers(PLURAL, [object()]) == []
    assert pointer_only_registers("", [DEPARTMENT]) == []


def test_the_capability_lane_logs_the_gap_without_changing_the_wording(caplog):
    from orchestrator.agents import capability_agent

    with caplog.at_level("INFO"):
        gap = capability_agent._log_selector_gap(PLURAL, [DEPARTMENT])
    assert gap == ["Department"]
    assert "REGISTER VOCABULARY GAP" in caplog.text


def test_the_declared_plurals_close_the_gap_for_the_measured_question():
    """The fix that WAS taken: the register declares the plural it wants (design contract #2).

    Read from the TBox rather than restated, so removing the term fails this test.
    """
    from pathlib import Path

    schema = (Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl").read_text(
        encoding="utf-8"
    )
    block = schema.split("ontosage:Department ontosage:layTerms")[-1].split(" .\n")[0]
    for term in ("escalation routes", "duty officers", "maintenance crew", "maintenance team"):
        assert f'"{term}"' in block, term


def test_the_decline_does_not_ask_for_a_record_it_has_just_named():
    """BUG-947's wording complaint, pinned where it was fixed."""
    from orchestrator.services.clarification import compose_abstract

    text = compose_abstract(
        "Example Building",
        "Which current departmental escalation routes are authorised and reachable tonight?",
        (),
        ("temperature",),
        [DEPARTMENT],
    )
    assert "The nearest things I can answer are" in text
    assert "and I will read them" in text
    assert "tell me which record" not in text
