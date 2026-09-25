# -*- coding: utf-8 -*-
"""Which of THIS building's concepts does a question mean, when no lay term matched?

WHY THIS EXISTS. The HBCO concept resolver maps lay words to sensor classes -- "stuffy" is a CO2
question, "chilly" a temperature one -- by matching against lay terms written into the ontology. It
works, and it is fast and free, but it only knows the words somebody thought to write down. The
register held "warmest", "hottest" and "coldest" and NOT "coolest", so "where's the coolest place to
work right now?" resolved to no concept at all. With no measurand resolved, nothing contradicted the
classifier's guess that a question mentioning "place to work" was about the workspace register, and
the building answered a temperature question from a register that holds no temperature.

Writing "coolest" into the ontology fixes that one word and leaves the next one. This module is the
general form: when the literal lookup finds nothing, ask the configured model which of the concepts
THIS BUILDING actually has the question is about.

WHAT KEEPS IT HONEST
    * It CHOOSES, it does not invent. The candidates are the building's own concepts, read from the
      live graph; a reply naming anything else is discarded. It can never name a sensor class the
      building does not have, which is the failure mode that would matter.
    * NONE is a first-class answer and the default on any doubt. A question about a quantity the
      building does not measure must keep resolving to nothing, so the honest "not measured" decline
      still fires.
    * It runs ONLY after the deterministic path returns nothing, so a building whose vocabulary
      already covers a word gets the same answer as before, at the same cost.
    * It fails open. A timeout, a provider error or an unparsed reply leave the question unresolved,
      which is exactly where it was without this module.

BUILDING-AGNOSTIC BY CONSTRUCTION. Nothing here names a building, a concept or a sensor class: the
candidate list is whatever the active building's graph holds, so another building's own vocabulary
is what its questions are matched against.

COST. One short call, only on a miss, and the result is cached per building, so the second person to
ask a newly-understood phrasing pays nothing.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from shared.utils import get_logger

logger = get_logger(__name__)

#: How long a reading of "what can this building measure" stays good. The answer changes only
#: when a TTL is uploaded or a datasource registered, so minutes are ample and the query is
#: never on the hot path twice.
READABLE_TTL_S = 900.0

#: How often the readable-class filter has ACTUALLY removed something, and how often it was
#: unavailable and therefore did nothing. A fail-open component that nobody counts is
#: indistinguishable from one that never runs -- lessons.md #126, learned when a gate was
#: believed to be protecting a lane it had silently stopped touching.
FILTER_STATS: Dict[str, int] = {"applied": 0, "removed": 0, "unavailable": 0}

_READABLE: Optional[Set[str]] = None
_READABLE_AT: float = 0.0

_READABLE_SPARQL = """
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?cls WHERE {
  ?s a ?cls ; ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?ts .
}
"""


def _local(class_iri: str) -> str:
    """`Temperature_Sensor` from any of the four ways a class gets written down here."""
    return str(class_iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1].strip().lower()


async def readable_classes(timeout_s: float = 10.0) -> Optional[Set[str]]:
    """The sensor classes this building can actually READ, by local name.

    A class earns a place here by having at least one instance that carries a timeseries
    reference -- not by being named like a sensor. That distinction is the whole point.
    `brick:Smoke_Detector` and `brick:Fire_Alarm` ARE sensor classes in the schema, and this
    building holds 2 and 6 instances of them, with **zero** readings between them. They are
    things the building has, not quantities it measures, and offering them as candidate
    measurands is what let "is there smoke in the lab?" resolve to an emergency exit.

    Returns None -- NOT an empty set -- when the graph could not be read. The difference
    matters: an empty set would filter every concept away and silently disable the matcher,
    turning one unreadable HTTP call into a building that understands nothing. None means
    "unknown", and an unknown must not be allowed to act.
    """
    global _READABLE, _READABLE_AT
    now = time.monotonic()
    if _READABLE is not None and (now - _READABLE_AT) < READABLE_TTL_S:
        return _READABLE
    try:
        import httpx

        from shared.config import settings

        endpoint = (
            f"http://{settings.GRAPHDB_HOST}:{settings.GRAPHDB_PORT}"
            f"/repositories/{settings.GRAPHDB_REPOSITORY}"
        )
        auth = (
            (settings.GRAPHDB_USER, settings.GRAPHDB_PASSWORD) if settings.GRAPHDB_USER else None
        )
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                endpoint,
                auth=auth,
                data={"query": _READABLE_SPARQL},
                headers={"Accept": "application/sparql-results+json"},
            )
            resp.raise_for_status()
            rows = resp.json().get("results", {}).get("bindings", [])
        found = {_local(r["cls"]["value"]) for r in rows if r.get("cls", {}).get("value")}
    except Exception as e:  # pragma: no cover - network path
        logger.warning(f"[semantic_concept] readable classes unreadable, filter stands down: {e}")
        return None
    if not found:
        # A reachable graph that names no readable class is a building with no timeseries at
        # all. Treat it as unknown rather than as a filter that removes everything.
        logger.warning("[semantic_concept] no class carries a reading; filter stands down")
        return None
    _READABLE, _READABLE_AT = found, now
    logger.info(f"[semantic_concept] {len(found)} classes carry readings in this building")
    return found

#: Big enough to hold a real building's whole vocabulary. This was 40, taken alphabetically, and
#: the bug that caused is worth keeping in mind: with 99 concepts the menu stopped at "busy", so
#: `too_warm` and `too_cold` were never offered and the model answered NONE to "where is it
#: coolest" -- correctly, for the menu it was given. A truncated menu does not produce a cautious
#: answer, it produces a confidently wrong one, and the fault is invisible from the reply.
MAX_CANDIDATES = 200
MAX_QUESTION_CHARS = 400
NONE = "NONE"

SYSTEM = (
    "You map a building occupant's everyday words to the concepts from a fixed list that the "
    "question is asking about, or to NONE.\n"
    "Each concept names a quantity the building actually measures.\n\n"
    "Reply with ONE line: the concept ids separated by a comma, a pipe, and a short reason.\n"
    "  example:  thermal_comfort | 'coolest' is an everyday way of saying lowest temperature\n"
    "  example:  thermal_comfort, stuffiness | 'warm and stuffy' names temperature AND CO2\n"
    "  example:  NONE | radiation is a different quantity from any of these\n\n"
    "NAME EVERY QUANTITY THE QUESTION ASKS ABOUT, and no others. A question comparing two "
    "conditions is asking about both: answering with one of them would silently drop half of what "
    "was asked. A question about a single condition names one.\n\n"
    "THE TEST TO APPLY. Match only when the person's words are a SYNONYM or an everyday "
    "description of the concept's own quantity -- another way of saying the same thing. If they "
    "name a DIFFERENT physical quantity, the answer is NONE, however close the subject feels.\n\n"
    "RULES\n"
    "- The id MUST be one of the ids listed. Never invent one, never combine two.\n"
    "- NEVER substitute the nearest available quantity for the one that was asked about. If "
    "somebody asks about radiation and the list offers solar irradiance, that is NONE: they are "
    "different quantities, and answering about the wrong one tells the person the building "
    "considered their question when it did not. The same goes for air pressure vs air flow, "
    "smoke vs dust, and water pressure vs water flow.\n"
    "- Reply NONE if you are unsure. NONE is the right answer far more often than a near miss. A "
    "wrong concept makes the building answer a question nobody asked; NONE makes it say honestly "
    "that it does not measure that, which is what the person needs to hear.\n"
    "- Judge what the person WANTS TO KNOW, not which words appear. 'Where can I cool off' is "
    "about temperature; 'how do I cool the room down' is still about temperature.\n"
    "- A question that is not about a measurable condition at all -- a policy, a person, a "
    "document, an opening time -- is NONE."
)


#: The second step. SELECTING from 92 options is a recall problem and the model is good at it; it is
#: much worse at declining, and reached for the nearest available quantity -- "radiation level" was
#: answered as solar irradiance and "is there smoke in the lab" as an emergency exit. Both are
#: honest-sounding answers to a question nobody asked, which is the failure this whole module exists
#: to avoid. A narrow yes/no about ONE pair is a different and much easier judgement, so the choice
#: is made first and confirmed second.
CONFIRM_SYSTEM = (
    "You answer YES or NO to one question about measurement.\n\n"
    "You are told what somebody asked, and one quantity the building measures. Answer YES if that "
    "quantity is ONE OF the things the person asked about -- the same physical thing, said in "
    "other words. Answer NO if it is a different quantity, however related the subject is.\n\n"
    "A QUESTION MAY ASK ABOUT SEVERAL THINGS. 'Warm and stuffy' asks about temperature AND about "
    "CO2, so each of those is YES on its own. Judge the one quantity you are given against "
    "everything the question asks, not against the question as a whole.\n\n"
    "  'where is it coolest' vs Temperature              -> YES ('cool' is everyday for temperature)\n"
    "  'which rooms are warm and stuffy' vs Temperature  -> YES ('warm' is one of the two asked)\n"
    "  'which rooms are warm and stuffy' vs CO2          -> YES ('stuffy' is the other one)\n"
    "  'what is the radiation level' vs Solar Irradiance -> NO (different quantities)\n"
    "  'is there smoke' vs Emergency Exit                -> NO (not a measurement of smoke)\n"
    "  'somewhere less muggy' vs Humidity                -> YES ('muggy' is everyday for humid)\n\n"
    "Reply with one word: YES or NO."
)


@dataclass
class SemanticMatch:
    """One resolution attempt.

    ``concept_id`` is the first chosen concept and ``concept_ids`` holds them all: a question can
    name two conditions ("warm AND stuffy") and answering with one silently drops half of it.
    """

    concept_id: str = ""
    reason: str = ""
    matched: bool = False
    skipped: str = ""
    candidates_offered: int = 0
    brick_classes: List[str] = field(default_factory=list)
    #: Every concept chosen, in the order the model named them. Always contains ``concept_id``
    #: first when anything matched.
    concept_ids: List[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def build_candidates(
    concept_map: Dict[str, Dict[str, Any]],
    limit: int = MAX_CANDIDATES,
    question: str = "",
    readable: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """The building's concepts, as a menu the model can choose from.

    Only concepts that name at least one sensor class are offered: a concept the building cannot
    measure is not a useful resolution, and offering it invites a match that leads nowhere.

    ``readable`` sharpens that from a claim about the SCHEMA into a fact about THIS BUILDING.
    Naming a sensor class only says the class exists; a concept earns its place on the menu by
    naming a class that some instance here actually reports readings for. Without it, the menu
    offered `fire_safety` and `emergency_exit` -- both carrying `brick:Smoke_Detector`, of which
    this building holds two instances and not one reading -- and "is there smoke in the lab?"
    duly matched one. No amount of prompt wording fixes a menu that contains the wrong answer;
    removing it from the menu does, for every building and every phrasing at once.

    Pass None when the graph could not be read: the filter then stands down and the menu is what
    it was before. See ``readable_classes``.

    A building with more concepts than ``limit`` is ranked by overlap with the question before the
    cut, so whatever is plausibly relevant survives it. Below the limit -- the normal case -- every
    concept is offered and the order is alphabetical.
    """
    if readable is None:
        FILTER_STATS["unavailable"] += 1
    else:
        FILTER_STATS["applied"] += 1
    out: List[Dict[str, Any]] = []
    for key, c in (concept_map or {}).items():
        classes = [str(x) for x in (c.get("brick_classes") or []) if x]
        if not classes:
            continue
        if readable is not None and not any(_local(x) in readable for x in classes):
            FILTER_STATS["removed"] += 1
            continue
        # The map is keyed by the concept's full IRI; the short id a person (and the model) can
        # read lives inside the entry. Offering the IRI made every reply look off-menu.
        cid = str(c.get("concept_id") or str(key).rsplit("#", 1)[-1].rsplit("/", 1)[-1])
        terms = [str(t) for t in (c.get("lay_terms") or []) if t][:6]
        out.append(
            {
                "id": cid,
                "label": str(c.get("label") or cid),
                "lay_terms": terms,
                "brick_classes": classes,
            }
        )
    out.sort(key=lambda d: d["id"])
    if len(out) <= limit:
        return out
    words = {w for w in re.findall(r"[a-z]{3,}", _norm(question))}

    def _overlap(d: Dict[str, Any]) -> int:
        text = " ".join([d["id"], d.get("label", "")] + list(d.get("lay_terms") or [])).lower()
        return sum(1 for w in words if w in text)

    out.sort(key=lambda d: (-_overlap(d), d["id"]))
    return out[:limit]


def _measures(classes: Sequence[str]) -> str:
    """"Temperature, Humidity" from the sensor classes, so the menu says what each concept READS."""
    seen, out = set(), []
    for c in classes:
        local = str(c).rsplit("#", 1)[-1].rsplit(":", 1)[-1]
        name = re.sub(r"_?Sensor$|_?Level$", "", local).replace("_", " ").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return ", ".join(out[:3])


def render_menu(candidates: Sequence[Dict[str, Any]]) -> str:
    """The candidate list as the model sees it: id, what it measures, and example words.

    WHAT IT MEASURES IS THE USEFUL PART. Many concepts have no label beyond their own id, so a menu
    of ids alone asks the model to guess what `acoustic_comfort` reads. Naming the sensor turns the
    choice into the one actually being made: which quantity does this person mean?
    """
    lines = []
    for c in candidates:
        words = ", ".join((c.get("lay_terms") or [])[:5])
        reads = _measures(c.get("brick_classes") or [])
        bits = [f"measures {reads}"] if reads else []
        if words:
            bits.append(f"said as: {words}")
        tail = f" — {'; '.join(bits)}" if bits else ""
        lines.append(f"- {c['id']}{tail}")
    return "\n".join(lines)


_LINE = re.compile(r"^\W*([A-Za-z0-9_.:-]+)\s*(?:[|:\-–—]\s*)?(.*)$", re.DOTALL)


def parse_choice(raw: str, valid_ids: Sequence[str]) -> SemanticMatch:
    """Read the model's one line, accepting only ids that are on the menu.

    A reply may name SEVERAL concepts, comma separated: "warm and stuffy" is a question about
    temperature and about CO2, and returning one of them drops half the question. Off-menu ids are
    discarded individually, so one bad name does not throw away a good one beside it — but if
    nothing survives, nothing matched.
    """
    text = (raw or "").strip()
    if not text:
        return SemanticMatch(skipped="error: empty reply")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    head, _, tail = first.strip().partition("|")
    reason = " ".join(tail.split())[:200]
    tokens = [t.strip() for t in re.split(r"[,;]+", head) if t.strip()]
    if not tokens:
        return SemanticMatch(skipped="error: unparsed reply")
    if any(t.upper() == NONE for t in tokens):
        return SemanticMatch(reason=reason or "no listed concept fits", skipped="")

    lookup = {str(v).lower(): str(v) for v in valid_ids}
    chosen, rejected = [], []
    for t in tokens:
        hit = lookup.get(t.lower())
        if hit and hit not in chosen:
            chosen.append(hit)
        elif not hit:
            rejected.append(t[:40])
    if rejected:
        # An off-menu id is the one thing that could name a sensor class the building lacks.
        logger.info("[semantic_concept] discarded off-menu reply(s) %r", rejected[:3])
    if not chosen:
        return SemanticMatch(skipped=f"error: off-menu id {rejected[0]!r}" if rejected
                             else "error: unparsed reply")
    return SemanticMatch(concept_id=chosen[0], concept_ids=chosen, reason=reason, matched=True)


def _client() -> Any:
    from orchestrator.llm_manager import llm_manager

    return llm_manager


def _task_type() -> Any:
    from orchestrator.llm_manager import TaskType

    return TaskType.INTENT


def _setting(name: str, default: Any) -> Any:
    try:
        from shared.config import settings

        return getattr(settings, name, default)
    except Exception:
        return default


def enabled() -> bool:
    return bool(_setting("SEMANTIC_CONCEPT_MATCH", True))


#: How often this actually CHANGED an outcome, by reason. A fail-open component that nobody counts
#: cannot be told apart from one that never runs (lessons.md #126).
ACTED: Dict[str, int] = {"matched": 0, "none": 0, "error": 0, "cache_hit": 0, "rejected": 0}


async def confirm(question: str, candidate: Dict[str, Any], timeout_s: float) -> bool:
    """Is the chosen concept really the quantity the question asked about?

    Returns False on any error or unclear reply: an unconfirmed match is not used, so the question
    stays unresolved and the honest "not measured" decline still fires.
    """
    reads = _measures(candidate.get("brick_classes") or []) or candidate["id"].replace("_", " ")
    prompt = f"SOMEBODY ASKED: {question[:MAX_QUESTION_CHARS]}\nTHE BUILDING MEASURES: {reads}"
    try:
        raw = await asyncio.wait_for(
            _client().generate(
                prompt, system_message=CONFIRM_SYSTEM, temperature=0, task_type=_task_type()
            ),
            timeout=timeout_s,
        )
    except Exception:
        return False
    head = (raw or "").strip().upper()
    return head.startswith("YES")


async def match(
    question: str,
    concept_map: Dict[str, Dict[str, Any]],
    *,
    timeout_s: Optional[float] = None,
    cache_get=None,
    cache_set=None,
    already: Optional[Sequence[str]] = None,
) -> SemanticMatch:
    """Choose one of the building's concepts for a question no lay term matched.

    Never raises. Returns an unmatched result on any doubt, error or timeout.
    """
    if not enabled():
        return SemanticMatch(skipped="disabled")
    q = _norm(question)
    if not q:
        return SemanticMatch(skipped="empty question")

    candidates = build_candidates(concept_map, question=q, readable=await readable_classes())
    if not candidates:
        return SemanticMatch(skipped="this building records no measurable concept")
    ids = [c["id"] for c in candidates]

    have = [str(a) for a in (already or [])]
    key = f"cache:semconcept:{abs(hash((q, tuple(ids), tuple(have)))):x}"
    if cache_get is not None:
        try:
            cached = await cache_get(key)
        except Exception:
            cached = None
        if cached:
            ACTED["cache_hit"] += 1
            if str(cached) == NONE:
                return SemanticMatch(reason="cached", skipped="")
            by_id = {c["id"]: c for c in candidates}
            cids = [c for c in str(cached).split(",") if c in by_id]
            if cids:
                classes: List[str] = []
                for cid in cids:
                    for k in by_id[cid]["brick_classes"]:
                        if k not in classes:
                            classes.append(k)
                return SemanticMatch(
                    concept_id=cids[0], concept_ids=cids, reason="cached", matched=True,
                    candidates_offered=len(candidates), brick_classes=classes,
                )

    prompt = (
        f"CONCEPTS THIS BUILDING CAN MEASURE:\n{render_menu(candidates)}\n\n"
        f"QUESTION: {q[:MAX_QUESTION_CHARS]}"
    )
    limit = float(timeout_s or _setting("SEMANTIC_CONCEPT_TIMEOUT_S", 8.0) or 8.0)
    try:
        raw = await asyncio.wait_for(
            _client().generate(prompt, system_message=SYSTEM, temperature=0, task_type=_task_type()),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        ACTED["error"] += 1
        return SemanticMatch(skipped=f"error: timed out after {limit:g}s")
    except Exception as exc:
        ACTED["error"] += 1
        return SemanticMatch(skipped=f"error: {type(exc).__name__}")

    out = parse_choice(raw, ids)
    out.candidates_offered = len(candidates)
    if out.matched:
        by_id = {c["id"]: c for c in candidates}
        # EVERY chosen concept is confirmed on its own. A question naming two conditions can have
        # one of them right and the other a near miss, and keeping the pair together would either
        # lose the good half or admit the bad one.
        kept = [cid for cid in out.concept_ids if await confirm(q, by_id[cid], limit)]
        if not kept:
            ACTED["rejected"] += 1
            logger.info("[semantic_concept] %r -> %s REJECTED at confirm",
                        q[:60], ",".join(out.concept_ids))
            out = SemanticMatch(
                reason=f"{out.concept_id} is a different quantity from the one asked about",
                candidates_offered=len(candidates),
            )
            if cache_set is not None:
                try:
                    await cache_set(key, NONE)
                except Exception:
                    pass
            return out
        if len(kept) < len(out.concept_ids):
            logger.info("[semantic_concept] %r kept %s, dropped %s at confirm",
                        q[:50], kept, [c for c in out.concept_ids if c not in kept])
        out.concept_ids = kept
        out.concept_id = kept[0]
        classes: List[str] = []
        for cid in kept:
            for k in by_id[cid]["brick_classes"]:
                if k not in classes:
                    classes.append(k)
        out.brick_classes = classes
        ACTED["matched"] += 1
        logger.info("[semantic_concept] %r -> %s (%s)",
                    q[:60], ",".join(out.concept_ids), out.reason[:60])
    elif not out.skipped:
        ACTED["none"] += 1
    else:
        ACTED["error"] += 1

    if cache_set is not None and not out.skipped:
        try:
            await cache_set(key, ",".join(out.concept_ids) or NONE)
        except Exception:
            pass
    return out
