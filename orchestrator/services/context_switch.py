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

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
