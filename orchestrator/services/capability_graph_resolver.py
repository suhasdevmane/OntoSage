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

    def render(self) -> str:
        head = f"**{self.label}**"
        if self.location:
            head += f" — {self.location}"
        # Physical amenity: location + note (unchanged output).
        if not (
            self.answer or self.report_to or self.url or self.email or self.phone or self.steps
        ):
            return f"{head}.{(' ' + self.note) if self.note else ''}"
        # Knowledge topic: canonical answer + contacts/report route + steps.
        body: List[str] = []
        if self.answer:
            body.append(self.answer)
        elif self.note:
            body.append(self.note)
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
        return f"{head}. " + " ".join(body)


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
        for am in amenities:
            score = _score(q, am.lay_phrases)
            if score >= _MIN_SCORE:
                scored.append((score, am))
        scored.sort(key=lambda x: -x[0])
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
            )
            for _, am in scored[:3]
        ]

    async def _amenities(self) -> List[_Amenity]:
        if self._cache is not None and (time.monotonic() - self._cache_ts) < _CACHE_TTL_S:
            return self._cache
        # Physical amenities AND knowledge topics (procedures / info / maintenance issues)
        # in one pass — both are lay-term-matched and rendered by CapabilityFact.
        q = (
            f"{_ONTO}{_RDFS}"
            "SELECT ?a ?label ?loc ?note ?cat ?lay ?answer ?url ?email ?phone ?report ?steps WHERE { "
            "{ ?a a ontosage:Amenity } UNION { ?a a ontosage:KnowledgeTopic } "
            "OPTIONAL { ?a rdfs:label ?label } "
            "OPTIONAL { ?a ontosage:locationText ?loc } "
            "OPTIONAL { ?a ontosage:note ?note } "
            "OPTIONAL { ?a ontosage:capabilityCategory ?cat } "
            "OPTIONAL { ?a ontosage:layTerms ?lay } "
            "OPTIONAL { ?a ontosage:answerText ?answer } "
            "OPTIONAL { ?a ontosage:infoUrl ?url } "
            "OPTIONAL { ?a ontosage:contactEmail ?email } "
            "OPTIONAL { ?a ontosage:contactPhone ?phone } "
            "OPTIONAL { ?a ontosage:reportTo ?report } "
            "OPTIONAL { ?a ontosage:steps ?steps } }"
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
