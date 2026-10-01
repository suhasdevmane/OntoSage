# -*- coding: utf-8 -*-
"""What to say when a question could not be answered, in the shape the question actually had.

Wave-1 development read: *"I couldn't answer that from Abacws Building's records. Which measurement
or record do you mean by **specialist** / **whole** / **weather**?"* is still machine-shaped. The
questions were not missing a measurement. "Does the verified timeline support the stated root cause,
what alternatives remain plausible, and which specialist evidence is still needed?" is an abstract,
multi-part question, and one odd word plucked from it and quoted back as though it were a field
asks the reader to translate a parser's guess.

Three shapes, three answers (all pure; the caller supplies what the building holds):

* **weather, outdoors, now** -- "I don't hold an outdoor forecast", then the outdoor readings the
  building DOES record, with the time of each. A forecast is Agent C's scope statement; this is the
  present-tense half.
* **a genuinely missing referent** -- "the incident", "this service", "that contract": ask WHICH,
  once, naming the record kinds the building holds that could be it. A referent is a definite noun
  from a short generic list, in a short question.
* **an abstract, multi-part question** -- never a question back. Say what came back nothing (as a
  phrase from the question, never one bare word), and list the two or three nearest things the
  building CAN answer, so the reader can pick one.

Nothing claims the building lacks the data: not answering and not holding are different facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from orchestrator.services.absence_wording import _singular
from orchestrator.services.fallback_wording import _close, and_list, nearest_holdings
from orchestrator.services.grounding_guard import content_terms

KIND_WEATHER = "weather"
KIND_REFERENT = "referent"
KIND_ABSTRACT = "abstract"
KIND_PLAIN = "plain"

# ── weather ──────────────────────────────────────────────────────────────────────────────────

_WEATHER = re.compile(
    r"\b(?:weather|outside|outdoors?|out\s+there|raining|rainy|windy|sunny|cloudy|snowing|"
    r"how\s+(?:hot|cold|warm)\s+is\s+it\s+outside)\b",
    re.IGNORECASE,
)
_FUTURE = re.compile(
    r"\b(?:tomorrow|tonight|next\s+\w+|later|this\s+weekend|forecast|will\s+it|going\s+to)\b",
    re.IGNORECASE,
)


#: "outside" or "outdoors" alone is a place, not a subject ("a muster point outside the building").
_WEATHER_WORD = re.compile(
    r"\b(?:weather|raining|rainy|windy|sunny|cloudy|snowing)\b", re.IGNORECASE
)
_OUTDOOR_CONDITION = re.compile(
    r"\b(?:temperature|hot|cold|warm|cool|humid|humidity|wind|rain|snow|sun|weather)\b",
    re.IGNORECASE,
)
#: The word sits in a LIST of things to be accounted for, or is what something is adjusted for:
#: "after timetable, weather, season and concurrent changes are accounted for". There the weather
#: is a confounder of the question, not its subject (wave 9: the decline for that question opened
#: with "I don't hold a weather forecast" and quoted the outdoor temperature).
_CONFOUNDER_LIST = re.compile(
    r"(?:\w+\s*,\s*(?:and\s+|or\s+)?(?:the\s+)?(?:weather|outside|outdoors?)\b)"
    r"|(?:\b(?:weather|outside|outdoors?)\s*,\s*\w+)"
    r"|(?:\b(?:and|or|plus|nor)\s+(?:the\s+)?(?:weather|outdoor\s+conditions)\b)"
    r"|(?:\b(?:weather|outdoor\s+conditions)\s+(?:and|or)\s+\w+)"
    r"|(?:\b(?:for|after|despite|given|controlling\s+for|adjusting\s+for|accounting\s+for|"
    r"regardless\s+of|because\s+of|due\s+to|net\s+of)\s+(?:\w+\s+){0,3}(?:weather|outdoor)\b)",
    re.IGNORECASE,
)
#: THE OUTDOORS AS ONE SIDE OF A COMPARISON, WHICH IS NOT THE SUBJECT EITHER (BUG-945).
#:
#: "How does today compare with the outside temperature?" was answered with
#: "**I don't hold a weather forecast.** Abacws Building's outdoor sensors last recorded:
#: outdoor temperature 20.7 ... Those are readings, not a forecast." Every figure was live and
#: correct, the feed was plainly working, and the question was never answered: it asks how the
#: building's own readings compare with the outdoor ones, and neither the indoor series nor any
#: comparison appears. The decline is honest and it is about a different question.
#:
#: This is the same distinction `_CONFOUNDER_LIST` already draws one line up — the weather as
#: something the question mentions rather than something it is about — applied to the other
#: shape it takes. A comparison names TWO things; answering about one of them is not an answer.
#:
#: Narrow on purpose: a comparison word must be present AND be joined to the outdoor term.
#: "Is it colder outside than in the atrium?" is claimed by this; "how cold is it outside?"
#: is not, and still gets the readings it asks for.
_COMPARED_WITH_OUTDOORS = re.compile(
    r"\b(?:compare[sd]?|comparison|versus|vs\.?)\b"
    r"|\b(?:hotter|colder|warmer|cooler|higher|lower|wetter|drier|damper|different)\s+than\b"
    r"|\bdifference\s+between\b"
    r"|\b(?:against|relative\s+to|compared\s+(?:with|to))\b",
    re.IGNORECASE,
)

_MAX_WEATHER_QUESTION_WORDS = 16


def is_current_weather_question(question: str) -> bool:
    """True for a present-tense question ABOUT the weather outside (a forecast is C's statement).

    The weather has to be the SUBJECT: a short question that names it, not a long one that lists it
    among the things to be accounted for, and not one side of a comparison with the building's own
    readings (BUG-945).
    """
    q = question or ""
    if not _WEATHER.search(q) or _FUTURE.search(q):
        return False
    if _CONFOUNDER_LIST.search(q) or len(q.split()) > _MAX_WEATHER_QUESTION_WORDS:
        return False
    if _COMPARED_WITH_OUTDOORS.search(q):
        return False
    if _WEATHER_WORD.search(q):
        return True
    # only a place word is left ("outside", "outdoors", "out there"): it needs a condition beside it
    return bool(_OUTDOOR_CONDITION.search(q))


@dataclass
class OutdoorReading:
    """One outdoor sensor's latest value, with the time it was recorded."""

    label: str  # "outdoor temperature"
    value: float
    unit: str = ""
    when: str = ""  # already formatted for the reader, e.g. "03:50 on 19 Sep"


def _fmt_value(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def compose_weather(building: str, readings: Sequence[OutdoorReading], tried: bool = True) -> str:
    """No forecast is held; here is what the outdoor sensors last said, with their times."""
    name = building or "this building"
    lead = "**I don't hold a weather forecast.**"
    if readings:
        parts = [
            f"{r.label} {_fmt_value(r.value)}{(' ' + r.unit) if r.unit else ''}"
            + (f" (at {r.when})" if r.when else "")
            for r in readings
        ]
        return (
            f"{lead} {name}'s outdoor sensors last recorded: {and_list(parts, 6)}.\n\n"
            "Those are readings, not a forecast."
        )
    if tried:
        return f"{lead} I also couldn't read {name}'s outdoor sensors just now."
    return lead


# ── a genuinely missing referent ─────────────────────────────────────────────────────────────

#: Generic nouns for a thing a person refers to by pointing at it ("the incident"). English, not a
#: building's vocabulary; the candidates named come from the building's own record classes.
_REFERENT_NOUNS = (
    "incident|incidents|event|events|service|services|contract|contracts|meeting|meetings|"
    "session|sessions|ticket|tickets|request|requests|order|orders|booking|bookings|fault|faults|"
    "issue|issues|permit|permits|inspection|inspections|audit|audits|project|projects|"
    "contractor|contractors|supplier|suppliers|department|departments|visit|visits|delivery|"
    "deliveries|complaint|complaints|report|reports"
)
_REFERENT = re.compile(
    rf"\b(?:the|this|that|these|those)\s+(?:(?:named|specific|particular|same|above)\s+)?"
    rf"(?P<noun>{_REFERENT_NOUNS})\b",
    re.IGNORECASE,
)

_MAX_REFERENT_QUESTION_TERMS = 7


def referent_noun(question: str) -> str:
    """The definite noun a SHORT question points at ('incident'), or ''. Long questions are abstract."""
    q = question or ""
    m = _REFERENT.search(q)
    if not m:
        return ""
    if len(content_terms(q)) > _MAX_REFERENT_QUESTION_TERMS:
        return ""
    return _singular(m.group("noun").lower())


def compose_referent(building: str, noun: str, records: Sequence[Any]) -> str:
    """Ask WHICH, once, naming the record kinds the building keeps that could be it."""
    name = building or "this building"
    candidates = [
        str(r.label)
        for r in records or ()
        if getattr(r, "label", "")
        and any(
            _close(noun, t)
            for t in content_terms(f"{r.label} {' '.join(getattr(r, 'terms', ()) or ())}")
        )
    ][:3]
    if candidates:
        return (
            f"Which {noun} do you mean? {name} keeps {and_list(candidates)} records — name one, "
            "or ask me to list them."
        )
    return f"Which {noun} do you mean? Name it, or give a room, floor or date, and I will look."


# ── an abstract, multi-part question ─────────────────────────────────────────────────────────

_MIN_ABSTRACT_TERMS = 6

_STOP_AFTER = {
    "and",
    "or",
    "the",
    "a",
    "an",
    "of",
    "for",
    "to",
    "in",
    "on",
    "is",
    "are",
    "was",
    "were",
    "be",
    "that",
    "which",
    "what",
    "who",
    "how",
    "still",
    "still",
    "needed",
    "remain",
    "remains",
}


def is_abstract(question: str) -> bool:
    """True for a long or multi-clause question, which no single missing word explains."""
    q = question or ""
    clauses = len(
        re.findall(r",|;|\band\b|\bor\b|\bwhich\b|\bwhat\b|\bwhether\b", q, re.IGNORECASE)
    )
    return len(content_terms(q)) >= _MIN_ABSTRACT_TERMS or clauses >= 3


def readable_names(entities: Sequence[Any]) -> List[str]:
    """Entities a reader can be shown: never an identifier such as ``Reactive_Power_Sensor``.

    A resolved ONTOLOGY CLASS reaches here spelled the way the graph spells it, with underscores.
    Printing one tells the reader how the store names things, which is not an answer.
    """
    out: List[str] = []
    for e in entities or ():
        text = str(e).strip()
        if text and "_" not in text and not re.search(r"[a-z][A-Z]", text) and text not in out:
            out.append(text)
    return out


def phrases_for(question: str, unmatched: Sequence[str], limit: int = 2) -> List[str]:
    """Up to ``limit`` short PHRASES from the question around the words nothing matched.

    A phrase is the unmatched word plus the content word next to it ("specialist evidence"), so the
    reader is never handed one odd word as though it were a field name. A word with no content word
    beside it is dropped: a bare word is exactly the machine-shaped thing this replaces.
    """
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", question or "")
    lowered = [w.lower() for w in words]

    def _content(index: int) -> bool:
        """Is the word at ``index`` a topic-bearing word, rather than glue?

        `content_terms` is the same stop-word list the rest of the pipeline judges topics by, so
        "into", "by" and "the" are never paired with anything: "convert into" and "booths by" were
        both produced by a neighbour rule that only checked a short local list.
        """
        if not 0 <= index < len(lowered):
            return False
        return bool(content_terms(lowered[index])) and lowered[index] not in _STOP_AFTER

    out: List[str] = []
    for term in unmatched or ():
        t = str(term).lower()
        if t not in lowered:
            continue
        i = lowered.index(t)
        phrase = ""
        if _content(i + 1):
            phrase = f"{lowered[i]} {lowered[i + 1]}"
        elif _content(i - 1):
            phrase = f"{lowered[i - 1]} {lowered[i]}"
        if phrase and phrase not in out:
            out.append(phrase)
        if len(out) >= limit:
            break
    return out


def lead_read_but_off_topic(name: str, about: str = "") -> str:
    """The first sentence when the building WAS read and the answer was judged off the point.

    BUG-1252 (P1). The default lead — "I couldn't answer that from <building>'s records" — is a
    statement about the BUILDING, and it is false on a turn that has just read 275 humidity
    series or 1,000 water-meter rows and then had that answer deleted by the answer-relevance
    gate. Four of tail N's six investigated false declines were exactly this, and the reader saw
    a refusal whose next paragraph named the very quantity the turn had read.

    THE GATE IS NOT WRONG TO FIRE and this does not stop it (BUG-873 scoped its ACTION; BUG-1252
    deliberately did not widen `_grounded_evidence_behind`, because the data lanes are where the
    gate measures best and in at least two of the four the answer really was about something
    else). What changes is only the sentence: "I read them, and what I could make of them did
    not answer you" is true where "I couldn't answer that from the records" is not.

    THE OPENING IS LOAD-BEARING. Five consumers classify a decline from its text —
    `regression_answerability._DECLINE_MARKERS`, `publication_gate._DECLINE_MARKERS`,
    `grade_answers_rubric._DECLINE_PATTERNS`, `scripts/audit_decline_markers.py` and
    `_orchestrator`'s `_decline_leads` — and a new opening they do not know is read as an
    ANSWER, which silently moves every decline-rate measurement in the project (lessons #141:
    one question produced three honest decline wordings in a day). So the opening is
    "I couldn't put an answer together", which `publication_gate` ALREADY carries, and the four
    lists that did not were updated in the same change. Measured over 2,985 stored answers
    (the 73-probe pack plus every `docs/phase0/*.jsonl`): the additions reclassify NONE of them,
    and no stored answer contains this lead, so that zero is not hiding a move.

    ``about`` is inserted AFTER the marker, never before it — a referent spliced into the middle
    of a fixed marker is BUG-876's exact shape.
    """
    return (
        f"I couldn't put an answer together{about} from {name or 'this building'}'s records — "
        "I did read them, but what I could make of them did not answer the question you asked."
    )


def compose_abstract(
    building: str,
    question: str,
    unmatched: Sequence[str],
    measured: Sequence[str],
    records: Sequence[Any],
    entities: Sequence[str] = (),
    read_but_off_topic: bool = False,
) -> str:
    """No question back: what found nothing, and the nearest things the building can answer.

    ``read_but_off_topic`` says the caller KNOWS this turn read the building and had its answer
    taken away — see `lead_read_but_off_topic` for why that needs a different first sentence.
    """
    name = building or "this building"
    # No fragment of the question is quoted back as though it were a topic. `phrases_for` paired an
    # unmatched word with whichever word stood next to it, which produced "nothing came back about
    # exported unavailable" and "about blocks processing and identity platform" -- two arbitrary
    # tokens presented as the subject. The only thing named is an entity a lane actually resolved.
    named = readable_names(entities)
    about = f" about **{', '.join(named[:3])}**" if named else ""
    lead = (
        lead_read_but_off_topic(name, about)
        if read_but_off_topic
        else f"I couldn't answer that{about} from {name}'s records."
    )
    # `named` is what a lane already resolved, and it is printed in bold one line above.
    # Ranking the holdings against it too is what stops the list being alphabetical
    # (BUG-950): 'why is pl 2.5 increasing' offered air quality, carbon monoxide, co2 and
    # damper position while the building holds 210 PM2.5 sensors and the answer had
    # already said **PM2.5**.
    names, labels = nearest_holdings(
        question, measured, records, max_measured=4, max_records=3, resolved=named
    )
    near: List[str] = []
    if labels:
        near.append(f"the {and_list(labels, 3)} records")
    if names:
        near.append(f"the readings of {and_list(names, 4)}")
    if not near:
        return (
            lead + " Naming one room, floor, record or date usually gives me enough to answer from."
        )
    # The closing used to end "…or tell me which record this should be in", immediately after
    # naming the records. BUG-947: four of the seven false declines hand-read on tail M named
    # the right register in the same sentence as the refusal, and this wording then asked the
    # reader to name a record the sentence had just named for them. Asking a question whose
    # answer is printed one clause earlier is what makes a decline read as a brush-off.
    return (
        f"{lead}\n\nThe nearest things I can answer are {' and '.join(near)}. Ask about one of "
        "those and I will read them."
    )


# ── the entry point ──────────────────────────────────────────────────────────────────────────


def classify(question: str, unmatched: Sequence[str] = ()) -> str:
    """Which shape this question has."""
    if is_current_weather_question(question):
        return KIND_WEATHER
    if referent_noun(question):
        return KIND_REFERENT
    if is_abstract(question):
        return KIND_ABSTRACT
    return KIND_PLAIN


def compose(
    *,
    building: str,
    question: str,
    unmatched: Sequence[str] = (),
    measured: Sequence[str] = (),
    records: Sequence[Any] = (),
    outdoor: Optional[Sequence[OutdoorReading]] = None,
    entities: Sequence[str] = (),
    read_but_off_topic: bool = False,
) -> Tuple[str, str]:
    """``(kind, text)``. ``outdoor`` is None when nobody tried to read the outdoor sensors.

    ``read_but_off_topic`` reaches only the two shapes that assert something about the records
    (BUG-1252). The weather shape names the outdoor readings it did find and the referent shape
    asks which one is meant; neither says the building could not answer, so neither is the
    falsehood this flag exists to stop.
    """
    kind = classify(question, unmatched)
    if kind == KIND_WEATHER:
        return kind, compose_weather(building, outdoor or (), tried=outdoor is not None)
    if kind == KIND_REFERENT:
        return kind, compose_referent(building, referent_noun(question), records)
    if kind == KIND_ABSTRACT:
        return kind, compose_abstract(
            building, question, unmatched, measured, records, entities, read_but_off_topic
        )
    return kind, compose_abstract(
        building, question, (), measured, records, entities, read_but_off_topic
    )
