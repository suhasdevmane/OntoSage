# -*- coding: utf-8 -*-
"""The five wave-2 fixes are connected where a reader meets them (2D-16 wave 2).

The pure modules are pinned in their own test files; this one proves the workflow uses them:

1. the trigger for a chart, and the visualization node, obey `chart_policy`;
2. the "nothing to say" fallback takes the shape of the question (abstract, missing referent,
   weather) instead of quoting one odd word;
3. the general-knowledge lane answers from the building's records first and labels the rest;
4. the semantic fallback's "results you received / add a field" prose becomes one plain sentence;
5. the withheld-figures message uses no verifier vocabulary.

Everything is offline; the graph, the stores and the model are fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.services import clarification as cl
from orchestrator.services import general_knowledge_gate as gk
from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


def _run(coro):
    return asyncio.run(coro)


def _state(question: str, **results) -> ConversationState:
    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=question,
        messages=[Message(role="user", content=question)],
    )
    s.intermediate_results.update(results)
    return s


def _orch():
    return mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)


NOTIFICATION_Q = (
    "I may not see visual alerts. Which verified audible or staff-assisted notification "
    "provision is available?"
)


# ── 1. charts ────────────────────────────────────────────────────────────────


def test_the_workflow_trigger_no_longer_reads_the_adjective_visual_as_a_picture_request():
    assert mod.WorkflowOrchestrator._user_wants_visualization(NOTIFICATION_Q) is False


@pytest.mark.parametrize(
    "question",
    [
        "plot the CO2 in room 5.01 today",
        "Graph humidity for the last week",
        "show the trend of energy use",
        "give me a heat map of CO2",
    ],
)
def test_real_chart_requests_still_trigger_the_workflow(question):
    assert mod.WorkflowOrchestrator._user_wants_visualization(question) is True


def test_the_visualization_node_does_not_draw_a_chart_nobody_asked_for():
    """The wave-1 failure: a noise series fetched for a notification question and plotted."""
    orch = _orch()
    drawn = []

    async def _viz(state, message, data):
        drawn.append(data)
        return {"formatted_response": "chart", "media": [{"type": "image"}]}

    async def _capability(state):
        state.intermediate_results["dialogue_response"] = "capability answered"
        return state

    orch.viz_agent = SimpleNamespace(create_visualization=_viz)
    orch._capability_node = _capability
    state = _state(
        NOTIFICATION_Q,
        sensor_metadata={"n1": {"label": "Floor 5 noise sensor", "unit": "dB"}},
    )
    state.current_intent = "visualization"
    state.query_results = {
        "data": [{"timestamp": "2026-09-19 01:00:00", "uuid": "n1", "value": 40}]
    }
    out = _run(orch._visualization_node(state))
    assert drawn == []
    viz = out.intermediate_results["viz_result"]
    assert viz["skipped"] == "not_a_chart_request" and "media" not in viz
    assert out.intermediate_results["dialogue_response"] == "capability answered"


def test_the_visualization_node_does_not_plot_the_wrong_quantity():
    orch = _orch()
    drawn = []

    async def _viz(state, message, data):
        drawn.append(data)
        return {"formatted_response": "chart", "media": [{"type": "image"}]}

    orch.viz_agent = SimpleNamespace(create_visualization=_viz)
    state = _state(
        "plot the CO2 in room 5.01",
        sensor_metadata={"n1": {"label": "Floor 5 noise sensor", "unit": "dB"}},
    )
    state.query_results = {
        "data": [{"timestamp": "2026-09-19 01:00:00", "uuid": "n1", "value": 40}]
    }
    out = _run(orch._visualization_node(state))
    assert drawn == []
    assert (
        out.intermediate_results["viz_result"]["skipped"] == "series_is_not_the_quantity_asked_for"
    )


def test_the_visualization_node_still_draws_what_was_asked_for():
    orch = _orch()
    drawn = []

    async def _viz(state, message, data):
        drawn.append(data)
        return {"formatted_response": "chart", "media": [{"type": "image"}]}

    orch.viz_agent = SimpleNamespace(create_visualization=_viz)
    state = _state(
        "plot the CO2 in room 5.01",
        sensor_metadata={"c1": {"label": "Room 5.01 CO2 sensor", "unit": "ppm"}},
    )
    state.query_results = {
        "data": [{"timestamp": "2026-09-19 01:00:00", "uuid": "c1", "value": 700}]
    }
    out = _run(orch._visualization_node(state))
    assert len(drawn) == 1 and out.intermediate_results["viz_result"]["media"]


def test_a_chart_caption_says_the_quantity_the_place_and_the_period(monkeypatch):
    from orchestrator.agents import visualization_agent as va

    agent = va.VisualizationAgent.__new__(va.VisualizationAgent)
    rows = [
        {"uuid": "c1", "timestamp": "2026-09-18 22:50:00", "value": 723},
        {"uuid": "c1", "timestamp": "2026-09-19 03:50:00", "value": 800},
    ]
    state = SimpleNamespace(
        intermediate_results={
            "sensor_metadata": {"c1": {"label": "Room 5.01 CO2 sensor", "unit": "ppm"}}
        },
        building_id=None,
    )

    async def fake_generate(prompt, **kw):
        return "A clear overnight plateau."

    # monkeypatch, not assignment: a bare assignment here left the fake on `llm_manager` for the
    # whole session and two capability tests later in the run answered from it.
    monkeypatch.setattr(va.llm_manager, "generate", fake_generate)
    caption = _run(
        agent._generate_description("Plot CO2", "line_chart", {"data": rows}, state=state)
    )
    assert caption.startswith("Chart of Room 5.01 CO2 sensor (ppm) — 18 Sep 22:50 to 19 Sep 03:50")


# ── 2. the fallback takes the shape of the question ─────────────────────────


@pytest.fixture
def holdings(monkeypatch):
    async def _fake(state, timeout_s=5.0):
        return (
            ["fan state", "lift state", "air quality"],
            [
                SimpleNamespace(
                    local_name="Incident",
                    label="Incident record",
                    instances=17,
                    terms=("incident",),
                )
            ],
        )

    monkeypatch.setattr(mod, "_closest_holdings", _fake)


def test_an_abstract_question_is_not_answered_with_one_odd_word(holdings):
    q = (
        "Does the verified timeline support the stated root cause, what alternatives remain "
        "plausible, and which specialist evidence is still needed?"
    )
    text = _run(mod._unanswered_response(_state(q, intent="diagnosis"), None))
    assert "Which measurement or record do you mean by" not in text
    assert "**specialist**" not in text and "?" not in text
    assert "diagnosis" not in text


def test_a_missing_referent_is_asked_about_once_naming_what_the_building_holds(holdings):
    text = _run(mod._unanswered_response(_state("What happened during the incident?"), None))
    assert text.startswith("Which incident do you mean?") and "Incident record" in text


def test_weather_now_gets_the_outdoor_readings_and_no_forecast_claim(holdings, monkeypatch):
    from orchestrator.services import outdoor_readings as orr

    async def _fetch(**_k):
        return [cl.OutdoorReading("outdoor temperature", 12.3, "°C", "03:50 on 19 Sep")]

    monkeypatch.setattr(orr, "fetch_outdoor_readings", _fetch)
    text = _run(mod._unanswered_response(_state("how is the weather outside now?"), None))
    assert text.startswith("**I don't hold a weather forecast.**")
    assert "outdoor temperature 12.3 °C (at 03:50 on 19 Sep)" in text
    assert "Which measurement" not in text


def test_a_named_place_is_still_kept_in_the_readers_words(holdings):
    st = _state("anything", entities=["Room 5.04"])
    assert "Room 5.04" in _run(mod._unanswered_response(st, None))


def test_the_step_error_stays_admin_only(holdings):
    reader = _state("anything", error="sql: timeout", user_role="facility_manager")
    admin = _state("anything", error="sql: timeout", user_role="admin")
    assert "timeout" not in _run(mod._unanswered_response(reader, None))
    assert "timeout" in _run(mod._unanswered_response(admin, None))


# ── 3. general knowledge is labelled, and the building's records come first ──


def _gk_orchestrator(monkeypatch, llm_reply="Parking lots hold cars and vans.", records=None):
    orch = _orch()

    async def _records(question, building="this building"):
        return records

    monkeypatch.setattr(gk, "records_answer", _records)

    async def _generate(prompt, **_k):
        return llm_reply

    monkeypatch.setattr(mod.llm_manager, "generate", _generate)
    return orch


def test_the_general_knowledge_lane_answers_from_the_building_first(monkeypatch):
    orch = _gk_orchestrator(monkeypatch, records="Here is what I found for **B**: motorcycle bays.")
    state = _state("What kind of vechicles park?")
    out = _run(orch._general_knowledge_node(state))
    assert out.intermediate_results["dialogue_response"].startswith(
        "Here is what I found for **B**"
    )
    assert "General knowledge" not in out.intermediate_results["dialogue_response"]


def test_anything_the_lane_takes_from_the_model_is_labelled(monkeypatch):
    orch = _gk_orchestrator(monkeypatch, records=None)
    out = _run(orch._general_knowledge_node(_state("What is the capital of Wales?")))
    text = out.intermediate_results["dialogue_response"]
    assert text.startswith(gk.LABEL) and "Parking lots hold cars and vans." in text


def test_a_labelled_model_answer_is_not_labelled_twice(monkeypatch):
    orch = _gk_orchestrator(monkeypatch, llm_reply=gk.LABEL + " Cardiff.")
    out = _run(orch._general_knowledge_node(_state("What is the capital of Wales?")))
    assert out.intermediate_results["dialogue_response"].count("General knowledge") == 1


def test_the_classifier_draft_used_when_the_model_fails_is_labelled_too(monkeypatch):
    orch = _gk_orchestrator(monkeypatch, records=None)

    async def _boom(prompt, **_k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mod.llm_manager, "generate", _boom)
    state = _state("What is the capital of Wales?", general_knowledge_draft="Cardiff.")
    out = _run(orch._general_knowledge_node(state))
    assert out.intermediate_results["dialogue_response"] == gk.LABEL + " Cardiff."


# ── 4. the semantic fallback's pipeline prose ────────────────────────────────


SWIMMING_POOL_PROSE = (
    "I'm sorry, but the building model does not record which rooms are swimming pools. "
    "The 100 query results you received only list spaces (floors and rooms); you would need "
    "a field that explicitly marks a space as a pool. Once that field is available, I can "
    "help you filter."
)
TEACHING_PROSE = (
    "The building's records do not contain any information about teaching sessions. The data "
    'you received only lists how many sensors are installed in each floor and room (e.g., "Room0.01" '
    "has 15 sensors)."
)


@pytest.mark.parametrize(
    "question,prose,subject",
    [
        ("Which rooms are swimming pools?", SWIMMING_POOL_PROSE, "swimming pool"),
        ("Which rooms have teaching sessions this week?", TEACHING_PROSE, "teaching session"),
    ],
)
def test_an_absence_narrated_in_the_pipelines_terms_becomes_one_plain_sentence(
    question, prose, subject
):
    out = mod._without_retrieval_narration(_state(question), prose)
    # The same sentence the referent gate gives "Is there a swimming pool?", so a reader who asks
    # the same thing two ways is not told two different things (wave-2 live read).
    assert out == (
        f"'{subject}' does not exist in this building, so there is nothing to report about it."
    )
    for internal in ("query results", "you received", "you provided", "field", "sorry"):
        assert internal not in out.lower()


def test_the_pass_runs_for_every_lane_not_only_the_semantic_fallback():
    """The teaching-sessions answer came from the metadata lane; the swimming-pool one too."""
    import inspect

    src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    assert "_without_retrieval_narration(state, final_response)" in src
    assert src.index("_without_retrieval_narration") < src.index("meta_answer_reason"), (
        "it must run BEFORE the meta guard, or an answer whose only flaw is that sentence is "
        "discarded whole instead of losing the sentence"
    )


def test_an_answer_with_substance_keeps_it_and_loses_only_the_narration():
    prose = (
        "The register records eight waste streams: general waste, mixed recycling and clinical "
        "sharps. The data you received also lists sensor counts. Collections run on Tuesdays and "
        "Fridays for every stream."
    )
    out = mod._without_retrieval_narration(_state("Which waste streams are held?"), prose)
    assert "eight waste streams" in out and "Collections run on Tuesdays" in out
    assert "data you received" not in out


def test_an_ordinary_answer_is_left_exactly_as_it_was():
    fine = "Rooms 5.01 and 5.09 are research laboratories, and Room 2.14 is a teaching laboratory."
    assert mod._without_retrieval_narration(_state("Which rooms are labs?"), fine) == fine


def test_the_pass_records_that_it_fired_and_never_empties_an_answer():
    state = _state("Which rooms are swimming pools?")
    out = mod._without_retrieval_narration(state, SWIMMING_POOL_PROSE)
    assert out.strip() and state.intermediate_results.get("retrieval_narration_removed") is True


# ── 5. withheld figures ──────────────────────────────────────────────────────


def test_the_withheld_message_names_none_of_the_verifiers_vocabulary():
    from orchestrator.services import publication_gate as pg

    decision = pg.evaluate(
        intent="analytics",
        final_response="The current load is 512 kW across 10 assets.",
        verification={
            "grounded": False,
            "confidence": 0.20,
            "source": "sql",
            "missing": ["time_series_data"],
        },
    )
    assert not decision.publish
    text = decision.text
    for internal in (
        "grounded=False",
        "confidence=0.20",
        "time_series_data",
        "grounding check",
        "path",
    ):
        assert internal not in text
    assert (
        "withheld" in text.lower() and "not a statement that the figures are wrong" in text.lower()
    )
    assert "narrower scope" in text.lower()
    assert decision.reason == "grounded=False and confidence=0.20", "the log keeps the diagnosis"


# ── 6. a fragment never reaches the reader (wave 3) ──────────────────────────


def test_the_answer_shape_guard_runs_in_the_response_node_and_replaces_with_the_decline():
    import inspect

    src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    assert "non_answer_reason(final_response, state.user_message" in src
    assert 'state.intermediate_results["non_answer_replaced"] = _shape' in src
    guard = src[src.index("non_answer_reason") :]
    assert "_unanswered_response(state, ctx)" in guard[:600], (
        "a fragment is replaced by the honest decline that names what the building can answer, "
        "not by another fragment"
    )


@pytest.mark.parametrize(
    "question,answer",
    [
        ("Has this reported spill already been attended?", "**Not met**"),
        ("Where do assets accumulate behind a common dependency?", "continuity_provision_register"),
    ],
)
def test_the_live_fragments_are_recognised_by_the_module_the_node_calls(question, answer):
    from orchestrator.services.answer_shape import non_answer_reason

    assert non_answer_reason(answer, question)
