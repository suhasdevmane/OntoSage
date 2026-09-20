# -*- coding: utf-8 -*-
"""BUG-812 (tail A rows F39, F40): an assistant for ONE building must not answer a weather
forecast by asking "which city?", nor an investment question from general model knowledge.

The weather answer asked for a location "as though it could forecast anywhere"; the Bitcoin
answer was a paragraph of investment guidance, unlabelled, after 98 seconds. The policy, pinned
here so a supervisor gets the same answer twice: a BRIEF, honest statement of what the building
can answer from, and for weather the statement names what the building's OWN outdoor sensors read
-- taken from the graph, never from a list in the code.

Owner policy 2026-09-19 ("answer MORE, honestly"): jokes, riddles, poems, trivia, coding help and
the like get the same brief statement; building KNOWLEDGE ("how do I control CO2?") is NOT declined
-- it is answered as labelled general guidance (see the guidance-shape tests).

The same tests pin what must NOT change: an indoor forecast, a data forecast, a definition of a
building term and a question about the building's showers are none of this module's business.
"""

import pytest

from orchestrator.services import scope_policy as sp

pytestmark = pytest.mark.unit

DECLINED_WEATHER = [
    "What's the weather forecast for tomorrow?",  # F39, the failing question
    "Will it rain tomorrow?",
    "Is it going to snow this weekend?",
    "What will the weather be like next week?",
    "Is the weather going to be sunny on Friday?",
    "Forecast for rain tonight?",
]

DECLINED_FINANCIAL = [
    "Should I buy Bitcoin?",  # F40, the failing question
    "Is Ethereum a good investment?",
    "Should we invest in stocks or bonds?",
    "Is it a good time to sell my shares?",
    "Is crypto worth buying right now?",
]

DECLINED_OFF_TOPIC = [
    "Tell me a joke.",  # B39: no longer answered from general knowledge, unlabelled
    "Tell me another joke",
    "Write me a poem about spring",
    "What's the capital of France?",
    "Who invented the telephone?",
    "Write me a python function to reverse a string",
    "Translate 'good morning' into French",
    "Give me a recipe for lasagne",
    "Who won the World Cup in 2018?",
]

#: Stakeholder-catalogue questions that MENTION the weather without asking for a forecast. The first
#: draft of the rule claimed all six: a premise ("rain is forecast"), an effect ("will the weather
#: affect ..."), a condition ("if the weather is good") is not a request for a forecast.
MENTIONS_THE_WEATHER = [
    "Forecast Friday's cafe queue if the weather is good.",
    "Heavy rain and wind are forecast for my visit. Which authorised entrance and verified "
    "step-free route would minimise outdoor exposure?",
    "Will tomorrow's weather affect the public entrance, walking route or arrival buffer we "
    "should allow?",
    "Storm warnings for tonight - should I move away from the glass atrium?",
    "Which day next week is best for the roof survey, weather-wise?",
    "Is the external section of the route sufficiently verified for the forecast light, rain, "
    "wind, ice, leaves and surface conditions?",
]

LEFT_ALONE = MENTIONS_THE_WEATHER + [
    "What's the weather like outside right now?",  # a current reading, the data lanes answer it
    "Is it raining?",
    "What is the outside temperature?",
    "Predict the temperature in Room 3.01 for tomorrow afternoon.",  # a data forecast
    "Forecast energy use for next week.",
    "Will Room 2.14 be too hot tomorrow?",
    "Are the showers on floor 2 open tomorrow?",  # a building amenity
    "Should we invest in solar panels for the roof?",  # a building decision
    "Is it worth replacing the boiler?",
    "What is Bitcoin?",  # a definition, not advice
    "Explain how the stock market works.",
    "What is HVAC?",  # building knowledge: answered as labelled guidance, never declined
    "How do I control CO2?",
    "Tell me a joke about HVAC.",  # it names a building term, so it is not the bare request
    "Write a python script to plot CO2 for last week.",  # building work, not off-topic
    "Does the building have a weather station?",
    "Hello",
    "Thanks!",
    "What can you do?",
]


@pytest.mark.parametrize("question", DECLINED_WEATHER)
def test_a_weather_forecast_is_recognised(question):
    assert sp.out_of_scope_kind(question) == sp.KIND_WEATHER_FORECAST, question
    assert sp.weather_forecast_question(question)


@pytest.mark.parametrize("question", DECLINED_FINANCIAL)
def test_a_request_for_financial_advice_is_recognised(question):
    assert sp.out_of_scope_kind(question) == sp.KIND_FINANCIAL_ADVICE, question
    assert sp.financial_advice_question(question)


@pytest.mark.parametrize("question", DECLINED_OFF_TOPIC)
def test_jokes_trivia_coding_and_other_non_building_requests_are_recognised(question):
    assert sp.out_of_scope_kind(question) == sp.KIND_OFF_TOPIC, question


@pytest.mark.parametrize("question", LEFT_ALONE)
def test_indoor_forecasts_definitions_amenities_and_pleasantries_are_left_alone(question):
    assert sp.out_of_scope_kind(question) is None, question


def test_the_off_topic_statement_names_what_the_assistant_can_answer_and_offers_guidance():
    text = sp.compose_statement(sp.KIND_OFF_TOPIC, building_name="Abacws Building")
    assert text.startswith("**That's outside what I can help with.**")
    for source in ("readings", "bookings", "work orders", "documents", "general building guidance"):
        assert source in text
    assert "joke" not in text.lower()


# ── what the building can say about the weather ─────────────────────────────


def test_outdoor_phrases_come_from_the_classes_the_graph_returned():
    rows = [
        {"cls": "https://brickschema.org/schema/Brick#Wind_Speed_Sensor"},
        {"cls": "https://brickschema.org/schema/Brick#Outside_Air_Temperature_Sensor"},
        {"cls": "https://brickschema.org/schema/Brick#Chiller"},  # not an outdoor class
    ]
    assert sp.phrases_from_rows(rows) == ["outdoor temperature", "wind speed"]


def test_the_query_asks_only_for_classes_the_table_can_name():
    query = sp.outdoor_classes_query()
    for cls, _phrase in sp.OUTDOOR_CLASSES:
        assert f"Brick#{cls}>" in query
    assert query.strip().upper().startswith("SELECT")  # read-only


def test_the_weather_statement_says_what_it_reads_now_and_that_it_holds_no_forecast():
    text = sp.compose_statement(
        sp.KIND_WEATHER_FORECAST,
        building_name="Abacws Building",
        outdoor=["outdoor temperature", "outdoor humidity", "wind speed"],
    )
    assert text.startswith("**I don't hold a weather forecast.**")
    assert "outdoor temperature, outdoor humidity and wind speed" in text
    assert "Abacws Building's outdoor sensors" in text
    assert "which location" not in text.lower() and "which city" not in text.lower()
    assert "?" in text and "outside temperature" in text  # the one question it offers


def test_a_building_with_no_outdoor_sensors_is_told_so_and_offers_nothing_it_lacks():
    text = sp.compose_statement(sp.KIND_WEATHER_FORECAST, building_name="X", outdoor=[])
    assert "records no outdoor conditions" in text
    assert "outside temperature" not in text


def test_the_financial_statement_names_what_the_assistant_can_answer_from():
    text = sp.compose_statement(sp.KIND_FINANCIAL_ADVICE, building_name="Abacws Building")
    assert text.startswith("**I can't advise on investments")
    for source in ("readings", "bookings", "work orders", "documents"):
        assert source in text
    assert "bitcoin" not in text.lower()


def test_no_statement_calls_the_building_data_synthetic_or_simulated():
    for kind in (sp.KIND_WEATHER_FORECAST, sp.KIND_FINANCIAL_ADVICE, ""):
        text = sp.compose_statement(kind, building_name="B", outdoor=["wind speed"]).lower()
        assert not any(w in text for w in ("synthetic", "simulated", "fake", "dummy"))


# ── the node ────────────────────────────────────────────────────────────────


class _Msg:
    def __init__(self, content):
        self.content = content


class _State:
    def __init__(self, question):
        self.messages = [_Msg(question)]
        self.intermediate_results = {}
        self.current_intent = ""
        self.building_id = None


async def test_the_node_writes_the_statement_into_the_response_slot_from_the_graph():
    async def run_select(query, limit=0):
        assert "VALUES ?cls" in query
        return {
            "ok": True,
            "rows": [{"cls": "https://brickschema.org/schema/Brick#Wind_Speed_Sensor"}],
        }

    state = await sp.scope_boundary_node(_State("Will it rain tomorrow?"), run_select=run_select)
    assert state.current_intent == sp.SCOPE_INTENT
    assert "wind speed" in state.intermediate_results["dialogue_response"]
    assert state.intermediate_results["scope_boundary"] == {
        "kind": sp.KIND_WEATHER_FORECAST,
        "outdoor": ["wind speed"],
    }


async def test_a_graph_that_cannot_be_read_still_gives_an_honest_statement():
    async def run_select(query, limit=0):
        raise RuntimeError("graphdb down")

    state = await sp.scope_boundary_node(_State("Will it rain tomorrow?"), run_select=run_select)
    text = state.intermediate_results["dialogue_response"]
    assert text.startswith("**I don't hold a weather forecast")
    assert "outside temperature" not in text  # it did not learn what is held, so it offers nothing


async def test_the_financial_node_never_touches_the_graph():
    async def run_select(query, limit=0):  # pragma: no cover - must not be called
        raise AssertionError("a financial question needs no graph read")

    state = await sp.scope_boundary_node(_State("Should I buy Bitcoin?"), run_select=run_select)
    assert state.intermediate_results["scope_boundary"]["kind"] == sp.KIND_FINANCIAL_ADVICE
