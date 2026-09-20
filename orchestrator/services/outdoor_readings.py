# -*- coding: utf-8 -*-
"""The outdoor readings a building records, with the time of each (2D-16 wave 2).

"How is the weather outside now?" cannot be answered with a forecast, and it was answered with a
question ("Which measurement or record do you mean by **weather**?"). The building DOES record
outdoor conditions -- its graph types weather-feed points with Brick's outdoor sensor classes -- so
the honest answer is "no forecast is held; here is what the outdoor sensors last recorded, and
when". This module finds those points in the graph and reads each one's newest row through the
adapter registry, the same way every other lane reads a store (design contract 9).

Nothing here names a building, a store or a table: classes are Brick vocabulary, the store comes
from ``ref:storedAt``, the unit from the point or the modality table. Every step is best-effort and
returns what it could read; a point that cannot be read is left out, never guessed.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from orchestrator.services.clarification import OutdoorReading
from shared.utils import get_logger

logger = get_logger(__name__)

#: (Brick class local name, the phrase a person uses). Vocabulary, not a building.
OUTDOOR_POINTS = (
    ("Outside_Air_Temperature_Sensor", "outdoor temperature"),
    ("Outside_Air_Humidity_Sensor", "outdoor humidity"),
    ("Wind_Speed_Sensor", "wind speed"),
    ("Solar_Irradiance_Sensor", "solar irradiance"),
    ("Rainfall_Sensor", "rainfall"),
    ("Rain_Sensor", "rainfall"),
    ("Precipitation_Sensor", "precipitation"),
)

_UUID = re.compile(r"^[0-9A-Fa-f][0-9A-Fa-f\-]{7,63}$")
_BRICK = "https://brickschema.org/schema/Brick#"
_REF = "https://brickschema.org/schema/Brick/ref#"
#: An old floor date: the narrow adapter otherwise limits the window to the last 30 days, and a
#: feed that stopped 40 days ago should still be reported as "last recorded then".
_FLOOR_DATE = "2000-01-01"

RunSelect = Callable[..., Awaitable[Any]]


def points_query() -> str:
    """One SELECT for every outdoor point's time-series id, store and (when declared) unit."""
    names = "|".join(cls for cls, _ in OUTDOOR_POINTS)
    return (
        f"PREFIX brick: <{_BRICK}>\nPREFIX ref: <{_REF}>\n"
        "SELECT DISTINCT ?cls ?uuid ?store ?unit WHERE {\n"
        "  ?s a ?cls .\n"
        f'  FILTER(REGEX(STR(?cls), "({names})$"))\n'
        "  ?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid .\n"
        "  OPTIONAL { ?r ref:storedAt ?store }\n"
        "  OPTIONAL { ?s brick:hasUnit ?unit }\n"
        "} LIMIT 20"
    )


def _val(cell: Any) -> str:
    if isinstance(cell, dict):
        cell = cell.get("value")
    return str(cell or "").strip()


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def parse_points(rows: Sequence[Any]) -> List[Dict[str, str]]:
    """Distinct ``{phrase, uuid, store, unit}`` points from a SELECT's rows, in table order."""
    phrase_of = {cls: phrase for cls, phrase in OUTDOOR_POINTS}
    seen = set()
    found: List[Dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        cls = _local(_val(row.get("cls")))
        uuid = _val(row.get("uuid"))
        if cls not in phrase_of or not _UUID.match(uuid) or uuid in seen:
            continue
        seen.add(uuid)
        found.append(
            {
                "cls": cls,
                "phrase": phrase_of[cls],
                "uuid": uuid,
                "store": _val(row.get("store")),
                "unit": _val(row.get("unit")),
            }
        )
    order = {cls: i for i, (cls, _) in enumerate(OUTDOOR_POINTS)}
    return sorted(found, key=lambda p: order[p["cls"]])


def _wide_latest_sql(uuid: str, ts_col: str, adapter: Any) -> str:
    """Newest (timestamp, value) of one point in a WIDE table; the table is discovered, not named."""
    table = "sensor_data"
    try:
        schema = getattr(adapter, "_schema", None) or getattr(adapter, "schema", None)
        for candidate in list(getattr(schema, "tables", []) or []):
            cols = {c for c, _t in (getattr(schema, "columns", {}) or {}).get(candidate, [])}
            if uuid in cols:
                table = candidate
                break
    except Exception:  # pragma: no cover - fall back to the conventional name
        pass
    return (
        f"SELECT `{ts_col}` AS timestamp, `{uuid}` AS value FROM `{table}` "
        f"WHERE `{uuid}` IS NOT NULL ORDER BY `{ts_col}` DESC LIMIT 1"
    )


def _number(row: Dict[str, Any], uuid: str) -> Optional[float]:
    for key in ("value", uuid, "val"):
        v = row.get(key)
        if v is not None and not isinstance(v, bool):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _when(raw: Any, tz_name: Optional[str]) -> str:
    """'03:50 on 19 Sep' in building time, or '' when the timestamp cannot be read."""
    from datetime import datetime

    from orchestrator.services.requested_interval import to_local

    ts = raw if isinstance(raw, datetime) else None
    if ts is None:
        text = str(raw or "").strip().replace("T", " ")[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                ts = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if ts is None:
        return ""
    local = to_local(ts, tz_name)
    return f"{local:%H:%M} on {local.day} {local:%b}"


async def read_point(
    point: Dict[str, str], adapter: Any, ts_col: str, tz_name: Optional[str] = None
) -> Optional[OutdoorReading]:
    """The newest reading of one point, or None when it cannot be read. Never raises."""
    uuid = point["uuid"]
    try:
        query = adapter.build_timeseries_query(
            uuids=[uuid], ts_col=ts_col, start_date=_FLOOR_DATE, end_date=None, limit=1
        ) or _wide_latest_sql(uuid, ts_col, adapter)
        result = await adapter.execute_query(query)
        if not getattr(result, "success", False) or not getattr(result, "data", None):
            return None
        row = result.data[0]
        value = _number(row, uuid)
        if value is None:
            return None
        unit = point.get("unit") or ""
        if not unit:
            try:
                from orchestrator.services.modality_units import unit_for_sensor

                unit = unit_for_sensor(point["cls"], point["phrase"]) or ""
            except Exception:  # a missing unit is left blank, not guessed
                unit = ""
        raw = row.get("timestamp") or row.get(ts_col) or row.get("Datetime") or row.get("datetime")
        return OutdoorReading(point["phrase"], value, unit, _when(raw, tz_name))
    except Exception as exc:
        logger.debug(f"[outdoor] could not read {uuid[:12]}: {exc}")
        return None


async def fetch_outdoor_readings(
    run_select: Optional[RunSelect] = None,
    adapter_for: Optional[Callable[[str], Any]] = None,
    tz_name: Optional[str] = None,
) -> List[OutdoorReading]:
    """Every outdoor point the graph declares, read through its own store; [] when none can be."""
    try:
        if run_select is None:
            from orchestrator.services.evidence.spatial_facts import default_run_select

            run_select = default_run_select
        res = await run_select(points_query(), limit=20)
        if isinstance(res, dict):
            if res.get("ok") is False:
                return []
            res = res.get("rows") or []
        points = parse_points(res)
    except Exception as exc:
        logger.debug(f"[outdoor] points unavailable: {exc}")
        return []
    if not points:
        return []
    registry = None
    if adapter_for is None:
        from orchestrator.services.adapters.registry import adapter_registry as registry

        adapter_for = registry.get
    out: List[OutdoorReading] = []
    for point in points:
        adapter = adapter_for(point["store"])
        if adapter is None:
            continue
        ts_col = "Datetime"
        if registry is not None:
            try:
                ts_col = registry.get_timestamp_column(point["store"])
            except Exception:  # pragma: no cover - the conventional column
                ts_col = "Datetime"
        reading = await read_point(point, adapter, ts_col, tz_name)
        if reading is not None:
            out.append(reading)
    return out
