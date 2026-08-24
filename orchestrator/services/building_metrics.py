"""Live building metrics — answer count/area questions from the graph, not frozen prose.

Every number this returns is computed at call time: sensor/point/zone counts from a live
SPARQL ``COUNT`` against GraphDB, floor areas from the DWG-derived floor-plan manifests.
Nothing is hardcoded, so a figure can never drift out of sync with the ontology the way a
literal in ``capability.yaml`` does.

Portability: scoped to the ACTIVE building's namespace (resolved from ``building_id``), so a
new building is measured from its own triples with no code change. Both the SPARQL executor
and the area provider are injectable, so the snapshot is unit-testable offline.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from shared.utils import get_logger

logger = get_logger(__name__)

# A building-WIDE inventory / size question. Deliberately narrow: it must name a
# building-scoped inventory noun (sensors/points/devices/cameras/meters) or a
# building-total-area phrase. Per-floor and per-room questions are excluded so they
# keep using the SPARQL/spatial paths that can scope to a floor.
_INVENTORY_RE = re.compile(
    r"(how many\s+(sensors?|points?|devices?|cameras?|meters?|floors?|rooms?)"
    r"|(sensor|point|device)\s+count"
    r"|number of\s+(sensors?|points?|devices?|cameras?|floors?|rooms?)"
    r"|total\s+(number of\s+)?(sensors?|points?|devices?|floors?|rooms?)"
    r"|how (big|large|tall) is the building"
    r"|how many floors"
    r"|total\s+(net\s+)?(internal\s+)?floor\s*area"
    r"|total\s+area\s+of\s+the\s+building)",
    re.IGNORECASE,
)
# A specific floor/zone/room scope → NOT building-wide; let the normal path handle it.
_FLOOR_SCOPE_RE = re.compile(r"(floor\s*\d|\bzone\b|\broom\b|\d{1,2}\.\d{1,2})", re.IGNORECASE)


def is_inventory_count_question(query: str) -> bool:
    """True for building-WIDE count/size questions that must be answered from a live
    SPARQL COUNT / DWG area (e.g. 'how many sensors are there?', 'total floor area').

    Excludes floor/zone/room-scoped questions ('how many sensors on floor 5', 'how many
    rooms on floor 3') — those keep the normal SPARQL/spatial routing so they can scope.
    """
    q = query or ""
    if not _INVENTORY_RE.search(q):
        return False
    if _FLOOR_SCOPE_RE.search(q):
        return False
    return True


SparqlExec = Callable[[str], Awaitable[dict]]
# (floor, area_m2, space_count) per floor
AreaProvider = Callable[[str], List[Tuple[int, float, int]]]

_RDFS = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
_BRICK = "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"

_CACHE_TTL_S = 300.0


@dataclass
class BuildingMetricsSnapshot:
    """A point-in-time, fully live view of the building's countable facts."""

    total_points: Optional[int] = None
    total_sensors: Optional[int] = None
    zone_count: Optional[int] = None
    floor_count: Optional[int] = None
    room_count: Optional[int] = None
    sensor_types: List[Tuple[str, int]] = field(default_factory=list)  # (class, count)
    total_area_m2: Optional[float] = None
    per_floor_area: List[Tuple[int, float, int]] = field(default_factory=list)
    # CAVEAT-007: declared-in-ontology vs actually-streaming are different facts.
    # reporting_sensors = DISTINCT declared sensors with at least one stored reading
    # inside the last `reporting_window_h` hours, checked live against every
    # registered time-series backend of the ACTIVE building. None = check unavailable.
    reporting_sensors: Optional[int] = None
    reporting_window_h: int = 24
    generated_at: float = 0.0

    def has_counts(self) -> bool:
        return self.total_points is not None or self.total_sensors is not None

    def has_area(self) -> bool:
        return self.total_area_m2 is not None


class BuildingMetrics:
    """Computes and briefly caches a live :class:`BuildingMetricsSnapshot`."""

    def __init__(
        self,
        sparql_exec: Optional[SparqlExec] = None,
        area_provider: Optional[AreaProvider] = None,
        reporting_provider: Optional[Callable[[int], Awaitable[Optional[int]]]] = None,
    ):
        self._exec = sparql_exec or _default_sparql_exec
        self._areas = area_provider or _default_area_provider
        self._reporting = reporting_provider or _default_reporting_provider
        self._cache: dict[str, BuildingMetricsSnapshot] = {}

    async def snapshot(
        self, building_id: str, namespace: Optional[str] = None
    ) -> BuildingMetricsSnapshot:
        """Return a live snapshot for ``building_id`` (cached ~5 min).

        Never raises: each metric is computed independently and left ``None`` on failure,
        so a degraded GraphDB yields a partial snapshot rather than an error.
        """
        cached = self._cache.get(building_id)
        if cached and (time.monotonic() - cached.generated_at) < _CACHE_TTL_S:
            return cached

        ns = namespace or _resolve_namespace(building_id)
        snap = BuildingMetricsSnapshot(generated_at=time.monotonic())

        snap.total_points = await self._count(
            f"{_RDFS}{_BRICK}SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"?s a ?t . ?t rdfs:subClassOf* brick:Point . "
            f'FILTER(STRSTARTS(STR(?s), "{ns}")) }}'
        )
        snap.total_sensors = await self._count(
            f"{_RDFS}{_BRICK}SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"?s a ?t . ?t rdfs:subClassOf* brick:Sensor . "
            f'FILTER(STRSTARTS(STR(?s), "{ns}")) }}'
        )
        snap.zone_count = await self._count(
            f"{_RDFS}{_BRICK}SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"?s a ?t . ?t rdfs:subClassOf* brick:Location . "
            f'FILTER(STRSTARTS(STR(?s), "{ns}")) }}'
        )
        snap.floor_count = await self._count(
            f"{_RDFS}{_BRICK}SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f'?s a brick:Floor . FILTER(STRSTARTS(STR(?s), "{ns}")) }}'
        )
        snap.room_count = await self._count(
            f"{_RDFS}{_BRICK}SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f'?s a brick:Room . FILTER(STRSTARTS(STR(?s), "{ns}")) }}'
        )
        snap.sensor_types = await self._sensor_types(ns)

        try:
            floors = self._areas(building_id) or []
            if floors:
                snap.per_floor_area = sorted(floors)
                snap.total_area_m2 = round(sum(a for _, a, _ in floors), 1)
        except Exception as e:
            logger.warning(f"[building_metrics] area provider failed: {e}")

        try:
            snap.reporting_sensors = await self._reporting(snap.reporting_window_h)
        except Exception as e:
            logger.warning(f"[building_metrics] reporting-coverage check failed: {e}")

        self._cache[building_id] = snap
        return snap

    async def _count(self, sparql: str) -> Optional[int]:
        try:
            data = await self._exec(sparql)
            b = _bindings(data)
            if b:
                return int(b[0].get("n", {}).get("value", 0))
        except Exception as e:
            logger.warning(f"[building_metrics] count query failed: {e}")
        return None

    async def _sensor_types(self, ns: str, top: int = 10) -> List[Tuple[str, int]]:
        """Best-effort breakdown by the sensor's declared Brick class (indicative)."""
        q = (
            f"{_RDFS}{_BRICK}SELECT ?t (COUNT(DISTINCT ?s) AS ?n) WHERE {{ "
            f"?s a ?t . ?t rdfs:subClassOf* brick:Sensor . "
            f'FILTER(STRSTARTS(STR(?s), "{ns}")) '
            f"FILTER(STRSTARTS(STR(?t), STR(brick:))) }} "
            f"GROUP BY ?t ORDER BY DESC(?n) LIMIT {top}"
        )
        try:
            data = await self._exec(q)
            out: List[Tuple[str, int]] = []
            for row in _bindings(data):
                cls = row.get("t", {}).get("value", "")
                local = cls.rsplit("#", 1)[-1].rsplit("/", 1)[-1].replace("_", " ")
                n = int(row.get("n", {}).get("value", 0))
                if local and local.lower() != "sensor":
                    out.append((local, n))
            return out
        except Exception as e:
            logger.warning(f"[building_metrics] sensor-type breakdown failed: {e}")
            return []


# ── default providers (production wiring) ────────────────────────────────────


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


def _default_area_provider(building_id: str) -> List[Tuple[int, float, int]]:
    """Per-floor (floor, area_m2, space_count) from the DWG/PDF floor-plan manifests."""
    from orchestrator.services.floor_plan_registry import get_floor_plan_registry

    reg = get_floor_plan_registry()
    out: List[Tuple[int, float, int]] = []
    for floor in range(0, 30):  # buildings rarely exceed this; missing floors return None
        try:
            manifest = reg.load_manifest(building_id, floor)
        except Exception:
            manifest = None
        if manifest is None:
            continue
        area = getattr(manifest, "total_area_m2", None)
        spaces = getattr(manifest, "spaces", None) or []
        if area:
            out.append((floor, float(area), len(spaces)))
    return out


def _wide_table_for(storage_key: str) -> str:
    """The wide table behind a store, from schema discovery.

    Returns "" when it cannot be established, which the caller reports as UNKNOWN freshness
    rather than as zero — an undiscovered table and a silent building are different facts.
    """
    try:
        from orchestrator.services.adapters.registry import adapter_registry

        disc = adapter_registry._discoveries.get(  # noqa: SLF001 - no public accessor yet
            storage_key
        ) or adapter_registry._discoveries.get(
            str(storage_key).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        )
        schema = getattr(disc, "schema", None)
        tables = list(getattr(schema, "tables", []) or [])
        if not tables:
            return ""
        # The wide table is the one whose COLUMNS are uuid-shaped. Picking the largest table
        # would pick whichever happens to have most rows, which is not the same question.
        import re as _re

        shape = _re.compile(
            r"^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$"
        )
        best, best_n = "", 0
        for t in tables:
            cols = [c[0] for c in (getattr(schema, "columns", {}) or {}).get(t, [])]
            n = sum(1 for c in cols if shape.match(str(c)))
            if n > best_n:
                best, best_n = t, n
        return best
    except Exception as exc:
        logger.debug(f"[building_metrics] wide-table discovery unavailable: {exc}")
        return ""


async def reporting_uuids_by_store(window_hours: int = 24) -> Optional[Dict[str, set]]:
    """``{storage key: declared uuids with a reading in the last window_hours}``.

    Building-agnostic: the declared uuid→storage mapping comes from the ACTIVE
    building's sensor-map cache (``settings.SENSOR_MAP_PATH``), and each storage
    key resolves through the adapter registry — the same config-driven routing the
    SQL pipeline uses. Never raises; returns ``None`` when the check can't run.

    Freshness is computed PER UUID, never per table (CAVEAT-233). A table-level
    ``MAX(datetime)`` would call a store live when a single sensor in it is: bldg1's
    ``noise_data`` has a table max of "now" and one current stream out of 236.

    Exposed as a map rather than a count so every surface that reports coverage can report
    the matching freshness beside it, from the one measurement — see
    :func:`_default_reporting_provider` for the count the metrics block uses.
    """
    import json
    from pathlib import Path

    from shared.config import settings

    try:
        smap = json.loads(Path(settings.SENSOR_MAP_PATH).read_text(encoding="utf-8"))
    except Exception:
        return None

    declared: dict[str, set] = {}  # storage key -> declared uuids
    for v in smap.values():
        if isinstance(v, dict) and v.get("uuid") and v.get("storage"):
            declared.setdefault(str(v["storage"]), set()).add(str(v["uuid"]))
    if not declared:
        return None

    try:
        from orchestrator.services.adapters.registry import adapter_registry
    except Exception:
        return None
    if not adapter_registry.is_available:
        return None

    # A store appears in this map only if its probe SUCCEEDED. Absent means "not measured",
    # which the callers must not render as zero: an unreachable datasource would otherwise be
    # indistinguishable from a building whose sensors have all gone quiet.
    by_store: Dict[str, set] = {}
    for storage_key, uuids in declared.items():
        try:
            adapter = adapter_registry.get(storage_key)
            if adapter is None or not hasattr(adapter, "execute_query"):
                continue
            table = getattr(adapter, "table", None)
            if table:  # narrow (uuid, datetime, value) table — direct DISTINCT
                sql = (
                    f"SELECT DISTINCT `uuid` FROM `{table}` "
                    f"WHERE `datetime` >= NOW() - INTERVAL {int(window_hours)} HOUR"
                )
                res = await adapter.execute_query(sql)
                if res.success:
                    fresh = {str(r.get("uuid")) for r in res.data} & uuids
                    by_store.setdefault(storage_key, set()).update(fresh)
            else:  # wide table — uuids are COLUMNS; sample recent rows
                # The table name comes from schema DISCOVERY, not from a literal. `sensor_data`
                # was hardcoded here, which is a building literal in core code (contract rule 3)
                # and silently wrong for any building whose wide table is named differently.
                wide = _wide_table_for(storage_key)
                if not wide:
                    logger.warning(
                        f"[building_metrics] no wide table discovered for '{storage_key}'; "
                        "freshness for this store is UNKNOWN rather than zero"
                    )
                    continue
                sql = (
                    f"SELECT * FROM `{wide}` "
                    f"WHERE `datetime` >= NOW() - INTERVAL {int(window_hours)} HOUR "
                    "ORDER BY `datetime` DESC LIMIT 25"
                )
                res = await adapter.execute_query(sql)
                if res.success:
                    seen: set = set()
                    for row in res.data:
                        seen |= {k for k, val in row.items() if val is not None}
                    by_store.setdefault(storage_key, set()).update(seen & uuids)
        except Exception as e:
            logger.warning(f"[building_metrics] reporting check failed for '{storage_key}': {e}")
    return by_store


#: (window_hours) -> (monotonic stamp, flattened fresh-uuid set). The measurement costs one
#: query per store, which is cheap for a page render and far too expensive per chat turn --
#: the coverage schema is rebuilt on every deliberate/diagnosis request.
_FRESH_CACHE: Dict[int, Tuple[float, Optional[set]]] = {}
_FRESH_TTL_S = 300.0


async def fresh_uuids(window_hours: int = 24, timeout_s: float = 20.0) -> Optional[set]:
    """Every declared uuid with a reading inside the window, flattened and CACHED.

    Returns ``None`` when the check cannot run (no sensor map, no adapters, timeout). Callers
    must treat ``None`` as "no freshness information", NEVER as "nothing is fresh" -- reading
    an unavailable measurement as an empty one would silently mark every sensor in the building
    stale, which is the degrade-to-a-legal-value failure this codebase keeps paying for.
    """
    import time

    now = time.monotonic()
    hit = _FRESH_CACHE.get(window_hours)
    if hit and (now - hit[0]) < _FRESH_TTL_S:
        return hit[1]
    try:
        by_store = await asyncio.wait_for(reporting_uuids_by_store(window_hours), timeout_s)
    except Exception as exc:
        logger.debug(f"[building_metrics] freshness unavailable: {exc}")
        by_store = None
    flat = None if by_store is None else (set().union(*by_store.values()) if by_store else set())
    _FRESH_CACHE[window_hours] = (now, flat)
    return flat


async def _default_reporting_provider(window_hours: int = 24) -> Optional[int]:
    """Total DISTINCT declared sensors reporting inside the window (the snapshot's number)."""
    by_store = await reporting_uuids_by_store(window_hours)
    if by_store is None:
        return None
    return len(set().union(*by_store.values())) if by_store else 0


def _resolve_namespace(building_id: str) -> str:
    """Active building's ontology namespace; falls back to the process-global default."""
    try:
        from orchestrator.services.building_context import resolve_building_context

        return resolve_building_context(building_id).namespace
    except Exception:
        from shared.config import settings

        return settings.BUILDING_NAMESPACE


def _bindings(data: dict) -> list:
    if not isinstance(data, dict):
        return []
    res = data.get("results", {})
    if isinstance(res, dict):
        b = res.get("bindings", [])
        return b if isinstance(b, list) else []
    return []


def render_metrics_block(snap: BuildingMetricsSnapshot, building_name: str) -> str:
    """Render the snapshot as an authoritative, human-readable markdown block."""
    lines = [f"**Live building figures for {building_name}** (computed now from the ontology):"]
    if snap.total_points is not None:
        lines.append(f"- Instrumented points in the ontology: **{snap.total_points:,}**")
    if snap.total_sensors is not None:
        # CAVEAT-007: never present the ontology count as operational reality —
        # say what is DECLARED and, when known, how many actually reported data.
        sensors_line = f"- Sensors declared in the building model: **{snap.total_sensors:,}**"
        lines.append(sensors_line)
        if snap.reporting_sensors is not None:
            lines.append(
                f"- Sensors that reported data in the last {snap.reporting_window_h} h: "
                f"**{snap.reporting_sensors:,}** (live check across the registered databases)"
            )
    if snap.zone_count is not None:
        lines.append(f"- Zones / locations: **{snap.zone_count:,}**")
    if snap.floor_count is not None:
        lines.append(f"- Floors: **{snap.floor_count}**")
    if snap.room_count is not None:
        lines.append(f"- Rooms: **{snap.room_count:,}**")
    if snap.total_area_m2 is not None:
        floors = len(snap.per_floor_area)
        lines.append(
            f"- Mapped floor area: **{snap.total_area_m2:,.0f} m²** across {floors} floors"
        )
    if snap.sensor_types:
        top = ", ".join(f"{name} ({n})" for name, n in snap.sensor_types[:6])
        lines.append(f"- Most common sensor types: {top}")
    return "\n".join(lines)


# Process-wide singleton (mirrors the repo's other service singletons).
_instance: Optional[BuildingMetrics] = None


def get_building_metrics() -> BuildingMetrics:
    global _instance
    if _instance is None:
        _instance = BuildingMetrics()
    return _instance
