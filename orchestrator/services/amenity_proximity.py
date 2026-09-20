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

THREE THINGS THE CATALOGUE GOT WRONG (BUG-827, 2026-09-19)
----------------------------------------------------------
    "Where is the nearest lift to Room 4.01?"
      -> "There is no lift recorded on 4.01's floor. The nearest is Passenger Lift 1 -- 3 floors
          down. Also recorded: Passenger Lift 2 / Goods Lift, Accessibility, Lift Accessibility
          Detail."

1. **A label's trailing digit is not a floor.** "Passenger Lift 1" has no floor of its own, so the
   floor was read from its label -- and 1 is the number of the lift. Both lifts serve every floor,
   and the building says so in each lift's own record. A floor now comes only from a declared floor,
   a location that IS a floor, or a label that says "floor N"; an amenity that stands on no floor
   but SERVES floors (`ontosage:servesFloor`) reaches every one of them.
2. **A topic is not an instance.** "Accessibility" and "Lift Accessibility Detail" are prose
   entries typed only as `ontosage:Amenity`; matching a kind through their lay terms listed them as
   lifts. An instance stands somewhere (a floor, a location, floors served) or has a specific kind.
3. **A broken amenity was offered as the nearest.** Status is read: the nearest is the nearest that
   works, and one that is out of service is named as such, never dropped silently.

BUILDING-AGNOSTIC
-----------------
Amenity kinds come from the ontology's `ontosage:Amenity` subclasses; floors come from the
amenity's own `onFloor`/`locatedIn`/`servesFloor`. No room number, floor count or building name
appears here, and a building whose amenities carry no floor gets an honest "located, floor not
recorded" rather than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from orchestrator.services.capability_graph_resolver import _is_out_of_service
from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

#: Classes that say "this is a capability" and name no KIND of thing (compare
#: scripts/register_reach.GENERIC_CAPABILITY_CLASSES).
_GENERIC_KINDS = frozenset(
    {"Capability", "Amenity", "KnowledgeTopic", "InformationTopic", "Policy", "Procedure"}
)


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
    #: The floors this amenity serves without standing on them (a lift), from servesFloor.
    serves: Tuple[int, ...] = ()
    #: The service state the building records (ontosage:statusValue); "" when it records none.
    status: str = ""
    #: A position somebody filled in (ontosage:isSimulated), not one the building itself states.
    placeholder: bool = False
    #: How the building describes where it is, in its own words (ontosage:locationText). Used when
    #: the asker stands at a named place rather than in a room: "left from the front entrance,
    #: approximately 25 m in" is the answer to "how do I get to the lifts from the entrance", and a
    #: floor count is not.
    location_text: str = ""

    @property
    def local(self) -> str:
        return self.iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]

    @property
    def floor_no(self) -> Optional[int]:
        return floor_number(self.floor) if self.floor else None

    @property
    def out_of_service(self) -> bool:
        return _is_out_of_service(self.status)

    def reaches(self, floor: int) -> bool:
        """True when it stands on that floor or serves it."""
        return self.floor_no == floor or floor in self.serves

    def gap_to(self, floor: int) -> Optional[int]:
        """Floors between it and `floor`; None when the building records no floor for it."""
        if self.reaches(floor):
            return 0
        candidates = list(self.serves)
        if self.floor_no is not None:
            candidates.append(self.floor_no)
        return min((abs(n - floor) for n in candidates), default=None)

    def nearest_floor_to(self, floor: int) -> Optional[int]:
        """The floor of it (or served by it) that is closest to `floor`."""
        candidates = list(self.serves)
        if self.floor_no is not None:
            candidates.append(self.floor_no)
        return min(candidates, key=lambda n: (abs(n - floor), n), default=None)


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
       (SAMPLE(?verified) AS ?acc_verified) (SAMPLE(?akind) AS ?acc_kind)
       (GROUP_CONCAT(DISTINCT ?sv; separator=" ") AS ?serves)
       (SAMPLE(?svc) AS ?service_status) (SAMPLE(?sim) AS ?simulated)
       (SAMPLE(?loctext) AS ?location_text) WHERE {
  ?a a o:Amenity .
  OPTIONAL { ?a rdfs:label ?lab }
  OPTIONAL { ?a o:onFloor ?fl }
  OPTIONAL { ?a o:locatedIn ?loc }
  OPTIONAL { ?a o:layTerms ?lay }
  OPTIONAL { ?a a ?cls . FILTER(STRSTARTS(STR(?cls), "%(ns)s") && ?cls != o:Amenity) }
  # ACCESSIBILITY IS A DECLARED FACT, asked for separately from everything else.
  OPTIONAL { ?a o:accessibilityVerified ?verified }
  OPTIONAL { ?a o:accessibilityKind ?akind }
  # A lift stands in one place and serves many floors; the building's own record says which.
  OPTIONAL { ?a o:servesFloor ?sv }
  # Service state, read the way the capability resolver reads it.
  OPTIONAL { { ?a o:amenityStatus ?st } UNION { ?st o:statusOf ?a } ?st o:statusValue ?svc }
  OPTIONAL { ?a o:isSimulated ?sim }
  # The building's own words for where it stands, for a reader who is not in a numbered room.
  OPTIONAL { ?a o:locationText ?loctext }
} GROUP BY ?a
"""

#: A floor identifier, wherever the building keeps one. Matched as "the trailing number of
#: a floor-ish name", never as a fixed grammar: `Floor3`, `Level 3`, `L3` and `3` all work,
#: and a building naming floors `Ground`/`Mezzanine` simply yields no number -- which is
#: reported as "floor not recorded" rather than guessed at.
_FLOOR_NUM_RE = re.compile(r"(-?\d+)\s*$")

#: A location IRI that IS a floor ("...#Floor4"), as against a room ("...#Room4.44").
_FLOOR_NODE_RE = re.compile(r"^(?:floor|level|storey|story|l)[\s_]*(-?\d+)$", re.IGNORECASE)

#: A label that says which floor it is on ("Accessible WC - Floor 4"). A label that merely ends in
#: a number ("Passenger Lift 1") says nothing about a floor.
_FLOOR_IN_LABEL_RE = re.compile(r"\b(?:floor|level|storey|story)\s*(-?\d+)\b", re.IGNORECASE)

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


def _floor_text(floor: str, located: str, label: str) -> str:
    """The floor an amenity stands on, in the building's own words; "" when it records none.

    A declared floor wins; then a location that is itself a floor; then a label that says
    "floor N". Nothing else is a floor -- in particular not the number a label happens to end in.
    """
    if floor:
        return floor
    local = located.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    if _FLOOR_NODE_RE.match(local):
        return located
    m = _FLOOR_IN_LABEL_RE.search(label or "")
    return f"Floor{m.group(1)}" if m else ""


def _served_floors(serves: str) -> Tuple[int, ...]:
    """The floor numbers in a space-separated list of floor IRIs, sorted and de-duplicated."""
    found = {
        n
        for n in (floor_number(part.rsplit("#", 1)[-1]) for part in (serves or "").split())
        if n is not None
    }
    return tuple(sorted(found))


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

    `namespace` is accepted for compatibility and no longer used: the query asks for ontosage
    classes, and a caller that passed the BUILDING's namespace here (the spatial lane did) made the
    class filter match nothing.
    """
    try:
        res = await sparql_exec(_QUERY % {"ns": _ONTOSAGE})
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
        serves = _served_floors((b.get("serves") or {}).get("value", ""))
        status = str((b.get("service_status") or {}).get("value", "")).strip()
        placeholder = str((b.get("simulated") or {}).get("value", "")).strip().lower() in (
            "true",
            "1",
        )
        # Lay terms are for FINDING a thing; they never establish what it is.
        haystack = " ".join([iri, label, lays, classes])
        if not _matches_kind(haystack, kind_words):
            continue
        floor_text = _floor_text(floor, located, label)
        # A TOPIC IS NOT AN INSTANCE. An entry typed only as ontosage:Amenity with no kind, no
        # floor, no location and no floors served is a paragraph of prose whose lay terms happen
        # to contain the word ("Accessibility", "Lift Accessibility Detail"); it does not stand
        # anywhere, and listing it as "also recorded" put two non-lifts in a list of lifts. The
        # generic classes do not count as a kind: a reasoner adds ontosage:Capability to all of them.
        kinds = [c for c in classes.split() if c.rsplit("#", 1)[-1] not in _GENERIC_KINDS]
        if not (kinds or floor_text or located or serves):
            continue
        # UNVERIFIED IS NOT ACCESSIBLE. The accessibility register's own doctrine, and the
        # reason `accessibilityVerified` exists: a feature nobody has surveyed is a
        # different answer from one that has been, and only the second can be relied on by
        # somebody planning a journey around it.
        is_accessible = verified in ("true", "1") or "AccessibilityFeature" in classes
        if "AccessibilityFeature" in classes and verified not in ("true", "1"):
            is_accessible = False
        hits.append(
            AmenityHit(
                iri=iri,
                label=label or iri.rsplit("#", 1)[-1],
                floor=str(floor_text),
                location=located,
                accessible=is_accessible,
                accessibility_kind=acc_kind,
                serves=serves,
                status=status,
                placeholder=placeholder,
                location_text=str((b.get("location_text") or {}).get("value", "")).strip(),
            )
        )

    if accessible_only:
        hits = [h for h in hits if h.accessible]

    # A record built from something the building states outranks a placeholder on the SAME floor:
    # a toilet in a research laboratory beside a restroom reads as a contradiction.
    real_floors = {h.floor_no for h in hits if not h.placeholder and h.floor_no is not None}
    hits = [h for h in hits if not h.placeholder or h.floor_no not in real_floors]

    if from_floor is None:
        return hits

    def distance(h: AmenityHit) -> tuple:
        gap = h.gap_to(from_floor)
        # An amenity whose floor the building does not record sorts LAST rather than
        # nearest. Treating "unknown" as "here" is how a confident wrong answer is built.
        return (0 if gap is not None else 1, gap or 0)

    return sorted(hits, key=distance)


def _where(hit: AmenityHit) -> str:
    """' in Room3.02' -- unless the label already says so, which the generated ones do."""
    local = hit.location.rsplit("#", 1)[-1]
    if not local:
        return ""
    squash = re.compile(r"\W")
    if squash.sub("", local.lower()) in squash.sub("", hit.label.lower()):
        return ""
    return f" in {local}"


#: The clause of a description that repeats which floors it serves. The answer states that once,
#: from the servesFloor triples; repeated under each lift it reads as two different facts.
_SERVES_CLAUSE = re.compile(r"[;,]?\s*(?:and\s+)?serves?\s+floors?\b[^.;]*[.;]?", re.IGNORECASE)


def _descriptions(hits: Sequence[AmenityHit]) -> List[str]:
    """Each amenity's own words for where it stands, minus what the answer already said."""
    out: List[str] = []
    for h in hits:
        blurb = _SERVES_CLAUSE.sub("", h.location_text or "").strip(" ;,.")
        # The label opens most descriptions ("Passenger Lift 1, left from ..."); said twice it
        # reads as a stutter, so it is removed where the description repeats it. The label's first
        # segment too: "Passenger Lift 2 / Goods Lift" is described as "Passenger Lift 2, ...".
        for opener in (h.label, h.label.split("/")[0].strip()):
            if opener and blurb.lower().startswith(opener.lower()):
                blurb = blurb[len(opener) :].strip(" ,;")
                break
        if blurb:
            out.append(f"\n- **{h.label}** — {blurb}.")
    return out


#: Recorded states that mean "can be used". Anything else the building records is repeated in its
#: own words rather than translated.
_IN_SERVICE = frozenset({"operational", "in_service", "in service", "working", "open", "available"})


def _service_line(hits: Sequence[AmenityHit]) -> str:
    """Answer 'is it in service?' from the recorded state, or say none is recorded.

    A question that asks whether the nearest one works must not be answered with only where it is.
    The state is the building's record (ontosage:statusValue) and can be old: it is reported as
    recorded, never as a live reading, and an amenity with no record is not assumed to work.
    """
    parts: List[str] = []
    for h in hits:
        state = (h.status or "").strip()
        low = state.lower().replace("-", "_")
        if not state:
            parts.append(f"the building records no service state for {h.label}, so I cannot say")
        elif h.out_of_service:
            parts.append(f"{h.label} is recorded as out of service")
        elif low in _IN_SERVICE:
            parts.append(f"{h.label} is recorded as in service")
        else:
            parts.append(f"{h.label} is recorded as {state.replace('_', ' ')}")
    return "\n**Service state:** " + "; ".join(parts) + "."


def _name(hit: AmenityHit) -> str:
    """The amenity's label, with its state when the building records it as out of service."""
    return f"{hit.label} (currently out of service)" if hit.out_of_service else hit.label


def _and_join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def render(
    hits: Sequence[AmenityHit],
    kind_word: str,
    from_label: str,
    from_floor: Optional[int],
    accessible_only: bool,
    from_is_floor: bool = False,
    describe_places: bool = False,
    asked_service: bool = False,
) -> str:
    """Say what the building knows, and say what it is not.

    Never called with an empty list by the caller -- an empty result is the floor plan's
    honest decline, which is already correct and should not be replaced.

    `from_is_floor` is set when the asker named a floor rather than a room ("on floor 1"), so
    the answer says "on floor 1" instead of "on floor 1's floor".

    `describe_places` adds each amenity's own description of where it stands. Somebody standing at
    the entrance asked HOW TO GET THERE: "left from the front entrance, approximately 25 m in" is
    an answer and "it serves your floor" is not. Off by default, because from a numbered room that
    description is about a different starting point than the one asked about.
    """
    qualifier = "accessible " if accessible_only else ""
    where = f"floor {from_floor}" if (from_is_floor and from_floor is not None) else None
    at = where or f"{from_label}'s floor"
    lines: List[str] = []

    # THE NEAREST IS THE NEAREST THAT WORKS. An amenity the building records as out of service is
    # named, and never offered as the place to go; when nothing works, what is recorded is
    # reported with its state instead of being dropped.
    working = [h for h in hits if not h.out_of_service]
    broken = [h for h in hits if h.out_of_service]
    pool = working or list(hits)

    on_floor = [h for h in pool if from_floor is not None and h.floor_no == from_floor]
    serving = [
        h for h in pool if from_floor is not None and h not in on_floor and from_floor in h.serves
    ]
    primary: List[AmenityHit]
    if on_floor:
        h = on_floor[0]
        here = _where(h)
        if where:
            lines.append(f"**A {qualifier}{kind_word} is recorded on {where}:** {_name(h)}{here}.")
        else:
            lines.append(
                f"**The {qualifier}{kind_word} nearest {from_label} is on the same floor:** "
                f"{_name(h)}{here}."
            )
        primary = [h]
    elif serving:
        names = _and_join([f"**{_name(h)}**" for h in serving])
        verb = "serves" if len(serving) == 1 else "serve"
        lines.append(f"{names} {verb} {at}" + ("" if where else f" (floor {from_floor})") + ".")
        if len(serving) > 1:
            lines.append(
                f"\nThe catalogue records which floors each serves, not how far each is from "
                f"{from_label}, so I cannot say which is nearer."
            )
        primary = list(serving)
        if describe_places:
            lines.extend(_descriptions(serving))
    else:
        nearest = pool[0]
        n = nearest.nearest_floor_to(from_floor) if from_floor is not None else None
        if from_floor is not None and n is not None:
            delta = abs(n - from_floor)
            direction = "up" if n > from_floor else "down"
            # STATED PLAINLY, because this is the case that matters. "There is none on
            # your floor" is the fact somebody plans around.
            lines.append(
                f"**There is no {qualifier}{kind_word} recorded on {at}.** "
                f"The nearest is {_name(nearest)} — {delta} floor{'s' if delta > 1 else ''} "
                f"{direction}."
            )
        else:
            lines.append(
                f"**The building records a {qualifier}{kind_word}:** {_name(nearest)}. Its "
                f"floor is not recorded, so I cannot say how far it is from {from_label}."
            )
        primary = [nearest]

    if asked_service:
        lines.append(_service_line(primary))

    others = [h for h in pool if h not in primary]
    if others:
        listed = ", ".join(f"{_name(h)}" for h in others[:4])
        lines.append(f"\nAlso recorded: {listed}.")

    down = [h for h in broken if h not in pool]
    if down:
        lines.append("\nCurrently out of service: " + ", ".join(h.label for h in down[:4]) + ".")
    elif not working and broken:
        lines.append("\n**Everything recorded here is currently out of service.**")

    # NOT A ROUTE, and it says so. Floors apart is not walking distance, and a lift may be out of
    # service -- presenting a floor delta as wayfinding would be the substitution the honesty
    # contract forbids.
    lines.append(
        "\n_From the building's amenity catalogue, measured in floors — not a surveyed "
        "route. It does not account for walking distance, door types or whether the lift "
        "is in service._"
    )
    return "\n".join(lines)
