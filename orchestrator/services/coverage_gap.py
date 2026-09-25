# -*- coding: utf-8 -*-
"""Which spaces have NO sensor of a quantity — answered from the coverage matrix (W1-05).

WHY THIS EXISTS, AND WHY IT IS NOT A NEW QUERY
-----------------------------------------------
"Which rooms have no temperature sensor?" is a set difference the graph can answer exactly, and
before this the LLM was asked to write the SPARQL for it. Measured live 2026-09-23, three
phrasings, three different wrong answers:

  * "Which rooms have no temperature sensor?"   -> "All of the rooms that are recorded in the
    building model have at least one temperature sensor", narrated from a query that returned a
    TOTAL sensor count per room and therefore cannot distinguish a temperature sensor from any
    other. A confident false negative, with a fabricated "Total spaces recorded: 100" in a
    building with 234.
  * "Which spaces have no CO2 sensor?"          -> honestly admitted the query had no types.
  * "Are there any rooms without a noise sensor?" -> a table of sound LEVELS. A different
    question answered confidently.

`deliberation/coverage_audit.py` already answers this. Its first line of documentation is the
question verbatim -- "which spaces lack which sensor modalities?" -- and it is already
subclass-closure-aware, already handles both location idioms in the wild (`brick:hasLocation`
and `brick:isPointOf` an equipment sited in the space), and already takes its modality list from
config with a per-building overlay. It was built for the SATURATE provisioner and never asked.

THE THREE-WAY ANSWER IS THE POINT
----------------------------------
The audit distinguishes PRESENT, UNBACKED (a sensor is modelled but carries no timeseries
reference) and MISSING (no sensor of the quantity at all). A set-difference SPARQL written for
this row would have collapsed the last two, and "there is no sensor" and "there is a sensor that
reports nothing" are different facts that lead to different repairs -- the four-kinds-of-nothing
distinction this project already keeps elsewhere. They are reported separately here.

BUILDING-AGNOSTIC BY CONSTRUCTION. No namespace, class, modality or space name appears in this
module: the quantity comes from the active building's own modality config, the spaces from its
own graph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[Dict[str, Any]]]

#: How many spaces to name before summarising. A reader cannot use a list of 200 room names, and
#: an answer that prints them all buries the count that was actually asked for.
NAME_LIMIT = 12

#: The question shape: a plural space noun, and an absence. Both halves are required -- "which
#: rooms have a temperature sensor" and "no parking today" must not match.
#:
#: The absence may come before the noun ("which rooms have NO x", "rooms WITHOUT x") or the
#: question may be existential ("are there any rooms without x"). `lacking`/`missing` are
#: included because operators write them; `not` is deliberately absent, because "which rooms are
#: not too warm" is a comfort question about readings, not about instrumentation.
_GAP_RE = re.compile(
    r"\b(?:rooms?|spaces?|zones?|areas?|offices?|labs?|laboratories)\b"
    r"[^?.]{0,60}?\b(?:without|no|lacking|lack|missing|not\s+(?:have|having|fitted|equipped))\b",
    re.IGNORECASE,
)

#: The question must also be about INSTRUMENTATION, not about a reading. "Which rooms have no
#: people in them" is an occupancy question the data lanes answer; "which rooms have no occupancy
#: sensor" is this one. The difference is the word for the instrument.
_INSTRUMENT_RE = re.compile(
    r"\b(?:sensors?|meters?|points?|detectors?|monitors?|instrumentation|instrumented|"
    r"monitoring|coverage)\b",
    re.IGNORECASE,
)


@dataclass
class GapAnswer:
    """What the coverage matrix says about one quantity across the building."""

    modality: str
    #: The reader's word for the quantity, from the question or the modality name.
    term: str
    total: int = 0
    present: int = 0
    unbacked: int = 0
    missing: int = 0
    missing_labels: List[str] = field(default_factory=list)
    unbacked_labels: List[str] = field(default_factory=list)


def _phrase(modality: str) -> str:
    return str(modality).replace("_", " ").strip()


def detect(question: str, modality_names: Sequence[str]) -> Optional[str]:
    """The modality a coverage-gap question is about, or None.

    Matched against the ACTIVE building's declared modality names, longest first, so a building
    that does not measure a quantity never matches a question about it -- which keeps the honest
    "not measured" decline reachable instead of answering "every room lacks it".
    """
    q = " ".join(str(question or "").split())
    if not q or not _GAP_RE.search(q) or not _INSTRUMENT_RE.search(q):
        return None
    low = q.lower()
    best: Optional[str] = None
    for name in sorted(modality_names, key=lambda n: -len(str(n))):
        phrase = _phrase(name).lower()
        if not phrase:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", low):
            best = str(name)
            break
    return best


async def resolve_modality(question: str, modality_names: Sequence[str]) -> Optional[str]:
    """`detect`, then the concept resolver for a lay word no modality name spells.

    "Which rooms have no stuffiness sensor" names no modality; the concept register knows the
    word means CO2. Resolution is the building's own vocabulary either way -- nothing here holds
    a synonym list.
    """
    direct = detect(question, modality_names)
    if direct:
        return direct
    q = " ".join(str(question or "").split())
    if not q or not _GAP_RE.search(q) or not _INSTRUMENT_RE.search(q):
        return None
    try:
        from orchestrator.services.concept_resolver import ConceptResolver

        matches = await ConceptResolver().resolve(q)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"[coverage_gap] concept resolution unavailable: {exc}")
        return None
    wanted = {str(c).rsplit("#", 1)[-1].rsplit(":", 1)[-1].lower()
              for m in (matches or []) for c in (getattr(m, "brick_classes", None) or [])}
    if not wanted:
        return None
    try:
        from orchestrator.services.deliberation.coverage_audit import load_modality_raw

        raw = load_modality_raw() or {}
    except Exception:  # pragma: no cover - defensive
        return None
    for name in sorted(modality_names, key=lambda n: -len(str(n))):
        spec = raw.get(str(name)) or {}
        classes = {str(c).rsplit("#", 1)[-1].rsplit(":", 1)[-1].lower()
                   for c in (spec.get("brick_classes") or [])}
        sat = (spec.get("sat") or {}).get("brick_class")
        if sat:
            classes.add(str(sat).rsplit(":", 1)[-1].lower())
        if classes & wanted:
            return str(name)
    return None


def summarise(spaces: Sequence[Any], modality: str, term: str = "") -> GapAnswer:
    """Fold the coverage matrix into the counts this question asks for. Pure."""
    from orchestrator.services.deliberation.coverage_audit import (
        STATUS_MISSING,
        STATUS_PRESENT,
        STATUS_UNBACKED,
    )

    out = GapAnswer(modality=modality, term=term or _phrase(modality))
    for sc in spaces or []:
        entry = (getattr(sc, "modalities", None) or {}).get(modality)
        if not entry:
            # A space the audit never judged for this modality is NOT evidence of absence.
            # Counting it as missing would turn an unaudited space into a reported gap.
            continue
        out.total += 1
        status = str(entry.get("status") or "")
        label = str(getattr(sc, "label", "") or "")
        if status == STATUS_PRESENT:
            out.present += 1
        elif status == STATUS_UNBACKED:
            out.unbacked += 1
            out.unbacked_labels.append(label)
        elif status == STATUS_MISSING:
            out.missing += 1
            out.missing_labels.append(label)
    out.missing_labels.sort()
    out.unbacked_labels.sort()
    return out


def _listing(labels: Sequence[str]) -> str:
    named = [x for x in labels if x][:NAME_LIMIT]
    if not named:
        return ""
    rest = len([x for x in labels if x]) - len(named)
    body = ", ".join(named)
    return f"{body}, and {rest} more" if rest > 0 else body


def render(answer: GapAnswer) -> str:
    """The answer, deterministically. Every number comes from the matrix, none from a model."""
    a = answer
    if a.total == 0:
        return (
            f"I have no coverage record for {a.term} in this building, so I cannot say which "
            f"spaces lack it."
        )
    lines: List[str] = []
    if a.missing == 0:
        lines.append(
            f"**Every one of the {a.total} spaces I audited has a {a.term} sensor.** "
            f"None is missing one."
        )
    else:
        lines.append(
            f"**{a.missing} of {a.total} spaces have no {a.term} sensor.** "
            f"{a.present} have one that reports readings."
        )
        listed = _listing(a.missing_labels)
        if listed:
            lines.append(f"Without one: {listed}.")
    if a.unbacked:
        # SAY THIS SEPARATELY. A modelled sensor that reports nothing is not a missing sensor,
        # and merging the two would send someone to install hardware that is already fitted.
        listed = _listing(a.unbacked_labels)
        lines.append(
            f"A further **{a.unbacked}** {'space has' if a.unbacked == 1 else 'spaces have'} a "
            f"{a.term} sensor recorded that carries no readings"
            + (f" ({listed})" if listed else "")
            + " — fitted but not reporting, which is a different problem from not having one."
        )
    lines.append(f"_Tested against the building's `{a.modality}` sensor coverage._")
    return "\n\n".join(lines)


async def answer(question: str, sparql_exec: SparqlExec, namespace: str) -> Optional[str]:
    """The finished answer for a coverage-gap question, or None to leave the lane alone."""
    try:
        from orchestrator.services.deliberation.coverage_audit import (
            CoverageAuditor,
            load_modalities,
        )

        modalities = load_modalities()
        modality = await resolve_modality(question, [m.name for m in modalities])
        if not modality:
            return None
        try:
            from orchestrator.services.building_metrics import fresh_uuids

            fresh = await fresh_uuids()
        except Exception:  # pragma: no cover - freshness is optional
            fresh = None
        auditor = CoverageAuditor(sparql_exec, modalities, fresh_uuids=fresh)
        spaces = await auditor.audit(namespace)
        got = summarise(spaces, modality)
        logger.info(
            f"[coverage_gap] {modality}: {got.missing} missing / {got.unbacked} unbacked / "
            f"{got.present} present of {got.total}"
        )
        return render(got)
    except Exception as exc:  # pragma: no cover - must never cost the lane its answer
        logger.warning(f"[coverage_gap] stood down: {exc}")
        return None
