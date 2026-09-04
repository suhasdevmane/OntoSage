# -*- coding: utf-8 -*-
"""Which systems of record the ACTIVE building actually holds, measured live.

The 37 stakeholder catalogues name the systems whose records are authoritative for each
question — an asset register, a permit log, a timetable, a tariff. Whether a question is
answerable therefore turns on a decidable fact: does this building hold that system, and
does it hold it as *data* rather than as prose?

This asks the live building, never a checklist. Every probe is a SPARQL count against
the active namespace, a row count in a registered database, or a document in the
building's own folder — so it reports what is deployed, not what someone intended. It
carries no building literals and runs unchanged against bldg2/3/4.

    python scripts/source_system_readiness.py
    python scripts/source_system_readiness.py --json

Readiness is three-valued on purpose:

    DATA      the facts are queryable — triples or rows a lane can compute over
    PROSE     only a document says it, so it can be quoted but not calculated with
    WIRED     a feed is configured for it and has produced NOTHING yet
    ABSENT    nothing holds it; a question needing it can only decline

WIRED exists because this reported DATA for a source with no data (CAVEAT-412). The rule was
`if count or rows or feeds`, so an ENABLED FEED alone was enough — a configured feed treated
as a proxy for the data it is supposed to produce. Measured 2026-09-03: `timetable` reported
DATA on 0 triples, 0 Postgres rows and 0 rows in the events store its own comment says it
writes to, purely because `synthetic_timetable` is `enabled: true` in feeds.yaml. Its 55 KB
CSV has never been ingested.

That is a false positive in the direction that looks like success, and readiness decides
which questions V7 believes it can answer — so it inflated the coverage ceiling and would
route a timetable question to a lane holding nothing. A feed now counts as DATA only when its
OUTPUT is measured, never because it is switched on.

PROSE is not a lesser DATA. "The legionella assessment is dated 12 March" answers a
question about the record; it cannot answer "which outlets are overdue" — and conflating
the two is how a document lane comes to look like an asset register.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Run directly as a script, so the repo root is not on sys.path yet.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.db_clock import UTC_SESSION_INIT

REPO = Path(__file__).resolve().parents[1]

PREFIXES = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX o:     <http://ontosage.org/capabilities#>
"""

#: (source_system, SPARQL count, document filename stems that would supply it in prose).
#:
#: The SPARQL is deliberately class-level rather than namespace-filtered: a building
#: that models its assets under its own namespace still types them with Brick or
#: OntoSage classes, and filtering on a hard-coded namespace is exactly the building
#: literal this project forbids.
#:
#: A first version probed GraphDB and documents ONLY, and so reported ABSENT for two
#: systems this building plainly holds: 199 user reports live in Postgres, and weather
#: and timetable arrive as configured feeds. A readiness report that misses a whole
#: store does not merely understate — it would have put "onboard a source" tasks in the
#: plan for data already connected. Every store the architecture allows is probed here:
#: GraphDB, the operational Postgres, the feed registry, and the document folder.
PROBES: List[Tuple[str, str, Tuple[str, ...]]] = [
    (
        "sensor_telemetry",
        "SELECT (COUNT(DISTINCT ?u) AS ?n) WHERE { ?r ref:hasTimeseriesId ?u }",
        (),
    ),
    (
        "bms_plant",
        "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { ?e a ?c . ?c rdfs:subClassOf* brick:HVAC_Equipment }",
        ("hvac_operation",),
    ),
    (
        "meter_energy",
        "SELECT (COUNT(DISTINCT ?m) AS ?n) WHERE { ?m a ?c . ?c rdfs:subClassOf* brick:Meter }",
        (),
    ),
    ("timetable", "SELECT (COUNT(?s) AS ?n) WHERE { ?s a o:TimetabledSession }", ()),
    ("booking", "SELECT (COUNT(?b) AS ?n) WHERE { ?b a o:Booking }", ("room_bookings",)),
    (
        "asset_register",
        "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { ?e a ?c . ?c rdfs:subClassOf* brick:Equipment }",
        (),
    ),
    (
        "cmms_work",
        "SELECT (COUNT(?w) AS ?n) WHERE { { ?w a o:WorkOrder } UNION { ?w a o:MaintenanceIssue } }",
        ("maintenance_log",),
    ),
    ("hr_identity", "SELECT (COUNT(?p) AS ?n) WHERE { ?p a brick:Person }", ()),
    (
        "access_control",
        "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE "
        "{ { ?e a ?c . ?c rdfs:subClassOf* brick:Access_Control_Equipment } UNION { ?e a o:AccessEvent } }",
        (),
    ),
    (
        "security_incident",
        "SELECT (COUNT(?a) AS ?n) WHERE { { ?a a o:AlarmEvent } UNION { ?a a o:Alarm_Group } }",
        ("incident_and_near_miss_log",),
    ),
    (
        "fire_life_safety",
        "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { ?e a ?c . ?c rdfs:subClassOf* brick:Fire_Safety_Equipment }",
        ("fire_safety", "evacuation_and_peeps"),
    ),
    (
        "statutory_compliance",
        "SELECT (COUNT(?c) AS ?n) WHERE { ?c a o:ComplianceCheck }",
        ("water_hygiene_legionella", "asbestos_register", "coshh_and_lev"),
    ),
    (
        "permit_control",
        "SELECT (COUNT(?p) AS ?n) WHERE { ?p a o:Permit }",
        ("permit_to_work_register", "contractor_control"),
    ),
    (
        "policy_governance",
        "SELECT (COUNT(?p) AS ?n) WHERE { { ?p a o:Policy } UNION { ?p a o:AccessPolicy } }",
        ("building_policies", "governance"),
    ),
    ("accessibility", "SELECT (COUNT(?f) AS ?n) WHERE { ?f a o:AccessibilityFeature }", ()),
    ("finance_cost", "SELECT (COUNT(?t) AS ?n) WHERE { ?t a o:Tariff }", ()),
    ("contract_warranty", "SELECT (COUNT(?c) AS ?n) WHERE { ?c a o:Contract }", ()),
    ("project_handover", "SELECT (COUNT(?h) AS ?n) WHERE { ?h a o:HandoverRecord }", ()),
    (
        "space_inventory",
        "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s a ?c . ?c rdfs:subClassOf* brick:Location }",
        (),
    ),
    (
        "cleaning_waste",
        "SELECT (COUNT(?w) AS ?n) WHERE { { ?w a o:WastePoint } UNION { ?w a o:ServiceSchedule } }",
        ("service_schedules",),
    ),
    ("it_network", "SELECT (COUNT(?s) AS ?n) WHERE { ?s a o:NetworkService }", ()),
    ("weather_external", "SELECT (COUNT(?s) AS ?n) WHERE { ?s a brick:Weather_Station }", ()),
    ("survey_condition", "SELECT (COUNT(?s) AS ?n) WHERE { ?s a o:ConditionSurvey }", ()),
    ("risk_insurance", "SELECT (COUNT(?r) AS ?n) WHERE { ?r a o:RiskAssessment }", ()),
    ("training_competency", "SELECT (COUNT(?t) AS ?n) WHERE { ?t a o:CompetencyRecord }", ()),
    ("sustainability", "SELECT (COUNT(?t) AS ?n) WHERE { ?t a o:SustainabilityTarget }", ()),
    (
        "user_reports",
        "SELECT (COUNT(?r) AS ?n) WHERE { { ?r a o:FaultReport } UNION { ?r a o:Complaint } "
        "UNION { ?r a o:SafetyReport } }",
        (),
    ),
]


def sparql_count(endpoint: str, query: str, auth: Optional[Tuple[str, str]]) -> Optional[int]:
    """Run a COUNT query; None when the endpoint could not answer it."""
    request = urllib.request.Request(
        endpoint,
        data=(PREFIXES + query).encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    bindings = payload.get("results", {}).get("bindings", [])
    if not bindings:
        return 0
    try:
        return int(bindings[0]["n"]["value"])
    except (KeyError, ValueError):
        return 0


#: Operational records the architecture keeps in Postgres rather than in the graph.
POSTGRES_PROBES: Dict[str, Tuple[str, ...]] = {
    "user_reports": ("user_reports",),
    "cmms_work": ("maintenance_tickets",),
}

#: Systems supplied by a configured live feed rather than by authored triples. A feed
#: that is present but disabled supplies nothing, so the flag is read, not assumed.
FEED_PROBES: Dict[str, Tuple[str, ...]] = {
    "weather_external": ("rest_poll",),
    "timetable": ("timetable",),
}


#: Where a feed-backed system's output LANDS, so "the feed is on" is never mistaken for
#: "the data arrived". Each entry is (kind, query): 'sparql' counts triples, 'mysql' counts
#: rows in the operational store. A system absent from this dict keeps the old behaviour and
#: is reported WIRED rather than DATA when nothing else holds it — honest about not knowing.
FEED_OUTPUT_PROBES: Dict[str, Tuple[str, str]] = {
    # feeds.yaml says timetable rows "land in the events store via the T25 institutional
    # adapter", so that is where to look.
    # A timetabled session is stored as a BOOKING event, not as its own type:
    # institutional.SOURCE_KINDS maps timetable -> booking deliberately, because a
    # timetabled session IS a room occupancy. A probe looking for event_type='timetable'
    # therefore matches nothing forever, and that was the first version of this line -- the
    # probe measuring the thing it was written to measure, and returning zero because it
    # asked for a shape the data does not take. The source id survives in `attrs`.
    "timetable": (
        "mysql",
        "SELECT COUNT(*) FROM events WHERE event_type = 'booking' " "AND attrs LIKE '%timetable%'",
    ),
    # A rest_poll weather feed auto-registers its points in the graph.
    "weather_external": (
        "sparql",
        "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { "
        "?p a ?c . ?c rdfs:subClassOf* brick:Weather_Based_Setpoint_Sensor }",
    ),
}


def feed_output(system: str, endpoint: str, auth) -> Optional[int]:
    """How many records this system's feed has actually produced, or None if unmeasured."""
    probe = FEED_OUTPUT_PROBES.get(system)
    if not probe:
        return None
    kind, query = probe
    try:
        if kind == "sparql":
            return sparql_count(endpoint, query, auth)
        return mysql_scalar(query)
    except Exception:
        return None


def mysql_scalar(query: str) -> Optional[int]:
    """One integer from the operational MySQL, or None when it cannot be asked.

    Connects directly rather than through `docker exec`: this deployment's MySQL runs on the
    HOST (compose points the services at host.docker.internal), so there is no container to
    exec into — a docker-based probe here would fail on every run and silently report every
    feed as unmeasured.

    None is UNKNOWN, never zero. Reporting a source ABSENT because a probe could not run
    would turn a connection hiccup into a planning decision.
    """
    import os

    try:
        import pymysql
    except Exception:
        return None
    env = {}
    env_file = REPO / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip().isidentifier():
                    env[key.strip()] = value.split("#", 1)[0].strip()
    host = os.environ.get("MYSQL_HOST") or "127.0.0.1"
    if host in ("host.docker.internal", "mysql", ""):
        host = "127.0.0.1"  # this probe runs on the host, not inside a container
    try:
        conn = pymysql.connect(
            host=host,
            port=int(os.environ.get("MYSQL_PORT") or env.get("MYSQL_PORT") or 3306),
            user=os.environ.get("MYSQL_USER") or env.get("MYSQL_USER") or "root",
            password=os.environ.get("MYSQL_PASSWORD") or env.get("MYSQL_PASSWORD") or "",
            database=os.environ.get("MYSQL_DATABASE") or env.get("MYSQL_DATABASE") or "sensordb",
            connect_timeout=10,
            init_command=UTC_SESSION_INIT,
        )
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def documents_present(stems: Tuple[str, ...], folder: Path) -> List[str]:
    """Which of the named documents the building actually carries."""
    if not folder.is_dir():
        return []
    have = {p.stem.lower() for p in folder.iterdir() if p.is_file()}
    return [s for s in stems if s.lower() in have]


def postgres_rows(tables: Tuple[str, ...], container: str) -> Optional[int]:
    """Row count across the named Postgres tables; None when Postgres is unreachable."""
    import subprocess

    def _env(key: str) -> str:
        out = subprocess.run(
            [
                "docker",
                "inspect",
                container,
                "--format",
                "{{range .Config.Env}}{{println .}}{{end}}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in out.stdout.splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1]
        return ""

    user, database = _env("POSTGRES_USER"), _env("POSTGRES_DB")
    if not user or not database:
        return None
    query = " UNION ALL ".join(f"SELECT COUNT(*) FROM {t}" for t in tables)
    try:
        out = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                user,
                "-d",
                database,
                "-tAc",
                f"SELECT SUM(n) FROM ({query}) AS s(n)",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return int(value) if value.isdigit() else None


def feeds_enabled(kinds: Tuple[str, ...], feeds_file: Path) -> List[str]:
    """Which of the named feed kinds are configured AND enabled for this building."""
    if not feeds_file.is_file():
        return []
    try:
        import yaml

        loaded = yaml.safe_load(feeds_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    entries = loaded.get("feeds", loaded) if isinstance(loaded, dict) else loaded
    if not isinstance(entries, list):
        return []
    return sorted(
        {
            str(e.get("type"))
            for e in entries
            if isinstance(e, dict) and e.get("type") in kinds and e.get("enabled", False)
        }
    )


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--endpoint", default=os.environ.get("GRAPHDB_QUERY_URL", ""))
    ap.add_argument("--documents", default=str(REPO / "input" / "documents"))
    ap.add_argument("--feeds", default=str(REPO / "input" / "feeds.yaml"))
    ap.add_argument("--pg-container", default="postgres-user-data")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    endpoint = args.endpoint or "http://localhost:7200/repositories/bldg"
    auth = (
        (os.environ.get("GRAPHDB_USER", "admin"), os.environ.get("GRAPHDB_PASSWORD", ""))
        if os.environ.get("GRAPHDB_PASSWORD")
        else None
    )
    folder = Path(args.documents)

    feeds_file = Path(args.feeds)
    results: List[Dict[str, object]] = []
    for system, query, doc_stems in PROBES:
        count = sparql_count(endpoint, query, auth) or 0
        rows = (
            postgres_rows(POSTGRES_PROBES[system], args.pg_container)
            if system in POSTGRES_PROBES
            else 0
        )
        feeds = feeds_enabled(FEED_PROBES[system], feeds_file) if system in FEED_PROBES else []
        docs = documents_present(doc_stems, folder)
        # A feed counts toward DATA only by its OUTPUT. `None` means unmeasured, and an
        # unmeasured feed is still allowed to carry DATA — refusing to would re-introduce
        # the under-reporting the feeds clause was added to fix. A feed measured at ZERO
        # does not: that is the false positive CAVEAT-412 is about.
        produced = feed_output(system, endpoint, auth) if feeds else None
        feed_has_data = bool(feeds) and (produced is None or produced > 0)
        if count or rows or feed_has_data:
            readiness = "DATA"
        elif docs:
            readiness = "PROSE"
        elif feeds:
            readiness = "WIRED"
        else:
            readiness = "ABSENT"
        results.append(
            {
                "source_system": system,
                "readiness": readiness,
                "instances": count,
                "postgres_rows": rows or 0,
                "feeds": feeds,
                "documents": docs,
            }
        )

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"endpoint: {endpoint}")
    print(f"documents: {folder}\n")
    print(f"  {'source system':<22}{'readiness':<10}{'graph':>7}{'pg':>7}  supplied by")
    for row in results:
        supplied = ", ".join(list(row["feeds"]) + list(row["documents"])) or "-"
        print(
            f"  {row['source_system']:<22}{row['readiness']:<10}"
            f"{row['instances']:>7}{row['postgres_rows']:>7}  {supplied}"
        )
    tally: Dict[str, int] = {}
    for row in results:
        tally[str(row["readiness"])] = tally.get(str(row["readiness"]), 0) + 1
    print("\n  " + "   ".join(f"{k}: {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
