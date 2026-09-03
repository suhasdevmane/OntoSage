#!/usr/bin/env python3
"""Load input/data CSV readings into NARROW per-modality MySQL tables (Workstream B2).

For each sensor in the extension UUID map (produced by generate_timeseries_extension.py):
  * ensure its narrow table exists  ->  (uuid CHAR(36), datetime DATETIME, value DOUBLE,
    PRIMARY KEY (uuid, datetime))
  * read input/data/<csv>.csv and upsert (uuid, timestamp, value) rows (idempotent).

Connects with the SAME MySQL env the orchestrator container uses
(MYSQL_HOST/PORT/USER/PASSWORD/DATABASE), so run it inside that container where
host.docker.internal:3306 resolves. `input/` CSVs are only a migration SOURCE — once
loaded, the DB is authoritative and the CSVs can be archived.
"""

from __future__ import annotations

import csv
import sys
import json
import os
from pathlib import Path
from typing import Dict

import pymysql

# Run directly as a script, so the repo root is not on sys.path yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db_clock import UTC_SESSION_INIT

INPUT_ROOT = Path(os.environ.get("INPUT_ROOT", "/app/input"))
MAP_PATH = INPUT_ROOT / "bldg1_timeseries_extension_uuids.json"
DATA_DIR = INPUT_ROOT / "data"

CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS `{table}` ("
    "  `uuid` CHAR(36) NOT NULL,"
    "  `datetime` DATETIME NOT NULL,"
    "  `value` DOUBLE NULL,"
    "  PRIMARY KEY (`uuid`, `datetime`),"
    "  INDEX `idx_{table}_uuid` (`uuid`)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
)
UPSERT_SQL = (
    "INSERT INTO `{table}` (`uuid`, `datetime`, `value`) VALUES (%s, %s, %s) "
    "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)"
)


def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "host.docker.internal"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "mysql"),
        database=os.environ.get("MYSQL_DATABASE", "sensordb"),
        connect_timeout=10,
        autocommit=False,
        # Same clock the rows are stamped in (BUG-403).
        init_command=UTC_SESSION_INIT,
    )


def main() -> None:
    uuid_map: Dict[str, dict] = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    conn = _connect()
    tables = sorted({e["table"] for e in uuid_map.values()})
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(CREATE_SQL.format(table=t))
    conn.commit()
    print(f"Ensured {len(tables)} narrow tables: {tables}")

    total = 0
    for local, e in uuid_map.items():
        csv_path = DATA_DIR / f"{e['csv']}.csv"
        if not csv_path.is_file():
            print(f"  SKIP {local}: {csv_path} missing")
            continue
        rows = []
        with open(csv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                ts = r.get("timestamp")
                raw = r.get(e["value_col"])
                if ts is None or raw is None or raw == "":
                    continue
                ts = ts.replace("T", " ")[:19]
                try:
                    val = float(raw)
                except ValueError:
                    continue
                rows.append((e["uuid"], ts, val))
        if not rows:
            print(f"  SKIP {local}: no rows in {csv_path.name}")
            continue
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL.format(table=e["table"]), rows)
        conn.commit()
        total += len(rows)
        print(f"  {local:30s} -> {e['table']:15s} {len(rows):5d} rows  (uuid {e['uuid'][:8]}…)")

    conn.close()
    print(f"Done. {total} rows loaded across {len(tables)} tables.")


if __name__ == "__main__":
    main()
