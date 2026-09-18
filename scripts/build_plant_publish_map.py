# -*- coding: utf-8 -*-
"""Build input/bldg1_plant_publish_map.json — equipment GROUPS, not loose points.

WHY A SEPARATE MAP AND A SEPARATE PUBLISHER.
plant_data holds CORRELATED series: a boiler's entering and leaving water temperatures are
one physical fact measured twice, and their difference IS the answer to "what's the delta-T
across the heating circuit, and is it healthy?". Publishing them as independent random walks
is what collapsed delta-T from 11.08 K to 0.12 K (BUG-638), which is why plant_data was
excluded from the ordinary narrow publish map and has had no new rows since.

So each group carries ONE seed role and derives the rest from it.

WHERE THE NUMBERS COME FROM.
The HEALTHY history, measured here, not invented and not the decayed tail: the last rows
written before publishing stopped had all drifted to ambient (~23 C on every boiler point,
delta -0.31 K, and the chiller inverted), so continuing from `last` would cement the defect.
Percentiles are taken over paired rows and exclude the decayed window.

AHU air temperatures are measured EXCLUDING near-zero rows: roughly half the history writes
~0 C whenever the fan is off, which is not what an air sensor does -- it keeps reading room
air. Flow and filter pressure legitimately fall to ~0 with the fan, and stay tied to it.
"""
import json
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())

import pymysql  # noqa: E402
import requests  # noqa: E402

from shared.config import settings  # noqa: E402

GRAPH = "http://localhost:7200/repositories/bldg"
OUT = "input/bldg1_plant_publish_map.json"

# role -> how the publisher treats it
ROLE_BY_SUFFIX = [
    # Longest first: "_Outside_Air_Damper_Position" must be tested before any shorter
    # suffix could claim part of it. A suffix table that matches on the first hit is only
    # correct if the specific entries precede the general ones.
    ("_Outside_Air_Damper_Position", "damper_position"),
    ("_Leaving_Water_Temperature", "leaving_water_temp"),
    ("_Entering_Water_Temperature", "entering_water_temp"),
    ("_Supply_Air_Temperature", "supply_air_temp"),
    ("_Return_Air_Temperature", "return_air_temp"),
    ("_Supply_Air_Flow", "supply_air_flow"),
    ("_Fan_Status", "fan_status"),
    ("_Filter_DP", "filter_dp"),
]

Q = """
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
SELECT DISTINCT ?s ?label ?uuid WHERE {
  ?s ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid ; ref:storedAt bldg:plant_data .
  OPTIONAL { ?s rdfs:label ?label }
}
"""


def role_and_group(local):
    for suffix, role in ROLE_BY_SUFFIX:
        if local.endswith(suffix):
            return role, local[: -len(suffix)]
    return None, None


def pct(values, q):
    if not values:
        return None
    vs = sorted(values)
    i = max(0, min(len(vs) - 1, int(round(q * (len(vs) - 1)))))
    return round(float(vs[i]), 3)


resp = requests.post(
    GRAPH,
    data=Q.encode("utf-8"),
    headers={
        "Content-Type": "application/sparql-query",
        "Accept": "application/sparql-results+json",
    },
    timeout=120,
)
resp.raise_for_status()

groups = defaultdict(dict)
skipped = []
for b in resp.json()["results"]["bindings"]:
    local = b["s"]["value"].rsplit("#", 1)[-1]
    role, group = role_and_group(local)
    if role is None:
        skipped.append(local)
        continue
    groups[group][role] = {"uuid": b["uuid"]["value"], "point": local}

print(f"groups: {len(groups)}   points: {sum(len(v) for v in groups.values())}")
if skipped:
    print(f"  NO ROLE (not published, deliberately): {sorted(set(skipped))}")

conn = pymysql.connect(
    host="127.0.0.1",
    port=int(getattr(settings, "MYSQL_PORT", 3306) or 3306),
    user=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD,
    database=settings.MYSQL_DATABASE,
    init_command="SET time_zone = '+00:00'",
)


def series(cur, uuid, where_extra=""):
    cur.execute(
        f"SELECT value FROM plant_data WHERE uuid=%s {where_extra} "
        f"AND datetime < UTC_TIMESTAMP() - INTERVAL 1 DAY",
        (uuid,),
    )
    return [float(r[0]) for r in cur.fetchall() if r[0] is not None]


def paired_delta(cur, hi_uuid, lo_uuid, where_extra=""):
    cur.execute(
        f"SELECT a.value - b.value FROM plant_data a JOIN plant_data b "
        f"ON a.datetime = b.datetime WHERE a.uuid=%s AND b.uuid=%s {where_extra} "
        f"AND a.datetime < UTC_TIMESTAMP() - INTERVAL 1 DAY",
        (hi_uuid, lo_uuid),
    )
    return [float(r[0]) for r in cur.fetchall() if r[0] is not None]


out = {"table": "plant_data", "groups": []}
with conn.cursor() as cur:
    for name, roles in sorted(groups.items()):
        spec = {"group": name, "roles": {}}

        if "leaving_water_temp" in roles and "entering_water_temp" in roles:
            lead, follow = "leaving_water_temp", "entering_water_temp"
        elif "supply_air_temp" in roles and "return_air_temp" in roles:
            lead, follow = "supply_air_temp", "return_air_temp"
        else:
            lead, follow = None, None

        fan_uuid = (roles.get("fan_status") or {}).get("uuid")

        for role, meta in roles.items():
            entry = dict(meta)
            positive_only = role in ("supply_air_temp", "return_air_temp")
            if role == "damper_position" and fan_uuid:
                # CONDITION ON THE FAN, or the band describes neither state.
                # A damper's history is bimodal: near shut while the unit is off, and
                # modulating 12-95% while it runs. Percentiles over the mixture returned
                # lo 0.9 / median 4.5 / hi 52.2 -- a band that is wrong for the running
                # case and pointless for the stopped one, since the publisher writes the
                # stopped case directly. Measure the OPEN band only.
                cur.execute(
                    "SELECT a.value FROM plant_data a JOIN plant_data b "
                    "ON a.datetime = b.datetime WHERE a.uuid=%s AND b.uuid=%s "
                    "AND b.value >= 0.5 AND a.datetime < UTC_TIMESTAMP() - INTERVAL 1 DAY",
                    (meta["uuid"], fan_uuid),
                )
                vals = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
                entry["fan_conditioned"] = True
            else:
                vals = series(cur, meta["uuid"], "AND value > 1" if positive_only else "")
            if vals:
                entry["lo"] = pct(vals, 0.10)
                entry["hi"] = pct(vals, 0.90)
                entry["mid"] = round(statistics.median(vals), 3)
                entry["n"] = len(vals)
            spec["roles"][role] = entry

        if lead and follow:
            deltas = paired_delta(
                cur,
                roles[lead]["uuid"],
                roles[follow]["uuid"],
                "AND a.value > 1 AND b.value > 1",
            )
            healthy = [d for d in deltas if abs(d) > 0.5]
            use = healthy or deltas
            if use:
                spec["delta"] = {
                    "lead": lead,
                    "follow": follow,
                    "lo": pct(use, 0.10),
                    "hi": pct(use, 0.90),
                    "mid": round(statistics.median(use), 3),
                    "n": len(use),
                    "n_all": len(deltas),
                }
        out["groups"].append(spec)

conn.close()

tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2)
os.replace(tmp, OUT)

for g in out["groups"]:
    d = g.get("delta")
    roles = ",".join(sorted(g["roles"]))
    if d:
        print(
            f"{g['group']:<12} {d['follow']} = {d['lead']} - delta"
            f"  delta p10/med/p90 = {d['lo']}/{d['mid']}/{d['hi']}  (n={d['n']}/{d['n_all']})"
        )
    else:
        print(f"{g['group']:<12} (no correlated pair)  roles: {roles}")
print(f"\nwritten: {OUT}")
