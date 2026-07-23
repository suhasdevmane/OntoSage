"""
Ingest a wide CSV (datetime + UUID columns) into ThingsBoard's TimescaleDB (ts_kv).

Assumptions:
- CSV header: first column named 'datetime' (ISO8601), followed by one column per sensor UUID
- Values are numeric or strings; we'll insert numerics into dbl_v, integers into long_v, booleans to bool_v, others to str_v
- Target schema is ThingsBoard SQL storage: ts_kv and ts_kv_dictionary
- Device scope:
        - Default (single-device mode): insert all columns into one device (TB_DEVICE_ID or TB_DEVICE_NAME)
        - Per-column mode (set TB_PER_COLUMN_DEVICES=true): treat each column header as a ThingsBoard ACCESS_TOKEN and
            resolve the corresponding device; ingest all columns to their respective devices in one run

Env vars:
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD, PG_SSLMODE (optional)
    TB_DEVICE_ID (uuid) or TB_DEVICE_NAME (string) [single-device mode]
    TB_PER_COLUMN_DEVICES (true/false) [enable per-column device ingestion, header == access token]
    TB_TOKEN_MAPPING_FILE (optional) [path to mapping file like sensor_uuids.txt with 'name,token' lines]

Usage (PowerShell):
    # from repo root
    $env:PG_HOST='localhost'; $env:PG_PORT='5433'; $env:PG_DATABASE='thingsboard'; $env:PG_USER='thingsboard'; $env:PG_PASSWORD='thingsboard'
    # Single-device mode
    $env:TB_DEVICE_NAME='TestDevice'
    python bldg2/trial/dataset/ingest_wide_csv_to_timescale.py bldg2/trial/dataset/synthetic_readings_wide.csv

    # Per-column devices mode (each column header is an ACCESS_TOKEN)
    $env:TB_PER_COLUMN_DEVICES='true'
    python bldg2/trial/dataset/ingest_wide_csv_to_timescale.py bldg2/trial/dataset/synthetic_readings_wide.csv

Notes:
- For large files, the script streams rows and batches inserts (default batch_size=2000 timestamps)
- It auto-creates missing keys in ts_kv_dictionary
- It upserts ts_kv rows; ts_kv primary key (entity_id, key, ts) will naturally deduplicate on retry if run within a transaction with ON CONFLICT
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
import logging
import time
from typing import Dict, List, Tuple, Optional, Any

try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.extras import execute_values
except Exception as e:
    print(f"Error: psycopg2 is required. Install psycopg2-binary. Details: {e}")
    sys.exit(2)


def _setup_logging() -> None:
    level_name = os.getenv("TB_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


logger = logging.getLogger("csv_ingester")


def pg_cfg() -> Dict[str, Any]:
    return {
        "host": os.getenv("PG_HOST", "timescaledb"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "database": os.getenv("PG_DATABASE", "thingsboard"),
        "user": os.getenv("PG_USER", "thingsboard"),
        "password": os.getenv("PG_PASSWORD", "thingsboard"),
        "sslmode": os.getenv("PG_SSLMODE", "disable"),
    }


def resolve_device(conn, device_id: Optional[str], device_name: Optional[str]) -> Optional[str]:
    if device_id:
        return device_id
    if not device_name:
        return None
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id FROM device WHERE name = %s LIMIT 1", (device_name,))
        row = cur.fetchone()
        return row["id"] if row else None


def resolve_devices_by_tokens(conn, tokens: List[str]) -> Dict[str, str]:
    """Resolve multiple ThingsBoard ACCESS_TOKEN values to device UUIDs.

    Returns a mapping token -> device_id (UUID string). Unknown tokens are omitted.
    """
    if not tokens:
        return {}
    tokens = [t for t in tokens if t]
    if not tokens:
        return {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT dc.credentials_id AS token, d.id AS device_id
            FROM device_credentials dc
            JOIN device d ON d.id = dc.device_id
            WHERE dc.credentials_type = 'ACCESS_TOKEN' AND dc.credentials_id = ANY(%s)
            """,
            (tokens,),
        )
        rows = cur.fetchall() or []
        return {str(r["token"]): str(r["device_id"]) for r in rows}


def load_token_mapping(file_path: Optional[str]) -> Dict[str, str]:
    """Load mapping of column header name -> ACCESS_TOKEN from a two-column CSV/TXT file.

    Each non-empty, non-comment line must be: name,token
    Returns empty mapping if file is missing or unreadable.
    """
    mapping: Dict[str, str] = {}
    if not file_path:
        return mapping
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split(",")
                if len(parts) >= 2:
                    name = parts[0].strip()
                    token = parts[1].strip()
                    if name and token:
                        mapping[name] = token
    except FileNotFoundError:
        # ignore silently; mapping is optional
        pass
    except Exception as e:
        print(f"Warning: failed to load token mapping file '{file_path}': {e}")
    return mapping


def ensure_keys(conn, keys: List[str]) -> Dict[str, int]:
    """Return mapping key->key_id, inserting any missing into ts_kv_dictionary."""
    if not keys:
        return {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT key, key_id FROM ts_kv_dictionary WHERE key = ANY(%s)", (keys,))
        rows = cur.fetchall() or []
        existing = {r["key"]: int(r["key_id"]) for r in rows}
        missing = [k for k in keys if k not in existing]
        if missing:
            # Insert missing keys and fetch their ids
            execute_values(cur, "INSERT INTO ts_kv_dictionary(key) VALUES %s ON CONFLICT DO NOTHING", [(k,) for k in missing])
            cur.execute("SELECT key, key_id FROM ts_kv_dictionary WHERE key = ANY(%s)", (missing,))
            for r in cur.fetchall() or []:
                existing[r["key"]] = int(r["key_id"])
        return existing


def parse_value(raw: str) -> Tuple[str, Optional[float], Optional[int], Optional[bool], Optional[str]]:
    """Return (kind, dbl_v, long_v, bool_v, str_v) based on the content of raw string."""
    s = raw.strip()
    if s == "":
        return ("null", None, None, None, None)
    # Boolean
    if s.lower() in ("true", "false"):
        return ("bool", None, None, s.lower() == "true", None)
    # Integer
    try:
        iv = int(s)
        return ("long", None, iv, None, None)
    except Exception:
        pass
    # Float
    try:
        fv = float(s)
        return ("dbl", fv, None, None, None)
    except Exception:
        pass
    # Fallback string
    return ("str", None, None, None, s)


def ingest_csv(csv_path: str, batch_size: int = 2000) -> int:
    _setup_logging()
    cfg = pg_cfg()
    device_id = os.getenv("TB_DEVICE_ID")
    device_name = os.getenv("TB_DEVICE_NAME")
    per_column = os.getenv("TB_PER_COLUMN_DEVICES", "true").strip().lower() in ("1", "true", "yes")
    log_every = int(os.getenv("TB_LOG_EVERY", "1000"))  # log progress every N CSV rows
    map_path_env = os.getenv("TB_TOKEN_MAPPING_FILE")

    # Log configuration (without secrets)
    logger.info(
        "Starting ingestion | csv=%s, batch_size=%s, per_column=%s, map_file=%s",
        os.path.basename(csv_path), batch_size, per_column, (os.path.basename(map_path_env) if map_path_env else "<default or none>")
    )
    logger.info(
        "DB config | host=%s port=%s db=%s user=%s sslmode=%s",
        cfg["host"], cfg["port"], cfg["database"], cfg["user"], cfg.get("sslmode", "disable")
    )
    if not per_column and not (device_id or device_name):
        logger.error("Set TB_DEVICE_ID or TB_DEVICE_NAME in env, or enable TB_PER_COLUMN_DEVICES=true")
        return 2
    conn = psycopg2.connect(host=cfg["host"], port=cfg["port"], dbname=cfg["database"], user=cfg["user"], password=cfg["password"], sslmode=cfg.get("sslmode", "disable"))
    conn.autocommit = False
    try:
        t0 = time.time()
        entity_id = None
        token_to_device: Dict[str, str] = {}
        if per_column:
            # Will resolve devices after reading headers
            pass
        else:
            entity_id = resolve_device(conn, device_id, device_name)
            if not entity_id:
                print(f"Error: Device not found for TB_DEVICE_NAME='{device_name}'")
                return 2

        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            if not header or header[0].lower() != "datetime":
                logger.error("first column must be 'datetime'")
                return 2
            uuid_cols = header[1:]
            logger.info("CSV header parsed | columns=%d (data columns=%d)", len(header), len(uuid_cols))
            logger.debug("First 10 data columns: %s", uuid_cols[:10])
            key_map = ensure_keys(conn, uuid_cols)
            key_ids = [key_map[u] for u in uuid_cols if u in key_map]
            if len(key_ids) != len(uuid_cols):
                missing = [u for u in uuid_cols if u not in key_map]
                logger.error("failed to register keys: %s", missing[:10])
                return 2

            if per_column:
                # Build column->token mapping: try mapping file first (name->token), else assume header is token
                default_map_path = os.path.join(os.path.dirname(__file__), "sensor_uuids.txt")
                map_path = map_path_env or default_map_path
                name_to_token = load_token_mapping(map_path)
                column_to_token: Dict[str, str] = {}
                for h in uuid_cols:
                    # Prefer mapped token if header is a name present in mapping; else treat header as the token itself
                    tok = name_to_token.get(h, h)
                    column_to_token[h] = tok.strip()

                unique_tokens = sorted({t for t in column_to_token.values() if t})
                token_to_device = resolve_devices_by_tokens(conn, unique_tokens)
                resolved_count = len(token_to_device)
                logger.info(
                    "Per-column: resolved %d/%d tokens (mapping file: %s)",
                    resolved_count, len(unique_tokens), os.path.basename(map_path) if map_path else "none"
                )
                if resolved_count:
                    sample = list(token_to_device.items())[:5]
                    if sample:
                        logger.info("Sample resolved tokens -> device_id:")
                        for tok, did in sample:
                            logger.info("  %s -> %s", tok, did)
                unresolved = [h for h, tok in column_to_token.items() if tok not in token_to_device]
                if unresolved:
                    logger.warning(
                        "Unresolved columns: %d will be skipped | sample=%s%s",
                        len(unresolved), unresolved[:10], "..." if len(unresolved) > 10 else ""
                    )

            rows_buffer: List[Tuple[int, str, int, Optional[bool], Optional[str], Optional[int], Optional[float], Optional[str]]] = []
            total = 0
            total_rows = 0
            total_nulls = 0
            buffer_flushes = 0
            column_attempts: Dict[str, int] = {h: 0 for h in uuid_cols}
            for line_num, row in enumerate(reader, start=2):
                if not row:
                    continue
                try:
                    dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                except Exception:
                    logger.warning("Skipping row %d with invalid datetime: %s", line_num, row[0])
                    continue
                ts_ms = int(dt.timestamp() * 1000)
                for col_idx, key in enumerate(uuid_cols, start=1):
                    raw = row[col_idx] if col_idx < len(row) else ""
                    kind, dbl_v, long_v, bool_v, str_v = parse_value(raw)
                    if kind == "null":
                        total_nulls += 1
                        continue
                    key_id = key_map[key]
                    # Choose device per mode
                    if per_column:
                        # Resolve device per column via mapped token
                        tok = column_to_token.get(key)
                        did = token_to_device.get(tok)
                        if not did:
                            continue  # skip columns without a resolved device
                        rows_buffer.append((ts_ms, did, key_id, bool_v, str_v, long_v, dbl_v, None))
                    else:
                        rows_buffer.append((ts_ms, entity_id, key_id, bool_v, str_v, long_v, dbl_v, None))
                    column_attempts[key] += 1
                if len(rows_buffer) >= batch_size:
                    flushed = _flush(conn, rows_buffer)
                    buffer_flushes += 1
                    total += flushed
                    logger.info("Flushed batch #%d | rows=%d | total_attempted=%d", buffer_flushes, flushed, total)
                    rows_buffer.clear()
                total_rows += 1
                if total_rows % max(1, log_every) == 0:
                    logger.info("Progress | csv_rows=%d | buffer=%d | total_attempted=%d | nulls=%d", total_rows, len(rows_buffer), total, total_nulls)
            if rows_buffer:
                flushed = _flush(conn, rows_buffer)
                buffer_flushes += 1
                total += flushed
                logger.info("Flushed final batch #%d | rows=%d | total_attempted=%d", buffer_flushes, flushed, total)
        conn.commit()
        elapsed = time.time() - t0
        # Summarize top columns by attempts
        try:
            top_cols = sorted(column_attempts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        except Exception:
            top_cols = []
        if per_column:
            devices_count = len(set(token_to_device.values())) if token_to_device else 0
            logger.info("SUMMARY | attempted_rows=%d | csv_rows=%d | nulls=%d | devices=%d | time=%.2fs", total, total_rows, total_nulls, devices_count, elapsed)
            if top_cols:
                logger.info("Top columns by values attempted: %s", top_cols)
            print(f"Inserted {total} ts_kv rows across up to {devices_count} devices in {elapsed:.2f}s")
        else:
            logger.info("SUMMARY | attempted_rows=%d | csv_rows=%d | nulls=%d | device=%s | time=%.2fs", total, total_rows, total_nulls, entity_id, elapsed)
            if top_cols:
                logger.info("Top columns by values attempted: %s", top_cols)
            print(f"Inserted {total} ts_kv rows for device {entity_id} in {elapsed:.2f}s")
        return 0
    except Exception as e:
        conn.rollback()
        logger.exception("Error ingesting CSV: %s", e)
        print(f"Error ingesting CSV: {e}")
        return 3
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _flush(conn, rows: List[Tuple[int, str, int, Optional[bool], Optional[str], Optional[int], Optional[float], Optional[str]]]) -> int:
    # Columns: ts, entity_id, key, bool_v, str_v, long_v, dbl_v, json_v
    # Use ON CONFLICT DO NOTHING to allow idempotent re-runs
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO ts_kv (ts, entity_id, key, bool_v, str_v, long_v, dbl_v, json_v)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            rows,
            page_size=10000,
        )
        # rowcount may be -1 depending on psycopg2; return attempted count as best-effort
        try:
            return cur.rowcount if isinstance(cur.rowcount, int) and cur.rowcount >= 0 else len(rows)
        except Exception:
            return len(rows)


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python ingest_wide_csv_to_timescale.py <wide_csv_path> [batch_size]")
        return 2
    csv_path = argv[1]
    batch_size = int(argv[2]) if len(argv) > 2 else 2000
    return ingest_csv(csv_path, batch_size=batch_size)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))


# DB connection
# $env:PG_HOST = 'localhost'
# $env:PG_PORT = '5433'
# $env:PG_DATABASE = 'thingsboard'
# $env:PG_USER = 'thingsboard'
# $env:PG_PASSWORD = 'thingsboard'

# # Enable per-column device mode
# $env:TB_PER_COLUMN_DEVICES = 'true'

# python ingest_wide_csv_to_timescale.py synthetic_readings_wide.csv 5000
