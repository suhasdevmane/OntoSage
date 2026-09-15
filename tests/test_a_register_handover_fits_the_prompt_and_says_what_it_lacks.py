# -*- coding: utf-8 -*-
"""BUG-546: a register handover is sized in characters, reads cleanly, and admits its limits.

Stakeholder run #1 (2026-09-15) through Open WebUI:

* a routes + workspaces handover passed the 1,300-CELL budget, rendered 55.9k characters,
  returned an empty completion three times, and the user got "Found 44 result(s): 1.
  register: Accessible route | record: …";
* narration read approval dates as plant start times and approval statuses as no-shows,
  certified compliance record retention, and called 5 September "today" on the 15th.
"""

import inspect

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def _lit(v):
    return {"type": "literal", "value": v}


def _row(i, register="Accessible route", **extra):
    base = {
        "register": _lit(register),
        "record": _lit(f"http://x#route/RTE-{i:03d}"),
        "label": _lit(f"Route {i}"),
        "recordStatus": _lit("open"),
        "derivedFromDocument": _lit("accessible_route_register.md"),
        "owningAuthority": _lit("Estates — Access Consultant survey"),
        "retrievedAt": _lit("2026-09-05T16:12:09"),
    }
    base.update({k: _lit(v) for k, v in extra.items()})
    return base


def test_values_every_row_shares_are_printed_once_and_nothing_is_lost():
    rows = [_row(i, routeTo=f"Room {i}") for i in range(1, 6)]
    flat = SPARQLAgent._render_rows(rows)
    hoisted = SPARQLAgent._render_rows(rows, hoist=True)
    assert len(hoisted) < len(flat)
    assert hoisted.count("accessible_route_register.md") == 1
    assert hoisted.count("2026-09-05T16:12:09") == 1
    for i in range(1, 6):
        assert f"Room {i}" in hoisted and f"Route {i}" in hoisted


def test_label_status_and_id_stay_on_every_row_even_when_shared():
    rows = [_row(i) for i in range(1, 4)]
    hoisted = SPARQLAgent._render_rows(rows, hoist=True)
    assert hoisted.count("recordStatus: open") == 3


def test_each_register_gets_its_own_header_and_a_padded_gap_is_stated_once():
    a = [_row(i, routeTo="") for i in range(1, 4)]
    b = [_row(i, register="Workspace profile", seatCount=str(i)) for i in range(4, 7)]
    for r in a:
        r["seatCount"] = _lit("")
    text = SPARQLAgent._render_rows(a + b, hoist=True)
    assert "of register Accessible route share" in text
    assert "of register Workspace profile share" in text
    assert "No record of register Accessible route has a value for: " in text
    assert "seatCount: |" not in text and "seatCount: \n" not in text


def test_the_budget_is_in_characters_of_the_rendered_rows():
    agent = SPARQLAgent.__new__(SPARQLAgent)
    long = "x" * 2000
    rows = [_row(i, comment=long + str(i)) for i in range(1, 25)]  # few cells, many chars
    results = {"head": {"vars": []}, "results": {"bindings": rows}}
    assert len(rows) * 8 < SPARQLAgent.MAX_RECORD_CELLS
    assert agent._rendered_chars(results) > SPARQLAgent.MAX_RECORD_CHARS


def test_an_unsummarised_handover_names_the_records_instead_of_dumping_them():
    rows = [_row(i) for i in range(1, 21)]
    text = SPARQLAgent._register_fallback(rows)
    assert "Found" not in text and "derivedFromDocument" not in text
    assert "**20 records**" in text and "- Route 1 (Accessible route, open)" in text
    assert "…and 5 more" in text and "haven't drawn a conclusion" in text


def _source_with_literals_joined() -> str:
    """The method's source with adjacent string literals joined, as Python joins them."""
    import re

    return re.sub(r'"\s*\n\s*(?:f)?"', "", inspect.getsource(SPARQLAgent._whole_register))


def test_the_register_guidance_carries_the_date_and_the_grounding_rules():
    src = _source_with_literals_joined()
    assert "building_local_now" in src and "Today is" in src
    for rule in ("never map a field onto a", "Never certify", "say so plainly"):
        assert rule in src
    assert src.count("{grounding}") == 2  # both the one- and two-register guidance


def test_the_second_register_is_also_held_to_the_character_budget():
    src = inspect.getsource(SPARQLAgent._whole_register)
    merge_block = src[src.index("merged = None"):src.index("second-register lookup skipped")]
    assert "_rendered_chars(merged[0]) > self.MAX_RECORD_CHARS" in merge_block


# BUG-547 — a count of things is not a reading.


def test_a_count_result_is_labelled_as_a_count_of_things():
    note = SPARQLAgent._count_meaning(
        "SELECT (COUNT(DISTINCT ?sensor) AS ?count) WHERE "
        "{ ?sensor rdf:type/rdfs:subClassOf* brick:Illuminance_Sensor . }"
    )
    assert "?count = how many ?sensor of type brick:Illuminance_Sensor" in note
    assert "NOT a reading, a measurement, a duration" in note


def test_a_grouped_count_says_it_is_per_group():
    note = SPARQLAgent._count_meaning(
        "SELECT ?floor (COUNT(?r) AS ?rooms) WHERE { ?r a brick:Room ; brick:isPartOf ?floor } "
        "GROUP BY ?floor"
    )
    assert "?rooms = how many ?r of type brick:Room" in note and "for that row's group" in note


def test_a_query_without_a_count_carries_no_note():
    assert SPARQLAgent._count_meaning("SELECT ?s WHERE { ?s a brick:Room } LIMIT 5") == ""


def test_the_note_reaches_the_prompt_above_the_rows():
    src = inspect.getsource(SPARQLAgent._format_results)
    assert "self._count_meaning(sparql_query)" in src
    assert src.index("_count_meaning") < src.index("summary_prompt = ")
