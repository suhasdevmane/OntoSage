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
