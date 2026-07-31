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

import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Tuple

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


async def _default_reporting_provider(window_hours: int = 24) -> Optional[int]:
    """DISTINCT declared sensors with a stored reading in the last ``window_hours``.

    Building-agnostic: the declared uuid→storage mapping comes from the ACTIVE
    building's sensor-map cache (``settings.SENSOR_MAP_PATH``), and each storage
    key resolves through the adapter registry — the same config-driven routing the
    SQL pipeline uses. Never raises; returns ``None`` when the check can't run.
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

    reporting: set = set()
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
                    reporting |= {str(r.get("uuid")) for r in res.data} & uuids
            else:  # wide table — uuids are COLUMNS; sample recent rows
                sql = (
                    "SELECT * FROM `sensor_data` "
                    f"WHERE `datetime` >= NOW() - INTERVAL {int(window_hours)} HOUR "
                    "ORDER BY `datetime` DESC LIMIT 25"
                )
                res = await adapter.execute_query(sql)
                if res.success:
                    seen: set = set()
                    for row in res.data:
                        seen |= {k for k, val in row.items() if val is not None}
                    reporting |= seen & uuids
        except Exception as e:
            logger.warning(f"[building_metrics] reporting check failed for '{storage_key}': {e}")
    return len(reporting)


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
