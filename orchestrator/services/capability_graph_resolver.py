"""Answer structured capability questions from ontology triples, not frozen KB prose.

Structured amenities (prayer room, café, lift, …) live as triples typed ``ontosage:Amenity``
(see ontology/ontosage_capabilities.ttl + input/<bldg>_capabilities.ttl). This resolver
fetches them via SPARQL and matches a user's question against each amenity's lay-term
phrases. It only returns a match when the signal is strong (a multi-word phrase or a
distinctive term), so anything it isn't sure about falls through to the existing capability
KB / document search unchanged.

Portability: queries by the building-agnostic ``ontosage:Amenity`` type — only the active
building's amenity triples are loaded, so no namespace literals are needed. The SPARQL
executor is injectable, so this is unit-testable offline (ROADMAP-009).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

SparqlExec = Callable[[str], Awaitable[dict]]

_ONTO = "PREFIX ontosage: <http://ontosage.org/capabilities#>\n"
_RDFS = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
_CACHE_TTL_S = 300.0
_MIN_SCORE = 2  # a single distinctive term (2) or a multi-word phrase (3) clears this

#: How many matching facts to hand back. NOT the presentation size -- the CALLER
#: filters these on-topic and ranks them, and cutting to the presentation size here
#: discards the candidates that would have survived that filter.
#:
#: This was 3, and it produced a wrong answer measured live (BUG-337). Every one of
#: the building's thirteen drinking-water amenities scores exactly 2 for "where can
#: I fill my water bottle?", so the cut kept an arbitrary three -- all of them
#: labelled "Drinking water point", none labelled "Bottle refill point". The
#: caller's on-topic guard then correctly rejected all three for not mentioning a
#: bottle, and the building answered that it had no information about a thing it
#: has twelve of. Truncating before filtering is the defect; the tie was only what
#: exposed it.
_MAX_FACTS = 12


@dataclass
class CapabilityFact:
    label: str
    location: str = ""
    note: str = ""
    category: str = ""
    # Knowledge-topic fields (empty for physical amenities).
    answer: str = ""
    url: str = ""
    email: str = ""
    phone: str = ""
    report_to: str = ""
    steps: str = ""
    # File name of the document that sets this topic out in full, as declared by
    # the building via ontosage:documentRef. Carried so the caller can scope
    # retrieval to THAT document instead of searching the whole corpus by score.
    document_ref: str = ""
    effective_date: str = ""
    owner: str = ""
    # Module P — a published potability statement. Never derived from a reading:
    # the schema is explicit that a sensor value does not support a health claim,
    # and being wrong about drinkability harms someone.
    potability: str = ""
    potability_authority: str = ""
    potability_issued_on: str = ""
    #: The floor an amenity sits on, as the building declares it (ontosage:onFloor).
    #: Read so a question naming a floor can be answered with THAT floor's amenity:
    #: "where can I fill my bottle on floor 3?" listed floors 0, 1 and 2 (BUG-337).
    on_floor: str = ""
    #: The lay phrasings the BUILDING declared for this amenity. Carried so the
    #: caller's on-topic guard can see them: a building that declares "fill my
    #: bottle" has said this amenity answers that question, and rejecting it for
    #: not repeating the word in its prose overrules the building about its own
    #: vocabulary (measured on bldg2, which declined a question it had four
    #: amenities for). NOT rendered into the answer -- it is matching surface,
    #: not prose.
    lay_terms: str = ""

    def render(self) -> str:
        head = f"**{self.label}**"
        if self.location:
            head += f" — {self.location}"
        # Physical amenity: location + note (unchanged output).
        if not (
            self.answer
            or self.report_to
            or self.url
            or self.email
            or self.phone
            or self.steps
            or self.potability
        ):
            return f"{head}.{(' ' + self.note) if self.note else ''}"
        # Knowledge topic: canonical answer + contacts/report route + steps.
        body: List[str] = []
        if self.answer:
            body.append(self.answer)
        elif self.note:
            body.append(self.note)
        if self.potability:
            body.append(self._potability_sentence())
        contact = []
        if self.report_to:
            contact.append(f"Report to: {self.report_to}")
        if self.email:
            contact.append(f"Email: {self.email}")
        if self.phone:
            contact.append(f"Phone: {self.phone}")
        if self.url:
            contact.append(f"More info: {self.url}")
        if contact:
            body.append(" · ".join(contact))
        if self.steps:
            step_list = [s.strip() for s in self.steps.split(";") if s.strip()]
            if step_list:
                body.append(
                    "Steps: " + " ".join(f"({i + 1}) {s}." for i, s in enumerate(step_list))
                )
        # Naming the governing document and its date lets the reader see WHICH
        # version this answer is quoting, and where to go for the full text.
        provenance = []
        if self.owner:
            provenance.append(f"Owner: {self.owner}")
        if self.effective_date:
            provenance.append(f"In force since {self.effective_date}")
        if provenance:
            body.append(" · ".join(provenance))
        return f"{head}. " + " ".join(body)

    def _potability_sentence(self) -> str:
        """The drinkability claim, with the owner who stands behind it.

        The schema requires an authority because a drinkability claim with no owner
        is exactly the confident unattributable assertion the evidence discipline
        exists to prevent, and requires a date because a statement issued years ago
        describes a plumbing system that may since have been altered. Surfacing the
        value WITHOUT them would reproduce the defect the module was written to stop
        — so an unattributed statement is reported as unverified rather than as a
        fact, and 'unknown' is stated plainly instead of being dressed up.
        """
        value = (self.potability or "").strip().lower()
        if value in ("unknown", ""):
            return (
                "Drinkability: no statement has been published for this outlet. "
                "That is not the same as unsafe — nobody has assessed it."
            )
        reading = "safe to drink" if value == "potable" else "NOT for drinking"
        if not self.potability_authority:
            return (
                f"Drinkability: recorded as {reading}, but the statement names no "
                f"issuing authority — treat it as unverified."
            )
        when = f" on {self.potability_issued_on}" if self.potability_issued_on else ""
        stale = "" if self.potability_issued_on else " (no issue date recorded)"
        return f"Drinkability: {reading} — published by {self.potability_authority}{when}.{stale}"


@dataclass
class _Amenity:
    label: str
    location: str
    note: str
    category: str
    lay_phrases: List[str]
    answer: str = ""
    url: str = ""
    email: str = ""
    phone: str = ""
    report_to: str = ""
    steps: str = ""
    document_ref: str = ""
    effective_date: str = ""
    owner: str = ""
    #: Current service state, from ontosage:amenityStatus -> AssetStatus. An amenity
    #: that is out of service must be EXCLUDED from an answer, not listed with a
    #: caveat: somebody who walks to a broken drinking fountain has been given a wrong
    #: answer, however well hedged (schema Module P, V6-T45).
    service_status: str = ""
    potability: str = ""
    potability_authority: str = ""
    potability_issued_on: str = ""
    on_floor: str = ""


#: Status values that mean an amenity cannot be used right now. Anything else --
#: including an empty string -- is treated as usable, because most buildings publish no
#: status at all and defaulting to "broken" would empty every answer.
_OUT_OF_SERVICE = frozenset({"out_of_service", "out of service", "broken", "closed", "fault"})


#: Categories where SILENCE is more dangerous than a broken entry. Excluding a
#: defibrillator because it is out of service tells somebody asking in an emergency
#: that the building has none — and the exclusion rule was written for a drinking
#: fountain, where walking to a broken one merely wastes a trip. For these, the answer
#: names the amenity AND its state, so the reader can decide.
_NEVER_SILENTLY_EXCLUDE = frozenset({"emergency", "safety", "accessibility", "security"})


def _is_safety_critical(category: str) -> bool:
    return (category or "").strip().lower() in _NEVER_SILENTLY_EXCLUDE


def _is_out_of_service(value: str) -> bool:
    return (value or "").strip().lower().replace("-", "_") in _OUT_OF_SERVICE


class CapabilityGraphResolver:
    """Match a question to structured amenity triples in the ontology."""

    def __init__(self, sparql_exec: Optional[SparqlExec] = None):
        self._exec = sparql_exec or _default_sparql_exec
        self._cache: Optional[List[_Amenity]] = None
        self._cache_ts: float = 0.0

    async def resolve(self, query: str) -> List[CapabilityFact]:
        """Return structured amenity facts matching ``query`` (empty if no strong match)."""
        q = (query or "").lower()
        if not q.strip():
            return []
        try:
            amenities = await self._amenities()
        except Exception as e:  # GraphDB down / malformed — fall through to the KB.
            logger.warning(f"[capability_graph] amenity fetch failed, deferring to KB: {e}")
            return []

        scored: List[tuple] = []
        withheld: List[str] = []
        for am in amenities:
            score = _score(q, am.lay_phrases)
            if score < _MIN_SCORE:
                continue
            if _is_out_of_service(am.service_status) and not _is_safety_critical(am.category):
                # EXCLUDED, not caveated. The schema is explicit about why: somebody who
                # walks to a broken drinking fountain has been given a wrong answer,
                # however well hedged. Nothing read amenityStatus until 2026-08-26, so an
                # out-of-service amenity was offered exactly as if it worked.
                withheld.append(am.label or "an amenity")
                continue
            scored.append((score, am))
        scored.sort(key=lambda x: -x[0])
        # A safety-critical amenity that is out of service is REPORTED, never hidden:
        # its note carries the state so the answer says "this one is out of service"
        # rather than pretending it works or pretending it is not there.
        for _s, am in scored:
            if _is_out_of_service(am.service_status):
                flag = "**Currently out of service.**"
                am.note = f"{flag} {am.note}".strip() if am.note else flag
        if withheld and not scored:
            # Everything that matched is out of service. "No drinking fountains here" is
            # a different and worse answer than "the ones here are not working" — the
            # first sends someone away, the second tells them what is wrong.
            return [
                CapabilityFact(
                    label="Currently out of service",
                    location="",
                    note="",
                    category="",
                    answer=(
                        f"This building does have {'that' if len(withheld) == 1 else 'those'}, "
                        f"but {'it is' if len(withheld) == 1 else 'they are'} currently out of "
                        f"service: {', '.join(sorted(set(withheld))[:4])}."
                    ),
                )
            ]
        return [
            CapabilityFact(
                label=am.label,
                location=am.location,
                note=am.note,
                category=am.category,
                answer=am.answer,
                url=am.url,
                email=am.email,
                phone=am.phone,
                report_to=am.report_to,
                steps=am.steps,
                document_ref=am.document_ref,
                effective_date=am.effective_date,
                owner=am.owner,
                potability=am.potability,
                potability_authority=am.potability_authority,
                potability_issued_on=am.potability_issued_on,
                on_floor=am.on_floor,
                lay_terms=", ".join(am.lay_phrases),
            )
            for _, am in scored[:_MAX_FACTS]
        ]

    async def _amenities(self) -> List[_Amenity]:
        if self._cache is not None and (time.monotonic() - self._cache_ts) < _CACHE_TTL_S:
            return self._cache
        # Physical amenities AND knowledge topics (procedures / info / maintenance issues)
        # in one pass — both are lay-term-matched and rendered by CapabilityFact.
        q = (
            f"{_ONTO}{_RDFS}"
            "SELECT ?a ?label ?loc ?note ?cat ?lay ?answer ?url ?email ?phone ?report ?steps "
            "?docref ?effective ?owner ?svc ?pot ?potauth ?potdate ?floor WHERE { "
            "{ ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } "
            "OPTIONAL { ?a rdfs:label ?label } "
            "OPTIONAL { ?a ontosage:locationText ?loc } "
            "OPTIONAL { ?a ontosage:onFloor ?floor } "
            "OPTIONAL { ?a ontosage:note ?note } "
            "OPTIONAL { ?a ontosage:capabilityCategory ?cat } "
            "OPTIONAL { ?a ontosage:layTerms ?lay } "
            "OPTIONAL { ?a ontosage:answerText ?answer } "
            "OPTIONAL { ?a ontosage:infoUrl ?url } "
            "OPTIONAL { ?a ontosage:contactEmail ?email } "
            "OPTIONAL { ?a ontosage:contactPhone ?phone } "
            "OPTIONAL { ?a ontosage:reportTo ?report } "
            "OPTIONAL { ?a ontosage:steps ?steps } "
            "OPTIONAL { ?a ontosage:documentRef ?docref } "
            "OPTIONAL { ?a ontosage:effectiveDate ?effective } "
            "OPTIONAL { ?a ontosage:policyOwner ?owner } "
            # Module P. Nothing read this until 2026-08-26, so an out-of-service
            # amenity was offered as though it worked -- the wrong-answer case the
            # vocabulary exists to prevent.
            "OPTIONAL { { ?a ontosage:amenityStatus ?st } UNION { ?st ontosage:statusOf ?a } "
            "?st ontosage:statusValue ?svc } "
            # Module P, the other half. A PotabilityStatement is a KnowledgeTopic
            # subclass so the resolver already FINDS it -- but it surfaced the
            # answerText alone, without the authority and date the schema requires,
            # which is the unattributable health claim the module exists to prevent.
            "OPTIONAL { ?a ontosage:potabilityValue ?pot } "
            "OPTIONAL { ?a ontosage:potabilityAuthority ?potauth } "
            "OPTIONAL { ?a ontosage:potabilityIssuedOn ?potdate } }"
        )
        data = await self._exec(q)
        out: List[_Amenity] = []
        for b in _bindings(data):
            lay = b.get("lay", {}).get("value", "")

            def _v(key: str) -> str:
                return b.get(key, {}).get("value", "").strip()

            out.append(
                _Amenity(
                    label=_v("label"),
                    location=_v("loc"),
                    note=_v("note"),
                    category=_v("cat"),
                    lay_phrases=[p.strip().lower() for p in lay.split(",") if p.strip()],
                    answer=_v("answer"),
                    url=_v("url"),
                    email=_v("email"),
                    phone=_v("phone"),
                    report_to=_v("report"),
                    steps=_v("steps"),
                    document_ref=_v("docref"),
                    effective_date=_v("effective")[:10],
                    owner=_v("owner"),
                    service_status=_v("svc"),
                    potability=_v("pot"),
                    potability_authority=_v("potauth"),
                    potability_issued_on=_v("potdate")[:10],
                    on_floor=_v("floor"),
                )
            )
        self._cache = out
        self._cache_ts = time.monotonic()
        return out


def _score(query_lc: str, lay_phrases: List[str]) -> int:
    """Score a query against an amenity's lay-term phrases.

    Multi-word phrase appearing in the query = strong (+3). A distinctive single word
    matched on a whole-word boundary = +2 (whole-word avoids 'desk' matching 'desktop').
    """
    score = 0
    for phrase in lay_phrases:
        if not phrase or len(phrase) < 3:
            continue
        if " " in phrase:
            if phrase in query_lc:
                score += 3
        elif re.search(rf"\b{re.escape(phrase)}\b", query_lc):
            score += 2
    return score


async def _default_sparql_exec(sparql: str) -> dict:
    """Query the active GraphDB repository over the Docker network (async httpx)."""
    import httpx

    from shared.config import settings

    endpoint = (
        f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
        f"/repositories/{settings.GRAPHDB_REPOSITORY}"
    )
    auth = (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            endpoint,
            auth=auth,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        return r.json()


def _bindings(data: dict) -> list:
    if not isinstance(data, dict):
        return []
    res = data.get("results", {})
    if isinstance(res, dict):
        b = res.get("bindings", [])
        return b if isinstance(b, list) else []
    return []


_instance: Optional[CapabilityGraphResolver] = None


def get_capability_graph_resolver() -> CapabilityGraphResolver:
    global _instance
    if _instance is None:
        _instance = CapabilityGraphResolver()
    return _instance
