import os
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from datetime import datetime, timedelta
from dateutil.parser import parse as dt_parse

import psycopg2
import psycopg2.extras

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet

# Reuse helpers and settings from the existing actions module to keep behavior consistent
from .actions import (
    get_user_artifacts_dir,
    BASE_URL_DEFAULT,
    PipelineLogger,
    new_correlation_id,
    ActionProcessTimeseries,  # for helper methods (payload builders, summarizer, mappings)
)


logger = logging.getLogger(__name__)


# -----------------------------
# PostgreSQL / Timescale config
# -----------------------------
def get_pg_config() -> Dict[str, Any]:
    """Return PostgreSQL config for Option 2 (TimescaleDB) with sensible defaults.

    Env vars:
      - PG_HOST (default: "timescaledb")
      - PG_PORT (default: 5432)
      - PG_DATABASE (default: "thingsboard")
      - PG_USER (default: "thingsboard")
      - PG_PASSWORD (default: "thingsboard")
      - PG_SSLMODE (optional, default: "disable")

    Optionally, you can specify TB_DEVICE_NAME or TB_DEVICE_ID to restrict queries
    to a single ThingsBoard device (entity_id).
    """
    return {
        "host": os.getenv("PG_HOST", "timescaledb"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "database": os.getenv("PG_DATABASE", "thingsboard"),
        "user": os.getenv("PG_USER", "thingsboard"),
        "password": os.getenv("PG_PASSWORD", "thingsboard"),
        "sslmode": os.getenv("PG_SSLMODE", "disable"),
    }


def _to_epoch_ms(value: Union[str, datetime], end_of_day_if_date: bool = False) -> int:
    """Convert various date strings to epoch milliseconds.

    - Accepts formats like DD/MM/YYYY, YYYY-MM-DD, with or without time.
    - If time is missing and end_of_day_if_date=True, set time to 23:59:59; otherwise 00:00:00.
    - Treat naive datetimes as local and convert directly to epoch ms.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = (value or "").strip()
        if not s:
            raise ValueError("Empty date value")
        try:
            # Heuristic: if it looks like DD/MM/YYYY, parse day-first
            if "/" in s and len(s.split("/")) == 3 and s.count(":") == 0:
                dt = dt_parse(s, dayfirst=True)
            else:
                dt = dt_parse(s)
        except Exception as e:
            raise ValueError(f"Could not parse date '{value}': {e}")

    if dt.hour == 0 and dt.minute == 0 and dt.second == 0 and end_of_day_if_date:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=0)

    # Convert to epoch ms (naive assumed local)
    epoch = datetime(1970, 1, 1)
    return int((dt - epoch).total_seconds() * 1000)


def _resolve_device_entity_id(conn, device_name: Optional[str], device_id: Optional[str]) -> Optional[str]:
    """Resolve ThingsBoard device entity_id (UUID) by name or return explicit device_id.

    Returns the UUID string or None if not found or no filter requested.
    """
    if device_id:
        return device_id
    if not device_name:
        return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM device WHERE name = %s LIMIT 1", (device_name,))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        logger.warning(f"Failed to resolve device by name '{device_name}': {e}")
        return None


def _lookup_key_ids(conn, keys: List[str]) -> Dict[str, int]:
    """Map telemetry key strings -> key_id via ts_kv_dictionary."""
    if not keys:
        return {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT key, key_id FROM ts_kv_dictionary WHERE key = ANY(%s)", (keys,)
        )
        rows = cur.fetchall() or []
    return {r["key"]: int(r["key_id"]) for r in rows}


def _fetch_timeseries(
    conn,
    keys: List[str],
    start_ms: int,
    end_ms: int,
    entity_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch telemetry for multiple keys from ts_kv over a time window.

    Output: { key_string: [ {datetime, reading_value}, ... ], ... }
    """
    key_map = _lookup_key_ids(conn, keys)
    if not key_map:
        return {k: [] for k in keys}

    key_ids = list(key_map.values())
    params: List[Any] = [key_ids, start_ms, end_ms]
    where = ["d.key_id = ANY(%s)", "k.ts BETWEEN %s AND %s"]
    if entity_id:
        where.append("k.entity_id = %s")
        params.append(entity_id)

    sql = f"""
        SELECT k.ts, k.entity_id, d.key AS key, k.bool_v, k.long_v, k.dbl_v, k.str_v, k.json_v
        FROM ts_kv k
        JOIN ts_kv_dictionary d ON k.key = d.key_id
        WHERE {' AND '.join(where)}
        ORDER BY k.ts ASC
    """

    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in keys}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        for row in cur.fetchall() or []:
            key = row["key"]
            ts_ms = int(row["ts"]) if row["ts"] is not None else None
            # Prefer numeric value; fallback to bool -> 0/1; then str/json as-is
            val = None
            if row.get("dbl_v") is not None:
                val = float(row["dbl_v"])
            elif row.get("long_v") is not None:
                val = float(row["long_v"])  # keep uniform type for charts
            elif row.get("bool_v") is not None:
                val = 1.0 if row["bool_v"] else 0.0
            elif row.get("str_v") is not None:
                val = row["str_v"]
            elif row.get("json_v") is not None:
                val = row["json_v"]

            if ts_ms is None or val is None:
                continue
            # Format ISO string for consistency with MySQL path
            dt_iso = datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
            out.setdefault(key, []).append({"datetime": dt_iso, "reading_value": val})

    return out


class ActionProcessTimeseriesBldg2(Action):
    """Process timeseries against PostgreSQL/Timescale (Option 2).

    This mirrors the MySQL-based ActionProcessTimeseries flow but queries ThingsBoard's
    ts_kv using telemetry keys that are UUIDs per sensor.
    """

    def name(self) -> str:
        return "action_process_timeseries_bldg2"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        corr = new_correlation_id()
        plog = PipelineLogger(corr, "TS-Option2")
        with plog.stage("collect_slots"):
            timeseries_ids = tracker.get_slot("timeseries_ids") or []
            if isinstance(timeseries_ids, str):
                timeseries_ids = [timeseries_ids]
            elif not isinstance(timeseries_ids, list):
                timeseries_ids = list(timeseries_ids or [])

            start_s = tracker.get_slot("start_date")
            end_s = tracker.get_slot("end_date")
            analytics_type = tracker.get_slot("analytics_type") or "analyze_sensor_trend"
            sensor_types = tracker.get_slot("sensor_type") or []
            plog.info(
                "Slots gathered",
                ids=len(timeseries_ids),
                start=start_s,
                end=end_s,
                analytics=analytics_type,
            )

        if not timeseries_ids:
            dispatcher.utter_message(text="No timeseries IDs provided.")
            return []

        try:
            start_ms = _to_epoch_ms(start_s, end_of_day_if_date=False)
            end_ms = _to_epoch_ms(end_s, end_of_day_if_date=True)
        except Exception as e:
            dispatcher.utter_message(text=f"Invalid date range: {e}")
            return []

        cfg = get_pg_config()
        device_name = os.getenv("TB_DEVICE_NAME")
        device_id = os.getenv("TB_DEVICE_ID")

        with plog.stage("db_connect"):
            conn = psycopg2.connect(
                host=cfg["host"],
                port=cfg["port"],
                dbname=cfg["database"],
                user=cfg["user"],
                password=cfg["password"],
                sslmode=cfg.get("sslmode", "disable"),
            )

        try:
            with plog.stage("resolve_device"):
                entity_id = _resolve_device_entity_id(conn, device_name, device_id)
                if device_name and not entity_id:
                    plog.warning("Device name not found; querying across all devices", device_name=device_name)

            with plog.stage("query_ts_kv"):
                # timeseries_ids are UUID strings we use as telemetry keys
                data_by_key = _fetch_timeseries(conn, timeseries_ids, start_ms, end_ms, entity_id)
                total_points = sum(len(v) for v in data_by_key.values())
                plog.info("Fetched data", series=len(data_by_key), points=total_points)

        finally:
            try:
                conn.close()
            except Exception:
                pass

        # Build analytics payload compatible with existing microservices
        helper = ActionProcessTimeseries()
        payload = helper.build_canonical_analytics_payload(
            analytics_type=analytics_type,
            sql_results_dict=data_by_key,
            sensor_types=sensor_types if isinstance(sensor_types, list) else [sensor_types],
        )

        # Persist artifact for the user and present link
        base_url = os.getenv("BASE_URL", BASE_URL_DEFAULT)
        user_safe, user_dir = get_user_artifacts_dir(tracker)
        ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"timescale_payload_{ts_label}.json"
        fpath = os.path.join(user_dir, fname)
        try:
            with open(fpath, "w") as f:
                json.dump(payload, f, indent=2)
            url = f"{base_url}/artifacts/{user_safe}/{fname}"
            dispatcher.utter_message(
                text="Prepared analytics payload from TimescaleDB:",
                attachment={"type": "json", "url": url, "filename": fname},
            )
        except Exception as e:
            logger.warning(f"Failed to save artifact: {e}")

        # Optional: summarize via the same LLM flow used elsewhere
        try:
            summary = helper.summarize_response(payload)
            if summary:
                dispatcher.utter_message(text=f"Summary: {summary}")
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")

        # Also return slots for downstream consumers if any
        return [
            SlotSet("sparql_error", False),
            SlotSet("timeseries_ids", timeseries_ids),
            SlotSet("analytics_type", analytics_type),
        ]


# Notes on TimescaleDB structure and querying multiple series
# -----------------------------------------------------------
# - ThingsBoard stores telemetry in ts_kv with a numeric key that maps to text keys in ts_kv_dictionary.
# - Using each sensor UUID string as the telemetry key is ideal: you can query single or many series by
#   looking up their key_id(s) and filtering WHERE d.key_id = ANY(array[...]) AND ts BETWEEN ...
# - For performance and readability, consider creating a view that flattens the dictionary join and converts ts:
#
#   CREATE VIEW IF NOT EXISTS telemetry_flat AS
#   SELECT to_timestamp(k.ts/1000.0) AS ts_utc,
#          k.entity_id,
#          d.key AS key,
#          COALESCE(k.dbl_v, k.long_v::double precision, CASE WHEN k.bool_v IS NULL THEN NULL WHEN k.bool_v THEN 1.0 ELSE 0.0 END) AS num_v,
#          k.str_v,
#          k.json_v
#   FROM ts_kv k JOIN ts_kv_dictionary d ON k.key = d.key_id;
#
# - Helpful indexes (safe on OSS):
#     CREATE INDEX IF NOT EXISTS idx_ts_kv_ts_key ON ts_kv (ts, key);
#     CREATE INDEX IF NOT EXISTS idx_ts_kv_entity_key_ts ON ts_kv (entity_id, key, ts DESC);
# - You do NOT need to change the base table structure to query single or multiple series.
#   Use IN/ANY with dictionary-joined key_ids, and optional device filter.
