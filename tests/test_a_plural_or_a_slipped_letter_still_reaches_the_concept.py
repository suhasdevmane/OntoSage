"""A lay term reaches its concept in the plural and through one slipped letter — and nowhere else.

The resolver matched every lay term as an EXACT whole word, so the vocabulary reached only the
form the mapping happened to list. Measured 2026-09-19 over the 10,339-question pool: 166
questions that reached no concept reach one once the LAST word of a term may be plural
("the lifts", "temperatures", "light levels", "VOCs"), and 44 more once a slipped letter is
repaired ("ennergy use", "occupany levels", "temprature", "ventilaton").

The repair is deliberately narrow, because a repair that turns one real word into another is
worse than no repair: it looks only at words the concept vocabulary already contains, refuses a
changed letter ("seating" is not "heating"), a different ending ("measured" is not "measure") and
any short word, and never repairs a word that two vocabulary words claim.
"""

import asyncio
import csv
import re
from pathlib import Path
from typing import Dict, List

import pytest
import rdflib

from orchestrator.services.concept_resolver import (
    ConceptResolver,
    _one_slip_apart,
    _term_regex,
    _vocabulary_words,
    repair_slips,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
HBCO = "http://ontosage.org/hbco#"


def _map(**terms: List[str]) -> Dict[str, dict]:
    return {
        cid: {"concept_id": cid, "lay_terms": lay, "brick_classes": ["brick:Sensor"]}
        for cid, lay in terms.items()
    }


def _resolve(concept_map: Dict[str, dict], text: str) -> List[str]:
    resolver = ConceptResolver()

    async def _load() -> Dict[str, dict]:
        return concept_map

    resolver._load_concept_map = _load  # type: ignore[method-assign]
    return [m.concept_id for m in asyncio.run(resolver.resolve(text))]


# ── plurals ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "are the lifts working",
        "Are there elevators and if so enough of them",
        "what were the temperatures on floor 3",
        "how do I reduce exposure to VOCs in this space",
        "are light levels adequate at the desks",
        "which meeting rooms are booked",
    ],
)
def test_the_plural_of_a_lay_terms_last_word_reaches_the_concept(text):
    concept_map = _map(
        lift=["lift", "elevator"],
        temp=["temperature"],
        voc=["voc"],
        light=["light level"],
        booked=["booked"],
    )
    assert _resolve(concept_map, text), text


def test_a_plural_never_matches_inside_a_longer_word():
    concept_map = _map(hot=["hot"], lift=["lift"])
    assert _resolve(concept_map, "I took a shot at cohort 3") == []
    assert _resolve(concept_map, "the box was lifted onto the shelf") == []


def test_a_term_ending_in_y_matches_its_ies_plural_only_when_long_enough():
    assert _term_regex("humidity").search("the humidities differ")
    assert _term_regex("occupancy").search("occupancies rise at noon")
    # too short to trust: "dry" -> "dries" is a verb about paint, not a humidity question
    assert not _term_regex("dry").search("the paint dries slowly")


def test_a_term_that_does_not_end_in_a_letter_takes_no_plural():
    assert _term_regex("pm2.5").search("what is pm2.5 today")
    assert not _term_regex("pm2.5").search("pm2.5s")


# ── one slipped letter ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "typo,word",
    [
        ("ennergy", "energy"),  # a doubled letter, in a six-letter word
        ("carbno", "carbon"),  # two letters swapped
        ("temprature", "temperature"),  # a dropped letter, in a long word
        ("occupany", "occupancy"),
        ("ventilaton", "ventilation"),
        ("emisions", "emissions"),  # an un-doubled letter
        ("temperaure", "temperature"),
        ("controll", "control"),  # a doubled final letter
    ],
)
def test_a_slip_of_one_letter_is_repaired_into_the_vocabulary_word(typo, word):
    assert _one_slip_apart(typo, word)
    assert repair_slips(f"how is the {typo} here", frozenset({word})) == f"how is the {word} here"


def test_a_slipped_word_reaches_the_concept_through_the_resolver():
    concept_map = _map(energy=["energy use"], occupancy=["occupancy"], air=["carbon monoxide"])
    assert _resolve(concept_map, "how do weekends compare for ennergy use") == ["energy"]
    assert _resolve(concept_map, "are fans adjusting on occupany levels") == ["occupancy"]
    assert _resolve(concept_map, "what is the carbno monoxide reading") == ["air"]


@pytest.mark.parametrize(
    "word,other",
    [
        ("seating", "heating"),  # a CHANGED letter turns one real word into another
        ("measured", "measure"),  # a different ENDING is an inflection, not a slip
        ("chargers", "charges"),  # a dropped letter, but the vocabulary word is short
        ("portable", "potable"),
        ("contract", "contact"),
        ("evaluation", "evacuation"),
        ("sheltering", "sweltering"),
        ("consumers", "consumes"),  # an extra letter inside the ENDING
    ],
)
def test_a_real_word_one_edit_from_the_vocabulary_is_never_repaired(word, other):
    assert not _one_slip_apart(word, other)
    assert repair_slips(f"the {word} here", frozenset({other})) == f"the {word} here"


@pytest.mark.parametrize("real", ["binding", "lightning", "dipping"])
def test_a_real_word_the_bank_showed_the_repair_touching_is_denied_by_name(real):
    vocab = frozenset({"blinding", "lighting", "dripping"})
    assert repair_slips(f"a {real} thing", vocab) == f"a {real} thing"


def test_a_word_claimed_by_two_vocabulary_words_is_left_alone():
    # "stardom" is a doubled letter from "starddom" AND a swap from "satrdom": which was meant?
    assert repair_slips("a stardom here", frozenset({"starddom"})) == "a starddom here"
    both = frozenset({"starddom", "satrdom"})
    assert repair_slips("a stardom here", both) == "a stardom here"


def test_a_word_far_from_the_vocabulary_is_untouched_and_short_words_are_never_looked_at():
    vocab = frozenset({"temperature", "energy"})
    assert repair_slips("the projector is off", vocab) == "the projector is off"
    assert repair_slips("the engy is low", vocab) == "the engy is low"  # under six letters
    assert repair_slips("anything at all", frozenset()) == "anything at all"


def test_the_vocabulary_is_the_words_of_the_lay_terms_and_nothing_else():
    concept_map = _map(a=["too warm", "stale air", "energy use"], b=["temperature"])
    assert _vocabulary_words(concept_map) == frozenset({"energy", "temperature"})


def test_an_unrepaired_question_resolves_exactly_as_before():
    concept_map = _map(hot=["hot"], stuffy=["stale air", "stuffy"])
    assert _resolve(concept_map, "the stale air is stuffy today") == ["stuffy"]
    assert _resolve(concept_map, "nothing relevant here") == []


# ── against the real vocabulary and the tracked question bank ────────────────────────────────


def _real_vocabulary() -> Dict[str, dict]:
    graph = rdflib.Graph()
    graph.parse(str(REPO / "ontology" / "hbco_mappings.ttl"), format="turtle")
    by_concept: Dict[str, dict] = {}
    for subject, term in graph.subject_objects(rdflib.URIRef(HBCO + "layTerm")):
        entry = by_concept.setdefault(
            str(subject), {"concept_id": str(subject).split("#")[-1], "lay_terms": []}
        )
        entry["lay_terms"].append(str(term).lower())
    return by_concept


def _tracked_questions() -> List[str]:
    with open(REPO / "docs" / "smart_building_questions.csv", encoding="utf-8-sig") as fh:
        return [row["Question"] for row in csv.DictReader(fh)]


def test_no_repair_fires_on_the_tracked_catalogue_and_synthetic_bank():
    """4,060 professionally written questions contain no typos, so every repair here would be a
    real word turned into another — the one this test found ("binding constraint" -> "blinding")
    is what put `binding` on the deny list."""
    vocab = _vocabulary_words(_real_vocabulary())
    assert len(vocab) > 150, "the real vocabulary did not load"
    changed = []
    for question in _tracked_questions():
        lowered = question.lower()
        if repair_slips(lowered, vocab) != lowered:
            changed.append(question[:90])
    assert not changed, f"a repair changed a well-formed question: {changed[:5]}"


def test_the_real_vocabulary_has_the_long_words_people_misspell():
    vocab = _vocabulary_words(_real_vocabulary())
    for word in ("temperature", "occupancy", "ventilation", "humidity", "emissions"):
        assert word in vocab
    assert re.fullmatch(r"[a-z]+", "".join(sorted(vocab)))
