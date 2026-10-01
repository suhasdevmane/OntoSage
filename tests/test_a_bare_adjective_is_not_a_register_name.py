# -*- coding: utf-8 -*-
"""BUG-1291: "clean energy" is not the cleaning register, "humidity detection" is not fire.

Tail N, 60 unseen questions from the real survey corpus, asked live as an occupant through
``/v1`` streaming on 2026-09-30:

* *"are EV chargers powered by clean energy?"* → **"The cleaning task register (30 records)
  cannot answer this: it records cleaning zone, location, service frequency and shift name,
  and nothing about chargers, energy and powered."**
* *"Could the humidity detection be tied in with the water sensors to more accurately tell if
  there are water/leakage issues?"* → a list of six FIRE-ALARM zone assets.

One bare lay term did each of these, and the consequence is larger than a wrong register.
``held_record_class`` is a ROUTING SHORT-CIRCUIT: the container log for the first question is

    [ttl-route] metadata via held record class: CleaningTask (30 instances)
                — skipping LLM intent call

so a four-letter adjective decided the entire turn before any classification ran.

THE FIX IS IN THE TBOX, NOT IN THE SCORER (design contract 2). ``ontosage:CleaningTask``
declared a bare ``"clean"`` and ``ontosage:FireSafetyAsset`` a bare ``"detection"``; both are
removed, ``"cleaned"`` and six ``"<x> detection"`` phrases are declared in their place.

MEASURED before the edit over 2,960 stakeholder-catalogue questions and 7,151 real survey
questions — 49 selections move, 39 of them from a wrong register to none or to the right one,
4 broken, and the 124-question guard set stays at 0 violations. The figures and the readings
are on the two layTerms lines in ``ontology/ontosage_schema.ttl``.

This test reads the vocabulary FROM THAT FILE, so re-adding either bare term fails here.
"""

import re
from pathlib import Path

import pytest

from orchestrator.services.record_registry import (
    RecordClass,
    _terms_for,
    rank_record_classes,
)

pytestmark = pytest.mark.unit

SCHEMA = Path(__file__).resolve().parents[1] / "ontology" / "ontosage_schema.ttl"

#: (class, rdfs:label, instance count as the live building holds them) for the classes under
#: test plus the neighbours a moved question could land on instead.
_UNDER_TEST = {
    "CleaningTask": ("Cleaning task", 30),
    "FireSafetyAsset": ("Fire safety asset", 30),
    "AlarmEvent": ("Alarm event", 270),
    "WasteCollectionPoint": ("Waste collection point", 24),
    "SustainabilityTarget": ("Sustainability target", 8),
}


def _declared_lay_terms(local_name: str) -> str:
    """The class's ``ontosage:layTerms`` from the schema TTL, as GraphDB would hand them over.

    Read from the file rather than restated here: the point of the test is that the TBox is
    where this vocabulary lives, so a test carrying its own copy would pass after a revert.
    """
    text = SCHEMA.read_text(encoding="utf-8")
    match = re.search(
        rf"^ontosage:{local_name}\s+ontosage:layTerms\s+(.*?)\s*\.\s*$",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"{local_name} declares no layTerms in {SCHEMA.name}"
    body = re.sub(r"#[^\n]*", "", match.group(1))  # strip trailing comments, keep the literals
    return "|".join(re.findall(r'"([^"]+)"', body))


@pytest.fixture(scope="module")
def classes():
    out = []
    for name, (label, count) in _UNDER_TEST.items():
        out.append(
            RecordClass(name, label, count, _terms_for(name, label, _declared_lay_terms(name)))
        )
    return out


def _top(question, classes):
    ranked = rank_record_classes(question, classes)
    return ranked[0][1].local_name if ranked else None


# ── the two live failures, verbatim ──────────────────────────────────────────────────────


def test_clean_energy_is_not_the_cleaning_register(classes):
    assert _top("are EV chargers powered by clean energy?", classes) != "CleaningTask"


def test_humidity_detection_is_not_a_fire_safety_asset(classes):
    question = (
        "Could the humidity detection be tied in with the water sensors to more accurately "
        "tell if there are water/leakage issues?"
    )
    assert _top(question, classes) != "FireSafetyAsset"


# ── the bare terms themselves, so a revert cannot pass quietly ───────────────────────────


@pytest.mark.parametrize(
    "local_name, bare",
    [("CleaningTask", "clean"), ("FireSafetyAsset", "detection")],
)
def test_the_bare_term_stays_out_of_the_tbox(local_name, bare):
    terms = _declared_lay_terms(local_name).split("|")
    assert bare not in terms, (
        f"{local_name} declares a bare {bare!r} again. It was removed after measuring 49 "
        "moves over 2,960 catalogue + 7,151 survey questions; re-add it only with a newer "
        "measurement, not on intuition."
    )


# ── what the removal must NOT cost: every one of these is a REAL question from the two
#    corpora that the edit was checked against ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        # preserved by "smoke detection", which is why the term was replaced and not just dropped
        "can i see which areas areas related to fire safty or smoke detection?",
        "when was the smoke detection system last tested?",
    ],
)
def test_fire_detection_phrases_still_reach_the_fire_register(question, classes):
    assert _top(question, classes) == "FireSafetyAsset"


@pytest.mark.parametrize(
    "question",
    [
        # gained by "cleaned": seven questions this register exists for and could not reach,
        # because the scorer matches \b<term>\b and "cleaning" does not span "cleaned".
        "When was the restroom cleaned?",
        "how often is this area cleaned or sanitized?",
        "When was the last time the lobby was cleaned?",
        "how often are the filters cleaned and maintained?",
    ],
)
def test_cleaned_reaches_the_cleaning_register(question, classes):
    assert _top(question, classes) == "CleaningTask"


@pytest.mark.parametrize(
    "question",
    [
        # the 11 air-quality questions six separate survey participants asked, every one of
        # which selected the CLEANING register before this edit
        "air clean?",
        "Is the air clean?",
        "is the air clean and safe to breathe?",
        "How clean is the indoor air compared to outdoor air today?",
        # the gas, motion and chemical questions that selected the FIRE register
        "is the gas detection sensor in the kitchen reading normal?",
        "Is it possible to disable motion detection in certain areas?",
    ],
)
def test_an_adjective_or_a_sensor_kind_selects_no_register(question, classes):
    assert _top(question, classes) not in ("CleaningTask", "FireSafetyAsset")
