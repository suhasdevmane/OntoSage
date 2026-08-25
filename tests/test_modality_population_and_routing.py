# -*- coding: utf-8 -*-
"""A modality is a class set AND a label discriminator (2026-08-25).

Every failure fixed here has one shape: a population was identified by its Brick
class alone, and the class turned out to hold more than one quantity.

* ``Particulate_Matter_Sensor`` is the parent of PM1, PM2.5 and PM10, and on this
  building the TVOC sensors carry it too. Four quantities, one class — so the
  coverage audit answered a PM2.5 question with a PM10 sensor, against a different
  exposure limit.
* ``Occupancy_Count_Sensor`` covers both entry counters and parking bays, so the
  absence guard reported "257 parking_free sensor(s)" where there is exactly one,
  inside a sentence whose first words are "to be accurate about one thing".

The second half is about the questions reaching the right lane at all: a metered
quantity nobody had written into a phrase list was invisible to ``is_data_query``,
and the referent gate swallowed quantifiers into space names ("many parking").
"""

import re

import pytest

from orchestrator.services.deliberation.coverage_audit import (
    ModalitySpec,
    load_modalities,
)

pytestmark = pytest.mark.unit


# ── the pm25 population ──────────────────────────────────────────────────────
def _spec(name):
    for s in load_modalities(None):
        if s.name == name:
            return s
    raise AssertionError(f"modality {name!r} not in the shared config")


def test_pm25_declares_its_siblings_as_exclusions():
    """Without this list the parent class silently drags in PM1, PM10 and TVOC."""
    spec = _spec("pm25")
    assert "Particulate_Matter_Sensor" in spec.brick_classes
    lowered = {t.lower() for t in spec.label_excludes}
    assert "pm10" in lowered
    assert "tvoc" in lowered
    assert any(t.startswith("pm1") and t != "pm10" for t in lowered), spec.label_excludes


@pytest.mark.parametrize(
    "sensor_text,expected",
    [
        ("PM2.5 Level Sensor installed-node 5.01 PM2.5_Level_Sensor_Atmospheric_5.01", True),
        ("PM10 Level Sensor installed-node 5.01 PM10_Level_Sensor_Atmospheric_5.01", False),
        ("PM1 Level Sensor installed-node 5.01 PM1_Level_Sensor_Atmospheric_5.01", False),
        ("TVOC Level Sensor 5.01 TVOC_Level_Sensor_5.01", False),
    ],
)
def test_only_genuine_pm25_matches_the_pm25_modality(sensor_text, expected):
    assert _spec("pm25").matches("Particulate_Matter_Sensor", sensor_text) is expected


def test_exclusion_written_in_either_vocabulary_works():
    """The IRI form and the label form must both be honoured.

    The audit used to match on ``label OR local name``, so for any sensor carrying
    an rdfs:label the IRI was never seen and a rule written in the underscore form
    matched nothing at all — a rule that silently does nothing is worse than one
    that fails, because nobody goes looking for it.
    """
    spec = ModalitySpec(name="x", brick_classes=["C"], label_excludes=["pm1_"])
    assert spec.matches("C", "PM1_Level_Sensor_Atmospheric_5.01") is False
    spec2 = ModalitySpec(name="x", brick_classes=["C"], label_excludes=["pm1 "])
    assert spec2.matches("C", "PM1 Level Sensor installed-node 5.01") is False


def test_audit_matches_on_label_and_local_name_together():
    """The audit's text field must carry both forms, not one or the other."""
    import inspect

    from orchestrator.services.deliberation import coverage_audit

    src = inspect.getsource(coverage_audit)
    idx = src.index('"text":')
    window = src[idx : idx + 240]
    assert "label" in window and "_local(" in window, window
    # the give-away of the old behaviour was an `or` between the two
    assert not re.search(r'"text":\s*\(_val\(b,\s*"label"\)\s+or\s+_local', src)


# ── the absence-guard count ──────────────────────────────────────────────────
def test_count_query_restricts_to_the_modality_population():
    from orchestrator.services.absence_guard import _count_query

    q = _count_query(
        ("Parking_Occupancy_Sensor", "Occupancy_Count_Sensor"),
        "http://ns#",
        ("parking",),
        (),
    )
    assert 'CONTAINS(?text, "parking")' in q
    assert "rdf-schema#label" in q, "the label half of the identity is missing"
    assert "COUNT(DISTINCT ?s)" in q


def test_count_query_applies_exclusions_negatively():
    from orchestrator.services.absence_guard import _count_query

    q = _count_query(("Particulate_Matter_Sensor",), "http://ns#", (), ("pm10", "tvoc"))
    assert 'FILTER(!(CONTAINS(?text, "pm10") || CONTAINS(?text, "tvoc")))' in q


def test_count_query_unchanged_when_no_discriminator_declared():
    """A modality defined by class alone must not acquire an empty filter."""
    from orchestrator.services.absence_guard import _count_query

    q = _count_query(("Air_Temperature_Sensor",), "http://ns#", (), ())
    assert "?text" not in q


def test_label_filters_are_read_from_the_same_loader_as_the_classes():
    from orchestrator.services.modality_repair import modality_label_filters

    contains, excludes = modality_label_filters("pm25", None)
    assert "pm10" in {e.lower() for e in excludes}
    contains2, _ = modality_label_filters("parking_free", None)
    assert "parking" in {c.lower() for c in contains2}


def test_unknown_modality_yields_no_filters_rather_than_raising():
    from orchestrator.services.modality_repair import modality_label_filters

    assert modality_label_filters("not_a_modality", None) == ((), ())


# ── metered-quantity routing ─────────────────────────────────────────────────
def test_metered_vocabulary_comes_from_the_modality_config():
    from orchestrator.services.routing_contract import metered_vocabulary

    vocab = metered_vocabulary(None)
    assert "parking" in vocab
    assert "occupancy" in vocab
    # function words carried by modality NAMES must never become subjects
    assert "free" not in vocab
    assert "state" not in vocab


@pytest.mark.parametrize(
    "query,expected",
    [
        ("How many parking bays are free right now?", True),
        ("How many parking spaces are free?", True),
        ("How much water did we use last week?", True),
        # the quantity shape is required, so the noun alone never claims a question
        ("Where is the car park?", False),
        ("Is there parking available?", False),
        ("Tell me about the parking", False),
        ("", False),
    ],
)
def test_metered_quantity_question(query, expected):
    from orchestrator.services.routing_contract import metered_quantity_question

    assert metered_quantity_question(query) is expected


def test_is_data_query_covers_metered_quantities():
    """This predicate is the FIRST condition of the capability short-circuit
    bypass, so anything invisible to it is answered before the classifier runs."""
    from orchestrator.services.semantic_router import SemanticRouter

    assert SemanticRouter.is_data_query("How many parking bays are free right now?") is True
    assert SemanticRouter.is_data_query("Where is the car park?") is False
    assert SemanticRouter.is_data_query("What are the cafe opening hours?") is False


# ── the referent gate must not invent referents ──────────────────────────────
@pytest.mark.parametrize(
    "query",
    [
        "How many parking bays are free right now?",
        "How many parking spaces are free?",
        "Is there parking available?",
        "Are there any toilets on this floor?",
    ],
)
def test_quantifiers_never_become_part_of_a_space_name(query):
    """ "many parking" is not a place. Refusing a question about a referent nobody
    named is the same fabrication the gate exists to prevent."""
    from orchestrator.services.referent_resolver import detect_typed_referent

    ref = detect_typed_referent(query)
    if ref is not None:
        phrase = ref.phrase.lower()
        for stop in ("many", "much", "there", "any", "some"):
            assert not phrase.startswith(stop + " "), f"{query!r} -> {ref.phrase!r}"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is the temperature in the main corridor?", "main corridor"),
        ("How many sensors are on the helipad?", "helipad"),
    ],
)
def test_real_modifiers_are_still_kept(query, expected):
    from orchestrator.services.referent_resolver import detect_typed_referent

    ref = detect_typed_referent(query)
    assert ref is not None and ref.phrase.lower() == expected


# ── the SPARQL fallback must stay bounded ────────────────────────────────────
def test_pattern_fallback_never_scans_the_whole_store():
    """The zero-match case is the one that happens: this fallback only runs after
    a class query returned nothing, i.e. the LLM invented a class. An unbounded
    `?s ?p ?o` scan then reads every triple before returning empty — measured at
    29.98s per attempt against 0.61s for the bounded form."""
    import inspect

    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent.SPARQLAgent._fallback_pattern_search)
    # Comments describe the old shape on purpose — judge the CODE.
    code = "\n".join(line for line in src.split("\n") if not line.lstrip().startswith("#"))
    assert "?sensor a brick:Point" in code, "the scan is no longer bounded by class"
    assert "?sensor ?p ?o" not in code, "the unbounded scan is back"
    # the OPTIONAL joins cost more than the scan they rode on: they belong in a
    # second, VALUES-bound query, never in the probe
    probe = src[src.index("probe_query") : src.index("alt_query = probe_query")]
    assert "OPTIONAL" not in probe
