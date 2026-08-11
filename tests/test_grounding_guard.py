"""BUG-103 — grounding guard + typed referent gate.

Two independent fabrication paths are covered:

* **Document path** — a vector hit that is topically unrelated must not be presented
  as an answer (the cosine floor alone is embedding-model dependent).
* **Data path** — a floor / named space / equipment / measurand that the building's
  model does not contain must not collect another entity's readings.

Every assertion is building-agnostic and offline: the graph is a stub, and a source
scan proves neither module hardcodes any building's vocabulary.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services import grounding_guard as gg
from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Lexical topicality (document path)
# ─────────────────────────────────────────────────────────────────────────────


def test_content_terms_drops_stopwords_and_singularises():
    terms = gg.content_terms("What are the CO2 readings for the sensors?")
    assert "co2" in terms
    assert "sensor" in terms  # 'sensors' singularised
    for filler in ("what", "are", "the", "for", "readings"):
        assert filler not in terms


def test_on_topic_passage_is_kept():
    assert gg.is_on_topic(
        "What does the wifi policy say about guest access?",
        "Guests connect to the BuildSys-Guest wifi network using a voucher.",
    )


def test_off_topic_passage_is_rejected():
    """The exact BUG-103 shape: a real HVAC table 'answering' a pH question."""
    assert not gg.is_on_topic(
        "What is the pH level of the water tank?",
        "CO2 < 800 ppm (occupied); > 1000 ppm triggers damper opening. Temperature 21-23 C.",
    )


def test_extra_vocab_rescues_lay_term_paraphrase():
    """A concept-resolver synonym ('stuffy' → CO2) must not be rejected as off-topic."""
    q, passage = "Why is it so stuffy in here?", "CO2 above 1000 ppm indicates poor ventilation."
    assert not gg.is_on_topic(q, passage)
    assert gg.is_on_topic(q, passage, extra_vocab=["co2"])


def test_is_on_topic_fails_open_on_contentless_query():
    assert gg.is_on_topic("tell me more", "any passage at all")


def test_filter_on_topic_drops_only_unrelated_hits():
    hits = [
        {"text": "The swimming pool is open 07:00-21:00."},
        {"text": "CO2 thresholds for the air handling unit."},
    ]
    kept = gg.filter_on_topic("Is the swimming pool open today?", hits)
    assert len(kept) == 1 and "swimming pool" in kept[0]["text"]


def test_enablement_hint_is_actionable_per_subject():
    sensor = gg.enablement_hint(gg.SUBJECT_SENSOR, "methane")
    assert "ref:hasTimeseriesId" in sensor and "ref:storedAt" in sensor
    assert "no code changes" in sensor.lower()
    space = gg.enablement_hint(gg.SUBJECT_SPACE, "west wing")
    assert "ontosage:Amenity" in space or "hasPart" in space
    doc = gg.enablement_hint(gg.SUBJECT_DOCUMENT)
    assert "documents" in doc.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Typed referent detection (data path)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,kind,phrase",
    [
        ("How many sensors are on floor 42?", rr.KIND_FLOOR, "floor 42"),
        ("What is the temperature on the 7th floor?", rr.KIND_FLOOR, "floor 7"),
        ("Show me the swimming pool water temperature", rr.KIND_SPACE, "swimming pool"),
        ("What is the average temperature in the west wing?", rr.KIND_SPACE, "west wing"),
        ("Noise level in the rooftop garden?", rr.KIND_SPACE, "rooftop garden"),
        ("When was chiller 7 last serviced?", rr.KIND_EQUIPMENT, "chiller 7"),
        ("Plot the methane concentration for last week", rr.KIND_MEASURAND, "methane"),
    ],
)
def test_typed_referent_detection(query, kind, phrase):
    ref = rr.detect_typed_referent(query)
    assert ref is not None, f"no referent detected in: {query}"
    assert ref.kind == kind and ref.phrase == phrase


@pytest.mark.parametrize(
    "query",
    [
        "How many floors are there?",  # no specific floor named
        "What is the temperature?",  # no referent at all
        "List all zones",
        "Is it too warm in here?",
    ],
)
def test_no_false_positive_referents(query):
    assert rr.detect_typed_referent(query) is None


# ─────────────────────────────────────────────────────────────────────────────
# Typed resolution against a stub graph
# ─────────────────────────────────────────────────────────────────────────────

NS = "http://example.org/anybuilding#"


def _graph(uris):
    """Stub SPARQL exec: matches when every term appears in a known URI's LOCAL name.

    Mirrors the real query, which compares against ?local (URI minus namespace) so a
    term that sits in the namespace itself cannot match every subject — the fix for
    "Building 47" resolving against the abacwsbuilding.cardiff.ac.uk namespace.
    """

    async def _exec(q: str) -> dict:
        import re as _re

        terms = [t.lower() for t in _re.findall(r'CONTAINS\(\?local, "([^"]+)"\)', q)]
        if not terms:
            return {"results": {"bindings": []}}
        # Compare against the local name only, matching the SUBSTR in the real query.
        # Existence needs ALL terms on one subject; suggestion needs ANY (one term).
        combine = all if "SELECT ?s WHERE" in q else any
        hits = [u for u in uris if combine(t in u.rsplit("#", 1)[-1].lower() for t in terms)]
        return {"results": {"bindings": [{"s": {"value": u}} for u in hits]}}

    return _exec


@pytest.mark.asyncio
async def test_existing_floor_resolves_and_passes_through():
    resolver = rr.ReferentResolver(_graph([NS + "Floor2", NS + "Floor3"]))
    res = await resolver.resolve("What is the temperature on floor 2?", [], NS, "Any Building")
    assert res.status == rr.RESOLVED


@pytest.mark.asyncio
async def test_absent_floor_is_refused_with_real_floors_and_guidance():
    resolver = rr.ReferentResolver(_graph([NS + "Floor2", NS + "Floor3"]))
    res = await resolver.resolve("How many sensors are on floor 42?", [], NS, "Any Building")
    assert res.status == rr.NOT_FOUND
    assert "floor 42" in res.message
    assert "Floor2" in res.message or "Floor3" in res.message  # suggests what DOES exist
    assert "no code changes" in res.message.lower()  # enablement guidance present


@pytest.mark.asyncio
async def test_absent_amenity_is_refused_and_never_substitutes():
    resolver = rr.ReferentResolver(_graph([NS + "Chilled_Water_Temp_Sensor"]))
    res = await resolver.resolve("Show me the swimming pool temperature", [], NS, "Any Building")
    assert res.status == rr.NOT_FOUND
    assert "swimming pool" in res.message


@pytest.mark.asyncio
async def test_absent_measurand_refuses_without_substituting_another_metric():
    resolver = rr.ReferentResolver(_graph([NS + "CO2_Level_Sensor_1"]))
    res = await resolver.resolve("Plot the methane concentration", [], NS, "Any Building")
    assert res.status == rr.NOT_FOUND
    assert "methane" in res.message
    assert "won’t substitute" in res.message or "won't substitute" in res.message


@pytest.mark.asyncio
async def test_gate_fails_open_when_graph_is_unavailable():
    async def _boom(_q):
        raise RuntimeError("GraphDB unreachable")

    resolver = rr.ReferentResolver(_boom)
    res = await resolver.resolve("temperature on floor 42?", [], NS, "Any Building")
    assert res.status == rr.SKIPPED  # never blocks a query on infrastructure failure


# ─────────────────────────────────────────────────────────────────────────────
# Portability
# ─────────────────────────────────────────────────────────────────────────────


def test_modules_contain_no_building_literals():
    for mod in (gg, rr):
        src = inspect.getsource(mod).lower()
        for literal in ("abacws", "bldg1", "bldg2", "bldg3", "cardiff", "buildsys"):
            assert literal not in src, f"building literal '{literal}' in {mod.__name__}"


def test_count_and_listing_intents_are_gated():
    """'how many sensors on floor 42' is a COUNT — it must be gated too (BUG-103)."""
    assert "metadata" in rr.GATED_INTENTS
    assert "discovery" in rr.GATED_INTENTS


# ── inflection: a question and its document rarely inflect the same way ──────


def test_a_past_tense_question_matches_a_present_tense_document():
    """ "when was it last SERVICED" against a log saying "SERVICING activity …
    SERVICE dates" shared no term at all, so the passage was judged off-topic and
    the answer became "I don't have that information" while the document said it."""
    passage = (
        "Maintenance and servicing activity for building equipment is recorded in the "
        "maintenance log, which covers service dates and work carried out."
    )
    assert gg.is_on_topic("When was equipment last serviced?", passage) is True


@pytest.mark.parametrize(
    "a,b",
    [
        ("serviced", "servicing"),
        ("service", "serviced"),
        ("booked", "booking"),
        ("sensors", "sensor"),
    ],
)
def test_inflections_of_one_word_share_a_stem(a, b):
    assert gg._singular(a) == gg._singular(b)


@pytest.mark.parametrize("word", ["fire", "water", "use", "zone", "lift"])
def test_short_words_are_not_collapsed_by_stemming(word):
    """Over-stemming would make unrelated short words collide and let any passage
    answer any question — the opposite failure."""
    assert gg._singular(word) == word


def test_stemming_does_not_make_an_unrelated_passage_on_topic():
    passage = (
        "Maintenance and servicing activity for building equipment is recorded in the "
        "maintenance log, which covers service dates and work carried out."
    )
    assert gg.is_on_topic("what is the pH of the water tank?", passage) is False


# ── does the passage contain the KIND of fact asked for? (CAVEAT-108) ────────


def test_a_date_question_answered_without_a_date_is_flagged():
    """ "when was chiller 7 last serviced?" returns HVAC prose that genuinely
    discusses chillers and contains no date. Printed plainly it reads as the
    answer; naming what is missing makes it an honest partial one."""
    passage = "Chillers are maintained under the HVAC operations plan by the estates team."
    caveat = gg.missing_fact_caveat("When was chiller 7 last serviced?", passage)
    assert caveat is not None
    assert "date" in caveat.lower()


@pytest.mark.parametrize(
    "passage",
    [
        "Chiller 7 was last serviced on 2026-03-14 by the estates team.",
        "Last service: 14 March 2026.",
        "Serviced Mar 2026 under contract.",
    ],
)
def test_a_date_question_answered_with_a_date_is_not_flagged(passage):
    assert gg.missing_fact_caveat("When was chiller 7 last serviced?", passage) is None


def test_a_quantity_question_answered_without_a_number_is_flagged():
    passage = "Sensors are distributed across the building according to the coverage plan."
    caveat = gg.missing_fact_caveat("How many sensors are on floor 2?", passage)
    assert caveat is not None
    assert "figure" in caveat.lower()


def test_a_quantity_question_answered_with_a_number_is_not_flagged():
    assert (
        gg.missing_fact_caveat("How many sensors are on floor 2?", "There are 12 sensors.") is None
    )


@pytest.mark.parametrize(
    "query",
    ["What is the wifi policy?", "Where is the prayer room?", "Is there a cafe?"],
)
def test_a_question_asking_for_no_particular_fact_kind_is_silent(query):
    """A caveat on every answer would be noise that teaches users to ignore it."""
    assert gg.missing_fact_caveat(query, "The prayer room is on floor 1.") is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_input_is_silent(blank):
    assert gg.missing_fact_caveat(blank, "some passage") is None
    assert gg.missing_fact_caveat("when was it serviced?", blank) is None
