# -*- coding: utf-8 -*-
"""The OCBV vocabulary was unreachable from the SPARQL lane (2026-08-26).

Two independent defects, each silent, which together meant a concept could name a class
Brick does not have and that class could never be used:

1. **The agent declared no ``ontosage:`` or ``hbco:`` prefix.** Every query it generated
   referencing an OCBV term was a SPARQL syntax error, so the whole conversational
   vocabulary — amenities, knowledge topics, lifts, AV, network services, asset status,
   service schedules — was unusable from the query lane.

2. **The concept resolver returned non-Brick classes as bare full IRIs.**
   ``_brick_local`` shortened only ``brickschema.org`` IRIs and passed everything else
   through untouched, so an OCBV class arrived as
   ``http://ontosage.org/capabilities#Parking_Occupancy_Sensor``. The caller's
   most-specific-class check looks for a CURIE prefix and could never match it, and a
   bare IRI embedded in generated SPARQL is a syntax error anyway — an IRI needs angle
   brackets where a CURIE does not.

The visible symptom: "how many parking spaces are free?" answered **294** — the
building's space count, produced by a COUNT over a 40-instance generic class — while one
parking sensor with 5,268 rows sat behind the specific class. A real number, from a real
query, to a different question, which is why the numeric guard had no reason to object.
"""

import pytest

pytestmark = pytest.mark.unit


# ── the agent must be able to name OCBV terms at all ─────────────────────────
@pytest.mark.parametrize("prefix", ["brick:", "rdfs:", "ref:", "ontosage:", "hbco:"])
def test_the_query_prefix_block_declares_the_vocabulary(prefix):
    from orchestrator.agents.sparql_agent import EXTENDED_PREFIXES

    block = "\n".join(EXTENDED_PREFIXES)
    assert f"PREFIX {prefix}" in block, f"{prefix} is not declared — any query using it is a syntax error"


# ── concept classes must come back as CURIEs, whatever the vocabulary ────────
@pytest.mark.parametrize(
    "iri,expected",
    [
        ("https://brickschema.org/schema/Brick#Occupancy_Count_Sensor", "brick:Occupancy_Count_Sensor"),
        ("http://ontosage.org/capabilities#Parking_Occupancy_Sensor", "ontosage:Parking_Occupancy_Sensor"),
        ("http://ontosage.org/hbco#Something", "hbco:Something"),
    ],
)
def test_class_iris_are_shortened_to_curies(iri, expected):
    from orchestrator.services.concept_resolver import _brick_local

    assert _brick_local(iri) == expected


def test_an_unknown_vocabulary_is_passed_through_untouched():
    """Better a recognisable full IRI than a wrong prefix invented for it."""
    from orchestrator.services.concept_resolver import _brick_local

    other = "http://example.org/Other#X"
    assert _brick_local(other) == other


# ── a concept naming a class AND its parent must resolve to the child ───────
@pytest.mark.parametrize(
    "candidates",
    [
        ["ontosage:Parking_Occupancy_Sensor", "brick:Occupancy_Count_Sensor"],
        ["brick:Occupancy_Count_Sensor", "ontosage:Parking_Occupancy_Sensor"],
    ],
)
def test_the_extension_class_wins_in_either_order(candidates):
    """brick_classes is a SET, so the order the store returns is arbitrary. Picking the
    first meant the PARENT won roughly half the time — and the parent matched 40
    instances where the child matches one."""
    from orchestrator.agents.sparql_agent import SPARQLAgent

    assert SPARQLAgent._most_specific_class(candidates) == "ontosage:Parking_Occupancy_Sensor"


def test_two_brick_classes_keep_the_declared_order():
    """With no extension class present there is nothing to prefer, and the concept's own
    ordering is as good a choice as any."""
    from orchestrator.agents.sparql_agent import SPARQLAgent

    pair = ["brick:Temperature_Sensor", "brick:Zone_Air_Temperature_Sensor"]
    assert SPARQLAgent._most_specific_class(pair) == "brick:Temperature_Sensor"


@pytest.mark.parametrize("candidates,expected", [(["brick:X"], "brick:X"), ([], "")])
def test_degenerate_inputs(candidates, expected):
    from orchestrator.agents.sparql_agent import SPARQLAgent

    assert SPARQLAgent._most_specific_class(candidates) == expected


def test_specificity_needs_no_network():
    """The first version asked the graph and ALWAYS fell back: _execute_query raised
    '[Errno -2] Name or service not known' from its Fuseki fallback, the except swallowed
    it at DEBUG level, and the function silently returned candidates[0] — so a fix that
    had never once run appeared to work whenever the right answer happened to be first.
    A pure function cannot fail that way."""
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    fn = SPARQLAgent._most_specific_class
    # The property that matters: it cannot await, so it cannot fail on a network call.
    assert not inspect.iscoroutinefunction(fn)

    # And judge the CODE, not the docstring — which names _execute_query on purpose.
    code = "\n".join(
        line
        for line in inspect.getsource(fn).split("\n")
        if not line.lstrip().startswith("#")
    )
    body = code.split('"""')[-1]  # everything after the docstring
    assert "await" not in body
    assert "_execute_query" not in body
