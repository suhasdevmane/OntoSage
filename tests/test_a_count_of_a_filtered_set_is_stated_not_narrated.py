# -*- coding: utf-8 -*-
"""BUG-955: an absence-selected result states its own count, and says what its rows are.

*"Are there any unacknowledged alarms?"* was asked three times on 2026-09-30 with
``resp_cache`` flushed between, and named **1, then 6, then 0** alarms. Six is exactly right:
``ontosage:acknowledgedAt`` is on 264 of 270 AlarmEvents, and two of the six that lack it are
HIGH priority — a circuit-breaker trip on Floor 3 and a frost-protection trip on an AHU.

**The fetch was never the problem.** The three runs produced three different queries — a
``!BOUND`` test over an ``OPTIONAL``, a ``FILTER NOT EXISTS``, and a ``COUNT`` over the same
filter — and each one returned the right answer. All the variance was in the narration, which
is why no routing work would have touched it (CAVEAT-891: the route is deterministic, the
answer is not).

Re-asked three more times after the wording work of the same day, the count had stabilised at
six and the defect had moved somewhere worse:

    "There are **six** active alarm events recorded in the building. None of the records
     include a field that indicates whether the alarm has been acknowledged, so we cannot say
     whether any of them have been addressed."

    "the building's records only tell us that **6 alarm events** are stored in the model"

Both sentences have the same mechanical cause. The query removed every record that CARRIES
``acknowledgedAt``, so the rows that come back necessarily lack it — the narrator sees a column
that is never populated and reports a gap, and sees a result-set size with no filter attached
and reports a population. Neither fact can be recovered from the rows; both are in the query.

So the filter is described in code, from the query's own text, and the count is stated in code
rather than derived: *a figure a narrator can get wrong is a figure it should not be deriving*
(BUG-937, BUG-936, BUG-950).
"""

import asyncio
import inspect

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


# The three queries the live system generated for ONE question, copied from the orchestrator
# log of 2026-09-30 09:04–09:05. They are here verbatim because the detector has to read what
# the generator writes, not what a fix author imagines it writes.
UNBOUND_RUN = """PREFIX ontosage: <http://ontosage.org/capabilities#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?alarm ?label WHERE {
  ?alarm a ontosage:AlarmEvent .
  OPTIONAL { ?alarm ontosage:acknowledgedAt ?ack . }
  FILTER (!BOUND(?ack)) .
  OPTIONAL { ?alarm rdfs:label ?label . }
}"""

NOT_EXISTS_RUN = """PREFIX ontosage: <http://ontosage.org/capabilities#>
SELECT ?r WHERE {
  ?r a ontosage:AlarmEvent .
  FILTER NOT EXISTS { ?r ontosage:acknowledgedAt ?t } .
}"""

COUNT_RUN = (
    "PREFIX ontosage: <http://ontosage.org/capabilities#> "
    "SELECT (COUNT(?r) AS ?count) WHERE { ?r a ontosage:AlarmEvent . "
    "FILTER NOT EXISTS { ?r ontosage:acknowledgedAt ?time } }"
)

PLAIN_LISTING = "SELECT ?s WHERE { ?s a brick:Temperature_Sensor } LIMIT 50"
PLAIN_OPTIONAL = "SELECT ?s ?l WHERE { ?s a brick:Room . OPTIONAL { ?s rdfs:label ?l } } LIMIT 50"


def _lit(value):
    return {"type": "literal", "value": value}


def _uri(value):
    return {"type": "uri", "value": value}


# ── what the query selected for ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("query", [UNBOUND_RUN, NOT_EXISTS_RUN, COUNT_RUN])
def test_all_three_shapes_the_generator_produced_are_recognised(query):
    """One question, three query shapes in one afternoon. One is not enough to read."""
    assert SPARQLAgent._absent_properties(query) == ["ontosage:acknowledgedAt"]


@pytest.mark.parametrize("query", [PLAIN_LISTING, PLAIN_OPTIONAL])
def test_an_ordinary_query_selects_no_absence_and_gains_nothing(query):
    """The change must be invisible to every query that did not filter on a missing property."""
    assert SPARQLAgent._absent_properties(query) == []
    assert SPARQLAgent._absence_selection_lead(query, 6) == ""
    assert SPARQLAgent._absence_selection_meaning(query, 6) == ""


def test_an_optional_that_is_merely_optional_is_not_an_absence():
    """`OPTIONAL { … ?l }` with no `!BOUND(?l)` asks for a label, not for rows without one."""
    assert "rdfs:label" not in SPARQLAgent._absent_properties(UNBOUND_RUN)


def test_a_class_exclusion_is_not_a_missing_property():
    query = (
        "SELECT ?s WHERE { ?s a brick:Room . FILTER NOT EXISTS { ?s a ontosage:Decommissioned } }"
    )
    assert SPARQLAgent._absent_properties(query) == []


# ── the count, stated by the code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("query", [UNBOUND_RUN, NOT_EXISTS_RUN])
def test_the_row_count_is_stated_deterministically(query):
    lead = SPARQLAgent._absence_selection_lead(query, 6)
    assert lead == "**6 alarm event records match this question.**"
    assert "6" in lead and "alarm event" in lead


def test_one_row_is_singular_in_both_the_noun_and_the_verb():
    """Caught by the corpus sweep: "1 alarm event record match this question" was ungrammatical."""
    lead = SPARQLAgent._absence_selection_lead(NOT_EXISTS_RUN, 1)
    assert lead == "**1 alarm event record matches this question.**"


def test_the_only_other_question_in_the_corpus_that_selects_an_absence_is_covered():
    """Swept over 16,847 saved turns: 12 select on a missing property, and this is the
    one that is not about alarms. Three properties at once, 21 rows — "is each asset linked
    to the correct parent, engineering system and served area?" — the same shape of question
    on a different register, where a narrator could as easily answer "all of them are"."""
    query = (
        "PREFIX ontosage: <http://ontosage.org/capabilities#> "
        "SELECT ?a WHERE { ?a a ontosage:AssetEngineeringProfile . "
        "FILTER NOT EXISTS { ?a ontosage:parentAsset ?p } "
        "FILTER NOT EXISTS { ?a ontosage:engineeringSystem ?e } "
        "FILTER NOT EXISTS { ?a ontosage:servesArea ?s } }"
    )
    assert SPARQLAgent._absent_properties(query) == [
        "ontosage:parentAsset",
        "ontosage:engineeringSystem",
        "ontosage:servesArea",
    ]
    assert (
        SPARQLAgent._absence_selection_lead(query, 21)
        == "**21 asset engineering profile records match this question.**"
    )
    note = SPARQLAgent._absence_selection_meaning(query, 21)
    assert "'parent asset', 'engineering system', 'serves area'" in note


def test_no_rows_means_no_lead():
    """An empty result is a different answer and this must not put a zero in front of it."""
    assert SPARQLAgent._absence_selection_lead(NOT_EXISTS_RUN, 0) == ""


def test_a_count_aggregate_gets_no_lead_because_its_one_row_is_the_six():
    """`len(bindings)` is 1 for `SELECT (COUNT(?r) AS ?count)`. Leading with 1 would be a lie."""
    assert SPARQLAgent._absence_selection_lead(COUNT_RUN, 1) == ""
    assert SPARQLAgent._absence_selection_meaning(COUNT_RUN, 1) == ""


# ── what the rows are, stated for the narration ──────────────────────────────────────────────


@pytest.mark.parametrize("query", [UNBOUND_RUN, NOT_EXISTS_RUN])
def test_the_note_forbids_the_two_sentences_that_were_actually_produced(query):
    note = SPARQLAgent._absence_selection_meaning(query, 6)
    assert "NOT every alarm event record the building holds" in note
    assert "never present 6 as a total" in note
    assert "SELECTED FOR the absence of 'acknowledged at'" in note
    assert "BY CONSTRUCTION" in note
    assert "not the model not recording" in note or "not recording the property" in note
    assert "status cannot be determined" in note


def test_the_note_never_shows_the_reader_an_internal_field_name():
    """The narration prompt forbids field names in an answer, so the note must not supply one."""
    note = SPARQLAgent._absence_selection_meaning(NOT_EXISTS_RUN, 6)
    assert "ontosage:acknowledgedAt" not in note
    assert "acknowledgedAt" not in note
    assert "'acknowledged at'" in note


def test_a_filtered_count_is_not_described_as_a_population():
    """ "6 alarm events are stored in the model" was said of a building holding 270."""
    note = SPARQLAgent._count_meaning(COUNT_RUN)
    assert "that have NO 'acknowledged at'" in note
    assert "FILTERED set" in note
    assert "never describe it as a total or as 'in total'" in note


def test_an_unfiltered_count_note_is_unchanged():
    """BUG-547's note must survive intact for every count that has no absence filter."""
    note = SPARQLAgent._count_meaning(
        "SELECT (COUNT(DISTINCT ?sensor) AS ?count) WHERE { ?sensor a brick:Illuminance_Sensor }"
    )
    assert "how many ?sensor of type brick:Illuminance_Sensor the building model holds" in note
    assert "FILTERED set" not in note
    assert SPARQLAgent._count_meaning(PLAIN_LISTING) == ""


def test_spaced_local_turns_a_curie_into_plain_words():
    assert SPARQLAgent._spaced_local("ontosage:AlarmEvent") == "alarm event"
    assert SPARQLAgent._spaced_local("ontosage:acknowledgedAt") == "acknowledged at"
    assert SPARQLAgent._spaced_local("brick:Temperature_Sensor") == "temperature sensor"
    assert SPARQLAgent._spaced_local("") == ""


# ── a reader cannot act on a hash ────────────────────────────────────────────────────────────


def _agent_with_labels(labels):
    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _execute(query):
        assert "VALUES ?subject" in query
        return {
            "results": {
                "bindings": [
                    {"subject": _uri(iri), "label": _lit(text)} for iri, text in labels.items()
                ]
            }
        }

    agent._execute_query = _execute
    return agent


ALARM_IRIS = {
    "http://x#AlarmEvent_8bd5d9f6": "Circuit breaker trip - Electrical Breaker Panel - Floor 3",
    "http://x#AlarmEvent_de870f75": "Frost protection trip - Air Handling Unit - Floor 4",
}


def test_bare_iri_rows_are_given_the_label_the_graph_already_holds():
    """Two of three runs identified the alarms only by IRI fragment. The graph has names."""
    rows = [{"r": _uri(iri)} for iri in ALARM_IRIS]
    out = asyncio.run(_agent_with_labels(ALARM_IRIS)._label_bare_subjects(rows))
    assert [r["label"]["value"] for r in out] == list(ALARM_IRIS.values())
    assert "Floor 3" in out[0]["label"]["value"]


def test_rows_that_already_read_well_are_returned_untouched():
    rows = [{"r": _uri(i), "label": _lit("already named")} for i in ALARM_IRIS]
    out = asyncio.run(_agent_with_labels(ALARM_IRIS)._label_bare_subjects(rows))
    assert out is rows


def test_two_iri_columns_are_left_alone_because_the_label_would_be_ambiguous():
    rows = [{"a": _uri("http://x#One"), "b": _uri("http://x#Two")}]
    out = asyncio.run(_agent_with_labels({})._label_bare_subjects(rows))
    assert out is rows


def test_a_long_listing_is_not_worth_a_round_trip():
    rows = [{"r": _uri(f"http://x#S{i}")} for i in range(SPARQLAgent._LABEL_LOOKUP_MAX_ROWS + 1)]
    out = asyncio.run(_agent_with_labels({})._label_bare_subjects(rows))
    assert out is rows


def test_a_failed_lookup_never_costs_the_answer():
    agent = SPARQLAgent.__new__(SPARQLAgent)

    async def _boom(query):
        raise RuntimeError("graphdb down")

    agent._execute_query = _boom
    rows = [{"r": _uri("http://x#AlarmEvent_8bd5d9f6")}]
    assert asyncio.run(agent._label_bare_subjects(rows)) is rows


# ── the wiring ───────────────────────────────────────────────────────────────────────────────


def test_both_narration_paths_publish_the_lead_and_neither_returns_a_bare_summary():
    """Two `return summary.strip()` sites; a fix applied to one of them is half a fix."""
    src = inspect.getsource(SPARQLAgent._format_results)
    assert src.count("_with_lead(summary)") == 2
    assert "return summary.strip()" not in src
    assert "self._absence_selection_lead(sparql_query, len(bindings))" in src
    assert "self._absence_selection_meaning(sparql_query, len(bindings))" in src
    # The note has to reach the prompt, which means it has to be built before the prompt is.
    assert src.index("_absence_selection_meaning") < src.index("summary_prompt = ")


def test_the_rows_are_labelled_before_anything_reads_them():
    src = inspect.getsource(SPARQLAgent._format_results)
    assert src.index("_label_bare_subjects") < src.index('result_text = f"Found ')
