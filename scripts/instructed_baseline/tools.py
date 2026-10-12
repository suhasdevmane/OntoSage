"""Seven retrieval tools for the instructed comparison assistant (spec §3).

Each tool wraps a service OntoSage itself uses, so the comparison assistant can reach the same data
(requirement R2). What the tools deliberately do NOT do is apply OntoSage's evidential checks: no
referent gate on their output, no claim binding, no relevance gate, no typed absence wording. Those
checks are what the comparison measures.

Rules every tool follows: return data, never prose; say explicitly when nothing matched; keep
"not found" apart from "error"; truncate long results to a fixed budget and say so.

Building-agnostic (R7): the namespace, building id and timezone come from the same settings as
OntoSage. External services are injected so the tools can be unit-tested with fakes.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

RESULT_BUDGET = 6000  # characters of JSON per tool result shown to the model
ROW_LIMIT = 400000  # per query (a month of 10-second readings is ~270k); hitting it is reported, never silent

TOOL_CATALOGUE = """Tools (call one per step by naming it in "action" and giving "arguments"):
- resolve_terms {"text": str}: building concepts and sensor classes that lay words map to.
- find_spaces {"name_or_kind": str}: rooms, zones and floors whose name or id contains the text, with the
  facts the building model records about each (type, floor, capacity and other properties).
- find_points {"place": str, "quantity": str}: sensor points measuring a quantity in a place, with their
  timeseries ids ("uuid") and stores ("stored_at"); lists the other points in the place when none match.
- get_readings {"points": [{"uuid": str, "stored_at": str}], "start": "YYYY-MM-DDTHH:MM", "end": "YYYY-MM-DDTHH:MM"}:
  readings between start and end in the building's LOCAL time: per point n, first/last time, min/mean/max,
  largest gap, and how many of the points asked had any data.
- query_records {"register": str, "contains": str (optional)}: rows of a building register (bookings,
  maintenance, schedules, inspections, ...); with no match, the list of registers the building holds.
- search_documents {"query": str}: passages from the building's uploaded documents, with document names.
- find_amenities_or_topics {"text": str}: facilities and knowledge topics the building describes.
- final_answer: give the answer to the person in "answer"."""

TOOL_NAMES = (
    "resolve_terms",
    "find_spaces",
    "find_points",
    "get_readings",
    "query_records",
    "search_documents",
    "find_amenities_or_topics",
)

#: Space classes only, matched on the class LOCAL NAME so "WorkspaceProfile" or a "Zone_Air_..._Sensor" never pass.
SPACE_TYPE_RE = r"[#/](Room|Space|Floor|HVAC_Zone|Zone|Office|Laboratory|Restroom|Lounge|Kitchen|Lobby|Corridor|Atrium|Hall|[A-Za-z_]*_Room)$"


def compact(result: Dict[str, Any], budget: int = RESULT_BUDGET) -> str:
    """JSON for the model, cut to the budget with the cut stated."""
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= budget:
        return text
    return text[:budget] + f" ... [TRUNCATED: {len(text) - budget} more characters not shown]"


def _lit(text: str) -> str:
    """A safe SPARQL string literal body (the model's text never reaches SPARQL unescaped)."""
    return re.sub(r'[\\"\n\r]', " ", str(text or ""))[:120]


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _bindings(res: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {k: v.get("value", "") for k, v in row.items()}
        for row in (res or {}).get("results", {}).get("bindings", [])
    ]


class Toolbox:
    """The tools, bound to one building. Inject fakes for tests; leave None for live wiring."""

    def __init__(
        self,
        sparql: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
        adapter_getter: Optional[Callable[[str], Any]] = None,
        concept_resolve: Optional[Callable[[str], Awaitable[List[Any]]]] = None,
        capability_resolve: Optional[Callable[[str], Awaitable[List[Any]]]] = None,
        document_search: Optional[Callable[[str], Awaitable[List[Dict[str, Any]]]]] = None,
        record_classes: Optional[Callable[[], Awaitable[List[Any]]]] = None,
        bind: Optional[Callable[..., Awaitable[Any]]] = None,
        namespace: str = "",
        building_id: str = "",
        tz: str = "Europe/London",
    ) -> None:
        self._sparql, self._adapter_getter = sparql, adapter_getter
        self._concepts, self._capabilities, self._documents = (
            concept_resolve,
            capability_resolve,
            document_search,
        )
        self._record_classes, self._bind = record_classes, bind
        self.namespace, self.building_id, self.tz = namespace, building_id, tz

    # ------------------------------------------------------------------ live wiring
    @classmethod
    async def live(cls) -> "Toolbox":
        """The same services, settings and building as the running OntoSage (inside its container)."""
        from orchestrator.services.adapters.registry import adapter_registry
        from orchestrator.services.capability_graph_resolver import get_capability_graph_resolver
        from orchestrator.services.concept_resolver import concept_resolver
        from orchestrator.services.deliberation.live import sparql_exec
        from orchestrator.services.record_registry import record_classes
        from orchestrator.services.sensor_binder import bind_sensors
        from shared.config import settings

        doc_fn: Optional[Callable[[str], Awaitable[List[Dict[str, Any]]]]] = None
        try:
            from qdrant_client import AsyncQdrantClient

            from orchestrator.services.document_indexer import search_documents
            from orchestrator.services.embedding_service import EmbeddingService

            qdrant = AsyncQdrantClient(url=settings.QDRANT_URL)
            embed = EmbeddingService(
                redis_manager=None, cache_ttl_seconds=settings.EMBEDDING_CACHE_TTL_SECONDS
            )

            async def _doc_search(q: str) -> List[Dict[str, Any]]:
                return await search_documents(qdrant, embed, q, settings.BUILDING_ID, top_k=4)

            doc_fn = _doc_search
        except Exception:  # noqa: BLE001 - the tool then reports itself unavailable
            doc_fn = None

        await adapter_registry.initialize()  # startup does this for the orchestrator; a fresh process must
        resolver = get_capability_graph_resolver()
        return cls(
            sparql=sparql_exec,
            adapter_getter=adapter_registry.get,
            concept_resolve=concept_resolver.resolve,
            capability_resolve=resolver.resolve,
            document_search=doc_fn,
            record_classes=record_classes,
            bind=bind_sensors,
            namespace=str(settings.BUILDING_NAMESPACE or ""),
            building_id=str(settings.BUILDING_ID or ""),
            tz=str(getattr(settings, "BUILDING_TIMEZONE", "") or "Europe/London"),
        )

    async def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run one tool. Errors come back as data (``{"error": ...}``), never raised."""
        if name not in TOOL_NAMES:
            return {"error": f"unknown tool '{name}'", "tools": list(TOOL_NAMES)}
        try:
            return await getattr(self, name)(**(arguments or {}))
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - a failed lookup is reported, not fatal
            return {"error": f"{name} failed: {type(exc).__name__}: {str(exc)[:200]}"}

    # ------------------------------------------------------------------ tools
    async def resolve_terms(self, text: str) -> Dict[str, Any]:
        matches = await self._concepts(text) if self._concepts else []
        rows = [
            {
                "concept": getattr(m, "concept_id", ""),
                "lay_term": getattr(m, "lay_term", ""),
                "classes": [_local(c) for c in getattr(m, "brick_classes", [])],
            }
            for m in matches
        ]
        return (
            {"matches": rows}
            if rows
            else {"matches": [], "note": f"no building concept matches '{text}'"}
        )

    async def find_spaces(self, name_or_kind: str) -> Dict[str, Any]:
        q = _lit(name_or_kind).lower()
        ns = _lit(self.namespace)
        query = f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?s ?label ?type WHERE {{
  ?s a ?type . OPTIONAL {{ ?s rdfs:label ?label }}
  FILTER(STRSTARTS(STR(?s), "{ns}"))
  FILTER(REGEX(STR(?type), "{SPACE_TYPE_RE}", "i"))
  FILTER(CONTAINS(LCASE(STR(?label)), "{q}") || CONTAINS(LCASE(STR(?s)), "{q.replace(' ', '')}"))
}} LIMIT 200"""
        rows = _bindings(await self._sparql(query))
        spaces: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            s = spaces.setdefault(
                r["s"], {"id": _local(r["s"]), "label": r.get("label", ""), "types": set()}
            )
            s["types"].add(_local(r.get("type", "")))
        if not spaces:
            return {
                "spaces": [],
                "note": f"no room, zone or floor in the building model matches '{name_or_kind}'",
            }
        out = []
        for iri, s in list(spaces.items())[:12]:
            facts = await self._facts(iri)
            out.append({"id": s["id"], "label": s["label"], "types": sorted(s["types"]), **facts})
        return {"spaces": out, "matched": len(spaces), "shown": len(out)}

    async def _facts(self, iri: str) -> Dict[str, Any]:
        """Literal properties of a space and what it is part of (floor, zone)."""
        query = f"""SELECT ?p ?o WHERE {{ <{iri}> ?p ?o . }} LIMIT 200"""
        props: Dict[str, List[str]] = {}
        for r in _bindings(await self._sparql(query)):
            key = _local(r["p"])
            if key in ("type", "label"):
                continue
            val = _local(r["o"]) if r["o"].startswith("http") else r["o"]
            props.setdefault(key, [])
            if val not in props[key] and len(props[key]) < 5:
                props[key].append(val[:160])
        return {"properties": {k: (v[0] if len(v) == 1 else v) for k, v in props.items()}}

    async def find_points(self, place: str, quantity: str) -> Dict[str, Any]:
        """EVERY point in the place (and the HVAC zone it belongs to) whose class or label matches the
        quantity, plus OntoSage's own binder selection marked as such. Listing all of them matters:
        a room can carry several series for one quantity (a real zone sensor and a generated room
        series, for example) with data in different periods; showing only one would turn a period
        the other covers into a false absence for the comparison assistant."""
        concepts = await self._concepts(quantity) if self._concepts else []
        concept_dicts = [m.to_dict() if hasattr(m, "to_dict") else m for m in concepts]
        classes = {_local(c).lower() for m in concepts for c in getattr(m, "brick_classes", [])}
        words = [w for w in re.findall(r"[a-z0-9]+", quantity.lower()) if len(w) > 1]
        in_place = await self._points_in(place)
        matching = [
            p
            for p in in_place
            if any(c.lower() in classes for c in p["classes"])
            or any(w in (p["label"] + " " + " ".join(p["classes"])).lower() for w in words)
        ]
        binder_pick: List[str] = []
        reason = ""
        if self._bind:
            b = await self._bind(
                f"{quantity} in {place}",
                [place],
                concept_dicts,
                self._sparql,
                self.namespace,
                self.building_id or None,
            )
            reason = getattr(b, "reason", "")
            binder_pick = [s.uuid for s in (getattr(b, "sensors", []) or [])]
            known = {p["uuid"] for p in matching}
            for s in getattr(b, "sensors", []) or []:
                if s.uuid not in known:
                    matching.append(
                        {
                            "point": _local(s.iri),
                            "label": s.label,
                            "classes": [_local(s.type_iri or "")],
                            "uuid": s.uuid,
                            "stored_at": _local(s.storage or ""),
                        }
                    )
        for p in matching:
            p["binder_selected"] = p["uuid"] in binder_pick
        for p in matching[:12]:
            # each series' own coverage, so a period one series lacks is not read as an absence
            p["series"] = await self._series_range(p.get("uuid", ""), p.get("stored_at", ""))
        if matching:
            return {
                "place": place,
                "quantity": quantity,
                "points": matching[:40],
                "count": len(matching),
            }
        return {
            "place": place,
            "quantity": quantity,
            "points": [],
            "note": f"no point measuring '{quantity}' found in '{place}'"
            + (f" (binder: {reason})" if reason else ""),
            "points_in_place": in_place[:40],
            "points_in_place_total": len(in_place),
        }

    async def _series_range(self, uuid: str, store: str) -> Dict[str, Any]:
        """First and last reading (building local time) and row count of one series; {} if unknown."""
        if (
            not re.fullmatch(r"[0-9a-fA-F-]{8,64}", uuid or "")
            or not store
            or not self._adapter_getter
        ):
            return {}
        adapter = self._adapter_getter(store)
        if adapter is None or not hasattr(adapter, "execute_query"):
            return {}
        table = getattr(adapter, "table", None)
        if table:
            sql = f"SELECT MIN(`datetime`) AS first_ts, MAX(`datetime`) AS last_ts, COUNT(*) AS n FROM `{table}` WHERE `uuid` = '{uuid}'"
        else:
            built = (
                adapter.build_timeseries_query(
                    [uuid], "datetime", "2000-01-01 00:00:00", "2100-01-01 00:00:00", limit=1
                )
                if hasattr(adapter, "build_timeseries_query")
                else None
            )
            m_tab = re.search(r"FROM\s+`([^`]+)`", built or "")
            m_ts = re.search(r"`(\w*[Dd]ate\w*|\w*time\w*)`\s+AS\s+`?timestamp", built or "", re.I)
            if not m_tab:
                return {}
            ts = m_ts.group(1) if m_ts else "Datetime"
            sql = (
                f"SELECT MIN(`{ts}`) AS first_ts, MAX(`{ts}`) AS last_ts, COUNT(`{uuid}`) AS n "
                f"FROM `{m_tab.group(1)}` WHERE `{uuid}` IS NOT NULL"
            )
        res = await adapter.execute_query(sql)
        rows = getattr(res, "data", None) or []
        if not getattr(res, "success", False) or not rows or not rows[0].get("n"):
            return {"n": 0}
        r = rows[0]
        return {
            "first": self._to_local(r["first_ts"]),
            "last": self._to_local(r["last_ts"]),
            "n": int(r["n"]),
        }

    async def _store_for(self, uuid: str) -> str:
        """The ref:storedAt key of a timeseries id, read from the graph."""
        u = _lit(uuid)
        query = f"""SELECT ?store WHERE {{ ?r ?ip "{u}" . FILTER(STRENDS(STR(?ip), "hasTimeseriesId"))
  ?r ?sp ?store . FILTER(STRENDS(STR(?sp), "storedAt")) }} LIMIT 1"""
        rows = _bindings(await self._sparql(query))
        return _local(rows[0]["store"]) if rows else ""

    async def _points_in(self, place: str) -> List[Dict[str, Any]]:
        spaces = (await self.find_spaces(place)).get("spaces", [])
        if not spaces:
            return []
        iri = self.namespace + spaces[0]["id"] if self.namespace else spaces[0]["id"]
        query = f"""PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?p ?label ?type ?uuid ?store WHERE {{
  {{ ?p ?loc <{iri}> . FILTER(STRENDS(STR(?loc), "hasLocation") || STRENDS(STR(?loc), "isPointOf")) }}
  UNION {{ <{iri}> ?part ?z . FILTER(STRENDS(STR(?part), "isPartOf")) ?z a ?zt . FILTER(STRENDS(STR(?zt), "HVAC_Zone"))
          ?p ?loc ?z . FILTER(STRENDS(STR(?loc), "hasLocation") || STRENDS(STR(?loc), "isPointOf")) }}
  UNION {{ ?z ?has <{iri}> . FILTER(STRENDS(STR(?has), "hasPart")) ?z a ?zt . FILTER(STRENDS(STR(?zt), "HVAC_Zone"))
          ?p ?loc ?z . FILTER(STRENDS(STR(?loc), "hasLocation") || STRENDS(STR(?loc), "isPointOf")) }}
  ?p a ?type . OPTIONAL {{ ?p rdfs:label ?label }}
  OPTIONAL {{ ?p ?rp ?r . FILTER(STRENDS(STR(?rp), "hasExternalReference"))
             ?r ?ip ?uuid . FILTER(STRENDS(STR(?ip), "hasTimeseriesId"))
             OPTIONAL {{ ?r ?sp ?store . FILTER(STRENDS(STR(?sp), "storedAt")) }} }}
}} LIMIT 400"""
        seen: Dict[str, Dict[str, Any]] = {}
        for r in _bindings(await self._sparql(query)):
            p = seen.setdefault(
                r["p"],
                {
                    "point": _local(r["p"]),
                    "label": r.get("label", ""),
                    "classes": set(),
                    "uuid": r.get("uuid", ""),
                    "stored_at": _local(r.get("store", "")),
                },
            )
            if not str(r.get("type", "")).endswith(("NamedIndividual", "Class")):
                p["classes"].add(_local(r.get("type", "")))
        return [{**p, "classes": sorted(p["classes"])} for p in seen.values()]

    async def _series_of(self, point: str) -> tuple:
        """(timeseries id, store key) of a point named by its id, read from the graph."""
        iri = point if point.startswith("http") else self.namespace + _lit(point)
        query = f"""SELECT ?uuid ?store WHERE {{ <{iri}> ?rp ?r . FILTER(STRENDS(STR(?rp), "hasExternalReference"))
  ?r ?ip ?uuid . FILTER(STRENDS(STR(?ip), "hasTimeseriesId"))
  OPTIONAL {{ ?r ?sp ?store . FILTER(STRENDS(STR(?sp), "storedAt")) }} }} LIMIT 1"""
        rows = _bindings(await self._sparql(query))
        return (rows[0].get("uuid", ""), _local(rows[0].get("store", ""))) if rows else ("", "")

    def _to_utc(self, local: str) -> datetime:
        dt = datetime.fromisoformat(str(local).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(self.tz))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    def _to_local(self, utc: Any) -> str:
        try:
            dt = (
                utc
                if isinstance(utc, datetime)
                else datetime.fromisoformat(str(utc).replace(" ", "T"))
            )
            return (
                dt.replace(tzinfo=timezone.utc)
                .astimezone(ZoneInfo(self.tz))
                .strftime("%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            return str(utc)

    async def get_readings(
        self, points: List[Dict[str, str]], start: str, end: str
    ) -> Dict[str, Any]:
        if not points:
            return {"error": "no points given; call find_points first"}
        s_utc, e_utc = self._to_utc(start), self._to_utc(end)
        if e_utc <= s_utc:
            return {"error": "end must be after start"}
        by_store: Dict[str, List[str]] = {}
        notes: List[str] = []
        points = [dict(p) for p in points if isinstance(p, dict)]
        for p in points:
            if not p.get("uuid") and p.get("point"):
                p["uuid"], p["stored_at"] = await self._series_of(p["point"])
            if not p.get("uuid"):
                notes.append(
                    f"point {p.get('point') or p}: no timeseries id recorded in the building model"
                )
                continue
            store = p.get("stored_at") or await self._store_for(p["uuid"])
            if not store:
                notes.append(f"point {p['uuid']}: no store recorded in the building model")
                continue
            by_store.setdefault(store, []).append(p["uuid"])
        series: Dict[str, List[tuple]] = {}
        for store, uuids in by_store.items():
            adapter = self._adapter_getter(store) if self._adapter_getter else None
            if adapter is None or not hasattr(adapter, "build_timeseries_query"):
                notes.append(f"no reader for store '{store}' ({len(uuids)} points not read)")
                continue
            sql = adapter.build_timeseries_query(
                sorted(set(uuids)),
                "datetime",
                s_utc.strftime("%Y-%m-%d %H:%M:%S"),
                e_utc.strftime("%Y-%m-%d %H:%M:%S"),
                limit=ROW_LIMIT,
            )
            res = await adapter.execute_query(sql)
            if not getattr(res, "success", False):
                notes.append(
                    f"lookup failed for store '{store}': {str(getattr(res, 'error', ''))[:120]}"
                )
                continue
            for row in getattr(res, "data", None) or []:
                try:
                    series.setdefault(str(row.get("uuid", "")), []).append(
                        (str(row.get("timestamp", "")), float(row.get("value")))
                    )
                except (TypeError, ValueError):
                    continue
        out = []
        for p in points:
            rows = sorted(series.get(p.get("uuid", ""), []))
            if not rows:
                out.append(
                    {
                        "uuid": p.get("uuid"),
                        "n": 0,
                        "note": "no readings for this point in the window",
                    }
                )
                continue
            vals = [v for _, v in rows]
            stamps = [datetime.fromisoformat(t.replace(" ", "T")) for t, _ in rows if t]
            gaps = [(b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:])]
            out.append(
                {
                    "uuid": p.get("uuid"),
                    "n": len(vals),
                    "first": self._to_local(rows[0][0]),
                    "last": self._to_local(rows[-1][0]),
                    "min": round(min(vals), 3),
                    "mean": round(statistics.fmean(vals), 3),
                    "max": round(max(vals), 3),
                    "largest_gap_minutes": round(max(gaps), 1) if gaps else None,
                    "row_limit_hit": len(vals) >= ROW_LIMIT,
                }
            )
        with_data = sum(1 for r in out if r.get("n"))
        return {
            "window_local": [start, end],
            "timezone": self.tz,
            "points_asked": len(points),
            "points_with_data": with_data,
            "readings": out,
            "notes": notes,
        }

    async def query_records(self, register: str, contains: str = "") -> Dict[str, Any]:
        classes = await self._record_classes() if self._record_classes else []
        want = (register or "").lower().strip()
        picked = [
            c
            for c in classes
            if want
            and (
                want in c.local_name.lower()
                or want in (c.label or "").lower()
                or any(want in t.lower() or t.lower() in want for t in c.terms)
            )
        ]
        if not picked:
            return {
                "rows": [],
                "note": f"no register matches '{register}'",
                "registers_held": sorted({f"{c.local_name} ({c.instances})" for c in classes})[:80],
            }
        c = picked[0]
        query = f"""SELECT ?s ?p ?o WHERE {{ ?s a ?cls . FILTER(STRENDS(STR(?cls), "#{_lit(c.local_name)}") || STRENDS(STR(?cls), "/{_lit(c.local_name)}"))
  ?s ?p ?o . }} LIMIT 20000"""
        recs: Dict[str, Dict[str, Any]] = {}
        for r in _bindings(await self._sparql(query)):
            key = _local(r["p"])
            if key == "type":
                continue
            row = recs.setdefault(r["s"], {"id": _local(r["s"])})
            val = _local(r["o"]) if r["o"].startswith("http") else r["o"]
            row[key] = val[:200] if key not in row else row[key]
        rows = list(recs.values())
        if contains:
            needle = contains.lower()
            rows = [r for r in rows if any(needle in str(v).lower() for v in r.values())]
        return {
            "register": c.local_name,
            "label": c.label,
            "instances": c.instances,
            "matched": len(rows),
            "rows": rows[:40],
            "rows_shown": min(len(rows), 40),
            "other_matching_registers": [x.local_name for x in picked[1:6]],
        }

    async def search_documents(self, query: str) -> Dict[str, Any]:
        if self._documents is None:
            return {"error": "document search is not available"}
        hits = await self._documents(query)
        if not hits:
            return {"passages": [], "note": f"no document passage matches '{query}'"}
        return {
            "passages": [
                {
                    "document": h.get("doc_name", ""),
                    "score": round(float(h.get("score", 0)), 3),
                    "text": str(h.get("text", ""))[:700],
                }
                for h in hits
            ]
        }

    async def find_amenities_or_topics(self, text: str) -> Dict[str, Any]:
        facts = await self._capabilities(text) if self._capabilities else []
        rows = []
        for f in facts[:8]:
            d = asdict(f) if is_dataclass(f) else dict(f)
            rows.append({k: (str(v)[:400] if isinstance(v, str) else v) for k, v in d.items() if v})
        return (
            {"facts": rows}
            if rows
            else {"facts": [], "note": f"no facility or topic matches '{text}'"}
        )
