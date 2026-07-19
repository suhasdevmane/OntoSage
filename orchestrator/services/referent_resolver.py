"""Referent resolution gate — verify a named zone/room/sensor exists before answering.

Problem this solves
--------------------
A data query that names a *specific* location — "what is the temperature in Zone 99.99?"
— used to be answered with fabricated-looking data. The pipeline's fallback cascade
(class+location SPARQL → ``_fallback_pattern_search`` which drops the location filter →
semantic RAG → SQL ``fetch_data_for_uuids`` → SQL auto-expand) is designed to always
surface *some* class-matching sensor's readings, which the response LLM then narrates as
belonging to the nonexistent zone. There was no step that asked "does Zone 99.99 exist?".

This module adds that step. It is intentionally **precision-first**: it only fires when the
user names a *specific* spatial referent, and it **fails open** (proceeds as before) on any
SPARQL error, so it can never block a legitimate query or a query against a degraded GraphDB.

Portability
-----------
Building-agnostic. The referent is validated against the ACTIVE building's ontology
namespace (passed in by the caller from the per-request building context) using generic
SPARQL over subject URIs / ``rdfs:label`` — no building-specific literals. A new building
works unchanged: its zones come from its own TTL.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from shared.utils import get_logger

logger = get_logger(__name__)

# An injected async callable: SPARQL string -> standard SPARQL-results JSON dict.
SparqlExec = Callable[[str], Awaitable[dict]]

# A dotted numeric location id (e.g. 5.28, 3.01, 99.99). Common Brick zone/room id shape.
_DOTTED_ID_RE = re.compile(r"\d{1,2}\.\d{1,2}")
# "zone|room|space|node|area <id>" — an explicitly location-qualified reference.
_WORDED_REF_RE = re.compile(
    r"\b(?:zone|room|space|node|area)\s+([A-Za-z0-9][A-Za-z0-9._-]{0,23})\b",
    re.IGNORECASE,
)
# Injection guard: only these characters may reach a SPARQL string literal.
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._-]{1,24}$")

# Data intents whose answer is scoped to a specific sensor/zone — worth gating.
# Broad intents (metadata, discovery, floor_plan, capability, …) are NOT gated: they
# legitimately answer without a specific referent.
GATED_INTENTS = frozenset(
    {
        "sensor_data",
        "analytics",
        "trend",
        "compare",
        "comparison",
        "anomaly",
        "compliance",
        "visualization",
    }
)

# Status values
RESOLVED = "resolved"
NOT_FOUND = "not_found"
NO_REFERENT = "no_referent"
SKIPPED = "skipped"  # existence check could not run (e.g. GraphDB down) — fail open


@dataclass
class ReferentResolution:
    """Outcome of resolving a named referent against the building ontology."""

    status: str
    referent: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    message: str = ""


def detect_referent(query: str, entities: Optional[List[str]] = None) -> Optional[str]:
    """Return the single explicit spatial referent token, or ``None``.

    Precision-first: only returns a token when the query/entities name a *specific*
    location (a location-qualified dotted id like "zone 5.28", or a bare dotted id that
    the dialogue agent already extracted as an entity). Broad queries ("all zones",
    "temperature", "26.5 degrees") return ``None`` and pass through the pipeline unchanged.
    """
    # 1) Entity list first — the dialogue agent already isolated building entities, so a
    #    dotted id here is a high-confidence zone/room reference (not a threshold value).
    for ent in entities or []:
        ent = str(ent)
        m = _DOTTED_ID_RE.search(ent)
        if m and _SAFE_TOKEN_RE.match(m.group(0)):
            return m.group(0)
        m = _WORDED_REF_RE.search(ent)
        if m and _SAFE_TOKEN_RE.match(m.group(1)):
            return m.group(1)

    # 2) Raw query — require an explicit location word before the id so we never trip on a
    #    threshold/value (e.g. "above 26.5 degrees" has no location word → ignored).
    m = _WORDED_REF_RE.search(query or "")
    if m and _SAFE_TOKEN_RE.match(m.group(1)):
        return m.group(1)

    return None


class ReferentResolver:
    """Validate a named referent against a building's ontology namespace."""

    def __init__(self, sparql_exec: SparqlExec):
        self._exec = sparql_exec

    async def resolve(
        self,
        query: str,
        entities: Optional[List[str]],
        namespace: str,
        building_name: str = "this building",
    ) -> ReferentResolution:
        """Resolve the query's spatial referent (if any) against ``namespace``.

        Never raises: on any SPARQL error returns ``SKIPPED`` so the caller proceeds
        exactly as it did before this gate existed (fail open).
        """
        token = detect_referent(query, entities)
        if not token:
            return ReferentResolution(status=NO_REFERENT)

        try:
            exists = await self._exists(token, namespace)
        except Exception as e:  # GraphDB down / timeout / malformed — fail OPEN.
            logger.warning(f"[referent_resolver] existence check failed, proceeding: {e}")
            return ReferentResolution(status=SKIPPED, referent=token)

        if exists:
            return ReferentResolution(status=RESOLVED, referent=token)

        # Not found — best-effort suggestions (never fatal).
        try:
            suggestions = await self._suggest(token, namespace)
        except Exception as e:
            logger.warning(f"[referent_resolver] suggestion lookup failed: {e}")
            suggestions = []

        return ReferentResolution(
            status=NOT_FOUND,
            referent=token,
            suggestions=suggestions,
            message=self._clarification(token, suggestions, building_name),
        )

    # ------------------------------------------------------------------ helpers

    async def _exists(self, token: str, namespace: str) -> bool:
        """True if any subject in ``namespace`` has ``token`` in its URI or rdfs:label."""
        t = token.lower()
        q = (
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s WHERE {\n"
            "  ?s ?p ?o .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            f'  FILTER( CONTAINS(LCASE(STR(?s)), "{t}")\n'
            f'          || EXISTS {{ ?s rdfs:label ?l . FILTER(CONTAINS(LCASE(STR(?l)), "{t}")) }} )\n'
            "} LIMIT 1"
        )
        data = await self._exec(q)
        return len(_bindings(data)) > 0

    async def _suggest(self, token: str, namespace: str) -> List[str]:
        """Return up to 5 real dotted-id locations closest to ``token``."""
        q = (
            "SELECT DISTINCT ?s WHERE {\n"
            "  ?s ?p ?o .\n"
            f'  FILTER(STRSTARTS(STR(?s), "{namespace}"))\n'
            '  FILTER(REGEX(STR(?s), "[0-9]{1,2}[.][0-9]{1,2}"))\n'
            "} LIMIT 400"
        )
        data = await self._exec(q)
        ids: set[str] = set()
        for b in _bindings(data):
            uri = b.get("s", {}).get("value", "")
            m = _DOTTED_ID_RE.search(uri)
            if m:
                ids.add(m.group(0))
        if not ids:
            return []
        ids_sorted = sorted(ids)
        # Prefer typo-close matches (e.g. "5.2" → "5.28"); otherwise fall back to a
        # small sample of real zones so a wildly-wrong id ("99.99") still gets the
        # user a concrete, valid starting point instead of an empty hand.
        close = difflib.get_close_matches(token, ids_sorted, n=5, cutoff=0.3)
        return close or ids_sorted[:5]

    @staticmethod
    def _clarification(token: str, suggestions: List[str], building_name: str) -> str:
        head = (
            f'I couldn’t find "{token}" in {building_name}, '
            f"so I can’t return sensor data for it."
        )
        if suggestions:
            opts = ", ".join(suggestions)
            return (
                f"{head} Did you mean one of these zones: **{opts}**? "
                'You can also ask "list all zones" to see what exists.'
            )
        return (
            f"{head} Try asking “list all zones” (or “list zones on floor N”) "
            "to see the valid locations, then name an existing zone or sensor."
        )


def _bindings(data: dict) -> list:
    """Extract the bindings list from a standard SPARQL-results dict, defensively."""
    if not isinstance(data, dict):
        return []
    results = data.get("results", {})
    if isinstance(results, dict):
        b = results.get("bindings", [])
        return b if isinstance(b, list) else []
    return []
