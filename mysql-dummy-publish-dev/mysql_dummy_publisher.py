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
import os
import random
import re
import sys
import time
import signal
import json
from typing import Dict, List, Optional, Tuple

try:
    import pymysql
except Exception:
    print("PyMySQL is required. Install it with: pip install PyMySQL", file=sys.stderr)
    raise

# Global maps
SENSOR_MAP = {}      # UUID -> Sensor Name
SCHEMA_MAP = {}      # UUID -> {data_type, precision, scale}

# Debug tracking
LAST_SENT_DATA = {}  # Stores last sent row for debug logging
LAST_DEBUG_TIME = 0  # Timestamp of last debug print

def load_sensor_map(filepath='sensor_uuids.json'):
    global SENSOR_MAP
    try:
        # Resolve path relative to script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)
        
        with open(full_path, 'r') as f:
            data = json.load(f)
            # Create reverse map: UUID -> Name
            SENSOR_MAP = {v: k for k, v in data.items()}
        print(f"[py-dummy] Loaded {len(SENSOR_MAP)} sensors from {filepath}")
    except Exception as e:
        print(f"[py-dummy] Warning: Could not load sensor map from {filepath}: {e}")

def load_schema_map(filepath='postgresql columns.csv'):
    # global SCHEMA_MAP  # Not needed for in-place modification
    try:
        import csv
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)
        
        with open(full_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                uuid = row['COLUMN_NAME']
                data_type = row['DATA_TYPE']
                precision = row.get('NUMERIC_PRECISION', 'NULL')
                scale = row.get('NUMERIC_SCALE', 'NULL')
                
                # Skip the Datetime column
                if uuid.lower() == 'datetime':
                    continue
                    
                SCHEMA_MAP[uuid] = {
                    'data_type': data_type,
                    'precision': int(precision) if precision != 'NULL' else None,
                    'scale': int(scale) if scale != 'NULL' else None
                }
        print(f"[py-dummy] Loaded {len(SCHEMA_MAP)} column schemas from {filepath}")
    except Exception as e:
        print(f"[py-dummy] Warning: Could not load schema map from {filepath}: {e}")

def get_realistic_value(sensor_name, uuid, enum_opts=None):
    """Generate realistic value based on sensor name and schema type."""
    name = sensor_name.lower()
    schema = SCHEMA_MAP.get(uuid, {})
    data_type = schema.get('data_type', '').lower()
    precision = schema.get('precision')
    scale = schema.get('scale', 2)
    
    # Temperature (18-28 C) - DECIMAL(6,2)
    if 'temperature' in name:
        return round(random.uniform(18.0, 28.0), scale or 2)
    
    # Humidity (30-70 %) - DECIMAL(6,2) or DECIMAL(8,2)
    if 'humidity' in name:
        return round(random.uniform(30.0, 70.0), scale or 2)
        
    # CO2 (400-1200 ppm) - DECIMAL(8,2)
    if 'co2' in name:
        if data_type == 'decimal':
            return round(random.uniform(400.0, 1200.0), scale or 2)
        return random.randint(400, 1200)
        
    # TVOC (0-500 ppb) - SMALLINT
    if 'tvoc' in name:
        return random.randint(0, 500)
        
    # Noise/Sound (30-80 dB) - SMALLINT
    if 'noise' in name or 'sound' in name:
        return random.randint(30, 80)
        
    # Illuminance/Light (0-1000 lux) - SMALLINT
    if 'illuminance' in name or 'light' in name:
        return random.randint(0, 1000)
        
    # Occupancy/Motion (0 or 1) - TINYINT
    if 'occupancy' in name or 'motion' in name:
        return random.choice([0, 1])
        
    # Air Quality Level (Enum) - ENUM
    if 'air_quality_level' in name:
        if enum_opts:
            return random.choice(enum_opts)
        return None

    # Air Quality (Index 0-500) - SMALLINT
    if 'air_quality' in name and 'level' not in name:
        return random.randint(0, 150)

    return None

# ============================ SETTINGS (edit me) ============================
SETTINGS = {
    # Connection
    'HOST': 'localhost',
    'PORT': 3307,
    'USER': 'thingsboard',
    'PASSWORD': 'thingsboard',
    'DB': 'sensordb',
    'TABLE': 'sensor_data',

    # Timestamp column: leave empty to auto-detect first TIMESTAMP/DATETIME
    'TIMESTAMP_COLUMN': 'Datetime',

    # Loop cadence
    'INTERVAL_SECONDS': 30,     # delay between insert ticks

    # Batching: when >1 uses executemany per tick
    'BATCH_SIZE': 1,            # set to e.g. 50 for batch mode

    # Limits: set to 0 to run forever (recommended)
    'MAX_ROWS': 0,              # 0 = no limit, otherwise stop after N inserted rows

    # Logging
    'VERBOSE': True,

    # Backoff on errors
    'BACKOFF_INITIAL_S': 1.0,   # initial backoff
    'BACKOFF_FACTOR': 2.0,      # multiplier per failure
    'BACKOFF_MAX_S': 30.0,      # cap
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
    cur = ''
    in_quote = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == "'":
            in_quote = not in_quote
        elif ch == ',' and not in_quote:
            opts.append(cur)
            cur = ''
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
        host=cfg['host'], port=cfg['port'], user=cfg['user'], password=cfg['password'], database=cfg['db'],
        autocommit=True, cursorclass=pymysql.cursors.DictCursor
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
            (cfg['db'], cfg['table'])
        )
        rows = cur.fetchall()
        if not rows:
            raise RuntimeError(f"Table {cfg['db']}.{cfg['table']} not found or has no columns")
    ts_col = (cfg.get('ts_col_override') or '').strip()
    if not ts_col:
        ts = next((r for r in rows if str(r['dtype']).lower() == 'timestamp'), None)
        if not ts:
            ts = next((r for r in rows if str(r['dtype']).lower() == 'datetime'), None)
        if not ts:
            ts = next((r for r in rows if 'time' in str(r['dtype']).lower()), None)
        if not ts:
            raise RuntimeError('No timestamp/datetime column detected; set TIMESTAMP_COLUMN in SETTINGS')
        ts_col = ts['cname']
    value_cols = [r for r in rows if r['cname'] != ts_col]
    return ts_col, value_cols

def gen_value(col: Dict[str, object]):
    """Generate value using both sensor semantics and schema constraints."""
    uuid = col['cname']
    sensor_name = SENSOR_MAP.get(uuid)
    dt = str(col['dtype']).lower()
    ctype = str(col['ctype']).lower()

    # Try realistic value generation if sensor is known
    if sensor_name:
        enum_opts = parse_enum_options(ctype) if dt == 'enum' else None
        val = get_realistic_value(sensor_name, uuid, enum_opts)
        if val is not None:
            return val

    # Fallback to generic generation based on data type
    if dt == 'enum':
        opts = parse_enum_options(ctype) or []
        return pick(opts) if opts else None
    if dt == 'tinyint':
        return rand_int(0, 1)
    if dt == 'smallint':
        return rand_int(0, 2000)
    if dt in ('mediumint', 'int', 'integer'):
        return rand_int(0, 100000)
    if dt == 'bigint':
        return rand_int(0, 10000000)
    if dt in ('decimal', 'numeric'):
        try:
            scale = int(col.get('nscale') or 2)
            prec = int(col.get('nprec') or 10)
        except Exception:
            scale, prec = 2, 10
        max_val = (10 ** max(1, prec - scale)) - 1
        return rand_float(0, max(1, min(max_val, 10000)), min(6, scale or 2))
    if dt in ('float', 'double', 'real'):
        return rand_float(0, 1000, 3)
    if dt == 'bit':
        return rand_int(0, 1)
    if dt in ('varchar', 'char', 'text', 'tinytext', 'mediumtext', 'longtext'):
        return f"val_{rand_int(0, 99999)}"
    if dt in ('date', 'datetime', 'timestamp'):
        return None  # handled by NOW()
    isnull = str(col.get('isnull', '')).upper() == 'YES'
    return None if isnull else f"val_{rand_int(0, 9999)}"

def build_insert_sql(cfg, ts_col: str, cols: List[Dict[str, object]]):
    col_names = [ts_col] + [c['cname'] for c in cols]
    placeholders = ['NOW()'] + ['%s' for _ in cols]
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
    LAST_SENT_DATA = {'sql': sql, 'values': vals, 'timestamp': time.time()}
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
        LAST_SENT_DATA = {'sql': sql, 'values': rows[0], 'timestamp': time.time()}
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
    
    vals = LAST_SENT_DATA.get('values', [])
    timestamp = LAST_SENT_DATA.get('timestamp', 0)
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}", flush=True)
    print(f"Total columns: {len(vals)}", flush=True)
    print("\nSample values (first 20):", flush=True)
    
    for i, (col, val) in enumerate(zip(cols[:20], vals[:20])):
        uuid = col.get('cname', 'unknown')
        sensor_name = SENSOR_MAP.get(uuid, 'unknown sensor')
        data_type = str(col.get('dtype', 'unknown'))
        print(f"  [{i+1:2}] {sensor_name[:45]:45} = {val!r:15} ({data_type})", flush=True)
    
    if len(vals) > 20:
        print(f"  ... and {len(vals) - 20} more columns", flush=True)
    
    print("=" * 80 + "\n", flush=True)

def main() -> int:
    cfg = {
        'host': SETTINGS['HOST'],
        'port': int(SETTINGS['PORT']),
        'user': SETTINGS['USER'],
        'password': SETTINGS['PASSWORD'],
        'db': SETTINGS['DB'],
        'table': SETTINGS['TABLE'],
        'ts_col_override': SETTINGS.get('TIMESTAMP_COLUMN') or '',
    }
    interval = max(0, int(SETTINGS.get('INTERVAL_SECONDS', 10)))
    verbose = bool(SETTINGS.get('VERBOSE', False))
    batch_size = max(1, int(SETTINGS.get('BATCH_SIZE', 1)))
    max_rows = int(SETTINGS.get('MAX_ROWS', 0))
    backoff = float(SETTINGS.get('BACKOFF_INITIAL_S', 1.0))
    backoff_factor = float(SETTINGS.get('BACKOFF_FACTOR', 2.0))
    backoff_cap = float(SETTINGS.get('BACKOFF_MAX_S', 30.0))

    register_signal_handlers()

    if verbose:
        print(f"[py-dummy] Connecting to MySQL {cfg['host']}:{cfg['port']} db={cfg['db']}", flush=True)

    conn = connect_mysql(cfg)

    # Load sensor and schema maps
    load_sensor_map()
    load_schema_map()

    try:
        ts_col, cols = load_columns(conn, cfg)
        cols = [c for c in cols if c and c.get('cname') is not None]
        sql = build_insert_sql(cfg, ts_col, cols)

        if verbose:
            mode = "batch" if batch_size > 1 else "single"
            limit = "infinite" if max_rows == 0 else str(max_rows)
            print(f"[py-dummy] Target: {cfg['db']}.{cfg['table']}, ts: {ts_col}, value cols: {len(cols)}", flush=True)
            print(f"[py-dummy] Mode={mode}, batch_size={batch_size}, interval={interval}s, max_rows={limit}", flush=True)

        total = 0
        while True:
            if _SHOULD_STOP:
                break

            try:
                if batch_size == 1:
                    vals = make_row_values(cols)
                    insert_single(conn, sql, vals, verbose=verbose)
                    total += 1
                else:
                    rows = [make_row_values(cols) for _ in range(batch_size)]
                    insert_batch(conn, sql, rows, verbose=verbose)
                    total += len(rows)

                # Print debug sample every 5 minutes
                print_debug_sample(cols)

                # reset backoff after a successful tick
                backoff = float(SETTINGS.get('BACKOFF_INITIAL_S', 1.0))

                if max_rows and total >= max_rows:
                    break

                # Sleep only if we’re not stopping
                if interval > 0:
                    for _ in range(interval):
                        if _SHOULD_STOP:
                            break
                        time.sleep(1)
            except KeyboardInterrupt:
                # Redundant due to signal handler but keeps behavior consistent
                break
            except Exception as e:
                # Log and back off, then retry until stopped
                print(f"[py-dummy] Error during insert: {e}. Backing off {backoff:.1f}s", file=sys.stderr, flush=True)
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

if __name__ == '__main__':
    raise SystemExit(main())
