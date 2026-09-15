"""
capability_schema.py — the live Building Capability Schema + admission gate (V4-T16).

Before ANY data is fetched, a compiled CQ-IR is validated against what the active
building actually is: which spaces exist, which modalities each space has backed
sensors for, which amenity kinds have located instances, which floors exist.
The verdict is one of:

  ADMIT    — every hard requirement is satisfiable; execution may proceed
             (partial soft coverage is allowed and lands in the coverage ledger).
  CLARIFY  — an anchor is ambiguous/unknown but real alternatives exist; carries
             ONE targeted question with concrete options.
  DECLINE  — a required modality has zero backed sensors anywhere (or the IR
             itself was not executable); carries the honest explanation inputs.

Asymmetric failure (the fabrication-gate rule): if the schema cannot be built,
the caller must decline — never assume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from orchestrator.services.deliberation.coverage_audit import (
    STATUS_PRESENT,
    CoverageAuditor,
    ModalitySpec,
    SpaceCoverage,
    SparqlExec,
    _local,
)
from orchestrator.services.deliberation.cqir import CQIR, SpatialRelation
from shared.utils import get_logger

logger = get_logger(__name__)

ADMIT = "admit"
CLARIFY = "clarify"
DECLINE = "decline"


#: WB-11: anchors that scope a question to the WHOLE building rather than naming a space.
#: Generic English only — no building's name.
_WHOLE_BUILDING_ANCHORS = frozenset(
    {"", "none", "null", "n/a", "room", "rooms", "space", "spaces", "building", "the building",
     "whole building", "entire building", "anywhere", "everywhere", "all", "all rooms",
     "any room", "place", "places", "area", "areas", "workspace", "workspaces"}
)


@dataclass
class AmenityInstance:
    iri: str
    kind: str  # e.g. DrinkingWater
    space_iri: str
    floor: str
    label: str = ""


@dataclass
class BuildingCapabilitySchema:
    """What the building can answer with, resolved live from its own graph."""

    building_id: str
    namespace: str
    spaces: List[SpaceCoverage]
    amenities: List[AmenityInstance]

    @property
    def floors(self) -> List[str]:
        return sorted({s.floor for s in self.spaces if s.floor})

    @property
    def amenity_kinds(self) -> List[str]:
        return sorted({a.kind for a in self.amenities})

    def coverage_for(self, modality: str) -> Dict[str, int]:
        present = sum(
            1 for s in self.spaces if s.modalities.get(modality, {}).get("status") == STATUS_PRESENT
        )
        return {"present": present, "total": len(self.spaces)}


@dataclass
class ClarifyQuestion:
    slot: str  # 'floor' | 'amenity' | 'space' | 'signals'
    question: str
    options: List[str] = field(default_factory=list)


@dataclass
class AdmissionResult:
    verdict: str  # ADMIT | CLARIFY | DECLINE
    reason: str = ""
    question: Optional[ClarifyQuestion] = None
    missing_modalities: List[str] = field(default_factory=list)
    # normalized anchors execution can trust
    floor_anchor: Optional[str] = None  # floor local name (e.g. 'floor1')
    amenity_anchor: Optional[str] = None  # amenity kind (e.g. 'DrinkingWater')
    space_anchor: Optional[str] = None  # space IRI
    coverage: Dict[str, Dict[str, int]] = field(default_factory=dict)


_AMENITY_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ontosage: <http://ontosage.org/capabilities#>
SELECT ?a ?kind ?space ?label WHERE {
    ?a a ontosage:Amenity ; a ?kind ; ontosage:locatedIn ?space .
    OPTIONAL { ?a rdfs:label ?label }
    FILTER(?kind != ontosage:Amenity && ?kind != ontosage:Capability)
    FILTER(STRSTARTS(STR(?kind), "http://ontosage.org/capabilities#"))
} LIMIT 500
"""


async def build_schema(
    building_id: str,
    namespace: str,
    sparql_exec: SparqlExec,
    modalities: List[ModalitySpec],
) -> BuildingCapabilitySchema:
    """Resolve the live schema (spaces × modalities + located amenities)."""
    # BUG-255: when a room holds two sensors of the same modality, the auditor must pick the
    # one that is actually reporting. Cached for 5 minutes and never fatal -- None means "no
    # freshness signal" and restores the historical first-match behaviour exactly.
    try:
        from orchestrator.services.building_metrics import fresh_uuids as _fresh_uuids

        fresh = await _fresh_uuids()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"[capability_schema] freshness unavailable: {exc}")
        fresh = None

    auditor = CoverageAuditor(sparql_exec, modalities, fresh_uuids=fresh)
    spaces = await auditor.audit(namespace)
    space_floor = {s.space_iri: s.floor for s in spaces}

    amenities: List[AmenityInstance] = []
    result = await sparql_exec(_AMENITY_QUERY)
    for b in (result.get("results", {}) or {}).get("bindings", []):
        space_iri = b.get("space", {}).get("value", "")
        amenities.append(
            AmenityInstance(
                iri=b.get("a", {}).get("value", ""),
                kind=_local(b.get("kind", {}).get("value", "")),
                space_iri=space_iri,
                floor=space_floor.get(space_iri, ""),
                label=b.get("label", {}).get("value", ""),
            )
        )
    logger.info(
        f"[capability_schema] {building_id}: {len(spaces)} spaces, "
        f"{len(amenities)} located amenities ({', '.join(sorted({a.kind for a in amenities}))})"
    )
    return BuildingCapabilitySchema(
        building_id=building_id, namespace=namespace, spaces=spaces, amenities=amenities
    )


#: How people and models write a storey. Matched against the BUILDING'S OWN floor list, so
#: nothing here assumes what a floor is called -- only how the same floor might be spelled.
_FLOOR_WORDS = ("floor", "level", "storey", "story", "fl", "lvl", "l")

#: Ordinals a model reaches for when the question says a digit.
_ORDINALS = {
    "ground": "0",
    "zeroth": "0",
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "fifth": "5",
    "sixth": "6",
    "seventh": "7",
    "eighth": "8",
    "ninth": "9",
    "tenth": "10",
}


def _floor_digits(token: str) -> Optional[str]:
    """The storey number inside a spelling of it, or None.

    A HYPHEN AFTER A LETTER IS A SEPARATOR, NOT A MINUS SIGN. `Niveau-3` is the third
    floor, not the third basement, and reading the hyphen as a sign made it -3 -- so a
    building naming floors that way matched nothing. The two readings are genuinely
    ambiguous in isolation (`Floor-1` could be either), and this resolves it the way that
    keeps BOTH SIDES consistent: a name like `Floor-1` still matches itself through the
    exact-match branch above, which runs first.
    """
    import re as _re

    for word, digit in _ORDINALS.items():
        if word in token:
            return digit
    cleaned = _re.sub(r"(?<=[a-z])-", "", token)
    m = _re.search(r"(-?\d+)", cleaned)
    return m.group(1) if m else None


#: What a model writes when it means "I did not fill this in".
#:
#: Measured live: the CQ-IR compile emitted an ON_FLOOR qualifier whose anchor was the
#: literal string "None" for the question "Which space on Floor 3 has the best conditions
#: for focused work this afternoon?". The admission gate dutifully reported "unknown floor
#: 'None'" and asked the reader which floor they meant, offering Floor3 among the options.
_NULLISH = {"", "none", "null", "nil", "n/a", "na", "unknown", "unspecified", "any"}


def floor_from_text(text: str, floors: List[str]) -> Optional[str]:
    """The floor a QUESTION names, matched against this building's own floor list.

    The compiler is one source and the question is the authoritative one. When the
    compiled anchor is missing or null-ish, reading the floor back out of the raw query is
    deterministic, costs nothing, and cannot invent a floor the building does not have --
    every candidate is checked against `floors`.
    """
    import re as _re

    low = (text or "").lower()
    for f in floors:
        digits = _floor_digits(f.lower())
        if digits is None:
            continue
        # "floor 3", "level 3", "3rd floor", "storey 3" -- the word next to the number is
        # what makes it a floor reference rather than a room number or a quantity.
        pattern = (
            r"\b(?:" + "|".join(_FLOOR_WORDS) + r")\s*-?\s*" + _re.escape(digits) + r"\b"
            r"|\b" + _re.escape(digits) + r"(?:st|nd|rd|th)?\s+(?:" + "|".join(_FLOOR_WORDS) + r")\b"
        )
        if _re.search(pattern, low):
            return f
    return None


def _norm_floor(anchor: str, floors: List[str]) -> Optional[str]:
    """Any spelling of a storey -> the matching floor local name, or None.

    WHY THIS IS MORE THAN A STRIP-AND-COMPARE
    -----------------------------------------
    It matched 'Floor 3', '3', 'floor3' and nothing else, and the anchor it is given comes
    from an LLM compile -- so the spelling varies between runs of the SAME question. The
    regression probe caught the consequence: "Which space on Floor 3 has the best
    conditions for focused work this afternoon?" -- a question that names its floor, and
    which this lane had ranked correctly in an earlier session -- came back as "Which floor
    did you mean? I know: Floor0, Floor1, ... Floor3", offering the reader the floor they
    had just named.

    An unstable input is not a reason to ask the user; it is a reason to normalise harder.
    'Level 3', '3rd floor', 'third floor', 'L3' and 'FL-3' now all resolve, by reducing
    both sides to a STOREY NUMBER and comparing that -- so nothing here assumes what this
    building calls a floor, only how the same floor might be written.
    """
    token = anchor.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for f in floors:
        f_norm = f.lower().replace(" ", "").replace("_", "").replace("-", "")
        if token == f_norm or token == f_norm.replace("floor", "") or f"floor{token}" == f_norm:
            return f

    # Fall back to comparing STOREY NUMBERS, which survives any spelling either side uses.
    want = _floor_digits(token)
    if want is None:
        return None
    for f in floors:
        have = _floor_digits(f.lower())
        if have is not None and have == want:
            return f
    return None


def validate(cqir: CQIR, schema: BuildingCapabilitySchema) -> AdmissionResult:
    """Admission gate: ADMIT / CLARIFY(one question) / DECLINE — before any data fetch."""
    # 0. compiler-level ambiguity: surface as ONE clarify question (policy owns wording)
    if not cqir.is_executable():
        phrases = [s.phrase for s in cqir.signals][:3]
        return AdmissionResult(
            verdict=CLARIFY,
            reason="query has unresolved parts",
            question=ClarifyQuestion(
                slot="signals",
                question=(
                    "I couldn't map part of your request"
                    + (f" ({'; '.join(p for p in phrases if p)})" if phrases else "")
                    + " — could you rephrase or drop that part?"
                ),
            ),
        )

    # 1. every constrained modality must have at least one BACKED sensor somewhere
    missing = []
    coverage: Dict[str, Dict[str, int]] = {}
    for c in cqir.constraints:
        cov = schema.coverage_for(c.modality)
        coverage[c.modality] = cov
        if cov["present"] == 0:
            missing.append(c.modality)
    if missing:
        return AdmissionResult(
            verdict=DECLINE,
            reason=f"no backed sensors anywhere for: {', '.join(missing)}",
            missing_modalities=missing,
            coverage=coverage,
        )

    # 2. spatial anchors must resolve against the building's own inventory
    floor_anchor = amenity_anchor = space_anchor = None
    for q in cqir.spatial:
        if q.relation == SpatialRelation.ON_FLOOR:
            floor_anchor = _norm_floor(q.anchor, schema.floors)
            if floor_anchor is None and str(q.anchor or "").strip().lower() in _NULLISH:
                # THE COMPILER LEFT IT BLANK; THE QUESTION DID NOT.
                #
                # An LLM compile that emits `anchor: "None"` alongside an ON_FLOOR
                # qualifier has told us a floor was mentioned and failed to say which.
                # Asking the reader is the wrong recovery when the reader already said:
                # the live failure offered "Floor0 ... Floor3 ..." to someone who had
                # written "Floor 3".
                floor_anchor = floor_from_text(cqir.raw_query, schema.floors)
            if floor_anchor is None:
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown floor '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="floor",
                        question=f"Which floor did you mean? I know: {', '.join(schema.floors)}",
                        options=schema.floors,
                    ),
                    coverage=coverage,
                )
        elif q.relation == SpatialRelation.NEAR_AMENITY:
            kinds = {k.lower(): k for k in schema.amenity_kinds}
            amenity_anchor = kinds.get(q.anchor.strip().lower().replace(" ", ""))
            if amenity_anchor is None:
                if not schema.amenity_kinds:
                    return AdmissionResult(
                        verdict=DECLINE,
                        reason="no located amenities are modelled for this building",
                        coverage=coverage,
                    )
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown amenity '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="amenity",
                        question=(
                            f"I don't know '{q.anchor}' here — nearest what? "
                            f"I have located: {', '.join(schema.amenity_kinds)}"
                        ),
                        options=schema.amenity_kinds,
                    ),
                    coverage=coverage,
                )
        elif q.relation in (SpatialRelation.IN_SPACE, SpatialRelation.ADJACENT_TO) and (
            (q.anchor or "").strip().lower() not in _WHOLE_BUILDING_ANCHORS
        ):
            # WB-11: "in the building" is the whole building, not a space to find. The compiler
            # emitted anchor 'None' and anchor 'Room' for "coolest place to work in the building"
            # and "which room in the building has the best air", and admission asked the user
            # which room they meant.
            token = q.anchor.strip().lower()
            matches = [
                s.space_iri
                for s in schema.spaces
                if token in s.space_iri.lower() or token in (s.label or "").lower()
            ]
            if len(matches) == 1:
                space_anchor = matches[0]
            elif not matches:
                sample = [(_local(s.space_iri)) for s in schema.spaces[:5]]
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"unknown space '{q.anchor}'",
                    question=ClarifyQuestion(
                        slot="space",
                        question=f"I can't find '{q.anchor}'. Did you mean one of: {', '.join(sample)}?",
                        options=sample,
                    ),
                    coverage=coverage,
                )
            else:
                opts = [_local(m) for m in matches[:5]]
                return AdmissionResult(
                    verdict=CLARIFY,
                    reason=f"'{q.anchor}' matches {len(matches)} spaces",
                    question=ClarifyQuestion(
                        slot="space",
                        question=f"'{q.anchor}' matches several spaces — which one? {', '.join(opts)}",
                        options=opts,
                    ),
                    coverage=coverage,
                )

    return AdmissionResult(
        verdict=ADMIT,
        floor_anchor=floor_anchor,
        amenity_anchor=amenity_anchor,
        space_anchor=space_anchor,
        coverage=coverage,
    )
