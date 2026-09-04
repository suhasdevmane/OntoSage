# -*- coding: utf-8 -*-
"""Which systems of record the ACTIVE building actually holds, read from the graph.

The first, load-bearing half of the answerability precheck (V7-T21). Before a lane is
chosen, one question has to be answerable: does this building hold the kind of record
being asked about, as data?

That is decidable — count the instances — and deciding it from the graph is what makes
it building-agnostic. A building with a permit register gets permit questions routed to
SPARQL; a building without one gets a decline that names what is missing. Neither needs
a line of code, and nothing here contains a building literal: the class labels come from
the ontology and the instance counts from the active namespace.

**Why this exists at all.** Lifting the permit register into 15 queryable instances
changed nothing on its own, because the capability short-circuit fired first: asking
"how many permits are open?" matched *"open"* against the Working Hours topic's lay
terms and returned the building's opening times, never reaching classification. Every
lifted register would have been swallowed the same way. A greedy lay-term match must not
outrank a class the building demonstrably holds.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.utils import describe_exception, get_logger

logger = get_logger(__name__)

ONTOSAGE = "http://ontosage.org/capabilities#"

#: Refreshed rather than pinned: a document lifted mid-session should become routable
#: without a restart, and a register that was dropped should stop being claimed.
_TTL_SECONDS = 300

_CACHE: Dict[str, Tuple[float, List["RecordClass"]]] = {}

#: Every record class the ontology defines. Their LABELS are matched, so a building that
#: types its records with these classes is understood without configuring anything.
#: Fallback only. The record classes are DISCOVERED from the ontology (see
#: ``_discover_record_classes``); this list is what to fall back on when that query cannot
#: run, so a GraphDB hiccup degrades to the classes that existed when it was written rather
#: than to none at all.
#:
#: IT USED TO BE THE ONLY SOURCE, and that was a contract-2 violation with teeth: adding
#: ontosage:CleaningTask, ontosage:PublicEvent and ontosage:AccessPermission to the TBox,
#: with lay terms, with documents lifted into 62 instances, changed nothing — every question
#: about them still reached the document lane and was told the building holds no such
#: record, because a Python tuple decided what the building could be asked about. "Extend
#: the TTL before adding code" is the design rule; this made the code the gate.
_FALLBACK_RECORD_CLASSES = (
    "Permit",
    "Contract",
    "Warranty",
    "HandoverRecord",
    "ConditionSurvey",
    "CompetencyRecord",
    "RiskAssessment",
    "Tariff",
    "Booking",
    "ComplianceCheck",
    "WorkOrder",
    "TimetabledSession",
)

#: Every class the ontology declares beneath a record root. A building that adds its own
#: register subclasses one of these and is found with no code change.
_DISCOVER_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?cls WHERE {
  VALUES ?root { o:Record o:IntervalRecord }
  ?cls rdfs:subClassOf+ ?root .
  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#"))
}
"""


async def _discover_record_classes() -> tuple:
    """Record class local names, read from the ontology rather than restated here."""
    try:
        from orchestrator.services.ontology_manager import run_sparql_select

        result = await run_sparql_select(_DISCOVER_QUERY, limit=200)
        if result.get("ok"):
            names = tuple(
                sorted(
                    {
                        str(row.get("cls", "")).rsplit("#", 1)[-1]
                        for row in (result.get("rows") or [])
                        if row.get("cls")
                    }
                )
            )
            if names:
                return names
    except Exception as exc:  # pragma: no cover - a graph hiccup must not empty the list
        logger.debug(f"[record_registry] class discovery failed: {describe_exception(exc)}")
    return _FALLBACK_RECORD_CLASSES


_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX o: <http://ontosage.org/capabilities#>
SELECT ?cls (SAMPLE(?lbl) AS ?label) (COUNT(DISTINCT ?i) AS ?n)
       (GROUP_CONCAT(DISTINCT ?lay; SEPARATOR="|") AS ?lays) WHERE {
  VALUES ?cls { %s }
  ?i a ?cls .
  OPTIONAL { ?cls rdfs:label ?lbl }
  OPTIONAL { ?cls o:layTerms ?lay }
} GROUP BY ?cls
"""

#: Lay terms for classes the building does NOT hold, so an absent system can still be
#: named. Read once from the TBox rather than from any building's data.
_LAY_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT ?cls (GROUP_CONCAT(DISTINCT ?lay; SEPARATOR="|") AS ?lays) WHERE {
  VALUES ?cls { %s }
  ?cls o:layTerms ?lay .
} GROUP BY ?cls
"""


@dataclass(frozen=True)
class RecordClass:
    """A record class this building holds, and the words a question would use for it."""

    local_name: str
    label: str
    instances: int
    terms: Tuple[str, ...]


def _terms_for(
    local_name: str, label: str, lay: str = "", include_head_words: bool = True
) -> Tuple[str, ...]:
    """The words a question would use for this class — all of them declared, none derived.

    Three sources, every one in the ontology: the class's ``ontosage:layTerms``, its
    rdfs:label and its class name. Each is taken WHOLE, with only its plural added.

    **Nothing is derived from part of a phrase.** That rule cost three separate defects
    before it was stated plainly. "roof access permit" contributed a bare *roof*, and a
    competency question was answered from the permit register. "Work Order" contributed
    *work*, and "what is the procedure for hot works?" was declined as a missing register.
    Worst of all, ontosage:Booking is labelled "Room booking", which contributed a bare
    *room* — and every question naming a room, including two wayfinding questions, was
    pulled into the register lane. In English a compound noun's head is its LAST word, so
    the first word of a phrase names a different concept nearly every time.

    Short forms are not lost by this, because they are declared: the TBox lists "permit",
    "booking", "condition" and the rest as layTerms. That is the design — the ontology
    says what a thing is called, and a building that calls it something else says so in
    its own TTL. ``include_head_words`` is kept for callers that want the older, looser
    behaviour, and nothing uses it.
    """

    def _plural(word: str) -> str:
        """English plural, enough for a class name.

        The y->ies rule needs a CONSONANT before the y: "warranty" becomes "warranties"
        but "survey" becomes "surveys", not "surveies" — which is what a naive rule
        produced, so "condition surveys" (the form anyone would type) matched nothing.
        """
        if word.endswith("s"):
            return word
        if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
            return word[:-1] + "ies"
        return word + "s"

    words: set = set()

    for seed in (label.lower().strip(), re.sub(r"(?<!^)(?=[A-Z])", " ", local_name).lower()):
        seed = seed.strip()
        if not seed:
            continue
        # The whole phrase and its plural, and NOTHING derived from part of it.
        # "work order" and "work orders" name one thing; "work" names something else.
        parts = seed.split()
        words.add(seed)
        words.add(" ".join(parts[:-1] + [_plural(parts[-1])]))

    # Declared lay terms are ALREADY the words people use, so they are taken whole and
    # never reduced to a head word. Reducing them was measured doing real damage: the
    # permit term "roof access permit" contributed a bare "roof", and "what competency is
    # required for the roof?" was then answered from the PERMIT register instead of the
    # competency one. A head word of a phrase is a different concept, not a shorter name
    # for the same one.
    for term in (lay or "").split("|"):
        term = term.strip().lower()
        if term:
            words.add(term)

    return tuple(sorted(w for w in words if len(w) > 3))


async def record_classes(namespace: str = "") -> List[RecordClass]:
    """The record classes the active building holds instances of, cached briefly."""
    key = namespace or "_active"
    hit = _CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _TTL_SECONDS:
        return hit[1]

    known = await _discover_record_classes()
    values = " ".join(f"o:{c}" for c in known)
    found: List[RecordClass] = []
    try:
        from orchestrator.services.ontology_manager import run_sparql_select

        result = await run_sparql_select(_QUERY % values, limit=len(known) + 1)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "SPARQL select failed")
        for row in result.get("rows") or []:
            cls = str(row.get("cls") or "")
            try:
                count = int(str(row.get("n") or "0"))
            except ValueError:
                count = 0
            if not cls or count <= 0:
                continue
            local = cls.rsplit("#", 1)[-1]
            label = str(row.get("label") or "") or local
            lays = str(row.get("lays") or "")
            found.append(RecordClass(local, label, count, _terms_for(local, label, lays)))
    except Exception as exc:
        logger.debug(f"[record_registry] could not read record classes: {exc}")
        # An unreachable graph must not make every register question route as if the
        # building held nothing — return the last known answer rather than a wrong one.
        return hit[1] if hit else []

    _CACHE[key] = (time.monotonic(), found)
    logger.info(
        "[record_registry] %s",
        ", ".join(f"{r.local_name}={r.instances}" for r in found) or "no record classes held",
    )
    return found


def held_record_class(query: str, classes: List[RecordClass]) -> Optional[RecordClass]:
    """The record class this question is about, when the building holds one."""
    low = f" {(query or '').lower()} "
    for record in classes:
        for term in record.terms:
            if re.search(rf"\b{re.escape(term)}\b", low):
                return record
    return None


#: Terms for every record class the ontology DEFINES, used to NAME what a building is
#: missing. Seeded from the class names and enriched from the TBox's declared layTerms on
#: first use, so adding a class to the ontology is all it takes.
#:
#: Head words are DELIBERATELY excluded here, unlike the held-class vocabulary. Matching
#: is asymmetric because the consequences are: claiming a question for a class the
#: building HOLDS sends it to data that exists and is checkable, while claiming one for an
#: ABSENT class produces a decline and costs a real answer. Measured — WorkOrder
#: contributed a bare "work", and "what is the procedure for hot works?" was declined as a
#: missing work-order register when the permit document answers it.
_ALL_CLASS_TERMS: Dict[str, Tuple[str, ...]] = {
    name: _terms_for(name, re.sub(r"(?<!^)(?=[A-Z])", " ", name), include_head_words=False)
    for name in _FALLBACK_RECORD_CLASSES
}
_LAY_LOADED = False


async def load_lay_terms() -> None:
    """Fold the TBox's declared lay terms into the absent-class vocabulary, once.

    Without this an ABSENT class is matched only by its class name, so a building with no
    condition survey could not name what it was missing when asked about "expected life".
    """
    global _LAY_LOADED
    if _LAY_LOADED:
        return
    try:
        from orchestrator.services.ontology_manager import run_sparql_select

        values = " ".join(f"o:{c}" for c in _FALLBACK_RECORD_CLASSES)
        result = await run_sparql_select(
            _LAY_QUERY % values, limit=len(_FALLBACK_RECORD_CLASSES) + 1
        )
        if not result.get("ok"):
            return
        for row in result.get("rows") or []:
            local = str(row.get("cls") or "").rsplit("#", 1)[-1]
            if local not in _ALL_CLASS_TERMS:
                continue
            _ALL_CLASS_TERMS[local] = _terms_for(
                local,
                re.sub(r"(?<!^)(?=[A-Z])", " ", local),
                str(row.get("lays") or ""),
                include_head_words=False,
            )
        _LAY_LOADED = True
    except Exception as exc:
        logger.debug(f"[record_registry] lay terms unavailable: {exc}")


def absent_record_class(query: str, held: List[RecordClass]) -> Optional[str]:
    """A record class the ONTOLOGY defines and this building does NOT hold.

    This is what turns one decline into a useful one. "Which contracts expire in the next
    six months?" currently reaches the document lane, which hands back the nearest passage
    — measured: it returned the PERMIT register for a contracts question. The building
    holds no contracts, and saying so, by name, is both true and actionable.

    Returns the class's local name, or None when the question is not about a record class
    at all — in which case nothing here should interfere with normal routing.
    """
    held_names = {r.local_name for r in held}
    low = f" {(query or '').lower()} "
    for name, terms in _ALL_CLASS_TERMS.items():
        if name in held_names:
            continue
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", low):
                return name
    return None


_SCHEMA_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?p (SAMPLE(?v) AS ?example) WHERE {
  ?i a o:%s ; ?p ?v .
} GROUP BY ?p
"""

_STATUS_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?s WHERE { ?i a o:%s ; o:recordStatus ?s }
"""

#: The ontology's own notes on the class and the predicates its instances carry.
#:
#: These comments already state the semantics that a query has to respect — "status is
#: READ from recordStatus, never inferred from the dates", "zero or less means at or
#: beyond expected life". Measured: without them, "which assets are beyond their expected
#: life?" returned the chiller at 0.0 years and omitted the generator at -1.0, because
#: the boundary was read as `= 0`. Putting the rule in the TBox rather than in Python
#: keeps it building-agnostic: a building that models condition differently says so in
#: its own ontology and the generator reads that instead.
_COMMENT_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?term ?c WHERE {
  { BIND(o:%s AS ?term) ?term rdfs:comment ?c }
  UNION
  { ?i a o:%s ; ?term [] . ?term rdfs:comment ?c }
}
"""


async def schema_hint(record: "RecordClass") -> str:
    """A SPARQL-generation hint for one record class, read from its own instances.

    The RAG index is built from the ontology as it stood when it was last embedded, so a
    class lifted from a document today returns zero entities and the generator writes
    SPARQL blind — measured: a permit count question hung for two minutes and timed out.

    The predicates are read from the INSTANCES rather than from a list in code, so this
    describes whatever the building actually holds. A building whose permits carry an
    extra field gets that field in the hint, with no code change.
    """
    try:
        from orchestrator.services.ontology_manager import run_sparql_select

        result = await run_sparql_select(_SCHEMA_QUERY % record.local_name, limit=40)
        if not result.get("ok"):
            return ""
        lines = []
        for row in result.get("rows") or []:
            predicate = str(row.get("p") or "")
            if not predicate or predicate.endswith("#type"):
                continue
            example = str(row.get("example") or "")[:60]
            lines.append(f"  ontosage:{predicate.rsplit('#', 1)[-1]}  e.g. {example!r}")
        if not lines:
            return ""

        status_result = await run_sparql_select(_STATUS_QUERY % record.local_name, limit=20)
        statuses = sorted(
            {str(r.get("s") or "") for r in (status_result.get("rows") or []) if r.get("s")}
        )

        comment_result = await run_sparql_select(
            _COMMENT_QUERY % (record.local_name, record.local_name), limit=40
        )
        notes = []
        for row in comment_result.get("rows") or []:
            term = str(row.get("term") or "").rsplit("#", 1)[-1]
            text = " ".join(str(row.get("c") or "").split())
            if term and text:
                notes.append(f"  ontosage:{term} — {text}")
    except Exception as exc:
        logger.debug(f"[record_registry] schema hint unavailable: {exc}")
        return ""

    # The status rule is not decoration. Measured on the first live run of the lifted
    # registers, BOTH answers were wrong in the same way: "is the standby generator under
    # warranty?" answered "expired" when the recorded status is VOID — cover withdrawn,
    # so the repair is chargeable whatever the term says — and "which contracts expire in
    # the next six months?" counted six including two that expired months ago. In each
    # case the model re-derived the state from the dates instead of reading it. The
    # catalogues forbid exactly that, and so do the registers themselves.
    status_rule = ""
    if statuses:
        status_rule = (
            "\nSTATUS IS READ, NEVER DERIVED. ontosage:recordStatus holds the owner's "
            f"recorded state, and the values actually present are: {', '.join(statuses)}. "
            "Filter on it. Do NOT infer status from effectiveFrom/effectiveTo — a record "
            "past its end date that was never closed is an exception worth reporting, and "
            "'void' is not 'expired'.\n"
        )

    ontology_notes = ""
    if notes:
        # The ontology's own words, verbatim. They state the semantics a query has to
        # respect, and they travel with the building rather than with the code.
        joined = "\n".join(sorted(set(notes))[:12])
        ontology_notes = (
            "\nWhat the ontology says about these terms — follow it exactly:\n" + joined + "\n"
        )

    today = date.today().isoformat()
    return (
        "=== RECORD CLASS HELD BY THIS BUILDING ===\n"
        "PREFIX ontosage: <http://ontosage.org/capabilities#>\n\n"
        f"This building holds {record.instances} instances of ontosage:{record.local_name} "
        f'("{record.label}"). Query them directly — they are ordinary triples.\n\n'
        "Predicates present on those instances:\n"
        + "\n".join(sorted(lines))
        + "\n"
        + status_rule
        + f"\nToday is {today}. A window such as 'in the next six months' is BOUNDED AT "
        f'BOTH ENDS — ?end >= "{today}"^^xsd:date AND ?end <= (six months later) — or '
        "records that already lapsed are counted as though they were still to come.\n"
        f"\nExample: SELECT (COUNT(?r) AS ?n) WHERE {{ ?r a ontosage:{record.local_name} }}\n"
    )


def clear_cache() -> None:
    """Drop the cache — used by tests and after a re-ingest."""
    global _LAY_LOADED
    _CACHE.clear()
    _LAY_LOADED = False
