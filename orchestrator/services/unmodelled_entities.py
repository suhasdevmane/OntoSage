# -*- coding: utf-8 -*-
""""Zero" and "not modelled" are different answers (CAVEAT-309).

*"How many desks are available in the building?"* answered **"0 desks
available"**. There is no desk or workspace entity in this model at all — no
class, no instances — so the honest answer is that the building does not model
desks. "0 available" reads as *every desk is taken*, which is a specific claim
about a specific building, made about something nobody ever recorded.

The distinction generalises well beyond desks, and deliberately carries no word
list:

* The graph **declares the class and holds no instances** → "none" is a real
  answer. A building with a defined ``brick:Bicycle_Rack`` and zero of them
  genuinely has no bike racks.
* The graph **does not define the class at all** → the concept was never
  modelled, and any count of it is meaningless. Saying "0" invents a fact.

So the check asks the ontology one question — *is there a class by this name?* —
and only rewrites when the answer is no. It fails open: an unverifiable lookup
leaves the answer exactly as it was, because a guard that edits answers on a
failed query is worse than the defect it corrects.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

#: A stated count of zero. Requires the number or an explicit "no" to sit next to
#: the noun, so "no data for 9am" (a windowing statement) and "no rooms above 25
#: degrees" (a result set, about rooms that DO exist) are not caught. The noun is
#: captured; nothing about which nouns are interesting is decided here.
_ZERO_CLAIM_RE = re.compile(
    r"\b(?:0|zero|no)\s+([a-z][a-z\- ]{2,30}?)"
    r"\s*(?:are|is|were|was)?\s*"
    r"(?:available|free|spare|unoccupied|in (?:the|this) building|here|found|modelled)\b",
    re.IGNORECASE,
)

#: Nouns that name a result set or a measurement rather than a thing the building
#: could model. A zero of one of these is a legitimate empty answer.
_NOT_AN_ENTITY = frozenset(
    {
        "data",
        "readings",
        "reading",
        "results",
        "result",
        "records",
        "record",
        "rows",
        "values",
        "value",
        "matches",
        "answers",
        "information",
        "sensors",
        "sensor",
    }
)

_STOP_WORDS = ("the ", "a ", "an ", "any ", "such ")


def _normalise_noun(raw: str) -> str:
    n = (raw or "").strip().lower()
    for w in _STOP_WORDS:
        if n.startswith(w):
            n = n[len(w) :]
    return " ".join(n.split())


def detect_zero_entity_claim(text: str) -> Optional[str]:
    """The entity a zero-claim is about, or None. Pure."""
    for m in _ZERO_CLAIM_RE.finditer(text or ""):
        noun = _normalise_noun(m.group(1))
        if not noun or noun in _NOT_AN_ENTITY:
            continue
        return noun
    return None


def _class_forms(noun: str) -> Tuple[str, ...]:
    """Plausible class local names for a noun ("hot desks" -> Hot_Desk, Hot_Desks…)."""
    words = [w for w in re.split(r"[\s\-]+", noun) if w]
    if not words:
        return ()
    singular = list(words)
    last = singular[-1]
    if last.endswith("ies") and len(last) > 4:
        singular[-1] = last[:-3] + "y"
    elif last.endswith("es") and len(last) > 4 and last[-3] in "sxzh":
        singular[-1] = last[:-2]
    elif last.endswith("s") and not last.endswith("ss"):
        singular[-1] = last[:-1]
    forms = {
        "_".join(w.capitalize() for w in words),
        "_".join(w.capitalize() for w in singular),
    }
    return tuple(sorted(forms))


def _class_exists_query(noun: str) -> str:
    forms = _class_forms(noun)
    if not forms:
        return ""
    # Match on the LOCAL NAME across every vocabulary, because a building may model
    # desks in Brick, in the OntoSage extension, or in a vocabulary of its own, and
    # a check that only knew one of them would call a modelled thing unmodelled.
    clauses = " || ".join(f'LCASE(STR(?local)) = "{f.lower()}"' for f in forms)
    return (
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE {\n"
        "  { ?c a owl:Class } UNION { ?c a rdfs:Class } UNION { ?c rdfs:subClassOf ?any }\n"
        "  BIND(REPLACE(STR(?c), '^.*[#/]', '') AS ?local)\n"
        f"  FILTER({clauses})\n"
        "}"
    )


def _first_count(res: Any) -> Optional[int]:
    rows = res.get("rows") if isinstance(res, dict) else res
    if not rows:
        return None
    row = rows[0]
    val = row.get("n") if isinstance(row, dict) else getattr(row, "n", None)
    try:
        return int(str(val))
    except (TypeError, ValueError):
        return None


async def class_is_modelled(noun: str, sparql_exec: Callable[[str], Any]) -> Optional[bool]:
    """True/False, or None when the question could not be put to the graph."""
    query = _class_exists_query(noun)
    if not query:
        return None
    try:
        n = _first_count(await sparql_exec(query))
    except Exception as exc:
        logger.debug(f"[unmodelled] class lookup failed for {noun!r}: {exc}")
        return None
    return None if n is None else n > 0


def correction_text(noun: str, original: str) -> str:
    """Replace a fabricated zero with what is actually known."""
    return (
        f"This building's model does not include **{noun}** at all — there is no such "
        f"class in its ontology and nothing has been recorded about them. That is not "
        f"the same as there being none: I have no basis to count them either way. "
        f"Adding them to the building's TTL would make the question answerable."
    )


async def guard_answer(
    text: str,
    sparql_exec: Callable[[str], Any],
) -> Tuple[str, Optional[dict]]:
    """Return (possibly corrected answer, violation record or None).

    Fails open in every uncertain case: no zero-claim, an unverifiable lookup, or a
    class that IS modelled all leave the answer untouched.
    """
    noun = detect_zero_entity_claim(text)
    if not noun:
        return text, None
    modelled = await class_is_modelled(noun, sparql_exec)
    if modelled is not False:
        return text, None
    logger.warning(
        f"[unmodelled] answer reported zero {noun!r}; the ontology defines no such class "
        f"— rewritten as not-modelled"
    )
    return correction_text(noun, text), {"entity": noun, "original": text[:300]}
