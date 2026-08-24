# -*- coding: utf-8 -*-
"""Meter boundary, allocation method, and the refusal of per-person attribution (V6-T27).

Master Package E: a consumption figure is meaningless without its **boundary**. "Floor 2 used
5.46 kWh" is four different claims wearing one number — a directly-metered floor, a share of a
building total apportioned by area, a single riser, or a circuit that merely sits on that floor.
The digits are identical in all four cases.

Measured before this turn, on the live system:

* every energy answer stated a figure and **no boundary at all**;
* *"How much energy did I use this month?"* was answered **"22.06 kWh"** by summing six floor
  meters — an attribution no meter in the building can support;
* *"Which employee uses the most electricity?"* answered **"Energy Meter Floor4"**, silently
  substituting a meter for a person.

The property that carries the most weight here is the one that is easiest to lose:
**placement is not boundary.** `brick:hasLocation` and `brick:isPartOf` say where a meter SITS.
This building asserts `Building_Water_Meter brick:isPartOf Floor0` — a whole-site water meter
installed on the ground floor. Read as a boundary, the site's water total would be published as
floor 0's.
"""

import pytest

from orchestrator.services.evidence.meter_boundary import (
    ALLOCATION_METHODS,
    ESTIMATED_METHODS,
    MeterBoundary,
    boundary_query,
    from_rows,
    match,
    method_phrase,
    statement,
)

pytestmark = pytest.mark.unit


def _b(name, serves="Floor 2", method="direct", source="declared", uuid=""):
    return MeterBoundary(
        meter_iri=f"http://x#{name}",
        serves_iri="http://x#Floor2",
        serves_label=serves,
        method=method,
        source=source,
        uuid=uuid,
    )


# ── the statement is never absent ────────────────────────────────────────────


def test_an_energy_figure_always_gets_a_boundary_line():
    """An empty statement is the state this module exists to end: a number with no scope."""
    assert statement([]).strip()
    assert "not declared" in statement([])


def test_a_declared_boundary_states_what_it_covers_and_how():
    text = statement([_b("Energy_Meter_Floor2")])
    assert "Energy_Meter_Floor2" in text
    assert "Floor 2" in text
    assert "measured directly" in text


def test_an_undeclared_meter_says_so_instead_of_guessing():
    b = MeterBoundary(meter_iri="http://x#Meter_X")
    text = statement([b])
    assert "not declared" in text
    assert "Meter_X" in text, "the answer should still name the meter it could not describe"


# ── placement is not boundary ────────────────────────────────────────────────


def test_a_boundary_inferred_from_placement_is_labelled_as_such():
    """The single most important sentence in this turn.

    A whole-site water meter bolted to the ground floor is `isPartOf Floor0`. Presenting that
    as its metering scope publishes the site's water as floor 0's — a confident wrong answer
    with a real number attached.
    """
    text = statement([_b("Energy_Meter_Floor2", source="placement", method="")])
    assert "inferred from where the meter sits" in text
    assert "not a declared metering boundary" in text
    assert (
        "estimate" in text
    ), "a sub-figure from an unconfirmed boundary must be called an estimate"


def test_a_declared_boundary_is_not_hedged():
    """The hedge must apply ONLY to proposals. Hedging a declared boundary would train readers
    to ignore the qualifier where it matters."""
    text = statement([_b("Building_Water_Meter", serves="Abacws Building", source="brick_class")])
    assert "inferred from where the meter sits" not in text
    assert "measured directly" in text


@pytest.mark.parametrize("source", ["declared", "brick_class"])
def test_authoritative_sources(source):
    assert _b("M", source=source).authoritative


@pytest.mark.parametrize("source", ["placement", "label", "", "guessed"])
def test_non_authoritative_sources(source):
    assert not _b("M", source=source).authoritative


# ── allocation method ────────────────────────────────────────────────────────


def test_only_direct_and_submetered_are_measurements():
    """Every other method yields an ESTIMATE, and the split is data so a new method cannot be
    added without deciding which side it falls on."""
    assert "direct" not in ESTIMATED_METHODS
    assert "sub_metered" not in ESTIMATED_METHODS
    assert "apportioned_by_area" in ESTIMATED_METHODS
    assert ESTIMATED_METHODS <= set(ALLOCATION_METHODS)


def test_every_estimated_method_says_estimated_in_its_prose():
    for key in ESTIMATED_METHODS:
        assert (
            "estimated" in ALLOCATION_METHODS[key].lower()
        ), f"{key} reads as a measurement; a reader cannot tell it is an estimate"


def test_an_unknown_method_is_treated_as_an_estimate_not_as_direct():
    """A building declaring something this version has never heard of must not have its
    estimate presented as a reading."""
    text = method_phrase("apportioned_by_headcount_v2")
    assert "does not recognise" in text and "estimate" in text


def test_a_missing_method_makes_the_statement_warn():
    text = statement([_b("Energy_Meter_Floor2", method="", source="declared")])
    assert "allocation method not declared" in text
    assert "estimate" in text


# ── summing several meters ───────────────────────────────────────────────────


def test_a_summed_total_says_it_is_a_sum_of_boundaries():
    """A building total assembled from floor meters is not a whole-site reading, and the
    difference matters: the sum misses anything no floor meter covers."""
    text = statement([_b("Energy_Meter_Floor1"), _b("Energy_Meter_Floor2")])
    assert "summed across 2 meters" in text
    assert "not a separate whole-site reading" in text


def test_a_sum_that_includes_an_estimate_says_so():
    text = statement([_b("M1"), _b("M2", method="apportioned_by_area")])
    assert "estimated share" in text


# ── matching a figure to its meters ──────────────────────────────────────────


def test_uuid_matching_wins_over_name_matching():
    """The uuid is what the reading was actually fetched with; a name in the prose is a weaker
    signal and must not override it."""
    bs = {"A": _b("A", uuid="u1"), "B": _b("B", uuid="u2")}
    hits = match(bs, ["u2"], ["A"])
    assert [h.meter_name for h in hits] == ["B"]


def test_name_matching_is_exact_not_substring():
    """Substring matching would attach Floor1's boundary to a figure about Floor10."""
    bs = {
        "Energy_Meter_Floor1": _b("Energy_Meter_Floor1"),
        "Energy_Meter_Floor10": _b("Energy_Meter_Floor10"),
    }
    hits = match(bs, [], ["Energy_Meter_Floor10"])
    assert [h.meter_name for h in hits] == ["Energy_Meter_Floor10"]


def test_no_match_yields_the_undeclared_statement_rather_than_silence():
    assert "not declared" in statement(match({}, ["nope"], ["nope"]))


# ── the query and row parsing ────────────────────────────────────────────────


def test_the_query_covers_energy_points_not_only_meter_individuals():
    """In a retrofitted estate the readable thing is the POINT; the meter individual often
    carries no timeseries reference at all. A boundary reachable only from the Meter would be
    correct and never found — the present-but-invisible failure from V6-T26."""
    q = boundary_query("http://x#")
    assert "brick:Meter" in q and "brick:Energy_Sensor" in q


def test_the_query_asks_for_the_boundary_source():
    assert "ontosage:boundarySource" in boundary_query("http://x#")


def test_rows_parse_from_raw_sparql_json():
    payload = {
        "results": {
            "bindings": [
                {
                    "meter": {"value": "http://x#Energy_Meter_Floor2"},
                    "serves": {"value": "http://x#Floor2"},
                    "method": {"value": "direct"},
                    "source": {"value": "declared"},
                }
            ]
        }
    }
    got = from_rows(payload)
    assert "Energy_Meter_Floor2" in got
    assert got["Energy_Meter_Floor2"].source == "declared"


def test_a_declared_row_is_not_displaced_by_an_undeclared_duplicate():
    """Reasoning returns a meter once per matched superclass. If the bare duplicate won, a
    declared boundary would vanish behind its own class hierarchy."""
    rows = {
        "ok": True,
        "rows": [
            {"meter": "http://x#M", "serves": "http://x#Floor2", "source": "declared"},
            {"meter": "http://x#M"},
        ],
    }
    got = from_rows(rows)
    assert got["M"].declared, "the undeclared duplicate displaced the declared row"


# ── per-person attribution is refused ────────────────────────────────────────


class TestAttributionRefusal:
    """A meter measures a boundary, never a person. Both of these were ANSWERED with figures
    before this class existed."""

    @pytest.mark.parametrize(
        "q",
        [
            "How much energy did I use this month?",
            "Which employee uses the most electricity?",
            "my electricity usage",
            "What is my manager's energy use?",
            "Break down energy by employee",
            "Bill each tenant for their electricity",
        ],
    )
    def test_attribution_questions_are_classified_for_refusal(self, q):
        from orchestrator.services.privacy.inference_classes import classify_inference

        assert classify_inference(q) == "individual_attribution", f"{q!r} would be answered"

    @pytest.mark.parametrize(
        "q",
        [
            "What is our energy use per capita?",
            "average energy per person across the building",
        ],
    )
    def test_per_capita_is_an_aggregate_and_stays_answerable(self, q):
        """A total divided by a headcount identifies nobody. Refusing it would deny a standard
        sustainability metric while protecting no one — the cost of a lazy pattern."""
        from orchestrator.services.privacy.inference_classes import classify_inference

        assert classify_inference(q) is None, f"{q!r} was refused; it identifies no individual"

    @pytest.mark.parametrize(
        "q",
        [
            "How much energy did the building use last week?",
            "What was the energy consumption on floor 2 yesterday?",
            "Which floor uses the most electricity?",
        ],
    )
    def test_boundary_scoped_questions_are_never_refused(self, q):
        from orchestrator.services.privacy.inference_classes import classify_inference

        assert classify_inference(q) is None

    def test_the_refusal_explains_what_a_meter_can_measure(self):
        """A refusal that only says no teaches nothing. This one says why the number cannot
        exist and names the questions that can be answered instead."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert 'cls == "individual_attribution"' in src
        block = src[src.index('cls == "individual_attribution"') :][:1400]
        assert "boundary" in block
        assert "per-capita" in block, "the refusal does not offer the aggregate alternative"


# ── routing ──────────────────────────────────────────────────────────────────


class TestConsumptionRouting:
    """An energy question answered from a document never reaches a lane that can state a
    figure — so it can state no boundary either. Sixth member of BUG-231's family."""

    @pytest.mark.parametrize(
        "q",
        [
            "How much energy did the building use last week?",
            "How much electricity does the lab on floor 5 use?",
            "What was the energy consumption on floor 2 yesterday?",
            "total water usage this month",
        ],
    )
    def test_consumption_questions_are_recognised(self, q):
        from orchestrator.services.routing_contract import consumption_question

        assert consumption_question(q), f"{q!r} will be answered from a document"

    @pytest.mark.parametrize(
        "q",
        [
            "How many energy meters are there?",
            "how many sensors are there?",
            "what is the temperature in 5.01?",
            "show me floor 3",
        ],
    )
    def test_inventory_and_unrelated_questions_are_not_claimed(self, q):
        from orchestrator.services.routing_contract import consumption_question

        assert not consumption_question(q)

    def test_the_capability_probe_bypasses_consumption_questions(self):
        from pathlib import Path

        src = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
        assert "consumption_question as _consumption_question" in src
        assert "not _consumption_question(user_query)" in src

    def test_an_attribution_question_is_refused_rather_than_routed_to_analytics(self):
        """Order matters: the privacy rule must win. Routing "how much energy did I use" to
        analytics is exactly how it got answered with 22.06 kWh."""
        from orchestrator.services.routing_contract import apply_contract

        st = {"intent": "capability", "concepts": [], "entities": []}
        apply_contract("How much energy did I use this month?", st, stage="parse")
        assert st["intent"] != "analytics", "the attribution question reached the data lane"


# ── the boundary reaches the answer ──────────────────────────────────────────


def test_the_boundary_is_appended_after_persona_formatting():
    """Appended BEFORE the formatter, the line was paraphrased away by it. A factual caveat an
    LLM may reword is a caveat that can vanish."""
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    fmt = src.index("Persona formatting (first pass)")
    boundary = src.index("_boundary_line = await self._meter_boundary_line")
    assert boundary > fmt, (
        "the boundary line is appended before persona formatting again; the formatter will "
        "rewrite it out of the answer"
    )


def test_the_boundary_also_rides_in_the_payload_for_the_numeric_guard():
    """ "Floor 2" puts a "2" in the prose. The numeric guard checks every number against the
    payload's fields, and an unbacked one suppresses the whole answer (V6-T26)."""
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    block = src[src.index("_boundary_line = await self._meter_boundary_line") :][:900]
    assert '_payload["meter_boundary"] = _boundary_line' in block


def test_the_boundary_never_costs_the_answer():
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    block = src[src.index("_boundary_line = await self._meter_boundary_line") :][:900]
    assert "except Exception" in block


def test_an_answer_with_no_figure_gets_no_boundary_line():
    """A boundary describes a FIGURE. Measured live: the per-person refusal picked up a
    "Boundary: not declared" line, which reads as though a number had been withheld rather than
    being impossible to produce — the opposite of what the refusal says."""
    from pathlib import Path

    src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    body = src[src.index("async def _meter_boundary_line") :][:2200]
    assert '"privacy_refusal"' in body, "a refusal can still collect a boundary line"
    assert 'search(r"\d", answer' in body, "an answer with no number can still collect one"
