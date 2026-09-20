# -*- coding: utf-8 -*-
"""Irrelevant fragments are not answers (2D-16, defect classes C10 and C11).

Five measured failures on the 2026-09-18 held-out reads, one fault: the capability/document lane
returned real text that had nothing to do with the question.

* a question about sound insulation answered with "Live building figures" (sensor and room counts);
* a question about the freshness of access-control feeds answered with "Designed / built by ...";
* a methodology question about aggregation answered with a quote from a cost-line register;
* a "what design choices?" question answered with a register's own design-rationale prose;
* "are there duplicate assets?" answered with equipment class counts.

Everything is offline: each source seam is injected, as in test_capability_bare_building.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import orchestrator.agents.capability_agent as cap
import orchestrator.services.building_context as bctx
import orchestrator.services.building_metrics as bmmod
import orchestrator.services.capability_graph_resolver as cgr
from orchestrator.services import passage_relevance as pr
from orchestrator.services.building_metrics import BuildingMetricsSnapshot
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

_NAME = "Example Building"


def _state(message: str) -> ConversationState:
    return ConversationState(
        conversation_id="rel-1",
        user_id="u",
        user_message=message,
        building_id="bldgX",
        current_intent="capability",
        messages=[Message(role="user", content=message)],
    )


def _building(
    monkeypatch,
    *,
    snapshot: Optional[BuildingMetricsSnapshot] = None,
    docs: Optional[List[Dict[str, Any]]] = None,
    composer=None,
) -> None:
    """A building whose every source misses except the ones passed in."""
    monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name=_NAME))
    snap = snapshot if snapshot is not None else BuildingMetricsSnapshot()

    class _Metrics:
        async def snapshot(self, _bid, namespace=None):
            return snap

    monkeypatch.setattr(bmmod, "get_building_metrics", lambda: _Metrics())

    class _Resolver:
        async def resolve(self, _q):
            return []

    monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

    async def _docs(_q, _bid, top_k=3, only_document="", stats=None):
        return list(docs or [])

    monkeypatch.setattr(cap, "_search_documents", _docs)
    # The composer is the one place a model would be called; pin it to "could not run" unless a
    # test supplies an answer, so nothing here ever reaches a provider.
    if composer is None:

        async def composer(_q, _hits):
            return None, False

    monkeypatch.setattr(cap.CapabilityAgent, "_answer_from_passages", staticmethod(composer))


async def _ask(message: str) -> Dict[str, Any]:
    out = await cap.CapabilityAgent().answer(_state(message))
    return out.intermediate_results["capability_result"]


# ── the gate itself ──────────────────────────────────────────────────────────


def test_one_incidental_word_no_longer_makes_a_passage_relevant():
    q = "How are the readings aggregated over time for the overnight ventilation periods?"
    cost_line = "Free balance = budget minus actual minus committed. Ventilation contract renewals."
    verdict = pr.assess(q, cost_line)
    assert not verdict.relevant, verdict


def test_a_passage_sharing_enough_subject_terms_is_relevant():
    q = "when is the chiller pump service due"
    text = "Chiller pump 1 service due 2026-11-01, planned maintenance visit."
    assert pr.assess(q, text).relevant


def test_the_number_of_shared_terms_needed_grows_slowly_with_the_question():
    assert [pr.needed_terms(n) for n in (1, 2, 3, 8, 9, 14)] == [1, 1, 2, 2, 3, 3]


def test_two_shared_terms_are_enough_for_a_long_analytical_question():
    """The one consistently correct document answer on the 147-question bank shares 2 of 8."""
    q = (
        "I have appointments on different floors with a short gap. "
        "What conservative travel and setup buffer should I allow?"
    )
    passage = "A travel buffer between floors is added; the lift adds waiting time."
    verdict = pr.assess(q, passage)
    assert verdict.relevant and set(verdict.shared) == {"travel", "buffer"}


def test_inflections_the_singulariser_leaves_apart_still_meet():
    """'isolate' in the question, 'isolation' in the register; 'aggregated' against 'aggregation'."""
    assert pr.assess(
        "where can i isolate the supply for the toilets",
        "isolation_point: MCC-0 way 3, local isolator. Supply to the toilets is here.",
    ).relevant
    assert pr.assess("how is the aggregation done", "Readings are aggregated by the hour.").relevant


def test_a_single_subject_term_must_itself_be_present():
    assert not pr.assess("what is the aggregation method", "The lift is out of service.").relevant
    assert pr.assess("what is the aggregation method", "Aggregation is by the hour.").relevant


def test_a_document_named_for_the_subject_is_relevant_without_lexical_overlap():
    verdict = pr.assess(
        "what is the wifi policy",
        "Guests use Guest-WiFi; no password.",
        doc_name="wifi_policy",
    )
    assert verdict.relevant and verdict.via == "name"


def test_a_score_well_above_the_floor_is_trusted_without_overlap():
    verdict = pr.assess(
        "how do people get in after hours",
        "Out of hours, use the intercom at the north door and state your name.",
        score=0.80,
        floor=0.55,
        margin=0.10,
    )
    assert verdict.relevant and verdict.via == "score"
    assert not pr.assess(
        "how do people get in after hours", "The lift is fine.", score=0.58, floor=0.55, margin=0.10
    ).relevant


def test_a_question_with_no_subject_terms_fails_open():
    assert pr.assess("tell me more", "anything").relevant


def test_a_lay_term_expansion_is_credited():
    q = "why is it so stuffy in the atrium"
    passage = "CO2 rose above 1200 ppm in the hall."
    assert not pr.assess(q, passage).relevant
    assert pr.assess(q, passage, extra_vocab=["co2"]).relevant


# ── the live-figures block answers counts and size, nothing else ─────────────


async def test_a_sound_insulation_question_is_not_answered_with_sensor_and_room_counts(
    monkeypatch,
):
    _building(
        monkeypatch,
        snapshot=BuildingMetricsSnapshot(total_points=533, total_sensors=326, zone_count=108),
    )
    res = await _ask("Is the sound insulation between the lecture theatres good enough?")
    assert res["provenance"] != "live_metrics"
    assert "Live building figures" not in res["response"]
    assert "326" not in res["response"]


@pytest.mark.parametrize(
    "question",
    ["how many sensors are there?", "how many rooms are there?", "how many floors are there?"],
)
async def test_a_count_or_size_question_still_gets_the_live_figures(monkeypatch, question):
    _building(
        monkeypatch,
        snapshot=BuildingMetricsSnapshot(total_points=533, total_sensors=326, zone_count=108),
    )
    res = await _ask(question)
    assert res["provenance"] == "live_metrics"


def test_only_counts_and_what_it_has_are_figure_questions():
    assert cap._asks_for_building_figures("How many rooms does it have?")
    assert cap._asks_for_building_figures("What does the building have in the way of sensors?")
    assert not cap._asks_for_building_figures("Is the sound insulation good?")
    assert not cap._asks_for_building_figures("Is the acoustic performance acceptable?")


# ── the building's own description answers only questions about the building ─


@pytest.mark.parametrize(
    "question",
    [
        "Who built it?",
        "How old is this building?",
        "Tell me about this building",
        "What type of building is this?",
        "Who owns and runs the building?",
        "What is the address?",
    ],
)
def test_a_question_about_the_building_gets_the_profile(question):
    assert cap._profile_is_the_subject(question)


@pytest.mark.parametrize(
    "question",
    [
        "How fresh is the data from the access-control feeds, and who built the system?",
        "Which contractor is responsible for the overdue lift inspection certificates?",
        "Who designed the ventilation control strategy for the laboratories?",
    ],
)
def test_profile_words_inside_a_question_about_something_else_do_not_trigger_it(question):
    assert not cap._profile_is_the_subject(question)


# ── a census answers what exists, not the quality of what exists ────────────


def test_an_attribute_question_is_not_answered_with_a_class_census():
    from orchestrator.services.ontology_inventory import is_inventory_question

    duplicate = "Are there duplicate assets in the register?"
    assert is_inventory_question(duplicate), "the shape that used to be claimed by the census"
    assert not cap._census_can_answer(duplicate)
    assert not cap._census_can_answer("Which meters are inconsistent with the drawings?")
    assert not cap._census_can_answer("when was each pump last serviced?")
    assert cap._census_can_answer("What equipment is installed in this building?")
    assert cap._census_can_answer("how many pumps are there?")


# ── the document lane ────────────────────────────────────────────────────────

_COST_LINE = {
    "doc_name": "cost_line_register",
    "score": 0.60,
    "text": "Free balance = budget minus actual minus committed minus accrued. Coding check marks "
    "a posting whose cost centre looks wrong. Coordination function owners confirm before use.",
}


async def test_an_unrelated_quote_is_declined_not_pasted_when_the_composer_cannot_run(monkeypatch):
    _building(monkeypatch, docs=[dict(_COST_LINE)])
    res = await _ask("How are the room temperature readings aggregated across the floors?")
    assert res["provenance"] in ("no_match", "documents_do_not_answer")
    assert "Free balance" not in res["response"]
    assert "Coordination function" not in res["response"]


async def test_passages_the_gate_removes_are_declined_unnamed_and_stay_on_the_record(monkeypatch):
    """Searched is not the same as about the question: the audit trail keeps it, the reader is not told."""
    incidental = dict(_COST_LINE, text=_COST_LINE["text"] + " Ventilation contract renewals.")
    _building(monkeypatch, docs=[incidental])

    async def composer(_q, _hits):
        raise AssertionError("the composer must not be handed passages the gate removed")

    monkeypatch.setattr(cap.CapabilityAgent, "_answer_from_passages", staticmethod(composer))
    # Shares one incidental word ("ventilation") with the question, so the on-topic guard keeps
    # it and only the relevance gate can remove it.
    res = await _ask("How are the ventilation readings aggregated across the overnight periods?")
    assert res["provenance"] == "documents_do_not_answer"
    assert res["documents"] == ["Cost Line Register"] and res["documents_named"] == []
    assert "Cost Line Register" not in res["response"]
    assert "could not find this in" in res["response"].lower()


async def test_the_gate_names_itself_on_the_evidence_record(monkeypatch):
    _building(monkeypatch, docs=[dict(_COST_LINE)])
    state = _state("How is the aggregation of the overnight set-back periods worked out?")
    out = await cap.CapabilityAgent().answer(state)
    applied = (out.intermediate_results.get("evidence") or {}).get("gates_applied", [])
    assert "passage_relevance" in applied or "grounding_guard" in applied


async def test_a_relevant_passage_still_answers(monkeypatch):
    doc = {
        "doc_name": "service_schedules",
        "score": 0.70,
        "text": "Chiller pump service due 2026-11-01. Planned maintenance is every 180 days.",
    }

    async def composer(_q, _hits):
        return "The chiller pump service is due on 2026-11-01.", True

    _building(monkeypatch, docs=[doc], composer=composer)
    res = await _ask("When is the chiller pump service due?")
    assert res["provenance"] == "document_answered"
    assert "2026-11-01" in res["response"]


async def test_the_kill_switch_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("DOCUMENT_RELEVANCE_GATE", "off")
    _building(monkeypatch, docs=[dict(_COST_LINE)])
    res = await _ask("How are the room temperature readings aggregated across the floors?")
    # Ungated, the passage reaches the composer, which (unavailable here) declines or pastes.
    assert res["provenance"] in ("documents_do_not_answer", "document_kb", "no_match")


# ── commentary is dropped where retrieval happens ────────────────────────────


async def test_search_documents_drops_a_register_s_own_rationale(monkeypatch, tmp_path):
    from orchestrator.services import document_indexer as di

    (tmp_path / "asset_engineering_register.md").write_text(
        "# R\n\n## What this register records\n\nThree duty columns, not one. design_duty is the "
        "claim on the drawing and commissioned_duty is what was witnessed on site.\n\n"
        "## Register\n\n| code | name |\n|---|---|\n| AEP-001 | Air Handling Unit |\n",
        encoding="utf-8",
    )
    rationale = {
        "doc_name": "asset_engineering_register",
        "score": 0.9,
        "text": "Three duty columns, not one. design_duty is the claim on the drawing and "
        "commissioned_duty is what was witnessed on site.",
    }
    table = {
        "doc_name": "asset_engineering_register",
        "score": 0.8,
        "text": "| AEP-001 | Air Handling Unit | duty 2.4 m3/s |",
    }

    async def _fake_search(*_a, **_k):
        return [rationale, table]

    monkeypatch.setattr(di, "search_documents", _fake_search)
    monkeypatch.setattr(pr, "_documents_dir", lambda _b: tmp_path)
    monkeypatch.setattr(cap, "_doc_qdrant_client", object())
    monkeypatch.setattr(cap, "_doc_embedding_service", object())

    hits = await cap._search_documents("what design choices were made?", "bx")
    assert [h["text"] for h in hits] == [table["text"]]
