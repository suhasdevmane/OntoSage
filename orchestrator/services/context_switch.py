# -*- coding: utf-8 -*-
"""When the subject changes, the inherited context must not (V12-11, review A13/A14).

    A14  "Incompatible inherited state is cleared on a context switch, and the co-reference
          rewrite cannot carry a stale referent."

TWO MECHANISMS CARRY STATE ACROSS A TURN, AND NEITHER CHECKED THE SUBJECT
-------------------------------------------------------------------------
1. `turn_memory` carries `forecast_result` and `analytics_result` forward so "now plot
   that" works. `main.py` injected them with `state.intermediate_results.update(...)` —
   unconditionally. Ask about room 5.01, then ask "what about room 3.27? plot it", and the
   plot is built from 5.01's analytics under a question naming 3.27.

2. `rewrite_to_standalone` asks an LLM to resolve "there"/"that" against six messages of
   history, and accepted whatever came back if it was non-empty, under 500 characters and
   not identical to the input. Nothing checked that the rewrite was about the same place
   the user had just named. The rewrite then becomes the query every downstream stage sees,
   including the referent gate — so a swapped referent is not caught later, it is LAUNDERED.

BUG-118 was one instance of this class ("floor 2" matched every floor whose name contained
the digit). The class itself had no test.

WHAT THIS IS
------------
A deterministic comparison of the PLACE two questions are about, reusing the referent
detection the existence gate already uses so there is no second opinion about what a
question's subject is. No LLM, no history model, no decomposition: it answers one question
— did the subject change — and says which inherited keys are no longer about it.

WHAT IT DELIBERATELY IS NOT
---------------------------
It does not clear state when it cannot tell. A follow-up that names no place ("now plot
that") is the case carry-forward exists for, and dropping state there would break the
feature to fix a bug it does not have. Silence is the common case and staying quiet in it
is what makes the rare positive meaningful.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestrator.services.referent_resolver import (
    KIND_FLOOR,
    KIND_LOCATION,
    KIND_SPACE,
    detect_referent,
    detect_typed_referent,
)

#: Bus keys whose value is ABOUT A PLACE, and which therefore stop being true when the
#: place changes. `forecast_result` and `analytics_result` are what turn_memory carries;
#: the rest are listed because the same rule applies if they are ever carried.
PLACE_BOUND_KEYS = (
    "analytics_result",
    "forecast_result",
    "sql_result",
    "sparql_result",
    "spatial_result",
    "floor_plan_result",
    "anomaly_result",
    "deliberate_result",
    "evidence_record",
    "evidence_dossier",
    "visualization_path",
)


@dataclass(frozen=True)
class Switch:
    """The subject changed from one place to another."""

    previous: str
    latest: str

    def describe(self) -> str:
        return f"subject changed from {self.previous} to {self.latest}"


def place_of(text: str, entities: Optional[List[str]] = None) -> Optional[str]:
    """A canonical token for the place a question is about, or None.

    Both detectors are consulted in the order the existence gate consults them, so this
    cannot disagree with the gate about what a question's subject is. A dotted or worded
    location wins; a floor, named space or explicitly-named other building is the fallback.

    None means "this question names no place", which is most follow-ups and is exactly the
    case where nothing may be cleared.
    """
    token = detect_referent(text or "", entities)
    if token:
        return f"loc:{str(token).strip().lower()}"
    typed = detect_typed_referent(text or "")
    if typed and typed.kind in (KIND_FLOOR, KIND_SPACE, KIND_LOCATION):
        return f"{typed.kind}:{str(typed.token).strip().lower()}"
    return None


def switched(previous: str, latest: str) -> Optional[Switch]:
    """Did the subject change between these two questions?

    Returns None unless BOTH name a place and the places differ. A question that names no
    place has not changed the subject — it has declined to restate it, which is what a
    follow-up is.
    """
    a, b = place_of(previous), place_of(latest)
    if not a or not b or a == b:
        return None
    return Switch(previous=a, latest=b)


def prune_inherited(
    inherited: Dict[str, Any], previous: str, latest: str
) -> Tuple[Dict[str, Any], List[str]]:
    """(what may still be inherited, what was dropped and why it had to be).

    Only place-bound keys are dropped, and only on a positive switch. Everything else is
    passed through untouched — a conversation's memory is the feature, and clearing it
    defensively would trade a rare wrong answer for a constant one.
    """
    if not inherited:
        return {}, []
    change = switched(previous, latest)
    if change is None:
        return dict(inherited), []
    kept = {k: v for k, v in inherited.items() if k not in PLACE_BOUND_KEYS}
    dropped = [k for k in inherited if k in PLACE_BOUND_KEYS]
    return kept, dropped


#: Place head-nouns, for rendering a bound referent the way the question wrote it. Generic
#: English, never this building's vocabulary — a building that calls them "pods" still gets the
#: bare identifier, which is honest, rather than a word invented for it.
_PLACE_HEADS = ("room", "zone", "floor", "level", "storey", "space", "area", "wing", "lab")


def assumed_place_note(original: str, rewritten: str) -> Optional[str]:
    """One line naming the place a co-reference rewrite BOUND, when the user named none.

    WHY DISCLOSE RATHER THAN CHOOSE BETTER (BUG-943). Measured live 2026-09-29: turn 1 said "I am
    looking into air quality in room 5.01 specifically", six turns about floor temperatures
    followed, and then "And what is the humidity in there right now?" was answered about FLOOR 1.
    Floor 1 is a place the user named twice, so this is not a fabrication — BUG-940 fixed that —
    and recency is a defensible reading of "there": a human asked the same sequence would very
    likely answer about floor 1 too.

    So the fix is not better ranking, which would be guessing more confidently. It is saying which
    one was assumed. A wrong guess then costs the user one correction instead of a figure they
    cannot see is wrong, and the reasoning is the project's own: the number is the same; the claim
    it makes must not be.

    Returns None — no note at all — in the three cases where a note would be noise: the user named
    the place themselves (nothing was assumed), the rewrite bound no place (nothing to name), or no
    deictic word can be found to quote back (nothing was resolved on their behalf).
    """
    if place_of(original or ""):
        return None  # they named it; nothing was assumed on their behalf
    bound = place_of(rewritten or "")
    if bound is None:
        return None  # no place was bound, so there is nothing to disclose

    # Punctuation-insensitive, because it is what defeats this kind of match every time:
    # " there " is not in " and there? ", so the note vanished on the commonest phrasing there
    # is. The same shape cost a register its plurals (BUG-948) and made "pm2.5" unrecognisable
    # as "pm25" (BUG-950).
    low = " " + re.sub(r"[^a-z0-9]+", " ", (original or "").lower()).strip() + " "
    word = next(
        (
            w
            for w in ("there", "that", "those", "these", "them", "it", "the same")
            if f" {w} " in low
        ),
        None,
    )
    if word is None:
        return None  # nothing deictic to quote back; a note would read as a non-sequitur

    token = bound.split(":", 1)[-1].replace("|", " ").strip()
    # Render it as the REWRITE wrote it where possible — "room 5.01" reads, "5.01" does not — by
    # looking for a place head-noun immediately before the identifier in the rewritten text.
    shown = token
    core = token.split()[-1] if token else ""
    if core:
        rl = (rewritten or "").lower()
        at = rl.find(core)
        if at > 0:
            before = rl[:at].rstrip().split()
            if before and before[-1] in _PLACE_HEADS:
                shown = f"{before[-1]} {core}"
    return f'Taking "{word}" as {shown}.'


def rewrite_invents_a_place(latest: str, rewritten: str, user_texts: Sequence[str]) -> bool:
    """True when the rewrite BINDS a place the user never named — so it must be refused.

    `rewrite_is_safe` guards the case where the user named a place and the rewrite changed it.
    This guards the case it explicitly does not cover, and which its own docstring calls "the
    case the rewrite exists for": the user named NO place, so anything the rewrite chooses is
    unopposed.

    Measured live 2026-09-29 (BUG-940). An eight-turn conversation: turn 1 "I am looking into
    air quality in room 5.01 specifically", six turns about floor temperatures, then "And what
    is the humidity in THERE right now?". The rewrite produced:

        "What is the current humidity in Telecommunications Room 1.34 on Floor 1?"

    Room 1.34 appears in no message the user wrote. The prompt asks the model to resolve a
    reference to "the concrete entity mentioned earlier", and the six messages it can see
    include the ASSISTANT's own answers, which name dozens of rooms — so "there" bound to a
    room from the previous answer rather than to the subject the user had declared. The reply
    then reported room 1.34's humidity with a mean, a range and a timestamp, and no hedge;
    room 5.01 has a humidity sensor of its own, so this was not an absence handled badly. The
    building has 287 of them and one was chosen.

    Nothing downstream can catch this. The rewrite REPLACES the user's message for
    classification, entity extraction, SPARQL and the referent existence gate itself, so a
    room that exists passes every check — the same laundering `rewrite_is_safe` was built for,
    arriving through the door it leaves open.

    THE RULE: a rewrite may bind only a referent the USER named, in this session, in their own
    words. Not one an answer mentioned. `user_texts` is therefore the user's messages and the
    session summary (itself built only from user questions), never the assistant's replies.
    """
    if place_of(latest or ""):
        return False  # the user named one; `rewrite_is_safe` owns that case
    added = place_of(rewritten or "")
    if added is None:
        return False  # nothing was bound, so nothing was invented
    for text in user_texts:
        if place_of(text or "") == added:
            return False
    # `place_of` returns ONE place per text, so a message naming two ("floor 3 and floor 4")
    # would hide the second from the check above. Fall back to the token itself.
    token = added.split(":", 1)[-1].replace("|", " ").strip()
    if token and token in " ".join(t or "" for t in user_texts).lower():
        return False
    return True


def rewrite_is_safe(latest: str, rewritten: str) -> bool:
    """May this co-reference rewrite replace the user's message?

    False when the user NAMED a place and the rewrite names a different one, or none. Both
    are failures of the same kind: the rewrite's job is to make an under-specified question
    self-contained, so it may ADD a referent and it may leave one alone. Changing one the
    user just typed, or losing it, makes the question less faithful than the original — and
    because the rewrite replaces the original everywhere downstream, nothing later can tell.

    True whenever the user named no place: that is the case the rewrite exists for, and
    refusing it there would disable the feature entirely.
    """
    named = place_of(latest or "")
    if named is None:
        return True
    return place_of(rewritten or "") == named


# ── Follow-ups that point at the PREVIOUS REPLY (Phase 1.2, 2026-10-02) ───────────────────
#
# A 20-conversation battery (docs/phase0/conversations/) showed the shape that fails: every
# follow-up that supplies a VALUE works ("2.01"), and every follow-up that points at what the
# assistant just said does not -- "the first one" after a list of ten rooms (no rewrite), "how
# warm is it there?" after three kitchens (a correct rewrite REJECTED by `rewrite_invents_a_place`,
# then answered building-wide), "what is the status of that report?" (the REP id dropped). The
# guard was right to refuse an assistant-named place SIX TURNS back (BUG-940); it was wrong to
# refuse the one the assistant named in the reply the user is replying to. These helpers read
# that reply alone, and only in the three deterministic shapes below.

_ORDINALS = {
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "last": -1,
}
_ORDINAL_REF_RE = re.compile(
    r"\bthe\s+(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last)\s+"
    r"(?:one|room|space|option|place)\b",
    re.IGNORECASE,
)
_ANAPHORA_RE = re.compile(
    r"\b(?:there|in\s+there|that\s+(?:one|room|space|place)|this\s+one|it)\b", re.IGNORECASE
)
_REPLY_PLACE_RE = re.compile(r"\b(?:room|rm\.?)\s*(\d{1,2}\.\d{2}[A-Za-z]?)\b", re.IGNORECASE)
_REPORT_REF_RE = re.compile(
    r"\b(?:that|this|the|my|the\s+last|that\s+last)\s+(?:report|ticket|request|issue)\b",
    re.IGNORECASE,
)
_REPORT_ID_RE = re.compile(r"\bREP-[A-Z0-9]{6}\b")


def places_in_reply(reply: str) -> List[str]:
    """The rooms an assistant reply names, in order, de-duplicated ('2.13', '2.15', ...)."""
    seen: List[str] = []
    for m in _REPLY_PLACE_RE.finditer(reply or ""):
        tok = m.group(1).lower()
        if tok not in seen:
            seen.append(tok)
    return seen


#: F11 (QA-trial plan, 2026-10-04): a floor named in a reply could not be referred back
#: to at all -- every resolver here matched ONLY a dotted room token. "Floor" alone (no
#: number) is deliberately excluded: "on the same floor" names no specific floor to bind.
_REPLY_FLOOR_RE = re.compile(r"\bfloor\s+(\d{1,2})\b", re.IGNORECASE)


def floors_in_reply(reply: str) -> List[str]:
    """The floors an assistant reply names, in order, de-duplicated ('0', '2', ...)."""
    seen: List[str] = []
    for m in _REPLY_FLOOR_RE.finditer(reply or ""):
        tok = m.group(1)
        if tok not in seen:
            seen.append(tok)
    return seen


def resolve_ordinal(latest: str, previous_reply: str) -> Optional[str]:
    """'what is the temperature in the first one?' after a reply listing rooms -> the same
    question with 'room 2.13' in place of 'the first one'. None when there is no ordinal, no
    list, or the ordinal is beyond it."""
    m = _ORDINAL_REF_RE.search(latest or "")
    if not m:
        return None
    places = places_in_reply(previous_reply)
    if not places:
        return None
    idx = _ORDINALS[m.group(1).lower()]
    try:
        chosen = places[idx]
    except IndexError:
        return None
    return (latest[: m.start()] + f"room {chosen}" + latest[m.end() :]).strip()


def previous_reply_named_it(latest: str, rewritten: str, previous_reply: str) -> bool:
    """True when the place the rewrite bound is the one the PREVIOUS reply named for this
    anaphor: the Nth room for an ordinal, or the reply's ONLY room for 'there'/'it'."""
    added = place_of(rewritten or "")
    if added is None or place_of(latest or ""):
        return False
    token = added.split(":", 1)[-1].replace("|", " ").strip().lower()
    places = places_in_reply(previous_reply)
    m = _ORDINAL_REF_RE.search(latest or "")
    if m and places:
        try:
            return places[_ORDINALS[m.group(1).lower()]] in token
        except IndexError:
            return False
    if _ANAPHORA_RE.search(latest or "") and len(places) == 1:
        return places[0] in token
    return False


def ambiguous_reference(latest: str, previous_reply: str) -> List[str]:
    """The rooms the previous reply named when the follow-up says 'there'/'it' and that reply
    named MORE THAN ONE -- the case to ASK about rather than guess ("which of the three
    kitchens?"). [] otherwise."""
    if place_of(latest or "") or not _ANAPHORA_RE.search(latest or ""):
        return []
    places = places_in_reply(previous_reply)
    return places if len(places) >= 2 else []


def resolve_report_reference(latest: str, previous_reply: str) -> Optional[str]:
    """'what is the status of that report?' after a reply that filed REP-EF64E3 -> the same
    question with the id in place of the phrase. None when either half is missing."""
    m = _REPORT_REF_RE.search(latest or "")
    ids = _REPORT_ID_RE.findall(previous_reply or "")
    if not m or not ids:
        return None
    return (latest[: m.start()] + ids[-1] + latest[m.end() :]).strip()


_LOCATION_STATEMENT_RE = re.compile(
    r"^\W*(?:i\s*am|i'm|im|we\s*are|we're)\s+(?:in|on|at|from)\s+"
    r"(?P<place>(?:room|rm\.?)\s*\d{1,2}\.\d{2}[A-Za-z]?|floor\s+\d{1,2})\W*$",
    re.IGNORECASE,
)
_PAIR_REF_RE = re.compile(
    r"\b(?:the\s+two|both(?:\s+of\s+them)?|those\s+two|these\s+two)\b", re.IGNORECASE
)
#: A BARE day-shift follow-up and nothing else -- "and the day before?", "what about the
#: day before that?", "the previous day?". Deliberately narrow: if the user added anything
#: else ("and the day before, for floor 3?") this must NOT fire, so the richer content goes
#: to the LLM rewrite instead of being silently dropped.
_RELATIVE_DAY_FOLLOWUP_RE = re.compile(
    r"^\W*(?:and\s+|what\s+about\s+)?the\s+(?:day\s+before(?:\s+that)?|previous\s+day)\W*$",
    re.IGNORECASE,
)


def resolve_relative_day_followup(latest: str, previous_user_question: str) -> Optional[str]:
    """G7 (QA-trial plan, 2026-10-04, BUG-1430): 'and the day before?' straight after a
    question naming a calendar day -- rewrite to the PREVIOUS question with its day phrase
    shifted one day further back, so the LLM rewrite (free-form, non-deterministic per
    CAVEAT-891) never has to guess, and `calendar_day_bounds` never sees a phrase like "the
    day before yesterday" that happens to contain "yesterday" as a substring.

    None when `latest` carries anything beyond the bare follow-up, or the previous question
    named no calendar day this module recognises."""
    from orchestrator.services.requested_interval import _CALENDAR_DAYS, _DAYS_BACK_TO_PHRASE

    if not _RELATIVE_DAY_FOLLOWUP_RE.match(latest or ""):
        return None
    prev = (previous_user_question or "").strip()
    if not prev:
        return None
    low = prev.lower()
    found = None
    for phrase, back in _CALENDAR_DAYS.items():
        m = re.search(rf"\b{re.escape(phrase)}\b", low)
        if m:
            found = (m.start(), m.end(), back)
            break
    if found is None:
        return None
    start, end, back = found
    new_phrase = _DAYS_BACK_TO_PHRASE.get(back + 1)
    if new_phrase is None:  # nothing named that far back (BUG-540's own caution)
        return None
    return prev[:start] + new_phrase + prev[end:]


def resolve_location_statement(latest: str, previous_user_question: str) -> Optional[str]:
    """'I am in room 3.01' straight after 'where's the nearest toilet?' -> that question again,
    'from room 3.01'. The battery (c08) answered the statement from the documents instead. Only
    a bare statement qualifies, only when the previous question names no start of its own, and
    the clause is the one the spatial lane already parses as a source."""
    m = _LOCATION_STATEMENT_RE.match(latest or "")
    prev = (previous_user_question or "").strip()
    if not m or not prev or re.search(r"\bfrom\b", prev, re.IGNORECASE) or place_of(prev):
        return None
    place = re.sub(r"\s+", " ", m.group("place").strip().lower())
    place = re.sub(r"^rm\.?\s*", "room ", place)
    return f"{prev.rstrip('?. ')} from {place}?"


def resolve_pair_reference(latest: str, earlier_user_texts: List[str]) -> Optional[str]:
    """'which of the two is busier?' after the USER asked about room 1.06 and then room 2.01
    -> 'which of room 1.06 and room 2.01 is busier?'. The two places come from the user's own
    earlier turns, never from a reply, and there must be exactly two; otherwise None and the
    clarification that asks which two stands (battery c05)."""
    m = _PAIR_REF_RE.search(latest or "")
    if not m or place_of(latest or ""):
        return None
    seen: List[str] = []
    for text in earlier_user_texts or []:
        for tok in places_in_reply(text):
            if tok not in seen:
                seen.append(tok)
    if len(seen) != 2:
        return None
    return (latest[: m.start()] + f"room {seen[0]} and room {seen[1]}" + latest[m.end() :]).strip()


#: Follow-ups that act on the PREVIOUS RESULT rather than ask a value of one place; an anaphor
#: in these is not a reference to one room. Shared by the resolvers and the rewrite's gate.
_ACTS_ON_PREVIOUS_RESULT_RE = re.compile(
    r"\b(?:plot|chart|graph|draw|show|visuali[sz]e|forecast|predict|export|compare|both|"
    r"all of them|each of them|rank|list)\b",
    re.IGNORECASE,
)
_LOCATIVE_ANAPHOR_RE = re.compile(
    r"\b(?:in\s+)?there\b|\bin\s+(?:that|this)\s+(?:one|room|space|place)\b|"
    r"\b(?:that|this)\s+(?:one|room|space|place)\b",
    re.IGNORECASE,
)
_BARE_IT_RE = re.compile(r"\bit\b", re.IGNORECASE)


def acts_on_previous_result(latest: str) -> bool:
    """True for 'plot that', 'forecast it', 'compare both': the previous RESULT is the referent."""
    return bool(_ACTS_ON_PREVIOUS_RESULT_RE.search(latest or ""))


def resolve_sole_room_anaphor(latest: str, previous_reply: str) -> Optional[str]:
    """'is it free this afternoon?' after a reply that named ONE room -> 'is room 1.06 free this
    afternoon?'; 'and the CO2 there?' -> 'and the CO2 in room 2.01?'.

    Live (c13, 2026-10-02) the model's rewrite bound the right room but as the register's
    label, "Level 1 computer lab 1.06 (WS-02)", whose words matched two knowledge topics and
    the TTL route skipped the classifier. The plain token is what every lane parses. None when
    the follow-up names a place, is not a question, acts on the previous result, has no
    anaphor, or the reply named zero or several rooms (several is `ambiguous_reference`).

    ROOM ONLY. F11's floor/amenity fallback (`resolve_sole_floor_or_amenity_anaphor`) is a
    SEPARATE function, deliberately not folded in here: an amenity reference must be tried
    BEFORE a bare floor number ("The Café is on Floor 0, open 08:00-16:00" -- a floor does
    not have closing hours, the Café does), and the amenity half needs a graph read this
    synchronous function cannot make. Keeping this one room-only means it can stay in the
    uniform synchronous resolver loop unchanged."""
    text = latest or ""
    if "?" not in text or place_of(text) or acts_on_previous_result(text):
        return None
    places = places_in_reply(previous_reply)
    if len(places) != 1:
        return None
    room = f"room {places[0]}"
    m = _LOCATIVE_ANAPHOR_RE.search(text)
    if m:
        return (text[: m.start()] + f"in {room}" + text[m.end() :]).strip()
    m = _BARE_IT_RE.search(text)
    if m:
        return (text[: m.start()] + room + text[m.end() :]).strip()
    return None


def amenities_in_reply(reply: str, amenity_labels: Sequence[str]) -> List[str]:
    """F11 (2026-10-04): which of the building's OWN declared amenity labels a reply
    names, in order, de-duplicated. "What time does it close?" after a café answer gave
    the BUILDING's hours (BUG-1426) because no resolver recognised an amenity reference
    at all -- only a dotted room token. Takes the vocabulary from the graph
    (record_registry.held_amenity_classes) rather than a hardcoded word list, so this
    holds for whatever amenities THIS building declares, not a guessed set."""
    text = (reply or "").lower()
    seen: List[str] = []
    for label in amenity_labels:
        label = (label or "").strip()
        if len(label) < 3:
            continue
        if re.search(rf"\b{re.escape(label.lower())}\b", text) and label not in seen:
            seen.append(label)
    return seen


def resolve_sole_floor_or_amenity_anaphor(
    latest: str, previous_reply: str, amenity_labels: Sequence[str]
) -> Optional[str]:
    """F11 (2026-10-04). Tried only after resolve_sole_room_anaphor finds nothing -- a
    room named in the reply is always the most specific referent and is handled there.

    Between a bare FLOOR number and a named AMENITY, the amenity wins: an amenity
    description routinely also states its floor ("The Café is on Floor 0, open
    08:00-16:00"), and a floor does not have opening hours, hours an amenity does. The
    first version of this fix tried the floor fallback INSIDE the synchronous room
    resolver and it matched "Floor 0" before the amenity step -- a real bug this
    module's OWN test caught, not a hypothetical one: 'and what time does it close?'
    would have rewritten to 'does floor 0 close?'."""
    text = latest or ""
    if "?" not in text or place_of(text) or acts_on_previous_result(text):
        return None
    if places_in_reply(previous_reply):
        return None
    amenities = amenities_in_reply(previous_reply, amenity_labels)
    if len(amenities) == 1:
        anchor = f"the {amenities[0]}"
        _for = f"for {anchor}"
    elif amenities:
        return None  # several named amenities -- ambiguous, not this resolver's case
    else:
        floors = floors_in_reply(previous_reply)
        if len(floors) != 1:
            return None
        anchor = f"floor {floors[0]}"
        _for = f"in {anchor}"
    m = _LOCATIVE_ANAPHOR_RE.search(text)
    if m:
        return (text[: m.start()] + _for + text[m.end() :]).strip()
    m = _BARE_IT_RE.search(text)
    if m:
        return (text[: m.start()] + anchor + text[m.end() :]).strip()
    return None
