# -*- coding: utf-8 -*-
"""What the building says about ITSELF — age, type, size, owner, purpose, access.

Measured against the survey corpus this was the largest class of unanswered
question, and none of it is about sensors:

    "how old is this building?"      "who built it?"        "what type of
    building is this?"               "how big is it?"       "what is it for?"
    "are visitors allowed?"          "is this commercial?"  "where is it?"

Every one deflected. The pipeline could route them; there was simply nothing to
route TO — no instance carried the facts, and no code referenced the predicates
that hold them.

Building-agnostic by construction
---------------------------------
Nothing here names a building or a value. The resolver asks the graph what the
active building's own node asserts and reports exactly that, so a building that
declares five facts answers five questions and one that declares none is told so
honestly. Quantitative facts use Brick's existing predicates (yearBuilt,
grossArea, buildingPrimaryFunction, …); the descriptive ones Brick has no term
for come from the OCBV schema. The question→facet mapping is ordinary English,
carrying no site's vocabulary.

Why a resolver rather than the LLM
----------------------------------
"How old is this building?" is exactly the shape an open-domain answerer will
answer confidently and wrongly, because a plausible year is easy to produce and
impossible for the reader to falsify. Grounding it in the graph — or declining —
is the same contract the sensor path already keeps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[dict]]

BRICK = "https://brickschema.org/schema/Brick#"
ONTOSAGE = "http://ontosage.org/capabilities#"

# ── the facts a building may state about itself ──────────────────────────────
# (facet, predicate IRI, human label). Order is the order they are reported in,
# which is the order a person tends to want them: what it is, then how big, then
# who is behind it, then how to deal with it.
_FACTS: List[Tuple[str, str, str]] = [
    ("purpose", ONTOSAGE + "buildingPurpose", "Purpose"),
    ("type", BRICK + "buildingPrimaryFunction", "Primary function"),
    ("occupancy", ONTOSAGE + "buildingOccupancyType", "Who uses it"),
    ("age", BRICK + "yearBuilt", "Year built"),
    ("size", BRICK + "grossArea", "Gross area"),
    ("size", BRICK + "netArea", "Net area"),
    ("storeys", ONTOSAGE + "buildingStoreys", "Storeys"),
    ("owner", ONTOSAGE + "buildingOwner", "Owner"),
    ("operator", ONTOSAGE + "buildingOperator", "Operated by"),
    ("architect", ONTOSAGE + "buildingArchitect", "Designed / built by"),
    ("address", ONTOSAGE + "buildingAddress", "Address"),
    ("access", ONTOSAGE + "buildingAccessPolicy", "Access"),
    ("stage", BRICK + "operationalStage", "Operational stage"),
]

# ── which facet a question is asking for ─────────────────────────────────────
# Generic English only. A facet that matches nothing still yields the full
# profile, which is the useful answer to "tell me about this building".
_FACET_PATTERNS: List[Tuple[str, str]] = [
    (
        "age",
        r"\bhow old\b|\byear (?:was )?(?:it |this |the building )?(?:built|constructed)\b|\bwhen was (?:it|this|the building) (?:built|constructed)\b|\bage of (?:the|this) building\b|\bhow long has (?:it|this building) (?:been|stood)\b",
    ),
    (
        "size",
        r"\bhow (?:big|large)\b|\bgross area\b|\bnet area\b|\bfloor area\b|\btotal area\b|\bsquare (?:met|foot|feet)\w*\b|\bsize of (?:the|this) building\b",
    ),
    (
        "type",
        r"\bwhat (?:type|kind|sort) of building\b|\bis (?:this|it) a (?:commercial|residential|office|educational|industrial|retail|public)\b|\bbuilding type\b|\bwhat type residence\b|\bprimary function\b",
    ),
    ("owner", r"\bwho owns\b|\bowner of\b|\bwho is the owner\b|\bowned by\b"),
    (
        "operator",
        r"\bwho (?:runs|operates|manages)\b|\boperated by\b|\bmanaged by\b|\bfacilities team\b|\bwho looks after\b",
    ),
    (
        "architect",
        r"\bwho (?:built|designed|constructed)\b|\barchitect\b|\bdesigned by\b|\bbuilt by\b|\bcontractor\b",
    ),
    (
        "address",
        r"\b(?:what|where) is (?:the |its )?address\b|\bwhere is (?:this|the) building (?:located|situated)\b|\bpostcode\b|\bwhereabouts is\b",
    ),
    (
        "access",
        r"\bare visitors allowed\b|\bcan (?:i|we|the public|visitors|anyone) (?:come |get )?in(?:to)?\b|\bvisitor (?:check|access|policy)\b|\bopen to the public\b|\bcheck.?in\b|\bdo i need (?:a )?(?:pass|badge|permit)\b",
    ),
    (
        "occupancy",
        r"\bwho (?:uses|occupies|works in)\b|\bis (?:this|it) a residence\b|\bwho (?:is|are) (?:in|inside)\b(?!.*\bright now\b)|\boccupancy type\b|\bresidential\b",
    ),
    (
        "purpose",
        r"\bwhat is (?:this|the) building for\b|\bpurpose of (?:this|the) building\b|\bwhat (?:is|are) (?:it|this) used for\b|\bwhat happens (?:here|in this building)\b",
    ),
    ("storeys", r"\bhow many (?:storeys|storys|stories)\b|\bnumber of storeys\b"),
]

# The whole profile, rather than one facet.
_WHOLE_PROFILE = re.compile(
    r"\btell me about (?:this|the) building\b"
    r"|\bdescribe (?:this|the) building\b"
    r"|\babout (?:this|the) building\b"
    r"|\bbuilding (?:profile|details|information|info)\b"
    r"|\bwhat (?:do you know|can you tell me) about (?:this|the) building\b",
    re.IGNORECASE,
)

# "Do you have a name?" / "what is this building called?" — the building's own
# label already answers this, so it is handled without needing a declared fact.
_NAME_Q = re.compile(
    r"\b(?:do you have|what(?:'s| is)) (?:a |the |its |your )?name\b"
    r"|\bwhat (?:is|are) (?:this|the) building called\b"
    r"|\bname of (?:this|the) building\b",
    re.IGNORECASE,
)

# Questions that merely CONTAIN "building" but are about its contents or live
# state — those belong to the sensor, spatial and metrics paths, not here.
_NOT_PROFILE = re.compile(
    r"\bhow many (?:sensors?|zones?|rooms?|floors?|points?|devices?|meters?)\b"
    r"|\b(?:temperature|humidity|co2|occupancy|energy|noise|air quality)\b"
    r"|\bright now\b|\bcurrently\b|\btoday\b|\bthis (?:week|month)\b"
    r"|\bshow me\b|\bfloor plan\b",
    re.IGNORECASE,
)


def detect_facet(query: str) -> Optional[str]:
    """Which self-description facet is being asked for, if any.

    Returns a facet name, ``"__all__"`` for a whole-profile request, ``"name"``
    for the building's own name, or None when the question is not about the
    building as an entity.
    """
    if not query or not query.strip():
        return None
    q = query.strip()

    # A question about the building's CONTENTS or live state is not a profile
    # question even when it says "building" — those paths answer it better.
    if _NOT_PROFILE.search(q):
        return None
    if _NAME_Q.search(q):
        return "name"
    if _WHOLE_PROFILE.search(q):
        return "__all__"
    for facet, pattern in _FACET_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return facet
    return None


@dataclass
class BuildingProfile:
    """Whatever the active building states about itself — possibly nothing."""

    facts: Dict[str, str] = field(default_factory=dict)  # label -> value
    facets: Dict[str, str] = field(default_factory=dict)  # facet -> value
    resolved: bool = False  # did the lookup actually run?

    @property
    def has_any(self) -> bool:
        return bool(self.facts)


def _building_query(namespace: str) -> str:
    """Ask for every descriptive predicate at once — one round trip."""
    values = " ".join(f"<{iri}>" for _f, iri, _l in _FACTS)
    return f"""
PREFIX brick: <{BRICK}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?p ?v WHERE {{
  ?b a brick:Building .
  FILTER(STRSTARTS(STR(?b), "{namespace}"))
  VALUES ?p {{ {values} }}
  ?b ?p ?v .
}} LIMIT 40
"""


async def resolve(namespace: str, sparql_exec: SparqlExec) -> BuildingProfile:
    """Read the active building's self-description from the graph.

    Never raises: an unavailable graph yields an unresolved profile, and the
    caller then says it could not look this up rather than inventing a value.
    """
    profile = BuildingProfile()
    try:
        data = await sparql_exec(_building_query(namespace))
    except Exception as e:  # graph down / malformed — say so, never guess
        logger.warning(f"[building_profile] lookup failed: {e}")
        return profile

    profile.resolved = True
    rows = (data or {}).get("results", {}).get("bindings", []) if isinstance(data, dict) else []
    by_iri = {iri: (facet, label) for facet, iri, label in _FACTS}
    for row in rows:
        iri = (row.get("p") or {}).get("value", "")
        val = (row.get("v") or {}).get("value", "")
        if not iri or not val or iri not in by_iri:
            continue
        facet, label = by_iri[iri]
        # A blank-node placeholder is not a value a person can use.
        if val.startswith("n") and len(val) > 24 and " " not in val:
            continue
        profile.facts.setdefault(label, val)
        profile.facets.setdefault(facet, val)
    return profile


def _format_area(value: str) -> str:
    """Areas are stored bare; give them a unit if they plainly lack one."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return value
    return f"{n:,.0f} m²"


def render(
    profile: BuildingProfile,
    facet: str,
    building_name: str,
    storeys_live: Optional[int] = None,
) -> Optional[str]:
    """Compose the answer, or None when the building states nothing relevant.

    Returning None is deliberate: the caller then runs its normal honest-decline
    path, so an absent fact is reported the same way an absent sensor is.
    """
    if not profile.resolved:
        return (
            f"I couldn't look up **{building_name}**'s own details just now — the ontology "
            "didn't answer in time. I'd rather tell you that than guess at them."
        )

    # The name is knowable without any declared fact.
    if facet == "name":
        return f"This building is **{building_name}**."

    if not profile.has_any:
        return None  # nothing declared — caller declines with its own guidance

    def _fmt(label: str, value: str) -> str:
        if "area" in label.lower():
            return _fmt_pair(label, _format_area(value))
        return _fmt_pair(label, value)

    def _fmt_pair(label: str, value: str) -> str:
        return f"- **{label}:** {value}"

    if facet == "__all__":
        lines = [f"Here is what **{building_name}** states about itself:", ""]
        lines += [_fmt(lbl, val) for lbl, val in profile.facts.items()]
        if storeys_live and "Storeys" not in profile.facts:
            lines.append(_fmt_pair("Floors modelled", str(storeys_live)))
        return "\n".join(lines)

    # A single facet: answer it directly, and only that.
    value = profile.facets.get(facet)
    if value is None:
        # The building describes itself, but not in the way this question asked.
        known = ", ".join(profile.facts.keys())
        return (
            f"**{building_name}** doesn't state that in its model. It does record: "
            f"{known}. Adding the missing fact to the building's TTL — or via the admin "
            "console — makes this question answerable with no code change."
        )

    label = next((lbl for f, _i, lbl in _FACTS if f == facet), facet.title())
    if facet == "size":
        value = _format_area(value)
    if facet == "age":
        answer = f"**{building_name}** was built in **{value}**."
        try:
            from datetime import datetime

            age = datetime.now().year - int(value)
            if 0 < age < 500:
                answer += f" That makes it about **{age} years old**."
        except (TypeError, ValueError):
            pass
        return answer
    return f"**{label}** for **{building_name}**: {value}"


def enablement_hint(building_name: str) -> str:
    """What to add so the building can describe itself — the same
    connect-data → get-answers contract the sensor path states."""
    return (
        f"**{building_name}** doesn't yet describe itself in its model, so I can't answer "
        "that from data rather than guesswork.\n\n"
        "You can add it — no code changes needed. On the building's own node in its TTL "
        "(the one typed `brick:Building`), assert what you know:\n"
        "- `brick:yearBuilt`, `brick:grossArea`, `brick:buildingPrimaryFunction` — Brick's own terms\n"
        "- `ontosage:buildingOwner`, `buildingOperator`, `buildingArchitect`, `buildingAddress`, "
        "`buildingPurpose`, `buildingOccupancyType`, `buildingAccessPolicy`\n\n"
        "Each one you add answers its question immediately."
    )
