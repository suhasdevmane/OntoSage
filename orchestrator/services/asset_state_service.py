# -*- coding: utf-8 -*-
"""
asset_state_service.py — the service/asset-state lane (V6-T58 / V6-T60).

Answers "is the lift working?", "is the AV in the seminar rooms broken?", "is the wifi
up on floor 3?", "when was floor 2 last cleaned?" from the graph.

**Why this exists.** The provisioner had been writing ``ontosage:AssetStatus`` and
``ontosage:ServiceSchedule`` triples for weeks — 21 status records and 8 schedules on
this building, each with a value, an observation time and an assistance contact — and
NOTHING read them. Measured 2026-08-25: "are the lifts working?" answered "this building
does not have lift sensors" while the lift's status sat in the graph. That is the
described-but-unconnected failure in its third form: not a sensor without data, and not
a file nothing ingests, but *data nothing queries*.

**A service state is not a sensor reading**, and the distinction matters for honesty:

* It has a SOURCE that is a system of record (a lift controller, an AV helpdesk), so
  precedence treats it as authoritative rather than inferred.
* It has an OBSERVATION TIME, and a status observed four days ago is not a statement
  about now. The answer always says when it was seen.
* When something is out of service, the useful answer includes WHO TO CONTACT. An
  outage report with no route to help is a worse answer than it looks.

Deterministic end to end: the question kind is matched by rules, the values come from
SPARQL, and the narration is a template over those values — so everything the prose says
exists in the payload and the numeric guard has nothing to object to.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

_ONTOSAGE = "http://ontosage.org/capabilities#"

#: Asset families this lane can speak about, as (kind, ontosage class local name,
#: question pattern, plural noun). The CLASS is the discriminator, never a name
#: heuristic — a building that types its assets gets answers; one that does not gets an
#: honest decline naming what to add.
_FAMILIES: List[Tuple[str, str, re.Pattern, str]] = [
    (
        "lift",
        "Lift",
        re.compile(r"\blifts?\b|\belevators?\b", re.IGNORECASE),
        "lift",
    ),
    (
        "av",
        "AVEquipment",
        re.compile(
            r"\bav\b|\baudio[- ]?visual\b|\bprojectors?\b|\bscreens?\b"
            r"|\bteaching equipment\b|\bdisplay\b",
            re.IGNORECASE,
        ),
        "AV unit",
    ),
    (
        "network",
        "NetworkService",
        re.compile(r"\bwi[- ]?fi\b|\bwifi\b|\bnetwork\b|\binternet\b|\beduroam\b", re.IGNORECASE),
        "network service",
    ),
]

#: Words that make a question about STATE rather than about existence or location.
#: "where is the lift" is wayfinding; "is the lift working" is this lane.
_STATE_RE = re.compile(
    r"\b(?:working|work|operational|out of (?:service|order)|broken|down|up|running"
    r"|available|status|faults?|failed|usable|in service|functioning)\b",
    re.IGNORECASE,
)

#: Cleaning-schedule questions. Deliberately NARROW — restricted to the cleaning
#: vocabulary this lane actually holds ServiceSchedule rows for.
#:
#: The first version also claimed "serviced" and "maintenance", which took
#: "when was chiller 7 last serviced?" from the capability/register lanes and
#: "scheduled maintenance" from the maintenance route. Equipment service history and
#: dated compliance checks are OTHER lanes' data; matching their vocabulary here would
#: answer from schedules that say nothing about a chiller. A lane should claim only the
#: questions its own data can answer.
_SCHEDULE_RE = re.compile(
    r"\bclean(?:ed|ing|er|ers)?\b|\bcleaning schedule\b",
    re.IGNORECASE,
)

#: Closure / planned-shutdown questions. A closure is a SCHEDULED state change, so it
#: belongs with schedules rather than with the maintenance-intake lane — where it was
#: going, and where "are there any planned closures coming up?" was FILED AS A TICKET
#: instead of answered (measured 2026-08-25).
_CLOSURE_RE = re.compile(
    r"\bclosures?\b|\bclosed\b.{0,30}\b(?:for|due|because)\b"
    r"|\bshut(?:ting)?\s+(?:down|for)\b|\bplanned\s+(?:closure|shutdown)\b",
    re.IGNORECASE,
)

#: A status older than this is reported as a last-known state, never as "now". Same
#: principle as the sensor freshness gate: an old observation is still informative about
#: the past and must not be dressed up as the present.
STALE_AFTER_HOURS = 24.0


def classify_asset_question(question: str) -> Optional[str]:
    """'lift' | 'av' | 'network' | 'schedule' | 'closure' | None.

    None means this lane should not have been asked, and the caller must not invent an
    answer from it.
    """
    q = question or ""
    if not q.strip():
        return None
    if _CLOSURE_RE.search(q):
        return "closure"
    if _SCHEDULE_RE.search(q):
        return "schedule"
    if not _STATE_RE.search(q):
        return None
    for kind, _cls, pattern, _noun in _FAMILIES:
        if pattern.search(q):
            return kind
    return None


def is_asset_state_question(question: str) -> bool:
    """True when this lane can speak to the question."""
    return classify_asset_question(question) is not None


def _age_hours(observed: str, now: datetime) -> Optional[float]:
    """Hours since an ISO timestamp, or None when it cannot be read.

    None is returned rather than a default, because a guessed age would let a stale
    reading be presented as current — which is the one thing this field exists to stop.
    """
    if not observed:
        return None
    try:
        text = observed.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (now - parsed).total_seconds() / 3600.0
    except Exception:
        return None


def _local(iri: str) -> str:
    s = str(iri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def _human_age(hours: Optional[float]) -> str:
    if hours is None:
        return "at an unknown time"
    if hours < 1:
        return f"{round(hours * 60)} minutes ago"
    if hours < 48:
        return f"{round(hours)} hours ago"
    return f"{round(hours / 24)} days ago"


def _named_location(question: str, known: List[str]) -> str:
    """The location from ``known`` that the question actually names, or "".

    Matched against the building's OWN local names rather than a vocabulary of floor
    words, so a building that calls its levels something else still resolves. Longest
    match wins: "Floor10" must not be claimed by "Floor1".
    """
    q = (question or "").lower().replace(" ", "")
    best = ""
    for name in known:
        token = (name or "").lower().replace(" ", "").replace("_", "")
        if token and token in q and len(token) > len(best):
            best = name
    return best


class AssetStateService:
    """Answers asset/service-state questions. `sparql_exec` is injected (testable)."""

    def __init__(self, sparql_exec: Callable, namespace: str, events_adapter=None):
        self._sparql = sparql_exec
        self._ns = namespace
        # OPTIONAL on purpose. Where an events store exists, OUTAGE EPISODES are the
        # authority on what is broken right now; where it does not, the graph's status
        # triple is still answered from, so a building that has only the static form
        # keeps working. The adapter is injected rather than constructed so the lane
        # stays unit-testable without a database.
        self._events = events_adapter

    async def _select(self, query: str) -> List[Dict[str, str]]:
        try:
            res = await self._sparql(query)
        except Exception as exc:
            logger.warning(f"[asset_state] query failed: {exc}")
            return []
        return [
            {k: v.get("value", "") for k, v in b.items()}
            for b in (res or {}).get("results", {}).get("bindings", [])
        ]

    # ── queries ──────────────────────────────────────────────────────────────
    def _status_query(self, class_local: str) -> str:
        """Latest status per asset of one class.

        GROUP BY the asset with SAMPLE over the rest: an asset carrying two status
        records would otherwise fan out into two rows and be counted twice — the same
        label fan-out that once reported fourteen floors in a six-storey building.
        """
        return (
            f"PREFIX ontosage: <{_ONTOSAGE}>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?asset (SAMPLE(?lab) AS ?label) (SAMPLE(?v) AS ?value)\n"
            "       (MAX(?t) AS ?observed) (SAMPLE(?src) AS ?source)\n"
            "       (SAMPLE(?contact) AS ?contact) (SAMPLE(?sim) AS ?simulated) WHERE {\n"
            f"  ?asset a ontosage:{class_local} .\n"
            "  ?st ontosage:statusOf ?asset ;\n"
            "      ontosage:statusValue ?v .\n"
            "  OPTIONAL { ?st ontosage:statusObservedAt ?t }\n"
            "  OPTIONAL { ?st ontosage:statusSource ?src }\n"
            "  OPTIONAL { ?st ontosage:assistanceContact ?contact }\n"
            "  OPTIONAL { ?st ontosage:isSimulated ?sim }\n"
            "  OPTIONAL { ?asset rdfs:label ?lab }\n"
            f'  FILTER(STRSTARTS(STR(?asset), "{self._ns}"))\n'
            "} GROUP BY ?asset"
        )

    def _schedule_query(self) -> str:
        return (
            f"PREFIX ontosage: <{_ONTOSAGE}>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?s (SAMPLE(?loc) AS ?location) (SAMPLE(?k) AS ?kind)\n"
            "       (SAMPLE(?from) AS ?starts) (SAMPLE(?to) AS ?ends)\n"
            "       (SAMPLE(?sim) AS ?simulated) WHERE {\n"
            "  ?s a ontosage:ServiceSchedule .\n"
            "  OPTIONAL { ?s ontosage:appliesTo ?loc }\n"
            "  OPTIONAL { ?s ontosage:scheduleKind ?k }\n"
            "  OPTIONAL { ?s ontosage:startedAt ?from }\n"
            "  OPTIONAL { ?s ontosage:endedAt ?to }\n"
            "  OPTIONAL { ?s ontosage:isSimulated ?sim }\n"
            "} GROUP BY ?s"
        )

    def _closure_query(self) -> str:
        return (
            f"PREFIX ontosage: <{_ONTOSAGE}>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "SELECT ?c (SAMPLE(?lab) AS ?label) (SAMPLE(?loc) AS ?location)\n"
            "       (SAMPLE(?why) AS ?reason) (SAMPLE(?from) AS ?starts)\n"
            "       (SAMPLE(?to) AS ?ends) (SAMPLE(?sim) AS ?simulated) WHERE {\n"
            "  ?c a ontosage:ClosurePeriod .\n"
            "  OPTIONAL { ?c rdfs:label ?lab }\n"
            "  OPTIONAL { ?c ontosage:appliesTo ?loc }\n"
            "  OPTIONAL { ?c ontosage:closureReason ?why }\n"
            "  OPTIONAL { ?c ontosage:startedAt ?from }\n"
            "  OPTIONAL { ?c ontosage:endedAt ?to }\n"
            "  OPTIONAL { ?c ontosage:isSimulated ?sim }\n"
            "} GROUP BY ?c"
        )

    async def _open_outages(self, building_id: str, assets: List[str]) -> Dict[str, Dict]:
        """{asset_local: episode} for outages in progress right now.

        A STATUS IS NOT A FACT. It is the current value of something that changes, and
        the provisioner wrote it as a fact — one status per asset, stamped once at
        provisioning time and never updated. Every answer on this building was therefore
        five days stale, the freshness caveat fired on all of them (so it stopped
        carrying information), and nothing had ever broken or been fixed. Episodes are
        the fix: the graph says what an asset IS, the event store says what is happening
        to it.
        """
        if self._events is None or not assets:
            return {}
        try:
            from orchestrator.services.deliberation.synthetic_events import subject_uuid

            by_uuid = {subject_uuid(building_id, a): a for a in assets}
            sql = self._events.build_active_now("asset_outage", subject_uuids=list(by_uuid))
            if not sql:
                return {}
            result = await self._events.execute_query(sql)
            # execute_query returns a RESULT OBJECT, not rows. The events lane unwraps
            # it the same way; treating the wrapper as a sequence yields nothing and
            # would have looked exactly like "no outages".
            rows = getattr(result, "rows", None) or getattr(result, "data", None) or []
        except Exception as exc:
            logger.debug(f"[asset_state] outage episodes unavailable: {exc}")
            return {}

        import json as _json

        def _col(row, idx, name):
            """By name for a live DictCursor, by position for tuple fixtures."""
            if isinstance(row, dict):
                return row.get(name)
            return row[idx]

        out: Dict[str, Dict] = {}
        for r in rows or []:
            try:
                subj = _col(r, 2, "subject_uuid")
                start = _col(r, 3, "start_dt")
                attrs_raw = _col(r, 6, "attrs")
            except Exception:
                continue
            local = by_uuid.get(str(subj))
            if not local:
                continue
            reason = ""
            try:
                reason = (_json.loads(attrs_raw) or {}).get("reason", "") if attrs_raw else ""
            except Exception:
                reason = ""
            out[local] = {"since": start, "reason": reason}
        return out

    # ── answers ──────────────────────────────────────────────────────────────
    def _decline(self, what: str, add: str) -> Dict[str, Any]:
        """An honest decline that names the unlock path, never an empty guess."""
        return {
            "success": False,
            "kind": "asset_state",
            "formatted_response": (
                f"This building has no {what} recorded in its model, so I can't tell you "
                f"its state. {add}"
            ),
        }

    async def _answer_status(self, kind: str, question: str, now: datetime) -> Dict[str, Any]:
        family = next((f for f in _FAMILIES if f[0] == kind), None)
        if family is None:
            return self._decline("assets of that kind", "")
        _k, class_local, _pat, noun = family
        rows = await self._select(self._status_query(class_local))
        if not rows:
            return self._decline(
                f"{noun}s",
                "Describe them in the ontology with a status source and this becomes "
                "answerable with no code change.",
            )

        # Episodes OUTRANK the graph's status triple. The triple records what was true
        # when the asset was described; an open outage records what is true now, and
        # where the two disagree the live one wins.
        from shared.config import settings as _settings

        open_outages = await self._open_outages(
            getattr(_settings, "BUILDING_ID", ""), [_local(r.get("asset", "")) for r in rows]
        )

        working, broken = [], []
        oldest: Optional[float] = None
        simulated = False
        for r in rows:
            local = _local(r.get("asset", ""))
            value = (r.get("value") or "").strip()
            age = _age_hours(r.get("observed", ""), now)
            episode = open_outages.get(local)
            if episode is not None:
                value = "out_of_service"
                # The age that matters is how long it has been BROKEN, not when the
                # description was written.
                ep_age = _age_hours(str(episode.get("since") or ""), now)
                age = ep_age if ep_age is not None else age
            if age is not None:
                oldest = age if oldest is None else max(oldest, age)
            if str(r.get("simulated", "")).lower() in ("true", "1"):
                simulated = True
            entry = {
                "asset": local,
                "label": r.get("label", ""),
                "status": value,
                "observed_hours_ago": None if age is None else round(age, 1),
                "source": r.get("source", ""),
                "contact": r.get("contact", ""),
                "reason": (episode or {}).get("reason", ""),
                "live_episode": episode is not None,
            }
            (working if value.lower() in ("operational", "ok", "up", "normal") else broken).append(
                entry
            )

        total = len(rows)
        # "last checked" is right for a status someone observed; for an OPEN episode the
        # same number means how long it has been BROKEN, and calling that a check reads
        # as though nobody has looked since.
        live = any(e.get("live_episode") for e in broken)
        age_phrase = "out of service since" if live else "last checked"
        rendered_age = _human_age(oldest)
        if not broken:
            text = f"**All {total} {noun}(s) are operational** " f"({age_phrase} {rendered_age})."
        else:
            names = ", ".join(
                (e["label"] or e["asset"]) + (f" ({e['reason']})" if e.get("reason") else "")
                for e in broken[:4]
            )
            text = (
                f"**{len(broken)} of {total} {noun}(s) are not operational**: {names}"
                f" ({age_phrase} {rendered_age})."
            )
            contact = next((e["contact"] for e in broken if e["contact"]), "")
            if contact:
                # An outage report with no route to help is a worse answer than it looks.
                text += f" Report or chase it with: {contact}."
        # The staleness caveat is about not having looked recently. An OPEN episode is
        # current knowledge — the outage is happening now and the age says how long it
        # has been going on — so firing the caveat there contradicts the sentence above
        # it: "out of service since 47 hours ago" followed by "this is not a live state"
        # tells the reader two different things about the same fact.
        if not live and oldest is not None and oldest > STALE_AFTER_HOURS:
            text += (
                f" *This is the last KNOWN state, not a live one — the most recent check "
                f"was {rendered_age}.*"
            )
        if simulated:
            text += " *Source: simulated service feed.*"

        return {
            "success": True,
            "kind": f"asset_state:{kind}",
            "total": total,
            "operational": len(working),
            "not_operational": len(broken),
            "assets": working + broken,
            "oldest_observation_hours": None if oldest is None else round(oldest, 1),
            # The RENDERED age travels with the answer. _human_age rounds hours into
            # days for display ("15 days ago"), and 15 appears nowhere else in the
            # payload — so the numeric guard correctly suppressed a correct answer for
            # a figure computed only for the prose. Same shape as the bookings_list
            # defect: the guard was right and the payload was thin.
            "last_observation_phrase": rendered_age,
            "simulated": simulated,
            "formatted_response": text,
        }

    async def _answer_schedule(self, question: str, now: datetime) -> Dict[str, Any]:
        rows = await self._select(self._schedule_query())
        if not rows:
            return self._decline(
                "cleaning or service schedules",
                "Add them as ontosage:ServiceSchedule entries and this becomes answerable.",
            )
        simulated = any(str(r.get("simulated", "")).lower() in ("true", "1") for r in rows)
        listed = [
            {
                "location": _local(r.get("location", "")) or "the building",
                "kind": r.get("kind", "service"),
                "starts": r.get("starts", ""),
                "ends": r.get("ends", ""),
            }
            for r in rows
        ]

        # HONOUR THE NAMED PLACE. "When was the last cleaning of floor 2?" listed every
        # floor's schedule and left the reader to find theirs -- the question named a
        # referent and the answer ignored it. Filtering on the location's own local name
        # keeps this building-agnostic: whatever the building calls its floors is what
        # the questioner will type.
        named = _named_location(question, [e["location"] for e in listed])
        scoped = [e for e in listed if e["location"] == named] if named else listed
        # NOTE: there is deliberately no 'named a place with no schedule' branch here.
        # `named` is derived from the scheduled locations themselves, so a non-empty
        # match always has rows -- a branch for the empty case would be unreachable.
        # Answering 'floor 9 has no cleaning schedule' needs the building's SPACE list,
        # not this query's result set, and that belongs with the referent gate rather
        # than here. Until then an unmatched place falls back to the full list.
        listed = scoped
        head = (
            f"**{len(listed)} service schedule(s) for {named}**"
            if named
            else f"**{len(listed)} service schedule(s) on record**"
        )
        lines = [
            f"- {e['location']}: {e['kind']}" + (f" from {e['starts'][:16]}" if e["starts"] else "")
            for e in listed[:8]
        ]
        text = head + ":\n" + "\n".join(lines)
        if simulated:
            text += "\n\n*Source: simulated service feed.*"
        return {
            "success": True,
            "kind": "asset_state:schedule",
            "count": len(listed),
            "schedules": listed,
            "simulated": simulated,
            "formatted_response": text,
        }

    async def _answer_closure(self, question: str, now: datetime) -> Dict[str, Any]:
        rows = await self._select(self._closure_query())
        if not rows:
            return {
                "success": True,
                "kind": "asset_state:closure",
                "count": 0,
                "closures": [],
                "formatted_response": (
                    "**No planned closures are recorded** for this building. That means none "
                    "are in the model — it is not a guarantee that none are planned."
                ),
            }
        simulated = any(str(r.get("simulated", "")).lower() in ("true", "1") for r in rows)
        listed = [
            {
                "label": r.get("label", "") or _local(r.get("c", "")),
                "location": _local(r.get("location", "")) or "the building",
                "reason": r.get("reason", ""),
                "starts": (r.get("starts", "") or "")[:16],
                "ends": (r.get("ends", "") or "")[:16],
            }
            for r in rows
        ]
        listed.sort(key=lambda e: e["starts"] or "9999")
        lines = [
            f"- {e['location']}: {e['reason'] or 'closed'}"
            + (f", from {e['starts']}" if e["starts"] else "")
            + (f" to {e['ends']}" if e["ends"] else "")
            for e in listed[:8]
        ]
        text = f"**{len(listed)} planned closure(s) on record**:\n" + "\n".join(lines)
        if simulated:
            text += "\n\n*Source: simulated estates feed.*"
        return {
            "success": True,
            "kind": "asset_state:closure",
            "count": len(listed),
            "closures": listed,
            "simulated": simulated,
            "formatted_response": text,
        }

    async def answer(self, question: str, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Answer an asset/service-state question. Never raises."""
        now = now or datetime.now(timezone.utc)
        kind = classify_asset_question(question)
        if kind is None:
            return {
                "success": False,
                "kind": "asset_state",
                "formatted_response": (
                    "I couldn't tell which service or asset you meant, so I'm not guessing."
                ),
            }
        if kind == "schedule":
            return await self._answer_schedule(question, now)
        if kind == "closure":
            return await self._answer_closure(question, now)
        return await self._answer_status(kind, question, now)


__all__ = [
    "AssetStateService",
    "unavailable_vertical_nodes",
    "classify_asset_question",
    "is_asset_state_question",
    "STALE_AFTER_HOURS",
]


async def unavailable_vertical_nodes(
    nodes: Any,
    building_id: str,
    namespace: str,
    sparql_exec: Callable,
    events_adapter=None,
) -> Dict[str, str]:
    """{zone_id: reason} for route nodes whose LIFT is currently out of service.

    A step-free route changes floors only by lift, so an out-of-service lift does not
    lengthen an accessible journey — it can remove the only one there is. Returning the
    route anyway, still labelled accessible, would send someone who cannot use stairs to
    a floor they cannot reach.

    The join is by LABEL, because the two sides come from different sources: lifts are
    ``ontosage:Lift`` entities in the graph, while route nodes come from the floor-plan
    manifests, and nothing links them structurally. Matching is deliberately strict —
    an exact label match, or the asset's label contained in the node's — so a lift is
    never confused with a neighbouring room. **A missed match leaves the route as it
    was**, which is the safer failure only because the alternative (matching loosely and
    blocking the wrong core) would strand people for no reason; a building that wants
    this guarantee should link the two explicitly.
    """
    try:
        service = AssetStateService(sparql_exec, namespace, events_adapter=events_adapter)
        rows = await service._select(service._status_query("Lift"))
        if not rows:
            return {}
        locals_ = [_local(r.get("asset", "")) for r in rows]
        open_outages = await service._open_outages(building_id, locals_)
        if not open_outages:
            return {}
        labels = {_local(r.get("asset", "")): (r.get("label") or "").strip().lower() for r in rows}
        blocked: Dict[str, str] = {}
        for node in getattr(nodes, "values", lambda: [])():
            node_label = (getattr(node, "label", "") or "").strip().lower()
            if not node_label:
                continue
            for asset_local, episode in open_outages.items():
                asset_label = labels.get(asset_local, "")
                if not asset_label:
                    continue
                if node_label == asset_label or asset_label in node_label:
                    blocked[getattr(node, "zone_id", "")] = (
                        episode.get("reason") or "out of service"
                    )
        return {k: v for k, v in blocked.items() if k}
    except Exception as exc:  # a lookup failure must never break routing
        logger.debug(f"[asset_state] vertical availability unavailable: {exc}")
        return {}
