"""Answer "what <things> does this building have?" from the ontology (BUG-122).

Capabilities are TTL triples now — ``ontosage:Amenity`` and
``ontosage:KnowledgeTopic`` for things a building *offers*. But a building also
*contains* things, and those are already described in Brick: equipment, terminal
units, meters, valves. Nothing was answering from that half, so
"what equipment is installed in this building?" returned "I don't have that
information on record" while the graph held 149 equipment instances — a
well-populated ontology reporting itself as empty.

This module closes that half. It matches the question's own nouns against the
*Brick class names* in the active building's ABox and reports what is there with
live counts. Brick class names come from the shared TBox, not from any building's
vocabulary, so the same lookup works everywhere: a building that calls its rooms
``RM157_room`` and one that calls them ``Room_5.01`` both type them ``brick:Room``.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

import httpx

from shared.config import settings
from shared.utils import get_logger

logger = get_logger(__name__)

# Umbrella types every instance carries. Reporting them would answer "what
# equipment do you have?" with "1047 Entities", which is true and useless.
_UMBRELLA_CLASSES = {
    "entity",
    "class",
    "point",
    "location",
    "collection",
    "namedindividual",
    "externalreference",
    "timeseriesreference",
    "relationship",
    "tag",
    "resource",
    "space",
}

# Nouns that name a *kind of thing a building contains*. A question has to use one
# of these to be an inventory question at all — otherwise every question with a
# stray noun would trigger a class census. Generic building-domain English; no
# building's own vocabulary and no Brick class list to keep in sync.
_INVENTORY_NOUNS = (
    "equipment",
    "device",
    "devices",
    "asset",
    "assets",
    "plant",
    "machinery",
    # "system" is deliberately absent. It is the most common way to refer to
    # OntoSage itself — "what data does the system collect about me?" is a privacy
    # question, and treating it as an inventory question answered it with a census
    # of equipment and meters. A genuine "what HVAC systems do we have?" still
    # reaches the graph through the normal path; the false positives are worse.
    "unit",
    "units",
    "sensor",
    "sensors",
    "meter",
    "meters",
    "valve",
    "valves",
    "pump",
    "pumps",
    "fan",
    "fans",
    "chiller",
    "chillers",
    "boiler",
    "boilers",
    "ahu",
    "vav",
    "actuator",
    "actuators",
    "setpoint",
    "setpoints",
    "controller",
    "controllers",
)

# "what/which/list/show … do we have / are installed / are there"
_INVENTORY_SHAPE = re.compile(
    r"\b(?:what|which|list|show|tell me|how many|are there|do (?:we|you) have|"
    r"is installed|are installed|does .{0,20}\bhave)\b",
    re.IGNORECASE,
)

# "what is a VAV box?" asks what the thing IS, not how many this building has —
# it names an inventory noun and opens like a question, so without this it would
# trigger a census and answer a vocabulary question with a count. The singular
# indefinite article is the discriminator: "what are the meters?" is an inventory
# question, "what is a meter?" is a definition.
_DEFINITION_SHAPE = re.compile(
    r"\bwhat(?:'s| is|s)\s+(?:a|an)\b"
    r"|\bwhat\s+does\s+(?:a|an|the)\b"
    r"|\bwhat\s+(?:is|are)\s+.{0,30}\b(?:mean|used for|for)\b"
    r"|\b(?:define|explain|describe)\b"
    r"|\bhow\s+(?:does|do)\s+.{0,30}\bwork\b",
    re.IGNORECASE,
)

_STOP = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "for",
    "to",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "do",
    "does",
    "did",
    "we",
    "you",
    "this",
    "that",
    "there",
    "here",
    "what",
    "which",
    "list",
    "show",
    "tell",
    "me",
    "my",
    "our",
    "have",
    "has",
    "had",
    "building",
    "buildings",
    "installed",
    "available",
    "all",
    "any",
    "many",
    "how",
    "get",
    "give",
    "please",
    "types",
    "type",
    "kind",
    "kinds",
}


def is_inventory_question(query: str) -> bool:
    """True when the user is asking what kinds of things the building contains."""
    q = (query or "").lower()
    if not q.strip():
        return False
    if _DEFINITION_SHAPE.search(q):
        return False
    if not _INVENTORY_SHAPE.search(q):
        return False
    return any(re.search(rf"\b{re.escape(n)}\b", q) for n in _INVENTORY_NOUNS)


def _query_terms(query: str) -> List[str]:
    """The question's own nouns, as candidate Brick class name fragments."""
    words = [w for w in re.findall(r"[a-z]+", (query or "").lower()) if len(w) > 2]
    out: List[str] = []
    for w in words:
        if w in _STOP:
            continue
        stem = w[:-1] if w.endswith("s") and not w.endswith("ss") else w
        if stem not in out:
            out.append(stem)
    return out[:6]


async def class_census(
    query: str,
    namespace: str,
    endpoint: str,
    *,
    limit: int = 25,
) -> List[Tuple[str, int]]:
    """Return [(brick class local name, instance count)] matching the question.

    Counts are computed now, from this building's own ABox — never a stored
    figure. An empty list means the building genuinely has nothing of that kind.
    """
    terms = _query_terms(query)
    if not terms:
        return []
    # Try the compound first: "air handling unit" must match a class containing ALL
    # three words. Matching any single word instead lets the most generic one win —
    # "air" alone pulls in every air-temperature sensor, so a question about air
    # handling units was answered with the sensor census. Fall back to any-word only
    # when the compound finds nothing, so single-word questions still work.
    for require_all in (True, False):
        rows = await _census_query(terms, namespace, endpoint, limit, require_all=require_all)
        if rows:
            return rows
        if len(terms) == 1:
            break
    return []


async def _census_query(
    terms: List[str],
    namespace: str,
    endpoint: str,
    limit: int,
    *,
    require_all: bool,
) -> List[Tuple[str, int]]:
    """One census pass — see class_census for why it runs twice."""
    # Match the class NAME, so "equipment" finds Equipment and HVAC_Equipment
    # whatever the building calls its individual units.
    if require_all:
        root_filter = "\n  ".join(
            f'FILTER(REGEX(STR(?root), "{re.escape(t)}", "i"))' for t in terms
        )
    else:
        root_filter = 'FILTER(REGEX(STR(?root), "{}", "i"))'.format(
            "|".join(re.escape(t) for t in terms)
        )
    # Match on one type and report ALL of the instance's types. Matching the
    # reported class instead answers "what equipment is here?" with "Equipment:
    # 149" — true, and useless. This way the umbrella class finds the instances
    # and their own types describe them: VAV boxes, air handling units, a chiller.
    # ?lo/?hi fingerprint the instance SET, not just its size — see _collapse_synonyms.
    sparql = f"""
SELECT ?cls (COUNT(DISTINCT ?s) AS ?n) (MIN(STR(?s)) AS ?lo) (MAX(STR(?s)) AS ?hi) WHERE {{
  ?s a ?cls ; a ?root .
  FILTER(STRSTARTS(STR(?s), '{namespace}'))
  FILTER(STRSTARTS(STR(?cls), 'https://brickschema.org/'))
  {root_filter}
}} GROUP BY ?cls ORDER BY DESC(?n) LIMIT {limit}"""
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            resp = await client.post(
                endpoint,
                auth=auth,
                data={"query": sparql},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("bindings", [])
    except Exception as e:
        logger.warning(f"[inventory] class census failed: {e}")
        return []

    found: List[Tuple[str, int, str, str]] = []
    for b in rows:
        uri = b.get("cls", {}).get("value", "")
        local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if local.lower() in _UMBRELLA_CLASSES:
            continue
        try:
            n = int(b.get("n", {}).get("value", "0"))
        except (TypeError, ValueError):
            continue
        if n > 0:
            found.append(
                (local, n, b.get("lo", {}).get("value", ""), b.get("hi", {}).get("value", ""))
            )
    return collapse_synonyms(found)


def collapse_synonyms(rows: List[Tuple[str, int, str, str]]) -> List[Tuple[str, int]]:
    """Keep one name per distinct instance SET — the most descriptive one.

    Brick types one population under several names at once: the same 132 boxes are
    a VAV, a Variable_Air_Volume_Box and a Terminal_Unit, and listing all three
    reads like three different things.

    Sameness is decided by the instance set, not by the count. Equal counts alone
    would be a guess, and a wrong one hides a real population: this building has
    139 supply-air and 139 discharge-air temperature sensors, which are in fact
    the same dual-typed 139 — but it also has 140 zone-air sensors sharing none of
    them. Each row carries the lowest and highest instance URI, so two classes
    collapse only when they span the identical set.
    """
    best: dict = {}
    for local, n, lo, hi in rows:
        key = (n, lo, hi)
        current = best.get(key)
        if current is None or len(local) > len(current):
            best[key] = local
    return sorted(((name, key[0]) for key, name in best.items()), key=lambda r: -r[1])


def render_census(rows: List[Tuple[str, int]], building_name: str) -> Optional[str]:
    """Render a census as prose, or None when there is nothing to report."""
    if not rows:
        return None
    lines = [f"Here is what **{building_name}** has, counted live from its ontology:\n"]
    for local, n in rows:
        lines.append(f"- **{local.replace('_', ' ')}** — {n}")
    lines.append("\n*Counted now from the building's own ontology (triples).*")
    return "\n".join(lines)
