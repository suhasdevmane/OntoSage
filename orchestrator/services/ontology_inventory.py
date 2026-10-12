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
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from shared.config import settings
from shared.utils import describe_exception, get_logger

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

# The shapes that ask for a COUNT, a LIST or the KINDS that exist. Bare "what"/"which" is not one.
_COUNT_OR_LIST_SHAPE = re.compile(
    r"\bhow\s+many\b|\blist\b|\bshow\b|\bcount\b|\btell\s+me\b|\b(?:kinds?|types?|sorts?)\b"
    r"|\bwhat\s+(?:are|were)\s+(?:the|all\s+the|our)\s+\w+s\b(?!\s+\w+\s+(?:for|to|that|which))"
    r"|\bdo\s+(?:we|you)\s+have\b|\bdoes\s+.{0,20}\bhave\b|\bare\s+there\b|\bis\s+there\b"
    r"|\b(?:is|are)\s+installed\b|\binstalled\b|\bexist\b|\bwhat\s+\w+(?:\s+\w+)?\s+(?:do|are)\s+"
    r"(?:we|you|there)\b"
    # BUG-1552: a place-scoped inventory. "What sensors are in room 2.03?" was answered with
    # readings; "What kinds of sensors are in room 5.01?" already reached the census.
    r"|\b(?:what|which)\s+(?:sensors?|devices?|equipment|points|meters?|instruments?)\s+(?:are|is)\s+"
    r"(?:in|on|inside|installed\s+in|fitted\s+in|located\s+in)\s+(?:room|floor|zone|level|the|this)\b",
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
    # A census answers HOW MANY / WHAT KINDS / LIST EVERYTHING and nothing else. "What asset and
    # space information may be shown to this user role ...?" and "Which BMS points are physically
    # verified against the assets ...?" have a bare what/which and an inventory noun, and were
    # answered "Room 234, Equipment 147 ..." (tail H, 2026-09-20).
    from orchestrator.services.governance_question import is_governance_question

    if is_governance_question(query):
        return False
    if not _COUNT_OR_LIST_SHAPE.search(q):
        return False
    # A question about an instrument's CONDITION is not a question about what the building
    # contains (BUG-427). "How many sensors are overdue for calibration?" has an inventory
    # shape and an inventory noun, so this claimed it and answered with the class census —
    # Sensor 2721, Air Quality Sensor 589, CO2 Sensor 280 — none of which is the number
    # asked for. The graph holds 194 overdue calibrations and a deterministic path counts
    # them; this must not take the question first.
    from orchestrator.services.routing_contract import _METROLOGY_RE

    if _METROLOGY_RE.search(query or ""):
        return False
    return any(re.search(rf"\b{re.escape(n)}\b", q) for n in _INVENTORY_NOUNS)


def _query_terms(query: str) -> List[str]:
    """The question's own nouns, as candidate Brick class name fragments."""
    # Letters-only tokens cut "CO2" to "co" and "PM2.5" to "pm", both then dropped as too short,
    # so "how many CO2 sensors?" counted EVERY sensor class (BUG-1573). A token starts with a
    # letter and may carry digits and an inner dot; a bare number or a room id is never one.
    words = [
        w.rstrip(".")
        for w in re.findall(r"[a-z][a-z0-9.]*", (query or "").lower())
        if len(w.rstrip(".")) > 2
    ]
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
            record_census_figures(rows)
            return rows
        if len(terms) == 1:
            break
    return []


#: The source name this lane's figures are filed under in the turn's evidence record.
EVIDENCE_SOURCE = "class_census"


def census_figures(rows: List[Tuple[str, int]]) -> Dict[str, float]:
    """The census as ``{class local name: count}`` -- the figures the answer will state.

    Pure, so what is COUNTED and what is RECORDED are pinned by a unit test. The names come
    from the graph's own class IRIs, never from the rendered sentence.
    """
    out: Dict[str, float] = {}
    for local, n in rows or []:
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            out[str(local)] = float(n)
    return out


def record_census_figures(rows: List[Tuple[str, int]]) -> None:
    """File a census as evidence for the turn that asked for it (CAVEAT-769).

    Without this the only place "280" existed was the sentence under test, so claim binding
    in enforce mode deleted the number the question had asked for. A count is the result of a
    query; recording it is what separates it from a guess. Never raises.
    """
    try:
        from orchestrator.services.evidence import computed

        computed.record(EVIDENCE_SOURCE, census_figures(rows))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"[inventory] evidence recording skipped: {e}")


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
    # A regex escape inside a SPARQL string literal needs its backslash doubled: "pm2\.5" is an
    # invalid string escape and the whole query would be rejected (BUG-1573).
    def _lit(t: str) -> str:
        return re.escape(t).replace("\\", "\\\\")

    if require_all:
        root_filter = "\n  ".join(f'FILTER(REGEX(STR(?root), "{_lit(t)}", "i"))' for t in terms)
    else:
        root_filter = 'FILTER(REGEX(STR(?root), "{}", "i"))'.format(
            "|".join(_lit(t) for t in terms)
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
        logger.warning(f"[inventory] class census failed: {describe_exception(e)}")
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
    return collapse_synonyms(found, prefer=terms)


def collapse_synonyms(
    rows: List[Tuple[str, int, str, str]], prefer: Sequence[str] = ()
) -> List[Tuple[str, int]]:
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
    want = [t.lower() for t in prefer]

    def _rank(name: str) -> Tuple[int, int]:
        # The name that says what the reader asked for wins over a longer, more general one:
        # the same 280 devices are CO2_Sensor and Air_Quality_Sensor, and "how many CO2 sensors?"
        # was answered "Air Quality Sensor — 280" (BUG-1573).
        hits = sum(1 for t in want if t in name.lower())
        return hits, len(name)

    for local, n, lo, hi in rows:
        key = (n, lo, hi)
        current = best.get(key)
        if current is None or _rank(local) > _rank(current):
            best[key] = local
    return sorted(((name, key[0]) for key, name in best.items()), key=lambda r: -r[1])


#: Off until the overlap is computed from the TBox rather than by a live ABox self-join
#: (BUG-535). A module constant, not a setting: turning it back on is a code decision that
#: needs the measurement above, not a line in .env.
OVERLAP_PROBE_ENABLED = False


async def overlap_notes(rows: List[Tuple[str, int]], namespace: str, endpoint: str) -> List[str]:
    """Which census rows are SUBSETS of other census rows (V12-09, CAVEAT-006 residual).

    A census reads as a partition. "Air Quality Sensor 523, CO2 Sensor 214, CO2 Level
    Sensor 208" invites the reader to add up to 945 devices in a building that has 523,
    because `collapse_synonyms` only merges classes spanning the IDENTICAL instance set —
    and a subclass spans a strict SUBSET, which is a different relation.

    Measured, not assumed. Whether two Brick classes overlap in THIS building is a fact
    about its ABox, and a building with 139 supply-air and 140 zone-air temperature sensors
    sharing nothing must not be told its categories overlap. So this asks.

    One query for every pair at once. Returns [] on any failure — a missing caveat is worse
    than none only if it is silently missing, and the caller keeps the census either way.
    """
    # Filtered ONCE. A class name carrying a double quote cannot go into the IN-list, and
    # building the list twice inline would let the two halves disagree about which names
    # survived — the same two-sources-of-truth shape this whole session has been unpicking.
    # DISABLED 2026-09-15 (BUG-535). This probe took GraphDB down for ~14 minutes during the
    # full regression run: 7 consecutive probe cases timed out at exactly 120 s each, starting
    # two seconds after its own ReadTimeout on "How many CO2 sensors are there?". A client-side
    # timeout does NOT cancel the query in GraphDB, and this one applied REPLACE() to every
    # type pair in the repository, so each census question left another runaway query behind
    # and every later graph call queued behind them. An index-driven rewrite still took 3.1 s
    # for 6 classes, and its answer is almost entirely inferred subclass nesting, which the
    # static Brick hierarchy can give without touching the ABox. Until that exists the census
    # renders exactly as it did before V12-09 — no overlap note, and no load.
    if not OVERLAP_PROBE_ENABLED:
        return []
    names = [local for local, _ in rows if '"' not in local]
    if len(names) < 2:
        return []
    counts = dict(rows)
    in_list = ", ".join(f'"{n}"' for n in names)
    # Bounded: at most `limit` classes reach here (25 by default), so at most limit*(limit-1)
    # ordered pairs. The LIMIT is a backstop against a graph whose class names collide after
    # the local-name reduction, not an expected truncation.
    sparql = f"""
SELECT ?an ?bn (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  ?s a ?a, ?b .
  FILTER(STRSTARTS(STR(?s), '{namespace}'))
  BIND(REPLACE(STR(?a), "^.*[#/]", "") AS ?an)
  BIND(REPLACE(STR(?b), "^.*[#/]", "") AS ?bn)
  FILTER(?an != ?bn)
  FILTER(?an IN ({in_list}))
  FILTER(?bn IN ({in_list}))
}} GROUP BY ?an ?bn LIMIT {max(2, len(names)) * max(1, len(names) - 1)}"""
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
            bindings = resp.json().get("results", {}).get("bindings", [])
    except Exception as e:
        logger.warning(f"[inventory] overlap probe failed: {describe_exception(e)}")
        return []

    return overlap_sentences(
        [
            (
                b.get("an", {}).get("value", ""),
                b.get("bn", {}).get("value", ""),
                int(b.get("n", {}).get("value", "0") or 0),
            )
            for b in bindings
        ],
        counts,
    )


def overlap_sentences(pairs: List[Tuple[str, str, int]], counts: Dict[str, int]) -> List[str]:
    """Turn measured pair overlaps into the sentences a reader needs. Pure, so it is
    testable without a graph.

    Only STRICT CONTAINMENT is reported — every instance of B also being an A. A partial
    overlap is real but saying "some of these are also those" without a number is a caveat
    nobody can act on, and this file's whole lesson is that a caveat which cannot be read
    is not a caveat.
    """
    contained: Dict[str, List[str]] = {}
    for a, b, shared in pairs:
        n_b = counts.get(b)
        n_a = counts.get(a)
        if not n_a or not n_b or shared != n_b or n_b >= n_a:
            continue
        contained.setdefault(a, []).append(b)

    def _pretty(name: str) -> str:
        return f"{name.replace('_', ' ')} ({counts[name]})"

    out = []
    for parent in sorted(contained):
        kids = sorted(set(contained[parent]))
        listed = ", ".join(_pretty(k) for k in kids)
        verb = "is" if len(kids) == 1 else "are"
        out.append(
            f"**These counts overlap — do not add them.** {listed} {verb} counted again "
            f"inside {_pretty(parent)}: every one of those devices also carries that class."
        )
    return out


def render_census(
    rows: List[Tuple[str, int]],
    building_name: str,
    overlaps: Optional[List[str]] = None,
) -> Optional[str]:
    """Render a census as prose, or None when there is nothing to report."""
    if not rows:
        return None
    # Recorded at the render too, so "every figure this block states was filed as evidence"
    # is true of the RENDER and not only of the fetch. A repeat record overwrites.
    record_census_figures(rows)
    # Worded for every reader (2026-09-17 user decision): "ontology" and "triples" are the
    # implementation, and a supervisor reading them sees a system talking to itself.
    lines = [f"Here is what **{building_name}** has, counted live from its building model:\n"]
    notes: List[str] = list(overlaps or [])
    for local, n in rows:
        lines.append(f"- **{local.replace('_', ' ')}** — {n}")
        # A count rolled up Brick's hierarchy can sweep in a DIFFERENT quantity.
        # brick:TVOC_Sensor is a subclass of brick:Particulate_Matter_Sensor, so
        # "how many particulate matter sensors?" counts 35 gas sensors among the
        # solids (CAVEAT-286). Say what the number includes, rather than repeating
        # it as though the class name meant what a reader assumes it means.
        try:
            from orchestrator.services.measurand_kinds import rollup_note

            note = rollup_note(local)
            if note and note not in notes:
                notes.append(note)
        except Exception:  # pragma: no cover - a disclosure must never break a count
            pass
    lines.append("\n*Counted now from the building's own model.*")
    lines.extend("\n" + n for n in notes)
    return "\n".join(lines)


# ── Instruments counted per floor (BUG-1614) ──────────────────────────────────────────────
#
# "Which floor has the most PM2.5 sensors?" was answered with PM2.5 LEVELS per floor (the
# aggregate lane read "most" as a statistic, BUG-1606) and, once that was stopped, declined: a
# census answers "how many" for the building, and nothing counted a class floor by floor. The
# graph holds the answer -- every point sits in a space and every space on a floor -- so it is
# counted there, never estimated. 0 of 4,060 bank questions take this shape; it came from a
# conversation ("How many PM2.5 sensors are there?" -> "which floor has the most of them?").

_INSTRUMENT_NOUN = r"(?:sensors?|devices?|meters?|detectors?|monitors?)"
_PER_FLOOR_RANK_RE = re.compile(
    r"\b(?:which|what)\s+(?:floor|level|storey)s?\b[^?]{0,40}?\b(?:has|have|holds?|contains?)\s+"
    r"the\s+(?P<dir>most|fewest|least|(?:greatest|highest|largest|smallest|lowest)\s+number\s+of)"
    r"\s+(?P<thing>(?:[\w.\-]+\s+){0,3}?" + _INSTRUMENT_NOUN + r")\b",
    re.IGNORECASE,
)
_PER_FLOOR_EACH_RE = re.compile(
    r"\bhow\s+many\s+(?P<thing>(?:[\w.\-]+\s+){0,3}?" + _INSTRUMENT_NOUN + r")\b[^?]{0,30}?"
    r"\b(?:on\s+each|per|by|on\s+every|for\s+each|in\s+each)\s+(?:floor|level|storey)\b"
    r"|\b(?P<thing2>(?:[\w.\-]+\s+){0,3}?" + _INSTRUMENT_NOUN + r")\s+"
    r"(?:per|by|on\s+each|for\s+each)\s+(?:floor|level|storey)\b",
    re.IGNORECASE,
)


def per_floor_instrument_ask(question: str) -> Optional[Tuple[str, str]]:
    """(the instruments named, "most" | "fewest" | "each") for a per-floor count, else None."""
    q = question or ""
    m = _PER_FLOOR_RANK_RE.search(q)
    if m:
        d = m.group("dir").lower()
        direction = "fewest" if d.startswith(("fewest", "least", "smallest", "lowest")) else "most"
        return m.group("thing").strip(), direction
    m = _PER_FLOOR_EACH_RE.search(q)
    if m:
        return (m.group("thing") or m.group("thing2") or "").strip(), "each"
    return None


def pick_counted_class(rows: Sequence[Tuple[str, int]], thing: str) -> Optional[str]:
    """The census class whose NAME carries every word of the instruments asked about, or None.

    "energy meters" ranked the umbrella class Equipment first, and counting every Equipment
    instance per floor answered a different question. With no class naming all the words the
    per-floor count is not given (the question falls through as before).
    """
    terms = _query_terms(thing)
    if not terms:
        return None
    for local, _n in rows or []:
        low = str(local).lower()
        if all(t in low for t in terms):
            return str(local)
    return None


#: The SCHEMA namespaces a counted class may come from: Brick, and the OCBV classes this system
#: declares where Brick has none (``ontosage:Sound_Level_Sensor``). No building namespace.
_SCHEMA_PREFIXES = {
    "brick": "https://brickschema.org/schema/Brick#",
    "ontosage": "http://ontosage.org/capabilities#",
    "hbco": "http://ontosage.org/hbco#",
}


def class_iri(ref: str) -> Optional[str]:
    """A class as a full IRI: a bare name is Brick's, a CURIE uses a schema prefix; else None."""
    ref = (ref or "").strip()
    if ref.startswith(("http://", "https://")):
        return None if re.search(r"[\s<>\"{}|\^`]", ref) else ref
    pfx, _, local = ref.partition(":")
    if not local:
        pfx, local = "brick", ref
    if pfx not in _SCHEMA_PREFIXES or not re.fullmatch(r"[A-Za-z0-9_.\-]+", local):
        return None
    return _SCHEMA_PREFIXES[pfx] + local


def class_local_name(ref: str) -> str:
    """'ontosage:Sound_Level_Sensor' -> 'Sound_Level_Sensor'."""
    return re.split(r"[#/:]", (ref or "").rstrip("#/"))[-1]


async def count_by_floor(
    class_ref: str, namespace: str, endpoint: str
) -> Optional[Tuple[List[Tuple[str, int]], int]]:
    """([(floor label, count)], total) for one class, from the graph; None on failure.

    The walk is the one ``scripts/floor_modality_matrix.py`` measures with: a point is located
    in, is a point of, or is part of a space, and the space is (transitively) part of a floor.
    The total counts every instance, so the ones placed on no floor can be stated, not dropped.
    """
    iri = class_iri(class_ref)
    if iri is None:
        return None
    cls = f"<{iri}>"
    per_floor = f"""
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?floor (SAMPLE(?fl) AS ?label) (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  ?s a {cls} .
  FILTER(STRSTARTS(STR(?s), '{namespace}'))
  ?s brick:hasLocation|brick:isPointOf|brick:isPartOf ?space .
  ?space brick:isPartOf* ?floor .
  ?floor a brick:Floor .
  OPTIONAL {{ ?floor rdfs:label ?fl }}
}} GROUP BY ?floor ORDER BY DESC(?n) LIMIT 100"""
    total_q = f"""
SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{
  ?s a {cls} .
  FILTER(STRSTARTS(STR(?s), '{namespace}'))
}}"""
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            auth = (
                (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD)
                if settings.GRAPHDB_USER
                else None
            )
            out = []
            for sparql in (per_floor, total_q):
                resp = await client.post(
                    endpoint,
                    auth=auth,
                    data={"query": sparql},
                    headers={"Accept": "application/sparql-results+json"},
                )
                resp.raise_for_status()
                out.append(resp.json().get("results", {}).get("bindings", []))
    except Exception as e:
        logger.warning(f"[inventory] per-floor count failed: {describe_exception(e)}")
        return None
    rows: List[Tuple[str, int]] = []
    for b in out[0]:
        iri = b.get("floor", {}).get("value", "")
        label = b.get("label", {}).get("value", "") or iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        try:
            n = int(b.get("n", {}).get("value", "0"))
        except (TypeError, ValueError):
            continue
        if n > 0:
            rows.append((label, n))
    try:
        total = int((out[1][0] if out[1] else {}).get("n", {}).get("value", "0"))
    except (TypeError, ValueError):
        total = sum(n for _, n in rows)
    return rows, total


async def count_concept_by_floor(
    thing: str, namespace: str, endpoint: str
) -> Optional[Tuple[str, List[Tuple[str, int]], int]]:
    """(class, per-floor rows, total) for the class the lay-term resolver gives ``thing``.

    For instruments no Brick class NAME carries: "noise sensors" are typed
    ``ontosage:Sound_Level_Sensor`` here, which a name match on "noise" cannot find. Of the
    concept's classes the one with the most instances in this building is counted; None when
    the concept resolves nothing or none of its classes is held.
    """
    try:
        from orchestrator.services.concept_resolver import concept_resolver

        matches = await concept_resolver.resolve(thing)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"[inventory] concept resolution skipped: {e}")
        return None
    classes = next((list(m.brick_classes) for m in matches if m.brick_classes), [])
    best: Optional[Tuple[str, List[Tuple[str, int]], int]] = None
    for ref in classes[:4]:
        got = await count_by_floor(ref, namespace, endpoint)
        if got and got[1] > 0 and (best is None or got[1] > best[2]):
            best = (ref, got[0], got[1])
    return best


def _short_floor(label: str) -> str:
    """'Floor 4 (Fourth Floor)' -> 'Floor 4'; any other label is kept as given."""
    return re.sub(r"\s*\(.*\)\s*$", "", label or "").strip() or label


def render_floor_census(
    class_local: str,
    rows: List[Tuple[str, int]],
    total: int,
    direction: str,
    building_name: str,
) -> Optional[str]:
    """The per-floor count as an answer, or None when no instance sits on any floor."""
    if not rows:
        return None
    name = class_local_name(class_local).replace("_", " ")
    placed = sum(n for _, n in rows)
    ordered = sorted(rows, key=lambda r: (-r[1], r[0]))
    try:
        from orchestrator.services.evidence import computed

        computed.record(
            EVIDENCE_SOURCE,
            {**{f"{_short_floor(f)} {name}": float(n) for f, n in ordered}, "total": float(total)},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"[inventory] evidence recording skipped: {e}")
    lines: List[str] = []
    if direction in ("most", "fewest"):
        pick = ordered[0][1] if direction == "most" else ordered[-1][1]
        tied = [_short_floor(f) for f, n in ordered if n == pick]
        word = "most" if direction == "most" else "fewest"
        if len(tied) == len(ordered) > 1:
            lines.append(f"**Every floor has the same number of {name}s: {pick}.**\n")
        else:
            who = tied[0] if len(tied) == 1 else " and ".join([", ".join(tied[:-1]), tied[-1]])
            verb = "has" if len(tied) == 1 else "have"
            tie = "" if len(tied) == 1 else " (tied)"
            lines.append(f"**{who} {verb} the {word} {name}s: {pick}{tie}.**\n")
    else:
        lines.append(f"**{name}s per floor in {building_name}:**\n")
    lines.append(f"| Floor | {name}s |")
    lines.append("|---|---|")
    for f, n in ordered:
        lines.append(f"| {_short_floor(f)} | {n} |")
    unplaced = max(0, total - placed)
    lines.append("")
    if unplaced:
        one = unplaced == 1
        lines.append(
            f"{unplaced} of the {total} {'is' if one else 'are'} not placed on a floor in the "
            f"building model, so {'it is' if one else 'they are'} not in this table."
        )
    else:
        lines.append(f"All {total} are placed on a floor.")
    lines.append("\n*Counted now from the building's own model.*")
    return "\n".join(lines)
