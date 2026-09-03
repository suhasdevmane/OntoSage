#!/usr/bin/env python3
"""
Continuous MySQL dummy data publisher for sensordb.sensor_data
- Inserts indefinitely until interrupted (Ctrl+C or SIGTERM)
- Graceful shutdown and resource cleanup
- Optional batching (executemany) for higher throughput
- Exponential backoff on transient failures
Requires: pip install PyMySQL
"""
from __future__ import annotations

import glob
import json
import os
import random
import re
import signal
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import pymysql
except Exception:
    print("PyMySQL is required. Install it with: pip install PyMySQL", file=sys.stderr)
    raise

# Global maps
SENSOR_MAP = {}  # UUID -> Sensor Name
SCHEMA_MAP = {}  # UUID -> {data_type, precision, scale}

# Debug tracking
LAST_SENT_DATA = {}  # Stores last sent row for debug logging
LAST_DEBUG_TIME = 0  # Timestamp of last debug print


def load_sensor_map(filepath="sensor_uuids.json"):
    global SENSOR_MAP
    try:
        # Resolve path relative to script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)

        with open(full_path, "r") as f:
            data = json.load(f)
            # Create reverse map: UUID -> Name
            SENSOR_MAP = {v: k for k, v in data.items()}
        print(f"[py-dummy] Loaded {len(SENSOR_MAP)} sensors from {filepath}")
    except Exception as e:
        print(f"[py-dummy] Warning: Could not load sensor map from {filepath}: {e}")


def load_schema_map(filepath="postgresql columns.csv"):
    # global SCHEMA_MAP  # Not needed for in-place modification
    try:
        import csv

        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)

        with open(full_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uuid = row["COLUMN_NAME"]
                data_type = row["DATA_TYPE"]
                precision = row.get("NUMERIC_PRECISION", "NULL")
                scale = row.get("NUMERIC_SCALE", "NULL")

                # Skip the Datetime column
                if uuid.lower() == "datetime":
                    continue

                SCHEMA_MAP[uuid] = {
                    "data_type": data_type,
                    "precision": int(precision) if precision != "NULL" else None,
                    "scale": int(scale) if scale != "NULL" else None,
                }
        print(f"[py-dummy] Loaded {len(SCHEMA_MAP)} column schemas from {filepath}")
    except Exception as e:
        print(f"[py-dummy] Warning: Could not load schema map from {filepath}: {e}")


# ── Narrow per-modality tables (uuid, datetime, value) ──────────────────────
# Standardized out of input/data CSVs. Published live alongside the wide table so
# "now" queries for energy/occupancy/water/noise/IAQ/light/equipment stay fresh.
NARROW_SENSORS: List[Dict[str, str]] = []  # [{uuid, table, value_col}]
_NARROW_RANGES = {
    "kwh": (1.0, 6.0, 2),
    "occupancy": (0, 30, 0),
    "flow_lpm": (0.0, 2.0, 3),
    "noise_db": (30.0, 70.0, 1),
    "pm25": (5.0, 35.0, 1),
    "voc": (50.0, 350.0, 0),
    "lux": (0.0, 600.0, 0),
    "vib_mm_s": (0.1, 1.2, 2),
    "runtime_h": (0.0, 1.0, 3),
    # Added when the publisher was widened from 19 hand-listed points to every point the
    # ontology registers to a narrow store (BUG-390). Without these the fallback range
    # applies, and (0, 100) is not merely vague for these modalities — it is impossible.
    # A CO2 reading of 12 ppm is below the outdoor atmosphere; a room at 3 degrees is not a
    # plausible office. Generated data still has to be data a building could produce, or the
    # first thing anyone notices about the system is that its readings are nonsense.
    "temp_c": (18.0, 26.0, 1),
    "rh_pct": (30.0, 65.0, 1),
    "co2_ppm": (400, 1200, 0),
    "contact": (0, 1, 0),  # a door or window is open or shut, never 0.47
    "generic": (0.0, 100.0, 2),
}


def _narrow_map_path():
    """The narrow publish map for whichever building is mounted.

    Prefers the GENERATED complete map (``*_narrow_publish_map.json``, produced by
    scripts/generate_publisher_map.py from the live graph) and falls back to the older
    hand-written extension file so a building that has not generated one still publishes
    something. Discovered by glob rather than named per building, so no building id appears
    in this service.
    """
    override = os.environ.get("NARROW_MAP", "").strip()
    if override:
        return override
    generated = sorted(glob.glob("/app/input/*_narrow_publish_map.json"))
    if generated:
        return generated[0]
    legacy = sorted(glob.glob("/app/input/*_timeseries_extension_uuids.json"))
    return legacy[0] if legacy else "/app/input/narrow_publish_map.json"


def load_narrow_sensors(filepath=None):
    global NARROW_SENSORS
    filepath = filepath or _narrow_map_path()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.values() if isinstance(data, dict) else data
        NARROW_SENSORS = [
            {"uuid": e["uuid"], "table": e["table"], "value_col": e.get("value_col", "generic")}
            for e in entries
            if e.get("uuid") and e.get("table")
        ]
        tables = sorted({s["table"] for s in NARROW_SENSORS})
        print(
            f"[py-dummy] Loaded {len(NARROW_SENSORS)} narrow sensors across "
            f"{len(tables)} table(s) from {filepath}"
        )
    except Exception as e:
        print(f"[py-dummy] Narrow sensors not loaded ({filepath}): {e}")


def _narrow_value(value_col: str):
    lo, hi, dec = _NARROW_RANGES.get(value_col, (0.0, 100.0, 2))
    return rand_int(int(lo), int(hi)) if dec == 0 else rand_float(lo, hi, dec)


def publish_narrow(conn, verbose=False) -> int:
    """Insert one fresh (uuid, NOW(), value) row into each narrow modality table."""
    if not NARROW_SENSORS:
        return 0
    # Batched per table. This wrote one INSERT per sensor, which was fine for the 19
    # hand-listed points and is not for the 1,528 the ontology actually registers: at a
    # 30-second interval a row-at-a-time loop spends most of the tick in round-trips and can
    # overrun the interval it is meant to keep. One executemany per table keeps a full pass
    # well inside the window.
    #
    # A failing table is logged and skipped rather than aborting the pass, so one broken
    # modality cannot stop every other sensor from being topped up.
    by_table = {}
    for s in NARROW_SENSORS:
        by_table.setdefault(s["table"], []).append((s["uuid"], _narrow_value(s["value_col"])))

    written = 0
    with conn.cursor() as cur:
        for table, rows in by_table.items():
            try:
                cur.executemany(
                    f"INSERT INTO `{table}` (`uuid`, `datetime`, `value`) "
                    f"VALUES (%s, NOW(), %s) "
                    f"ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
                    rows,
                )
                written += len(rows)
            except Exception as e:
                if verbose:
                    print(f"[py-dummy] narrow insert {table} failed: {e}", flush=True)
    return written


# ── Extended narrow tables (bulk) ───────────────────────────────────────────
# Sensors that don't fit database1's column-capped wide table live in companion
# narrow tables (sensor_data_floors04 = 522 real floor 0-4 sensors,
# sensor_data_synth = 106 synthetic). Values are typed per Brick class in the
# manifest (lo/hi/dec), so a temperature reads 18-28, not 0-100.
EXTENDED_SENSORS: List[Dict[str, object]] = []  # [{uuid, table, lo, hi, dec}]


def _extended_map_path() -> str:
    """Discovered, not hardcoded — this named bldg1's file, so no other building was fed."""
    override = os.environ.get("EXTENDED_MAP", "").strip()
    if override:
        return override
    found = sorted(glob.glob("/app/input/*_extended_narrow_uuids.json"))
    return found[0] if found else "/app/input/extended_narrow_uuids.json"


def load_extended_sensors(filepath=None):
    global EXTENDED_SENSORS
    filepath = filepath or _extended_map_path()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        EXTENDED_SENSORS = [
            {
                "uuid": e["uuid"],
                "table": e["table"],
                "lo": float(e.get("lo", 0)),
                "hi": float(e.get("hi", 100)),
                "dec": int(e.get("dec", 2)),
            }
            for e in data.values()
        ]
        # A uuid written by BOTH maps on the same tick doubles its apparent sampling rate,
        # and every window a detector or a freshness check reasons about is expressed in
        # samples somewhere. The maps are disjoint by construction today (the generator
        # defers to this file); this makes a hand-edit that overlaps them fail loudly
        # instead of silently halving every detector's effective view (CAVEAT-402).
        already = {s["uuid"] for s in NARROW_SENSORS}
        collisions = [s for s in EXTENDED_SENSORS if s["uuid"] in already]
        if collisions:
            EXTENDED_SENSORS = [s for s in EXTENDED_SENSORS if s["uuid"] not in already]
            print(
                f"[py-dummy] {len(collisions)} sensor(s) appear in BOTH publish maps; the "
                f"narrow map keeps them so they are not written twice per tick"
            )
        print(f"[py-dummy] Loaded {len(EXTENDED_SENSORS)} extended narrow sensors from {filepath}")
    except Exception as e:
        print(f"[py-dummy] Extended sensors not loaded ({filepath}): {e}")


def publish_extended(conn, verbose=False) -> int:
    """Insert one fresh (uuid, NOW(), value) row per extended sensor into its narrow table."""
    if not EXTENDED_SENSORS:
        return 0
    written = 0
    with conn.cursor() as cur:
        for s in EXTENDED_SENSORS:
            try:
                lo, hi, dec = s["lo"], s["hi"], s["dec"]
                val = rand_int(int(lo), int(hi)) if dec == 0 else rand_float(lo, hi, dec)
                cur.execute(
                    f"INSERT INTO `{s['table']}` (`uuid`, `datetime`, `value`) "
                    f"VALUES (%s, NOW(), %s) "
                    f"ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
                    (s["uuid"], val),
                )
                written += 1
            except Exception as e:
                if verbose:
                    print(f"[py-dummy] extended insert {s['table']} failed: {e}", flush=True)
    return written


def get_realistic_value(sensor_name, uuid, enum_opts=None):
    """Generate realistic value based on sensor name and schema type."""
    name = sensor_name.lower()
    schema = SCHEMA_MAP.get(uuid, {})
    data_type = schema.get("data_type", "").lower()
    precision = schema.get("precision")
    scale = schema.get("scale", 2)

    # Temperature (18-28 C) - DECIMAL(6,2)
    if "temperature" in name:
        return round(random.uniform(18.0, 28.0), scale or 2)

    # Humidity (30-70 %) - DECIMAL(6,2) or DECIMAL(8,2)
    if "humidity" in name:
        return round(random.uniform(30.0, 70.0), scale or 2)

    # CO2 (400-1200 ppm) - DECIMAL(8,2)
    if "co2" in name:
        if data_type == "decimal":
            return round(random.uniform(400.0, 1200.0), scale or 2)
        return random.randint(400, 1200)

    # TVOC (0-500 ppb) - SMALLINT
    if "tvoc" in name:
        return random.randint(0, 500)

    # Noise/Sound (30-80 dB) - SMALLINT
    if "noise" in name or "sound" in name:
        return random.randint(30, 80)

    # Illuminance/Light (0-1000 lux) - SMALLINT
    if "illuminance" in name or "light" in name:
        return random.randint(0, 1000)

    # Occupancy/Motion (0 or 1) - TINYINT
    if "occupancy" in name or "motion" in name:
        return random.choice([0, 1])

    # Air Quality Level (Enum) - ENUM
    if "air_quality_level" in name:
        if enum_opts:
            return random.choice(enum_opts)
        return None

    # Air Quality (Index 0-500) - SMALLINT
    if "air_quality" in name and "level" not in name:
        return random.randint(0, 150)

    return None


# ============================ SETTINGS (edit me) ============================
# All connection settings can be overridden by environment variables,
# making this script work both locally and inside Docker containers.
SETTINGS = {
    # Connection (env vars: MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, MYSQL_TABLE)
    "HOST": os.environ.get("MYSQL_HOST", "localhost"),
    "PORT": int(os.environ.get("MYSQL_PORT", "3307")),
    "USER": os.environ.get("MYSQL_USER", "thingsboard"),
    "PASSWORD": os.environ.get("MYSQL_PASSWORD", "thingsboard"),
    "DB": os.environ.get("MYSQL_DB", "sensordb"),
    "TABLE": os.environ.get("MYSQL_TABLE", "sensor_data"),
    # Timestamp column: leave empty to auto-detect first TIMESTAMP/DATETIME
    "TIMESTAMP_COLUMN": "Datetime",
    # Loop cadence (env var: PUBLISH_INTERVAL)
    "INTERVAL_SECONDS": int(os.environ.get("PUBLISH_INTERVAL", "30")),
    # BUG-144: bldg1's wide table is the REAL abacws historian — fabricated rows
    # must never land there. Wide-table publishing is therefore opt-in (dev only);
    # the narrow synthetic-labeled tables are this publisher's actual job.
    "PUBLISH_WIDE": os.environ.get("PUBLISH_WIDE", "false").strip().lower() in ("1", "true", "yes"),
    # Batching: when >1 uses executemany per tick
    "BATCH_SIZE": 1,  # set to e.g. 50 for batch mode
    # Limits: set to 0 to run forever (recommended)
    "MAX_ROWS": 0,  # 0 = no limit, otherwise stop after N inserted rows
    # Logging
    "VERBOSE": True,
    # Backoff on errors
    "BACKOFF_INITIAL_S": 1.0,  # initial backoff
    "BACKOFF_FACTOR": 2.0,  # multiplier per failure
    "BACKOFF_MAX_S": 30.0,  # cap
}
# ===========================================================================

# Shutdown flag (set by signal handlers)
_SHOULD_STOP = False


def _signal_handler(sig, frame):
    global _SHOULD_STOP
    _SHOULD_STOP = True
    # Second signal forces immediate exit
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    print("[py-dummy] Stop requested; finishing current tick and shutting down ...", flush=True)


def register_signal_handlers():
    # Handle Ctrl+C and SIGTERM for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


def pick(seq):
    return random.choice(seq)


def rand_int(a: int, b: int) -> int:
    return random.randint(a, b)


def rand_float(a: float, b: float, decimals: int = 2) -> float:
    v = random.random() * (b - a) + a
    return round(v, decimals)


def parse_enum_options(column_type: str) -> Optional[List[str]]:
    m = re.match(r"^enum\((.*)\)$", column_type.strip(), re.IGNORECASE)
    if not m:
        return None
    inner = m.group(1)
    opts = []
    cur = ""
    in_quote = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "'":
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            opts.append(cur)
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    if cur:
        opts.append(cur)
    cleaned = [s.strip().strip("'").replace("\\'", "'") for s in opts]
    return cleaned


def connect_mysql(cfg) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["db"],
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        # Stamp rows in the SAME clock every reader uses (BUG-403).
        #
        # mysql_adapter pins its own sessions to UTC and its comment states that "the
        # dummy-data generator writes UTC". It did not. Narrow rows are written with SQL
        # NOW() on a session that inherited the server's SYSTEM zone — BST, UTC+1 — into
        # DATETIME columns, which store what they are given without conversion. So every
        # narrow row was stamped ONE HOUR AHEAD of the clock every consumer reads with.
        #
        # The wide table hid it: its timestamp column is TIMESTAMP, which MySQL converts on
        # write and on read, so the same NOW() landed correctly there. One table type was
        # right and eighteen were wrong, which is why this survived so long.
        #
        # What it cost: any window bounded by NOW() dropped the newest hour of narrow data,
        # so the anomaly sweep saw a truncated series and a freshly injected fault was
        # outside its own window; and the freshness gate, ENFORCING since 2026-09-02, read
        # a future timestamp as current and would keep calling a dead point fresh for a
        # full hour.
        init_command="SET time_zone='+00:00'",
    )


def load_columns(conn, cfg) -> Tuple[str, List[Dict[str, object]]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name AS cname,
                   data_type   AS dtype,
                   column_type AS ctype,
                   is_nullable AS isnull,
                   numeric_precision AS nprec,
                   numeric_scale     AS nscale
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (cfg["db"], cfg["table"]),
        )
        rows = cur.fetchall()
        if not rows:
            raise RuntimeError(f"Table {cfg['db']}.{cfg['table']} not found or has no columns")
    ts_col = (cfg.get("ts_col_override") or "").strip()
    if not ts_col:
        ts = next((r for r in rows if str(r["dtype"]).lower() == "timestamp"), None)
        if not ts:
            ts = next((r for r in rows if str(r["dtype"]).lower() == "datetime"), None)
        if not ts:
            ts = next((r for r in rows if "time" in str(r["dtype"]).lower()), None)
        if not ts:
            raise RuntimeError(
                "No timestamp/datetime column detected; set TIMESTAMP_COLUMN in SETTINGS"
            )
        ts_col = ts["cname"]
    value_cols = [r for r in rows if r["cname"] != ts_col]
    return ts_col, value_cols


def gen_value(col: Dict[str, object]):
    """Generate value using both sensor semantics and schema constraints."""
    uuid = col["cname"]
    sensor_name = SENSOR_MAP.get(uuid)
    dt = str(col["dtype"]).lower()
    ctype = str(col["ctype"]).lower()

    # Try realistic value generation if sensor is known
    if sensor_name:
        enum_opts = parse_enum_options(ctype) if dt == "enum" else None
        val = get_realistic_value(sensor_name, uuid, enum_opts)
        if val is not None:
            return val

    # Fallback to generic generation based on data type
    if dt == "enum":
        opts = parse_enum_options(ctype) or []
        return pick(opts) if opts else None
    if dt == "tinyint":
        return rand_int(0, 1)
    if dt == "smallint":
        return rand_int(0, 2000)
    if dt in ("mediumint", "int", "integer"):
        return rand_int(0, 100000)
    if dt == "bigint":
        return rand_int(0, 10000000)
    if dt in ("decimal", "numeric"):
        try:
            scale = int(col.get("nscale") or 2)
            prec = int(col.get("nprec") or 10)
        except Exception:
            scale, prec = 2, 10
        max_val = (10 ** max(1, prec - scale)) - 1
        return rand_float(0, max(1, min(max_val, 10000)), min(6, scale or 2))
    if dt in ("float", "double", "real"):
        return rand_float(0, 1000, 3)
    if dt == "bit":
        return rand_int(0, 1)
    if dt in ("varchar", "char", "text", "tinytext", "mediumtext", "longtext"):
        return f"val_{rand_int(0, 99999)}"
    if dt in ("date", "datetime", "timestamp"):
        return None  # handled by NOW()
    isnull = str(col.get("isnull", "")).upper() == "YES"
    return None if isnull else f"val_{rand_int(0, 9999)}"


def build_insert_sql(cfg, ts_col: str, cols: List[Dict[str, object]]):
    col_names = [ts_col] + [c["cname"] for c in cols]
    placeholders = ["NOW()"] + ["%s" for _ in cols]
    sql = (
        f"INSERT INTO `{cfg['db']}`.`{cfg['table']}` ("
        + ", ".join([f"`{n}`" for n in col_names])
        + ") VALUES ("
        + ", ".join(placeholders)
        + ")"
    )
    return sql


def make_row_values(cols: List[Dict[str, object]]):
    return [gen_value(c) for c in cols]


def insert_single(conn, sql: str, vals: List[object], verbose=False):
    global LAST_SENT_DATA
    with conn.cursor() as cur:
        cur.execute(sql, vals)
    # Store last sent data for debug logging
    LAST_SENT_DATA = {"sql": sql, "values": vals, "timestamp": time.time()}
    if verbose:
        print("[py-dummy] Inserted 1 row", flush=True)


def insert_batch(conn, sql: str, rows: List[List[object]], verbose=False):
    global LAST_SENT_DATA
    # Temporarily disable autocommit for batch, then commit once
    prev_autocommit = conn.get_autocommit()
    try:
        conn.autocommit(False)
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.autocommit(prev_autocommit)
    # Store last sent data for debug logging (just the first row)
    if rows:
        LAST_SENT_DATA = {"sql": sql, "values": rows[0], "timestamp": time.time()}
    if verbose:
        print(f"[py-dummy] Inserted batch of {len(rows)} rows", flush=True)


def print_debug_sample(cols: List[Dict[str, object]]):
    """Print a sample of the last sent data with sensor names for debugging."""
    global LAST_DEBUG_TIME
    current_time = time.time()

    # Print every 5 minutes (300 seconds)
    if current_time - LAST_DEBUG_TIME < 300:
        return

    LAST_DEBUG_TIME = current_time

    if not LAST_SENT_DATA:
        return

    print("\n" + "=" * 80, flush=True)
    print("[DEBUG] Sample of last sent data:", flush=True)
    print("=" * 80, flush=True)

    vals = LAST_SENT_DATA.get("values", [])
    timestamp = LAST_SENT_DATA.get("timestamp", 0)
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}", flush=True)
    print(f"Total columns: {len(vals)}", flush=True)
    print("\nSample values (first 20):", flush=True)

    for i, (col, val) in enumerate(zip(cols[:20], vals[:20])):
        uuid = col.get("cname", "unknown")
        sensor_name = SENSOR_MAP.get(uuid, "unknown sensor")
        data_type = str(col.get("dtype", "unknown"))
        print(f"  [{i+1:2}] {sensor_name[:45]:45} = {val!r:15} ({data_type})", flush=True)

    if len(vals) > 20:
        print(f"  ... and {len(vals) - 20} more columns", flush=True)

    print("=" * 80 + "\n", flush=True)


def main() -> int:
    cfg = {
        "host": SETTINGS["HOST"],
        "port": int(SETTINGS["PORT"]),
        "user": SETTINGS["USER"],
        "password": SETTINGS["PASSWORD"],
        "db": SETTINGS["DB"],
        "table": SETTINGS["TABLE"],
        "ts_col_override": SETTINGS.get("TIMESTAMP_COLUMN") or "",
    }
    interval = max(0, int(SETTINGS.get("INTERVAL_SECONDS", 10)))
    verbose = bool(SETTINGS.get("VERBOSE", False))
    batch_size = max(1, int(SETTINGS.get("BATCH_SIZE", 1)))
    max_rows = int(SETTINGS.get("MAX_ROWS", 0))
    backoff = float(SETTINGS.get("BACKOFF_INITIAL_S", 1.0))
    backoff_factor = float(SETTINGS.get("BACKOFF_FACTOR", 2.0))
    backoff_cap = float(SETTINGS.get("BACKOFF_MAX_S", 30.0))

    register_signal_handlers()

    if verbose:
        print(
            f"[py-dummy] Connecting to MySQL {cfg['host']}:{cfg['port']} db={cfg['db']}", flush=True
        )

    conn = connect_mysql(cfg)

    # Load sensor and schema maps
    load_sensor_map()
    load_schema_map()
    load_narrow_sensors()
    load_extended_sensors()

    try:
        publish_wide = bool(SETTINGS.get("PUBLISH_WIDE", False))
        ts_col, cols, sql = None, [], None
        if publish_wide:
            ts_col, cols = load_columns(conn, cfg)
            cols = [c for c in cols if c and c.get("cname") is not None]
            sql = build_insert_sql(cfg, ts_col, cols)

            if verbose:
                mode = "batch" if batch_size > 1 else "single"
                limit = "infinite" if max_rows == 0 else str(max_rows)
                print(
                    f"[py-dummy] Target: {cfg['db']}.{cfg['table']}, ts: {ts_col}, value cols: {len(cols)}",
                    flush=True,
                )
                print(
                    f"[py-dummy] Mode={mode}, batch_size={batch_size}, interval={interval}s, max_rows={limit}",
                    flush=True,
                )
        elif verbose:
            print(
                f"[py-dummy] Wide-table publishing DISABLED (PUBLISH_WIDE=false, BUG-144) — "
                f"`{cfg['db']}`.`{cfg['table']}` will not be written; narrow tables only",
                flush=True,
            )

        total = 0
        while True:
            if _SHOULD_STOP:
                break

            # Start of this tick, so the sleep below can subtract the work from the interval.
            _tick_started = time.time()
            try:
                if publish_wide:
                    if batch_size == 1:
                        vals = make_row_values(cols)
                        insert_single(conn, sql, vals, verbose=verbose)
                        total += 1
                    else:
                        rows = [make_row_values(cols) for _ in range(batch_size)]
                        insert_batch(conn, sql, rows, verbose=verbose)
                        total += len(rows)

                # Live-publish the narrow per-modality tables (the publisher's real job).
                publish_narrow(conn, verbose=verbose)
                # Live-publish the extended narrow tables (floors 0-4 + synthetic sensors).
                publish_extended(conn, verbose=verbose)

                # Print debug sample every 5 minutes
                if publish_wide:
                    print_debug_sample(cols)

                # reset backoff after a successful tick
                backoff = float(SETTINGS.get("BACKOFF_INITIAL_S", 1.0))

                if max_rows and total >= max_rows:
                    break

                # Sleep the REMAINDER of the interval, not the whole of it.
                #
                # PUBLISH_INTERVAL=30 is meant to be the cadence, and this slept 30s AFTER
                # the work. That was invisible while the pass wrote 19 narrow points; once
                # it wrote the 1,528 the ontology actually registers (BUG-390) the pass took
                # ~10s and the observed spacing drifted to ~40s. Measuring the elapsed time
                # and sleeping the difference makes the env var mean what it says, and a
                # pass that overruns simply starts the next one immediately rather than
                # falling further behind every tick.
                if interval > 0:
                    remaining = interval - (time.time() - _tick_started)
                    while remaining > 0 and not _SHOULD_STOP:
                        time.sleep(min(1.0, remaining))
                        remaining = interval - (time.time() - _tick_started)
            except KeyboardInterrupt:
                # Redundant due to signal handler but keeps behavior consistent
                break
            except Exception as e:
                # Log and back off, then retry until stopped
                print(
                    f"[py-dummy] Error during insert: {e}. Backing off {backoff:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
                slept = 0.0
                while slept < backoff and not _SHOULD_STOP:
                    time.sleep(0.2)
                    slept += 0.2
                backoff = min(backoff * backoff_factor, backoff_cap)
                # On some network failures, reconnect
                try:
                    conn.ping(reconnect=True)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = connect_mysql(cfg)

        if verbose:
            print(f"[py-dummy] Stopping. Inserted total {total} rows.", flush=True)
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
