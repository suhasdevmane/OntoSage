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
from typing import Awaitable, Callable, Dict, List, Optional

from shared.utils import describe_exception, get_logger

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
#:
#: 12 became too few on 2026-09-19 (BUG-827): a building with more than twelve amenities of ONE
#: kind -- bldg1 has fifteen toilets -- ties them all on score, the cut kept the first twelve in
#: graph order, and a question naming a floor could lose the very rooms on that floor before the
#: caller's floor answer ever saw them. Forty leaves room for the largest kind the buildings
#: measured so far (13 drinking-water points, 15 toilets) with a margin, and the caller still
#: presents three.
_MAX_FACTS = 40


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
    #: The service state the building records for this amenity; "" when it records none.
    service_status: str = ""

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


#: The lay terms an amenity INHERITS from its kind, declared once on the class in the OCBV
#: TBox ("multi-faith room" on ontosage:PrayerRoom) rather than on every building's instances.
#:
#: Nothing read them before 2026-09-17. The query below this one asked only for
#: `?a ontosage:layTerms`, so a synonym declared on a class did nothing, and a building was
#: reachable only by the words its own TTL happened to repeat on each instance: bldg1's
#: amenities carried their vocabulary, and a building typed `a ontosage:PrayerRoom` with no
#: instance terms could not be asked about its prayer room at all.
#:
#: Restricted to Capability subclasses so a class from another module (a record register, a
#: sensor class) can never lend its vocabulary to an amenity that happens to share a type.
_KIND_TERMS_QUERY = (
    f"{_ONTO}{_RDFS}"
    'SELECT ?a (GROUP_CONCAT(DISTINCT ?klay; separator="|") AS ?klays) WHERE { '
    "{ ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } "
    "?a a ?kind . ?kind rdfs:subClassOf+ ontosage:Capability ; ontosage:layTerms ?klay . "
    "} GROUP BY ?a"
)


def _phrases(value: str) -> List[str]:
    """Lay-term text as lower-cased phrases: instance literals use ',', class terms '|'."""
    return [p.strip().lower() for p in re.split(r"[,|]", value or "") if p.strip()]


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


def _to_fact(am: "_Amenity") -> CapabilityFact:
    """The caller-facing fact for an amenity; one place, so a withheld fact and a kept one agree."""
    return CapabilityFact(
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
        service_status=am.service_status,
    )


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

    async def resolve(
        self, query: str, withheld_out: Optional[List[CapabilityFact]] = None
    ) -> List[CapabilityFact]:
        """Return structured amenity facts matching ``query`` (empty if no strong match).

        ``withheld_out``, when given, receives the matching amenities that were left out for being
        out of service, so a caller can SAY so (BUG-827) instead of leaving the reader to infer a
        gap from what is missing.
        """
        q = (query or "").lower()
        if not q.strip():
            return []
        try:
            amenities = await self._amenities()
        except Exception as e:  # GraphDB down / malformed — fall through to the KB.
            logger.warning(
                f"[capability_graph] amenity fetch failed, deferring to KB: "
                f"{describe_exception(e)}"
            )
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
                if withheld_out is not None:
                    withheld_out.append(_to_fact(am))
                continue
            scored.append((score, am))
        scored.sort(key=lambda x: -x[0])
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
        facts: List[CapabilityFact] = []
        for _, am in scored[:_MAX_FACTS]:
            fact = _to_fact(am)
            # A safety-critical amenity that is out of service is REPORTED, never hidden:
            # its note carries the state so the answer says "this one is out of service"
            # rather than pretending it works or pretending it is not there. Set on the fact,
            # not the cached amenity: mutating the cache stacked one more flag onto the note on
            # every call for the next five minutes.
            if _is_out_of_service(am.service_status):
                flag = "**Currently out of service.**"
                fact.note = f"{flag} {am.note}".strip() if am.note else flag
            facts.append(fact)
        return facts

    async def resolve_with_withheld(
        self, query: str
    ) -> "tuple[List[CapabilityFact], List[CapabilityFact]]":
        """`resolve`, plus the matches left out for being out of service (BUG-827)."""
        withheld: List[CapabilityFact] = []
        return await self.resolve(query, withheld), withheld

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
            "OPTIONAL { ?a ontosage:potabilityIssuedOn ?potdate } "
            "}"
        )
        # Kind vocabulary first, in its own query: a failure here must cost only the inherited
        # terms, never the amenities themselves.
        kind_terms: dict = {}
        try:
            for kb in _bindings(await self._exec(_KIND_TERMS_QUERY)):
                iri = kb.get("a", {}).get("value", "")
                klays = kb.get("klays", {}).get("value", "")
                if iri and klays:
                    kind_terms[iri] = _phrases(klays)
        except Exception as e:  # an older GraphDB, a malformed class term: keep instance terms
            logger.debug(f"[capability_graph] kind lay terms unavailable: {describe_exception(e)}")
        data = await self._exec(q)
        out: List[_Amenity] = []
        by_iri: Dict[str, _Amenity] = {}
        for b in _bindings(data):
            lay = b.get("lay", {}).get("value", "")

            def _v(key: str) -> str:
                return b.get(key, {}).get("value", "").strip()

            own = _phrases(lay)
            inherited = [p for p in kind_terms.get(_v("a"), []) if p not in own]
            seen = by_iri.get(_v("a")) if _v("a") else None
            if seen is not None:
                # The same amenity again: a second status row, or a second lay-term literal. One
                # amenity is one answer -- "Where are the lifts?" printed the first lift twice.
                seen.lay_phrases += [p for p in own + inherited if p not in seen.lay_phrases]
                seen.service_status = seen.service_status or _v("svc")
                continue
            out.append(
                _Amenity(
                    label=_v("label"),
                    location=_v("loc"),
                    note=_v("note"),
                    category=_v("cat"),
                    lay_phrases=own + inherited,
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
            if _v("a"):
                by_iri[_v("a")] = out[-1]
        self._cache = out
        self._cache_ts = time.monotonic()
        return out


#: Words that locate or frame a question about an amenity without changing what it is about.
_FRAME_WORDS = frozenset(
    "a an the is are was be there any some this that these those in on at of for to from by with "
    "near nearest closest nearby where what which who how when do does did can could would will "
    "i me my we our you your it its please get find go use using have has having got available "
    "open located location building floor level ground first second third fourth fifth here "
    "somewhere anywhere inside outside around one ones "
    # cost framing: "is it free", "do I have to pay / buy" asks about the amenity itself
    "free paid pay buy cost costs charge need must".split()
)


def leftover_content_words(query_lc: str, lay_phrases: List[str]) -> List[str]:
    """Content words of a question NOT covered by an amenity's lay phrases (BUG-601).

    "Where are the toilets?" leaves nothing: the amenity IS the question. "Where can I isolate
    the water supply for the second-floor toilets?" leaves isolate/water/supply — a plumbing
    question that merely names toilets, and a toilet-location topic answered it with a list of
    toilets. Used to decide whether a topic may ANSWER, never whether it is retrieved.
    """
    phrases = [p.lower() for p in lay_phrases if p and len(p) >= 3]
    text = query_lc
    for phrase in sorted(phrases, key=len, reverse=True):
        text = re.sub(rf"(?<![a-z0-9]){re.escape(phrase)}(?:s|es)?(?![a-z0-9])", " ", text)
    # A word inside the topic's OWN vocabulary is covered by it, even where the declared phrase
    # is longer: a drinking-water point declares "bottle filling", and "bottles" in the question
    # is that same thing, not a second subject.
    declared = {w for p in phrases for w in re.findall(r"[a-z]+", p) if len(w) > 2}
    words = re.findall(r"[a-z]+", text)
    return [
        w
        for w in words
        if len(w) > 2
        and w not in _FRAME_WORDS
        and w not in declared
        and w.rstrip("s") not in declared
        and not any(w.startswith(d) or d.startswith(w) for d in declared if len(d) > 4)
    ]


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
    # NOT plural-tolerant, and measured: a plural tail ("shower" also matching "showers") moved 1
    # of 2,960 corpus questions and broke THREE guard questions — "Are the lifts working?" (the
    # asset-state lane owns lift status; the amenity lane must not claim it) and the demo question
    # "Which hazard controls are overdue for test?" twice. A lay term is a corpus-wide change
    # (lessons.md #38). A missing plural is fixed where it is missing: on the topic's own terms.


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
