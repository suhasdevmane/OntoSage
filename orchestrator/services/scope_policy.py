# -*- coding: utf-8 -*-
"""What a building assistant does with a request that is not about the building (BUG-812).

The failure this prevents (tail A rows F39 and F40, 2026-09-18):

* "What's the weather forecast for tomorrow?" was answered *"which location would you like the
  forecast for? For example: your city, the Abacws building, or another place"* -- as though an
  assistant for one building could forecast weather anywhere;
* "Should I buy Bitcoin?" was answered with a paragraph of investment guidance from general model
  knowledge, in 98 seconds, with nothing to say it was not from the building's data.

THE POLICY (one place, so a supervisor gets the same answer twice; revised 2026-09-19 by the owner
to "answer MORE, honestly"):

* A request that needs a fact this assistant cannot ground (a forecast it has no source for) or
  that asks it to advise on a decision outside the building (an investment) gets a BRIEF, honest
  statement of what it can answer from -- never an apology, never a redirect question, never a
  guess.
* Building KNOWLEDGE that needs no building data ("how do I control CO2?", "what does a delta-T
  mean?") is NOT declined: it is answered as labelled general guidance (``guidance_shape`` decides
  the shape, ``general_guidance`` writes the answer). Only what is not about buildings at all --
  jokes, riddles, poems, trivia, coding help, translation, recipes, sport, entertainment -- gets
  the brief scope statement. Greetings and thanks are not requests and are left alone.
* The off-topic list is POSITIVE (shapes recognised, not "everything without a building word"), on
  purpose: an unrecognised question keeps the path it has today, where the document probe still
  gets its turn. A broader net would decline questions the building's own documents answer.
* Weather is checked against what the building HOLDS. Its outdoor sensors report current
  conditions, so a question about the future is declined and the statement names what it can
  read now; the names come from the graph, not from this file.

No LLM, no building literal: the shapes are English, the outdoor classes are Brick vocabulary.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: The intent this module's node serves.
SCOPE_INTENT = "scope_boundary"

KIND_WEATHER_FORECAST = "weather_forecast"
KIND_FINANCIAL_ADVICE = "financial_advice"

# ── the shapes ──────────────────────────────────────────────────────────────

#: The sky, as a person asks about it. Deliberately NOT "hot", "cold" or "warm": "will it be too
#: hot in Room 2.14 tomorrow?" is an indoor forecast the trend lane owns.
_SKY = r"sunny|rainy|snowy|cloudy|foggy|stormy|windy|icy"

#: A DIRECT request for a forecast, in the shapes people use. Each alternative is a request, not a
#: mention: the first draft matched any weather word near any future word and claimed ten stakeholder
#: questions that were not asking for a forecast at all -- "heavy rain and wind ARE FORECAST for my
#: visit, which entrance ...", "will tomorrow's weather AFFECT the public entrance", "forecast
#: Friday's cafe queue IF the weather is good". A premise, an effect and a condition are none of them
#: a request, and each is a negative case in the tests.
WEATHER_FORECAST_RE = re.compile(
    # the weather forecast / a rain forecast
    r"\b(?:weather|rain|snow|storm)\s+forecast\b"
    r"|\bforecast\s+(?:for\s+)?(?:the\s+)?(?:weather|rain|snow)\b"
    # will it rain tomorrow / is it going to snow / will it be sunny
    rf"|\bwill\s+(?:it|there)\s+(?:be\s+)?(?:rain|snow|{_SKY})\b"
    rf"|\bis\s+(?:it|there)\s+going\s+to\s+(?:be\s+)?(?:rain|snow|{_SKY})\b"
    # what will the weather be like next week / what's the weather tomorrow
    r"|\bwhat(?:'s|\s+is|\s+will|\s+would)\s+the\s+weather\b[^.?!]{0,40}"
    r"\b(?:tomorrow|tonight|weekend|next\s+\w+|later|be\s+like)\b"
    # how is the weather looking / is the weather going to be sunny
    rf"|\bhow(?:'s|\s+is|\s+will)\s+the\s+weather\s+(?:looking|going\s+to\s+be|be)\b"
    rf"|\b(?:is|will)\s+the\s+weather\s+(?:going\s+to\s+be|be|look)\b",
    re.IGNORECASE,
)

#: Instruments a person can be advised to buy, sell or hold. Deliberately financial ASSETS: "invest
#: in solar panels" and "is it worth replacing the boiler" are building decisions this assistant
#: can help with, and none of these words appears in them.
_ASSET = (
    r"bitcoin|btc|ethereum|crypto\w*|dogecoin|nfts?|stocks?|shares|equities|bonds?|etfs?|"
    r"mutual\s+funds?|forex|penny\s+stocks?|stock\s+market|ipo|index\s+funds?|options\s+trading"
)
_TRADE_VERB = r"buy|buying|sell|selling|invest(?:ing)?|trade|trading|short|hold|worth\s+(?:buying|investing)"

FINANCIAL_ADVICE_RE = re.compile(
    rf"\b(?:{_TRADE_VERB})\b[^.?!]{{0,40}}\b(?:{_ASSET})\b"
    rf"|\b(?:{_ASSET})\b[^.?!]{{0,40}}\b(?:a\s+good\s+(?:buy|investment)|worth\s+(?:buying|investing)"
    rf"|going\s+(?:up|down)|good\s+time\s+to\s+(?:buy|sell))\b",
    re.IGNORECASE,
)

KIND_OFF_TOPIC = "off_topic"
KIND_TRANSACTION = "transaction"
KIND_FAULT_TIMELINE = "fault_timeline"
KIND_PERSONAL_RECORD = "personal_record"
KIND_DISTANCE_COMPARISON = "distance_comparison"

#: A cross-system TIMELINE of a fault: "what is the most defensible event timeline for this
#: intermittent M&E fault across power, controls and plant states?". The building holds commissioning
#: records, incident logs and alarm events; it does not assemble a fault chronology, and the
#: capability lane answered with a list of commissioning dates from 2019 (tail K, 2026-09-20).
FAULT_TIMELINE_RE = re.compile(
    r"\b(?:(?:event\s+)?timeline|sequence\s+of\s+events|chronology)\b[^?.!]{0,80}"
    r"\b(?:intermittent|fault|failure|outage|incident|breakdown)\b"
    r"|\b(?:intermittent|fault|failure|outage|breakdown)\b[^?.!]{0,60}"
    r"\b(?:timeline|sequence\s+of\s+events|chronology)\b"
    r"|\bdefensible\b[^?.!]{0,30}\b(?:timeline|chronology|sequence)\b",
    re.IGNORECASE,
)

#: "summarise MY verified route, support contacts, recheck points and contingencies": a personal
#: itinerary the building does not hold. It was answered with advice about CO2 ventilation.
PERSONAL_RECORD_RE = re.compile(
    r"\b(?:summari[sz]e|recap|remind\s+me\s+of|read\s+back)\b[^?.!]{0,30}\bmy\s+(?:\w+\s+){0,3}"
    r"(?:route|itinerary|plan|contacts?|notes?|checklist|contingenc\w+|recheck\w*)\b",
    re.IGNORECASE,
)

#: "Are the steps closer to the elevators?": a comparison of DISTANCES between two kinds of place,
#: with no place named. The spatial lane answered "No lift spaces found."
DISTANCE_COMPARISON_RE = re.compile(
    r"\b(?:is|are)\s+(?:the\s+)?(?:\w+\s+){1,2}?(?:closer|nearer|further|farther)\s+(?:to|from)\b"
    r"(?!.*\b(?:room|floor)\s*\d|.*\b\d{1,2}\.\d{1,3}\b)",
    re.IGNORECASE,
)

#: A request that the ASSISTANT make, change or cancel something: "can you make reservations in the
#: cafe", "book me a room", "please reserve a table". The assistant reads this building's records
#: and does not transact, so the answer is a statement of that, not a list of bookings. A PROCEDURE
#: question ("how do I book a room?") and a user's own ability ("can I book a room?") are not this.
TRANSACTION_RE = re.compile(
    r"\b(?:can|could|will|would)\s+you\s+(?:please\s+)?(?:make|book|reserve|cancel|order|place|"
    r"arrange|purchase|buy)\b[^.?!]{0,50}\b(?:reservations?|bookings?|room|rooms|table|tables|"
    r"seat|seats|meeting|order|orders|appointments?|tickets?|space|lunch|food|coffee)\b"
    r"|\b(?:book|reserve)\s+(?:me|us)\s+(?:a|an|the|some)\b"
    r"|^\s*please\s+(?:book|reserve|cancel|order)\b"
    r"|\bmake\s+(?:me\s+|us\s+)?(?:a\s+)?(?:reservations?|bookings?)\b(?!\s+(?:data|records?|list))",
    re.IGNORECASE,
)

#: Requests that are not about buildings at all, recognised by SHAPE. A joke, a riddle, a poem, a
#: trivia frame, a coding request, a translation, a recipe, a sport or entertainment question.
#: Each entry needs the question to carry NO building-domain term, so "write a python script to plot
#: CO2" and "tell me a joke about HVAC" are not caught here.
OFF_TOPIC_RE = re.compile(
    r"\b(?:tell|say|give|crack)\s+(?:me\s+)?(?:a|an|another|one|some)\s+(?:\w+\s+){0,2}"
    r"(?:jokes?|riddles?|puns?|limericks?|stor(?:y|ies)|fairy\s*tales?|poems?|haiku|"
    r"fun\s+facts?)\b"
    r"|\bmake\s+me\s+laugh\b|\bknock[- ]knock\b|\bsing\s+(?:me\s+)?(?:a|the)\b"
    r"|\bwrite\s+(?:me\s+)?(?:a|an)\s+(?:poem|song|story|haiku|limerick|essay|joke)\b"
    r"|\bwhat(?:'s|\s+is)\s+the\s+capital\s+of\b"
    r"|\bwho\s+(?:is|was|were|are)\s+the\s+(?:current\s+)?(?:president|prime\s+minister|king|"
    r"queen|pope|richest)\b"
    r"|\bwho\s+(?:invented|discovered|wrote|painted|directed|composed|won\s+the)\b"
    r"|\bhow\s+(?:tall|old|far|big|deep)\s+is\s+(?:mount|the\s+(?:moon|sun|earth|eiffel|"
    r"great\s+wall))\b"
    r"|\bwhat\s+year\s+(?:did|was|were)\b"
    r"|\b(?:world\s+cup|olympics|premier\s+league|super\s+bowl|oscars?|grammys?|celebrit\w+|"
    r"horoscope|zodiac|recipe|lyrics)\b"
    r"|\bwrite\s+(?:me\s+)?(?:a|an|some)\s+(?:python|java|javascript|c\+\+|rust|bash|code|script|"
    r"function|program|regex|class)\b|\bdebug\s+(?:my|this)\s+code\b"
    r"|\btranslate\b[^.?!]{0,60}\b(?:into|to)\s+(?:french|spanish|german|italian|chinese|japanese|"
    r"welsh|latin|arabic|russian|portuguese)\b",
    re.IGNORECASE,
)


def _off_topic(question: str) -> bool:
    from orchestrator.services.guidance_shape import names_building_domain

    return bool(OFF_TOPIC_RE.search(question or "")) and not names_building_domain(question)


#: (kind, shape). Order matters only when two shapes could both match; none does today.
_SHAPES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (KIND_WEATHER_FORECAST, WEATHER_FORECAST_RE),
    (KIND_FINANCIAL_ADVICE, FINANCIAL_ADVICE_RE),
    (KIND_TRANSACTION, TRANSACTION_RE),
    (KIND_FAULT_TIMELINE, FAULT_TIMELINE_RE),
    (KIND_PERSONAL_RECORD, PERSONAL_RECORD_RE),
    (KIND_DISTANCE_COMPARISON, DISTANCE_COMPARISON_RE),
)


def out_of_scope_kind(question: str) -> Optional[str]:
    """The kind of out-of-scope request this is, or None when it is anything else."""
    q = question or ""
    for kind, shape in _SHAPES:
        if shape.search(q):
            return kind
    return KIND_OFF_TOPIC if _off_topic(q) else None


def weather_forecast_question(question: str) -> bool:
    """True for a request about FUTURE weather ("will it rain tomorrow?")."""
    return out_of_scope_kind(question) == KIND_WEATHER_FORECAST


def financial_advice_question(question: str) -> bool:
    """True for a request to advise on buying, selling or holding a financial asset."""
    return out_of_scope_kind(question) == KIND_FINANCIAL_ADVICE


# ── what the building can read about the weather ────────────────────────────

#: Brick class -> the phrase a person uses. Vocabulary, not a building: any Brick building that
#: types a point with one of these classes gets it named in the statement.
OUTDOOR_CLASSES: Tuple[Tuple[str, str], ...] = (
    ("Outside_Air_Temperature_Sensor", "outdoor temperature"),
    ("Outside_Air_Humidity_Sensor", "outdoor humidity"),
    ("Wind_Speed_Sensor", "wind speed"),
    ("Solar_Irradiance_Sensor", "solar irradiance"),
    ("Precipitation_Sensor", "precipitation"),
    ("Rain_Sensor", "rainfall"),
)

_BRICK = "https://brickschema.org/schema/Brick#"


def outdoor_classes_query() -> str:
    """One SELECT for which outdoor classes the graph actually has instances of."""
    values = " ".join(f"<{_BRICK}{cls}>" for cls, _ in OUTDOOR_CLASSES)
    return (
        "SELECT DISTINCT ?cls WHERE {\n"
        f"  VALUES ?cls {{ {values} }}\n"
        "  ?s a ?cls .\n"
        "} LIMIT 20"
    )


def phrases_from_rows(rows: Sequence[Any]) -> List[str]:
    """The outdoor phrases for the classes a SELECT returned, in the table's order."""
    held = set()
    for row in rows or []:
        value = row.get("cls") if isinstance(row, dict) else row
        if isinstance(value, dict):
            value = value.get("value")
        if value:
            held.add(str(value).rsplit("#", 1)[-1].rsplit("/", 1)[-1])
    return [phrase for cls, phrase in OUTDOOR_CLASSES if cls in held]


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


# ── the statements ──────────────────────────────────────────────────────────


def compose_statement(
    kind: str, *, building_name: str = "this building", outdoor: Sequence[str] = ()
) -> str:
    """The brief, honest statement for one kind of out-of-scope request."""
    name = building_name or "this building"
    if kind == KIND_WEATHER_FORECAST:
        if outdoor:
            return (
                "**I don't hold a weather forecast.** "
                f"{name}'s outdoor sensors report what the weather is doing now — "
                f"{_join(outdoor)} — not what it will do tomorrow.\n\n"
                'Ask for one of those, for example *"what is the outside temperature?"*, and I '
                "will answer from its latest reading."
            )
        return (
            "**I don't hold a weather forecast**, and this building records no outdoor conditions "
            "I can read, so I can't say what the weather is doing either."
        )
    if kind == KIND_FINANCIAL_ADVICE:
        return (
            "**I can't advise on investments or other financial decisions.** "
            f"I'm the assistant for {name}: I answer from its own data — live readings and "
            "trends, rooms and equipment, bookings, work orders, compliance records and its "
            "documents. Ask me about any of those."
        )
    if kind == KIND_FAULT_TIMELINE:
        return (
            f"**I don't hold a fault timeline for {name}.** What its records do hold is "
            "commissioning records, incident logs and alarm events, each dated on its own, and I "
            "won't stitch them into a chronology of one intermittent fault — that would be a "
            "judgement, not a record. Ask for one of those directly, for example *which alarms "
            "were raised this week?* or *what incidents are logged for the chiller?*"
        )
    if kind == KIND_PERSONAL_RECORD:
        return (
            f"**I don't hold a personal itinerary, contact list or plan of yours.** {name}'s "
            "records describe the building, not your journey, so there is nothing of yours to "
            "summarise. What I can give is the building's own information: a route between two "
            "places (*route from the main entrance to room 2.14*), who to contact (*who do I "
            "contact about a fault?*) or what to do in an emergency."
        )
    if kind == KIND_DISTANCE_COMPARISON:
        return (
            "**I can't compare distances between kinds of place.** \"Closer\" needs two named "
            "places to measure from, and this asks about all of them at once. Ask for the "
            "distance or route from one named place to another (*route from room 2.14 to the "
            "nearest lift*) and I will give the walking route and its length."
        )
    if kind == KIND_TRANSACTION:
        return (
            "**I can't make, change or cancel bookings or place orders** — I read "
            f"{name}'s records; I don't act on them, so nothing has been reserved. What I can do is "
            "tell you what is booked or free: try *which rooms are free right now?* or *is a "
            "particular room booked this afternoon?*"
        )
    return (
        f"**That's outside what I can help with.** I'm the assistant for {name}: I answer from "
        "its own data — readings and trends, rooms and equipment, bookings, work orders, "
        "compliance records and documents — and I can give general building guidance, clearly "
        "labelled as such. Ask me about any of those."
    )


RunSelect = Callable[..., Awaitable[Any]]


async def outdoor_phrases(run_select: Optional[RunSelect] = None) -> List[str]:
    """What this building's graph can say about outdoor conditions; [] when it says nothing."""
    try:
        if run_select is None:
            from orchestrator.services.evidence.spatial_facts import default_run_select

            run_select = default_run_select
        res = await run_select(outdoor_classes_query(), limit=20)
        if isinstance(res, dict):
            if res.get("ok") is False:
                return []
            res = res.get("rows") or []
        return phrases_from_rows(res)
    except Exception as exc:
        logger.debug(f"[scope_boundary] outdoor classes unavailable: {exc}")
        return []


async def scope_boundary_node(state: Any, run_select: Optional[RunSelect] = None) -> Any:
    """Write the scope statement for this turn's question into the dialogue-response slot."""
    question = state.messages[-1].content if getattr(state, "messages", None) else ""
    kind = out_of_scope_kind(question) or ""
    logger.info(f"[scope_boundary] kind={kind or 'unclassified'} q={question[:60]!r}")

    building_name = "this building"
    try:
        from orchestrator.services.building_context import resolve_building_context
        from shared.config import settings

        building_name = (
            resolve_building_context(getattr(state, "building_id", None) or settings.BUILDING_ID).name
            or building_name
        )
    except Exception as exc:  # pragma: no cover - the generic name is a sane fallback
        logger.debug(f"[scope_boundary] building name unavailable: {exc}")

    outdoor: List[str] = []
    if kind == KIND_WEATHER_FORECAST:
        outdoor = await outdoor_phrases(run_select)

    state.intermediate_results["dialogue_response"] = compose_statement(
        kind, building_name=building_name, outdoor=outdoor
    )
    state.intermediate_results["scope_boundary"] = {"kind": kind, "outdoor": list(outdoor)}
    state.current_intent = SCOPE_INTENT
    return state


__all__: List[str] = [
    "KIND_FINANCIAL_ADVICE",
    "KIND_OFF_TOPIC",
    "KIND_TRANSACTION",
    "KIND_FAULT_TIMELINE",
    "KIND_PERSONAL_RECORD",
    "KIND_DISTANCE_COMPARISON",
    "KIND_WEATHER_FORECAST",
    "OUTDOOR_CLASSES",
    "SCOPE_INTENT",
    "compose_statement",
    "financial_advice_question",
    "out_of_scope_kind",
    "outdoor_phrases",
    "scope_boundary_node",
    "weather_forecast_question",
]

