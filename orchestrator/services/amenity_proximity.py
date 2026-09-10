# -*- coding: utf-8 -*-
"""Where the nearest amenity of a kind is, when the floor plan cannot say (V10 W0-7).

WHAT WENT WRONG
---------------
    "Nearest accessible toilet to room 3.10?"
      -> "No toilet is reachable from 3.10 in the floor-plan adjacency data - either none
          is mapped or the adjacency is incomplete."

The floor-plan adjacency genuinely could not answer it. The BUILDING could:

    Amenity_ToiletFacility_Floor3   locatedIn Room3.02      (same floor as the question)
    access_accessible_wc_0          locatedIn Floor0
    access_accessible_wc_4          locatedIn Floor4        <- and no accessible WC on 3

So the honest answer is *"there is no accessible WC on floor 3; the nearest are one floor
up on Floor 4, and on the ground floor"* -- and the system said the building has none
reachable at all.

WHY THIS ONE MATTERS MORE THAN ITS SIZE
---------------------------------------
For someone with mobility needs, *"no toilet is reachable"* and *"the accessible one is one
floor up"* are not degrees of the same answer. The first ends a journey. The accessible-
route mapping in `ontology/record_documents/` says as much in its own header: people with
access requirements do not ask whether a building is accessible in general, they ask about
a specific journey, and 53 of their questions were unanswered at capture.

WHAT THIS IS NOT
----------------
**Not a route, and it never claims to be.** Floor distance is not walking distance, and a
lift may be out of service. Every answer says what it measured -- floors apart -- and says
plainly that it is not a surveyed route. Presenting a floor delta as wayfinding would be
the substitution this project's honesty contract exists to prevent.

**Not a search of the floor plan.** That is the RouteFinder's job and it runs first. This
is what the building's own amenity catalogue knows when the geometry does not.

BUILDING-AGNOSTIC
-----------------
Amenity kinds come from the ontology's `ontosage:Amenity` subclasses; floors come from the
amenity's own `onFloor`/`locatedIn`. No room number, floor count or building name appears
here, and a building whose amenities carry no floor gets an honest "located, floor not
recorded" rather than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"


@dataclass(frozen=True)
class AmenityHit:
    """One amenity of the requested kind, and where the building says it is."""

    iri: str
    label: str
    floor: str = ""
    location: str = ""
    #: True only when the building DECLARES it accessible and records that as verified.
    accessible: bool = False
    accessibility_kind: str = ""

    @property
    def local(self) -> str:
        return self.iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


#: Every amenity, with whatever the building records about where it is.
#:
#: Deliberately UNFILTERED by kind. Filtering in SPARQL would need the kind's class IRI,
#: and a building may express "toilet" as a subclass, a label or a lay term -- so the
#: filtering happens in Python against all three, and a building that spells it a fourth
#: way is one lay term away from working.
_QUERY = """
PREFIX o:    <http://ontosage.org/capabilities#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?a (SAMPLE(?lab) AS ?label) (SAMPLE(?fl) AS ?floor) (SAMPLE(?loc) AS ?located)
       (GROUP_CONCAT(DISTINCT ?lay; separator=" | ") AS ?lays)
       (GROUP_CONCAT(DISTINCT ?cls; separator=" ") AS ?classes)
       (SAMPLE(?verified) AS ?acc_verified) (SAMPLE(?akind) AS ?acc_kind) WHERE {
  ?a a o:Amenity .
  OPTIONAL { ?a rdfs:label ?lab }
  OPTIONAL { ?a o:onFloor ?fl }
  OPTIONAL { ?a o:locatedIn ?loc }
  OPTIONAL { ?a o:layTerms ?lay }
  OPTIONAL { ?a a ?cls . FILTER(STRSTARTS(STR(?cls), "%(ns)s") && ?cls != o:Amenity) }
  # ACCESSIBILITY IS A DECLARED FACT, asked for separately from everything else.
  OPTIONAL { ?a o:accessibilityVerified ?verified }
  OPTIONAL { ?a o:accessibilityKind ?akind }
} GROUP BY ?a
"""

#: A floor identifier, wherever the building keeps one. Matched as "the trailing number of
#: a floor-ish name", never as a fixed grammar: `Floor3`, `Level 3`, `L3` and `3` all work,
#: and a building naming floors `Ground`/`Mezzanine` simply yields no number -- which is
#: reported as "floor not recorded" rather than guessed at.
_FLOOR_NUM_RE = re.compile(r"(-?\d+)\s*$")

#: Words that mean "step-free / usable with a mobility aid" IN THE QUESTION.
#:
#: Used to read what the ASKER wants, and never to decide whether an amenity delivers it.
#: The first version of this module searched the same pattern across each amenity's lay
#: terms, and every ordinary toilet in this building carries "accessible toilet" among
#: them -- for SEARCH, so that somebody typing those words finds a toilet. The result was
#: the worst answer this file could produce: it told a wheelchair user that the toilet on
#: their own floor was accessible, when the building's accessibility register records
#: verified accessible WCs only on floors 0 and 4.
_ACCESSIBLE_RE = re.compile(
    r"\b(accessible|step[- ]free|wheelchair|disabled|ambulant|mobility)\b", re.IGNORECASE
)


def floor_number(text: str) -> Optional[int]:
    """The floor number in a floor name, or None when the building does not use numbers."""
    m = _FLOOR_NUM_RE.search(str(text or "").strip())
    return int(m.group(1)) if m else None


def wants_accessible(question: str) -> bool:
    return bool(_ACCESSIBLE_RE.search(question or ""))


def _matches_kind(hit_text: str, kind_words: Sequence[str]) -> bool:
    low = hit_text.lower()
    return any(w.lower() in low for w in kind_words if w)


async def nearest_by_floor(
    sparql_exec: Callable,
    namespace: str,
    kind_words: Sequence[str],
    from_floor: Optional[int],
    accessible_only: bool = False,
) -> List[AmenityHit]:
    """Amenities of this kind, ordered by how many floors away they are.

    `from_floor` None means the reference point's floor is unknown; results come back in
    the building's own order rather than sorted, because "nearest" would then be a claim
    nothing supports.
    """
    try:
        res = await sparql_exec(_QUERY % {"ns": namespace or _ONTOSAGE})
    except Exception as exc:
        logger.warning(f"[amenity_proximity] lookup failed: {exc}")
        return []

    hits: List[AmenityHit] = []
    for b in (res or {}).get("results", {}).get("bindings", []):
        iri = b.get("a", {}).get("value", "")
        label = (b.get("label") or {}).get("value", "")
        floor = (b.get("floor") or {}).get("value", "")
        located = (b.get("located") or {}).get("value", "")
        lays = (b.get("lays") or {}).get("value", "")
        classes = (b.get("classes") or {}).get("value", "")
        verified = str((b.get("acc_verified") or {}).get("value", "")).strip().lower()
        acc_kind = str((b.get("acc_kind") or {}).get("value", "")).strip()
        # Lay terms are for FINDING a thing; they never establish what it is.
        haystack = " ".join([iri, label, lays, classes])
        if not _matches_kind(haystack, kind_words):
            continue
        # UNVERIFIED IS NOT ACCESSIBLE. The accessibility register's own doctrine, and the
        # reason `accessibilityVerified` exists: a feature nobody has surveyed is a
        # different answer from one that has been, and only the second can be relied on by
        # somebody planning a journey around it.
        is_accessible = verified in ("true", "1") or "AccessibilityFeature" in classes
        if "AccessibilityFeature" in classes and verified not in ("true", "1"):
            is_accessible = False
        # A located amenity with no `onFloor` still often names its floor in the location
        # IRI or the label; both are the building's own words, so both are read.
        floor_text = floor or located or label
        hits.append(
            AmenityHit(
                iri=iri,
                label=label or iri.rsplit("#", 1)[-1],
                floor=str(floor_text),
                location=located,
                accessible=is_accessible,
                accessibility_kind=acc_kind,
            )
        )

    if accessible_only:
        hits = [h for h in hits if h.accessible]

    if from_floor is None:
        return hits

    def distance(h: AmenityHit) -> tuple:
        n = floor_number(h.floor)
        # An amenity whose floor the building does not record sorts LAST rather than
        # nearest. Treating "unknown" as "here" is how a confident wrong answer is built.
        return (0 if n is not None else 1, abs(n - from_floor) if n is not None else 0)

    return sorted(hits, key=distance)


def render(
    hits: Sequence[AmenityHit],
    kind_word: str,
    from_label: str,
    from_floor: Optional[int],
    accessible_only: bool,
) -> str:
    """Say what the building knows, and say what it is not.

    Never called with an empty list by the caller -- an empty result is the floor plan's
    honest decline, which is already correct and should not be replaced.
    """
    qualifier = "accessible " if accessible_only else ""
    lines: List[str] = []

    same = [h for h in hits if from_floor is not None and floor_number(h.floor) == from_floor]
    if same:
        h = same[0]
        where = f" in {h.location.rsplit('#', 1)[-1]}" if h.location else ""
        lines.append(
            f"**The {qualifier}{kind_word} nearest {from_label} is on the same floor:** "
            f"{h.label}{where}."
        )
    else:
        nearest = hits[0]
        n = floor_number(nearest.floor)
        if from_floor is not None and n is not None:
            delta = abs(n - from_floor)
            direction = "up" if n > from_floor else "down"
            # STATED PLAINLY, because this is the case that matters. "There is none on
            # your floor" is the fact somebody plans around.
            lines.append(
                f"**There is no {qualifier}{kind_word} recorded on {from_label}'s floor.** "
                f"The nearest is {nearest.label} — {delta} floor{'s' if delta > 1 else ''} "
                f"{direction}."
            )
        else:
            lines.append(
                f"**The building records a {qualifier}{kind_word}:** {nearest.label}. Its "
                f"floor is not recorded, so I cannot say how far it is from {from_label}."
            )

    others = [h for h in hits if h is not (same[0] if same else hits[0])]
    if others:
        listed = ", ".join(f"{h.label}" for h in others[:4])
        lines.append(f"\nAlso recorded: {listed}.")

    # NOT A ROUTE, and it says so. Floors apart is not walking distance, and a lift may be
    # out of service -- presenting a floor delta as wayfinding would be the substitution
    # the honesty contract forbids.
    lines.append(
        "\n_From the building's amenity catalogue, measured in floors — not a surveyed "
        "route. It does not account for walking distance, door types or whether the lift "
        "is in service._"
    )
    return "\n".join(lines)
