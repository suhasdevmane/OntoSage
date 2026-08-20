#!/usr/bin/env python3
"""Building-agnostic synthetic time-series generator (portability tooling).

Reads every (uuid, most-specific Brick class) for the ACTIVE building from GraphDB,
then builds/fills a WIDE ``sensor_data`` table (``datetime`` + one DOUBLE column per
uuid) in the active MySQL database with realistic synthetic history keyed by modality.
Grants the app user read access so the storage adapter can query it.

Zero building literals — the uuid set comes from the graph and the DB from env. Run it
inside the orchestrator container (has pymysql + reaches graphdb:7200 and MySQL):

    docker compose exec -T orchestrator python - < scripts/generate_dummy_timeseries.py

Env: GRAPHDB_QUERY_URL, MYSQL_HOST/PORT, MYSQL_ROOT_PASSWORD (DDL+GRANT), MYSQL_USER
(app user to grant), MYSQL_DATABASE, plus HISTORY_HOURS / STEP_MINUTES (optional).
"""
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta

import pymysql

_BID = os.environ.get("BUILDING_ID", "")
# GRAPHDB repo 'bldg' is the SINGLE shared repository for every building (buildings are
# distinguished by ontology namespace, not by repo) — so this default is building-agnostic.
GRAPHDB = os.environ.get("GRAPHDB_QUERY_URL", "http://graphdb:7200/repositories/bldg")
HOST = os.environ.get("MYSQL_HOST", "host.docker.internal")
PORT = int(os.environ.get("MYSQL_PORT", "3306"))
ROOT_PW = os.environ.get("MYSQL_ROOT_PASSWORD") or os.environ.get("MYSQL_PASSWORD", "mysql")
APP_USER = os.environ.get("MYSQL_USER", "ontosage")
# DB derives from the active BUILDING_ID (no hardcoded building) — env still wins if set.
DB = os.environ.get("MYSQL_DATABASE") or (f"{_BID}_sensordb" if _BID else "sensordb")
HOURS = int(os.environ.get("HISTORY_HOURS", "336"))  # 14 days hourly
STEP = int(os.environ.get("STEP_MINUTES", "60"))

# modality keyword -> (base, daily_amplitude, noise, has_daily_cycle)
RANGES = [
    ("chilled_water", (9.0, 2.0, 0.5, True)),
    ("hot_water", (55.0, 6.0, 1.0, True)),
    ("supply_water", (50.0, 6.0, 1.0, True)),
    ("water_temperature", (14.0, 4.0, 0.8, True)),
    ("zone_air_temperature", (21.5, 2.0, 0.4, True)),
    ("air_temperature", (21.0, 2.5, 0.5, True)),
    ("temperature", (21.0, 2.5, 0.5, True)),
    ("co2", (600.0, 250.0, 40.0, True)),
    ("carbon_dioxide", (600.0, 250.0, 40.0, True)),
    ("humidity", (45.0, 12.0, 3.0, True)),
    ("particulate", (18.0, 12.0, 4.0, True)),
    ("pm", (18.0, 12.0, 4.0, True)),
    ("air_quality", (35.0, 20.0, 6.0, True)),
    ("occupancy", (8.0, 8.0, 2.0, True)),
    ("energy", (30.0, 20.0, 4.0, True)),
    ("power", (2.5, 1.8, 0.3, True)),
    ("air_flow", (0.6, 0.4, 0.1, True)),
    ("water_flow", (12.0, 8.0, 2.0, True)),
    ("flow", (15.0, 10.0, 3.0, True)),
    ("differential_pressure", (25.0, 15.0, 4.0, True)),
    ("static_pressure", (250.0, 120.0, 25.0, True)),
    ("pressure", (101.3, 0.6, 0.15, False)),
    ("illuminance", (350.0, 250.0, 40.0, True)),
    ("light", (350.0, 250.0, 40.0, True)),
    ("noise", (45.0, 15.0, 5.0, True)),
    ("sound", (45.0, 15.0, 5.0, True)),
    ("wind_speed", (3.0, 3.0, 1.0, True)),
    ("voltage", (230.0, 5.0, 1.0, False)),
    ("current", (5.0, 3.0, 0.8, True)),
    ("setpoint", (21.0, 0.5, 0.05, False)),
]
DEFAULT = (50.0, 20.0, 5.0, True)


def sparql(query):
    req = urllib.request.Request(
        GRAPHDB,
        data=query.encode(),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["results"]["bindings"]


# Wide-table store keys: ONLY points whose ref:storedAt local name is listed here
# become wide-table columns. Narrow-stored points (occupancy_data, co2_data, ...)
# have their own tables and adapters — adding them as wide columns bloated the
# table past MySQL's 8126-byte row limit when the V4 saturation TTLs landed.
WIDE_STORE_KEYS = {
    k.strip()
    for k in os.environ.get("WIDE_STORE_KEYS", "database1,database2").split(",")
    if k.strip()
}
BLDG_NS = os.environ.get("BUILDING_NAMESPACE", "")


def fetch_points():
    """{uuid: best_class} for the active building's WIDE-stored points only.

    storedAt filter: narrow per-modality points must never become wide columns.
    Namespace filter: never pick up another building's points from a shared
    repo state (BUG-105 class).
    """
    ns_filter = f'FILTER(STRSTARTS(STR(?s), "{BLDG_NS}"))' if BLDG_NS else ""
    rows = sparql(
        f"""PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
        SELECT ?uuid ?cls ?st WHERE {{
          ?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid .
          ?r ref:storedAt ?st .
          {ns_filter}
          OPTIONAL {{ ?s a ?cls FILTER(STRSTARTS(STR(?cls),"https://brickschema.org")) }}
        }}"""
    )
    pts = {}
    for b in rows:
        st_local = b.get("st", {}).get("value", "").split("#")[-1].split("/")[-1]
        if st_local not in WIDE_STORE_KEYS:
            continue
        u = b["uuid"]["value"]
        cls = b.get("cls", {}).get("value", "")
        cls = cls.split("#")[-1].split("/")[-1]
        cur = pts.get(u, "")
        # prefer the most specific (longest) class name
        if len(cls) > len(cur):
            pts[u] = cls
    return pts


def range_for(cls):
    c = cls.lower()
    for kw, rng in RANGES:
        if kw in c:
            return rng
    return DEFAULT


def value_at(rng, ts, seed):
    base, amp, noise, daily = rng
    random.seed((hash(seed) ^ hash(ts.strftime("%Y%m%d%H%M"))) & 0xFFFFFFFF)
    v = base
    if daily:
        hour = ts.hour + ts.minute / 60.0
        v += amp * math.sin((hour - 6.0) / 24.0 * 2.0 * math.pi)  # afternoon peak
    v += random.uniform(-noise, noise)
    return round(max(0.0, v), 3)


def main():
    print(f"[gen] GraphDB={GRAPHDB}  MySQL={HOST}:{PORT}/{DB}  history={HOURS}h/{STEP}min")
    points = fetch_points()
    print(f"[gen] {len(points)} time-series points from the graph")
    if not points:
        raise SystemExit("no points with hasTimeseriesId — is the ontology loaded?")
    uuids = sorted(points)
    rng = {u: range_for(points[u]) for u in uuids}

    conn = pymysql.connect(
        host=HOST, port=PORT, user="root", password=ROOT_PW, database=DB, autocommit=True
    )
    cur = conn.cursor()
    cols = ", ".join(f"`{u}` DOUBLE NULL" for u in uuids)
    cur.execute("DROP TABLE IF EXISTS sensor_data")
    cur.execute(f"CREATE TABLE sensor_data (`datetime` DATETIME PRIMARY KEY, {cols})")
    print(f"[gen] created sensor_data ({len(uuids)} uuid columns)")

    now = datetime.utcnow().replace(second=0, microsecond=0, minute=0)
    start = now - timedelta(hours=HOURS)
    collist = "`datetime`, " + ", ".join(f"`{u}`" for u in uuids)
    ph = ", ".join(["%s"] * (len(uuids) + 1))
    sql = f"INSERT INTO sensor_data ({collist}) VALUES ({ph})"
    batch, total, t = [], 0, start
    while t <= now:
        batch.append((t, *[value_at(rng[u], t, u) for u in uuids]))
        t += timedelta(minutes=STEP)
        if len(batch) >= 40:
            cur.executemany(sql, batch)
            total += len(batch)
            batch = []
    if batch:
        cur.executemany(sql, batch)
        total += len(batch)
    print(f"[gen] inserted {total} rows (through {now} UTC)")

    # grant the app user read access so the storage adapter can query it
    for host_pat in ("%", "localhost"):
        try:
            cur.execute(f"GRANT SELECT ON `{DB}`.* TO '{APP_USER}'@'{host_pat}'")
        except Exception as e:  # user@host may not exist for both patterns
            print(f"[gen] grant {APP_USER}@{host_pat}: {str(e)[:70]}")
    cur.execute("FLUSH PRIVILEGES")
    print(f"[gen] granted SELECT on {DB}.* to {APP_USER}")
    conn.close()
    print("[gen] done")


def _ensure_table_and_columns(cur, uuids):
    """Create sensor_data if missing (NEVER drop → preserves history across restarts) and
    ALTER-ADD a column for any uuid not yet present. Grants the app user read on new columns.
    Returns the count of columns added. Building-agnostic."""
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name='sensor_data'",
        (DB,),
    )
    if cur.fetchone()[0] == 0:
        cur.execute("CREATE TABLE sensor_data (`datetime` DATETIME PRIMARY KEY)")
        print("[gen] created empty sensor_data (no history dropped)", flush=True)
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='sensor_data'",
        (DB,),
    )
    have = {r[0] for r in cur.fetchall()}
    added = 0
    for u in uuids:
        if u not in have:
            cur.execute(f"ALTER TABLE sensor_data ADD COLUMN `{u}` DOUBLE NULL")
            added += 1
    if added:
        print(f"[gen] added {added} new sensor column(s)", flush=True)
        for host_pat in ("%", "localhost"):
            try:
                cur.execute(f"GRANT SELECT ON `{DB}`.* TO '{APP_USER}'@'{host_pat}'")
            except Exception:
                pass
        cur.execute("FLUSH PRIVILEGES")
    return added


# ── V4-T11: live append for SATURATE narrow sensors ─────────────────────────
# The wide loop above serves the building's native points; saturation sensors
# live in narrow per-modality tables and get their current 10-min-grid value
# from the SAME deterministic signal model the backfill used — so live rows
# continue the backfilled series without a seam.
_SAT_MARKER = "synthetic-saturation-v4"
_sat_state = {"points": [], "day": None, "series": {}, "import_warned": False}

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_DIR not in sys.path:
    sys.path.insert(0, _REPO_DIR)


def fetch_sat_points():
    """[(uuid, table, space_local, modality)] for the active building's sat sensors."""
    ns_filter = f'FILTER(STRSTARTS(STR(?s), "{BLDG_NS}"))' if BLDG_NS else ""
    rows = sparql(
        f"""PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?s ?uuid ?st WHERE {{
          ?s rdfs:comment "{_SAT_MARKER}" ;
             ref:hasExternalReference [ ref:hasTimeseriesId ?uuid ; ref:storedAt ?st ] .
          {ns_filter}
        }}"""
    )
    pts = []
    for b in rows:
        local = b["s"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if "_sat_" not in local:
            continue
        space_local, modality = local.rsplit("_sat_", 1)
        table = b["st"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        pts.append((b["uuid"]["value"], table, space_local, modality))
    return pts


def publish_sat_tick(cur, now):
    """Write the current 10-min-grid value for every sat sensor (INSERT IGNORE)."""
    pts = _sat_state["points"]
    if not pts:
        return
    try:
        from orchestrator.services.deliberation.synthetic_signals import (
            STEP_MINUTES,
            generate_room_day,
        )
    except Exception as e:  # container without the module — degrade, never die
        if not _sat_state["import_warned"]:
            print(f"[gen] sat publish disabled (import failed: {str(e)[:80]})", flush=True)
            _sat_state["import_warned"] = True
        return
    from datetime import timedelta

    bid = os.environ.get("BUILDING_ID", DB.replace("_sensordb", ""))
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if _sat_state["day"] != day:
        by_room = {}
        for _u, _t, room, modality in pts:
            by_room.setdefault(room, set()).add(modality)
        _sat_state["series"] = {
            room: generate_room_day(bid, room, sorted(mods), day) for room, mods in by_room.items()
        }
        _sat_state["day"] = day
    step = (now.hour * 60 + now.minute) // STEP_MINUTES
    grid_ts = day + timedelta(minutes=step * STEP_MINUTES)
    by_table = {}
    for uuid_, table, room, modality in pts:
        series = _sat_state["series"].get(room, {}).get(modality)
        if series and step < len(series):
            by_table.setdefault(table, []).append((uuid_, grid_ts, series[step]))
    for table, rows in by_table.items():
        cur.executemany(
            f"INSERT IGNORE INTO {table} (uuid, datetime, value) VALUES (%s, %s, %s)", rows
        )


_evt_state = {"hour": None, "rooms": None, "warned": False}


def publish_events_tick(cur, now):
    """V5-T08: keep TODAY's events current (hourly regenerate + INSERT IGNORE).

    Deterministic event_ids make this idempotent: only genuinely new records
    (later work orders, the day's remaining bookings once their windows exist)
    insert; everything else is ignored on the PK.
    """
    hour = now.replace(minute=0, second=0, microsecond=0)
    if _evt_state["hour"] == hour:
        return
    try:
        from orchestrator.services.deliberation.synthetic_events import (
            generate_building_day,
            to_row,
        )
    except Exception as e:
        if not _evt_state["warned"]:
            print(f"[gen] events publish disabled (import failed: {str(e)[:80]})", flush=True)
            _evt_state["warned"] = True
        return
    if _evt_state["rooms"] is None:
        # rooms from the sat-point inventory (already graph-derived, no extra query)
        _evt_state["rooms"] = sorted({room for _u, _t, room, _m in _sat_state["points"]})
    rooms = [r for r in _evt_state["rooms"] if not r.lower().startswith(("floor", "building"))]
    if not rooms:
        return
    bid = os.environ.get("BUILDING_ID", DB.replace("_sensordb", ""))
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = generate_building_day(bid, rooms, day, now)
    if events:
        cur.executemany(
            "INSERT IGNORE INTO events "
            "(event_id, event_type, subject_uuid, start_dt, end_dt, status, attrs) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [to_row(e) for e in events],
        )
    _evt_state["hour"] = hour


def publish_loop(interval=None):
    """Keep the wide table live: append one fresh (now) row every ``interval`` seconds so
    'current reading' queries always find recent data. Building-agnostic and self-healing:

    - reads the active building's uuids from the graph and RE-READS them every
      ``PUBLISH_REFRESH_EVERY`` ticks, so sensors added after start (admin GUI, a topology/
      spatial backfill, a new TTL) automatically get a column + data with NO restart;
    - self-bootstraps: creates ``sensor_data`` if absent WITHOUT dropping existing history,
      so it is safe to run as an always-on service that survives orchestrator restarts.
    """
    interval = interval or int(os.environ.get("PUBLISH_INTERVAL", "60"))
    refresh_every = max(1, int(os.environ.get("PUBLISH_REFRESH_EVERY", "10")))
    points, uuids, rng, sql = {}, [], {}, ""
    tick = 0
    print(
        f"[gen] publisher starting → {DB}.sensor_data every {interval}s "
        f"(re-scan graph every {refresh_every} ticks)",
        flush=True,
    )
    while True:
        try:
            conn = pymysql.connect(
                host=HOST, port=PORT, user="root", password=ROOT_PW, database=DB, autocommit=True
            )
            cur = conn.cursor()
            # Periodically discover new sensors (and on the very first tick).
            if tick % refresh_every == 0 or not uuids:
                new_points = fetch_points()
                if new_points and set(new_points) != set(points):
                    points = new_points
                    uuids = sorted(points)
                    rng = {u: range_for(points[u]) for u in uuids}
                    _ensure_table_and_columns(cur, uuids)
                    collist = "`datetime`, " + ", ".join(f"`{u}`" for u in uuids)
                    ph = ", ".join(["%s"] * (len(uuids) + 1))
                    sql = f"INSERT INTO sensor_data ({collist}) VALUES ({ph})"
                    print(f"[gen] tracking {len(uuids)} sensors", flush=True)
                sat_points = fetch_sat_points()
                if len(sat_points) != len(_sat_state["points"]):
                    print(f"[gen] tracking {len(sat_points)} SATURATE narrow sensors", flush=True)
                _sat_state["points"] = sat_points
            now = datetime.utcnow().replace(microsecond=0)
            if sql:
                cur.execute(sql, (now, *[value_at(rng[u], now, u) for u in uuids]))
            publish_sat_tick(cur, now)
            publish_events_tick(cur, now)
            conn.close()
        except Exception as e:  # keep the loop alive on transient DB/graph hiccups
            print(f"[gen] publish tick failed: {str(e)[:120]}", flush=True)
        tick += 1
        time.sleep(interval)


if __name__ == "__main__":
    if "--publish" in sys.argv:
        publish_loop()
    else:
        main()
