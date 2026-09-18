# -*- coding: utf-8 -*-
"""conformance_report.py — what THIS building can be asked, measured from its own data.

OntoSage's claim is "connect a building's data, then ask it anything in plain English."
Three buildings have been onboarded by hand and the claim has been asserted from that.
What has never existed is an artifact an adopter can RUN against their own building that
says, with numbers behind every line, what it can answer, what it cannot, and which
missing data would change that. This is A4 of ``tasks/ARCH_UPGRADE_PLAN_2026-09-18.md``.

It produces three things:

1. **Data-contract checks** — each PASS/FAIL with the count behind it. Declared modalities
   resolve to points; every point resolves to exactly ONE timeseries reference (the metric
   that caught BUG-531, where 77 sensors carried two references and one answer merged two
   stores); every store the graph names is registered in BOTH the building config and the
   datasource registry and answers a probe query; freshness per modality; spaces, floors
   and rooms resolve; floor-plan manifests link to graph IRIs.
2. **A capability matrix** — for each question class the running system declares an intent
   for, a verdict of SUPPORTED / SUPPORTED-WITH-LIMITATION / NOT-SUPPORTED, with the reason
   stated in one sentence using the numbers from step 1.
3. **A conformance question set** — a JSONL of questions generated from templates filled
   with referents this building actually holds (a real room, a real floor, a register it
   holds instances of). This script NEVER asks them; it writes them for a live run.

Design rules it keeps, because breaking either would defeat the point:

* **No building literals.** The id, namespace, prefix, paths, stores, modalities, floors,
  rooms and registers are all read from the active building's own files and graph. There
  is no room number, floor list, sensor count or namespace anywhere in this file. The
  litmus test is that it runs unchanged against another building and prints a different,
  correct matrix — which the tests exercise against the bldg4 fixture.
* **Read-only.** SPARQL SELECTs and SELECT-only SQL. Nothing is written to any store and
  no question is asked of the running system.
* **Unknown is not PASS.** A store this host has no driver for reports UNKNOWN, never
  "fine". A check that could not run says so and is excluded from the pass count.

The heavy lifting is split so the verdict logic is pure and testable offline:
``gather_*`` functions do I/O and return plain dicts; ``check_*``, ``derive_matrix`` and
``build_question_set`` are pure functions over those dicts.

Usage
-----
    python scripts/conformance_report.py                       # active building
    python scripts/conformance_report.py --input-dir bldg4     # any building's files
    python scripts/conformance_report.py --offline             # files only, no graph/SQL
    python scripts/conformance_report.py --fresh-hours 48

Exit status is 1 when a data-contract check FAILS, so it can gate a release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Verdict vocabulary, chosen so "it works" and "it is evidenced" cannot be confused.
PASS = "PASS"
FAIL = "FAIL"
LIMITED = "LIMITED"  # runs, but a limitation must be said aloud
UNKNOWN = "UNKNOWN"  # could not be measured from here — never counted as a pass

SUPPORTED = "SUPPORTED"
SUPPORTED_LIMITED = "SUPPORTED-WITH-LIMITATION"
NOT_SUPPORTED = "NOT-SUPPORTED"

#: One sensor, one series. Mirrors scripts/certify_building.py, whose threshold is the
#: same number for the same reason; this file measures the finer-grained shape as well.
MAX_REFERENCE_FANOUT = 1.5

#: Words that must never reach a reader of the report. A building's provenance block may
#: legitimately say `nature: synthetic` in its own config; repeating that to a stakeholder
#: is a different act, and the project forbids it. Enforced by a test over the renderer.
_FORBIDDEN_IN_PROSE = ("simulated", "synthetic", "fake")

_PREFIXES = (
    "PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
    "PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>\n"
    "PREFIX brick: <https://brickschema.org/schema/Brick#>\n"
    "PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>\n"
    "PREFIX o:     <http://ontosage.org/capabilities#>\n"
)


# ─────────────────────────────────────────────────────────────────────────────
# Records
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Check:
    """One data-contract check, with the number that decided it."""

    key: str
    title: str
    status: str
    detail: str
    #: What an adopter would have to supply to turn a FAIL or LIMITED into a PASS.
    remedy: str = ""
    #: The measurement itself, so the JSON is machine-readable without parsing prose.
    measured: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    """One question class and this building's verdict on it."""

    key: str
    title: str
    verdict: str
    reason: str
    intents: List[str] = field(default_factory=list)
    required_data: str = ""
    missing: str = ""
    measured: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Question:
    """One generated conformance question. Written out; never asked here."""

    id: str
    question_class: str
    question: str
    expects: str
    referent: str = ""
    verdict_at_generation: str = ""


@dataclass
class Profile:
    """The active building's identity and declarations, read from its own files."""

    building_id: str
    building_name: str
    namespace: str
    prefix: str
    timezone: str
    input_dir: Path
    declared_stores: List[str] = field(default_factory=list)
    registry_stores: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    modalities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    intents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    document_count: int = 0
    floor_plan_source_files: int = 0
    problems: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Profile — everything that can be known without touching a server
# ─────────────────────────────────────────────────────────────────────────────

_ENV_PATTERN = re.compile(r"\$\{([^}:]+?)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` exactly as the adapter registry does.

    Copied in shape rather than imported: importing ``adapters.registry`` pulls the whole
    orchestrator package (and an LLM client) into a read-only reporting tool, and this
    report has to run against a building that is NOT the active one, which that package
    cannot do.
    """
    if not isinstance(value, str):
        return value

    def _sub(m: "re.Match[str]") -> str:
        return os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else "")

    return _ENV_PATTERN.sub(_sub, value)


def load_env_file(path: Path) -> int:
    """Seed the process environment from the deployment's own env file, without overriding it.

    The datasource registry declares hosts and credentials as ``${VAR}`` placeholders and
    the stack resolves them from the env file the compose project reads. A report run from
    a shell that has never sourced that file resolved every placeholder to its DEFAULT and
    then reported all twenty stores as unreachable — a measurement of the shell, not of the
    building. Already-set variables win, so an operator can still override one on the
    command line. Nothing is printed: these are secrets.
    """
    if not path.is_file():
        return 0
    loaded = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        loaded += 1
    return loaded


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_modality_config(input_dir: Path, repo: Path = REPO) -> Dict[str, Dict[str, Any]]:
    """Declared modalities: shared config plus the building's overlay, overlay wins.

    Same two files and same merge order as
    ``orchestrator/services/deliberation/coverage_audit._config_candidates`` — a building
    that declares its own modality set is measured against ITS set, not the default one.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for path in (
        repo / "config" / "saturation_modalities.yaml",
        input_dir / "saturation_modalities.yaml",
    ):
        if not path.is_file():
            continue
        for name, spec in (_read_yaml(path).get("modalities") or {}).items():
            merged[str(name)] = spec or {}
    return merged


def load_intents(input_dir: Path, repo: Path = REPO) -> Dict[str, Dict[str, Any]]:
    """The intents this deployment actually registers, shipped defaults + overlay.

    Mirrors ``orchestrator/intents/registry._load_yaml``: the shipped file is the
    baseline and the building's overlay merges on top, last writer per ``name`` winning.
    This is what makes the capability matrix DERIVED — a building that drops a lane from
    its overlay loses the corresponding question class instead of being graded on it.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for path in (
        repo / "orchestrator" / "intents" / "intent_definitions.yaml",
        input_dir / "_defaults" / "intents.yaml",
        input_dir / "intents.yaml",
    ):
        if not path.is_file():
            continue
        for item in _read_yaml(path).get("intents") or []:
            if isinstance(item, dict) and item.get("name"):
                merged[str(item["name"])] = item
    return merged


def load_profile(input_dir: Path, repo: Path = REPO) -> Profile:
    """Read identity, declared stores, modalities and intents from the building's files."""
    input_dir = Path(input_dir)
    cfg = _read_yaml(input_dir / "building.yaml")
    problems: List[str] = []
    if not cfg:
        problems.append(f"{input_dir / 'building.yaml'} is missing or unreadable")

    namespace = str(cfg.get("ontology_namespace") or "").strip()
    if namespace and not namespace.endswith(("#", "/")):
        problems.append("ontology_namespace does not end in '#' or '/'")

    registry_raw = _read_yaml(input_dir / "database_registry.yaml").get("databases") or {}
    registry: Dict[str, Dict[str, Any]] = {}
    for key, entry in registry_raw.items():
        if isinstance(entry, dict):
            registry[str(key)] = {k: expand_env(v) for k, v in entry.items()}

    declared = [str(s) for s in ((cfg.get("storage") or {}).get("databases") or [])]

    documents_dir = input_dir / "documents"
    docs = (
        len([p for p in documents_dir.iterdir() if p.is_file() and p.suffix.lower() != ".json"])
        if documents_dir.is_dir()
        else 0
    )
    plans = (
        len([p for p in input_dir.iterdir() if p.suffix.lower() in (".pdf", ".dwg", ".dxf")])
        if input_dir.is_dir()
        else 0
    )

    return Profile(
        building_id=str(cfg.get("building_id") or "").strip(),
        building_name=str(cfg.get("building_name") or "").strip(),
        namespace=namespace,
        prefix=str(cfg.get("ontology_prefix") or "").strip(),
        timezone=str(cfg.get("timezone") or "").strip(),
        input_dir=input_dir,
        declared_stores=declared,
        registry_stores=registry,
        modalities=load_modality_config(input_dir, repo),
        intents=load_intents(input_dir, repo),
        document_count=docs,
        floor_plan_source_files=plans,
        problems=problems,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Graph facts
# ─────────────────────────────────────────────────────────────────────────────


def local_name(iri: str) -> str:
    s = str(iri or "")
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


class GraphClient:
    """Read-only SPARQL SELECT over HTTP. No writes, no updates, no repository admin."""

    def __init__(self, endpoint: str, timeout: float = 180.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.last_error = ""

    def select(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Bindings, or None when the endpoint could not answer (which is not an empty result)."""
        body = (_PREFIXES + query).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as fh:  # nosec B310
                payload = json.load(fh)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        return list(((payload.get("results") or {}).get("bindings")) or [])


def _v(binding: Dict[str, Any], var: str) -> str:
    entry = binding.get(var)
    return str(entry.get("value") or "") if isinstance(entry, dict) else ""


def gather_graph_facts(graph: GraphClient, namespace: str) -> Dict[str, Any]:
    """Everything the report needs from the graph, in one pass of SELECTs.

    Scoped to the building's own namespace wherever a subject belongs to the building, so
    the shared Brick/BACnet TBox and any other building's leftovers cannot inflate a count.
    """
    facts: Dict[str, Any] = {"reachable": True, "error": ""}
    ns = namespace

    fanout = graph.select(
        "SELECT (COUNT(?r) AS ?refs) (COUNT(DISTINCT ?u) AS ?uuids) "
        "WHERE { ?r ref:hasTimeseriesId ?u }"
    )
    if fanout is None:
        return {"reachable": False, "error": graph.last_error}
    facts["reference_refs"] = int(_v(fanout[0], "refs") or 0) if fanout else 0
    facts["reference_uuids"] = int(_v(fanout[0], "uuids") or 0) if fanout else 0

    # BUG-531's shape: fan-out stays at 1.00 because each reference carries its own uuid,
    # while one sensor resolves to two stores and one answer's statistics merge them.
    dual = graph.select(
        "SELECT ?s (COUNT(DISTINCT ?u) AS ?n) WHERE { "
        "?s ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?u "
        "} GROUP BY ?s HAVING (COUNT(DISTINCT ?u) > 1) LIMIT 500"
    )
    facts["dual_series"] = [local_name(_v(b, "s")) for b in (dual or [])]
    facts["dual_series_known"] = dual is not None

    points = graph.select(
        "SELECT ?p ?cls ?label ?uuid ?stored WHERE { "
        "  ?p a ?cls . ?cls rdfs:subClassOf* brick:Point . "
        "  ?p ref:hasExternalReference ?r . ?r ref:hasTimeseriesId ?uuid . "
        "  OPTIONAL { ?r ref:storedAt ?stored } "
        "  OPTIONAL { ?p rdfs:label ?label } "
        f'  FILTER(STRSTARTS(STR(?p), "{ns}")) '
        "}"
    )
    facts["points"] = [
        {
            "iri": _v(b, "p"),
            "class_local": local_name(_v(b, "cls")),
            "text": " ".join(x for x in (_v(b, "label"), local_name(_v(b, "p"))) if x),
            "uuid": _v(b, "uuid"),
            "store": local_name(_v(b, "stored")),
        }
        for b in (points or [])
    ]
    facts["points_known"] = points is not None

    # Points the building models but never linked to a series: the half of contract 8 that
    # looks like success on every other screen.
    unbacked = graph.select(
        "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { "
        "  ?p a ?cls . ?cls rdfs:subClassOf* brick:Point . "
        "  FILTER NOT EXISTS { ?p ref:hasExternalReference/ref:hasTimeseriesId ?u } "
        f'  FILTER(STRSTARTS(STR(?p), "{ns}")) '
        "}"
    )
    facts["points_unbacked"] = int(_v(unbacked[0], "n") or 0) if unbacked else 0

    floors = graph.select(
        "SELECT ?f ?l WHERE { ?f a brick:Floor . OPTIONAL { ?f rdfs:label ?l } "
        f'FILTER(STRSTARTS(STR(?f), "{ns}")) }}'
    )
    facts["floors"] = sorted({(_v(b, "l") or local_name(_v(b, "f"))) for b in (floors or [])})

    spaces = graph.select(
        "SELECT DISTINCT ?s ?l ?fl WHERE { "
        "  ?s a ?c . ?c rdfs:subClassOf* brick:Room . "
        "  OPTIONAL { ?s rdfs:label ?l } "
        "  OPTIONAL { ?s brick:isPartOf ?f . ?f a brick:Floor . OPTIONAL { ?f rdfs:label ?fl } } "
        f'  FILTER(STRSTARTS(STR(?s), "{ns}")) '
        "} LIMIT 5000"
    )
    facts["spaces"] = [
        {
            "iri": _v(b, "s"),
            "label": _v(b, "l") or local_name(_v(b, "s")),
            "floor": _v(b, "fl"),
        }
        for b in (spaces or [])
    ]
    facts["spaces_known"] = spaces is not None

    # Which points sit on which floor, stated by the building rather than parsed out of a
    # sensor's name — the correction scripts/floor_modality_matrix.py exists to make.
    placed = graph.select(
        "SELECT ?uuid ?fl WHERE { "
        "  ?p ref:hasExternalReference/ref:hasTimeseriesId ?uuid . "
        "  ?p brick:hasLocation|brick:isPointOf|brick:isPartOf ?space . "
        "  ?space brick:isPartOf* ?floor . ?floor a brick:Floor . "
        "  OPTIONAL { ?floor rdfs:label ?l } "
        '  BIND(COALESCE(?l, REPLACE(STR(?floor), "^.*[/#]", "")) AS ?fl) '
        f'  FILTER(STRSTARTS(STR(?p), "{ns}")) '
        "}"
    )
    by_floor: Dict[str, Set[str]] = {}
    for b in placed or []:
        by_floor.setdefault(_v(b, "fl"), set()).add(_v(b, "uuid"))
    facts["uuids_by_floor"] = {k: sorted(v) for k, v in by_floor.items()}

    # The two roots are EXCLUDED. They are abstract, and a store with inference enabled
    # counts every subclass instance under each of them — so including them both invents a
    # register the building does not hold and doubles the total number of records it does.
    registers = graph.select(
        "SELECT ?cls (COUNT(DISTINCT ?x) AS ?n) WHERE { "
        "  VALUES ?root { o:Record o:IntervalRecord } "
        "  ?cls rdfs:subClassOf+ ?root . "
        "  FILTER(?cls != o:Record && ?cls != o:IntervalRecord) "
        '  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#")) '
        "  OPTIONAL { ?x a ?cls } "
        "} GROUP BY ?cls"
    )
    facts["registers"] = {local_name(_v(b, "cls")): int(_v(b, "n") or 0) for b in (registers or [])}
    facts["registers_known"] = registers is not None

    amenities = graph.select(
        "SELECT ?a ?l WHERE { { ?a a o:Amenity } UNION { ?a a o:KnowledgeTopic } "
        "OPTIONAL { ?a rdfs:label ?l } } LIMIT 500"
    )
    facts["amenities"] = sorted({(_v(b, "l") or local_name(_v(b, "a"))) for b in (amenities or [])})

    return facts


def index_points_by_modality(
    modalities: Dict[str, Dict[str, Any]], points: Sequence[Dict[str, str]]
) -> Dict[str, Dict[str, Any]]:
    """Group backed points under the modality names the building declares.

    Matching follows ``coverage_audit.ModalitySpec.matches``: class local name first, then
    an exclusion list that wins over an inclusion list, applied to the label AND the IRI's
    local name concatenated — the pair, because a discriminator written in either
    vocabulary has to work (the defect that let PM1 count as PM2.5).
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in modalities.items():
        classes = {str(c).lower() for c in (spec.get("brick_classes") or [])}
        includes = [str(s).lower() for s in (spec.get("label_contains") or [])]
        excludes = [str(s).lower() for s in (spec.get("label_excludes") or [])]
        matched: List[Dict[str, str]] = []
        for p in points:
            if p.get("class_local", "").lower() not in classes:
                continue
            text = p.get("text", "").lower()
            if excludes and any(sub in text for sub in excludes):
                continue
            if includes and not any(sub in text for sub in includes):
                continue
            matched.append(p)
        seen: Set[str] = set()
        uuids: List[str] = []
        for p in matched:
            if p["uuid"] and p["uuid"] not in seen:
                seen.add(p["uuid"])
                uuids.append(p["uuid"])
        out[name] = {
            "points": len({p["iri"] for p in matched}),
            "uuids": uuids,
            "stores": sorted({p["store"] for p in matched if p["store"]}),
            "unrouted": len([p for p in matched if not p["store"]]),
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Store probes
# ─────────────────────────────────────────────────────────────────────────────

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_UUID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{7,63}$")

#: How the adapter registry's `type:` maps onto a table shape this probe understands.
#: A narrow store is (uuid, datetime, value) rows; a wide store is one COLUMN per uuid.
_NARROW_TYPES = {"mysql_narrow", "mysql_events"}
_WIDE_TYPES = {"mysql"}


def _column_map(entry: Dict[str, Any]) -> Tuple[str, str]:
    """(uuid column, timestamp column) for a narrow store, from its own declaration."""
    cols = entry.get("columns") or {}
    return (
        str(cols.get("uuid") or "uuid"),
        str(cols.get("timestamp") or cols.get("datetime") or "datetime"),
    )


def probe_mysql_store(
    key: str,
    entry: Dict[str, Any],
    uuids: Sequence[str],
    fresh_hours: int,
    connect: Optional[Callable[..., Any]] = None,
    groups: Optional[Dict[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Does this store answer, how new is its newest row, and which of ITS points reported?

    ``groups`` names subsets of ``uuids`` — the quantities the building declares — and each
    is COUNTED against the store rather than apportioned from the store's total. An earlier
    pass did apportion, and the report then said every quantity was 100% fresh because the
    stores were: an arithmetic identity presented as a measurement. Per-group counting costs
    one indexed query per group and cannot produce that answer.

    ``connect`` is injected so the probe is exercisable without a server. The session time
    zone is pinned to UTC on every connection: ``sensor_data.Datetime`` is a TIMESTAMP that
    MySQL converts to the session zone on read, and measuring through a local-zone session
    is what produced three wrong "fixes" and two withdrawn defects in this project
    (BUG-403, lessons.md #103).
    """
    kind = str(entry.get("type") or "").lower()
    # Deduped: a point is returned once per class in its subclass closure, so the raw list
    # carries the same id several times and an undeduped "expected" reads as a coverage gap
    # that does not exist.
    uuids = list(dict.fromkeys(str(u) for u in uuids))
    result: Dict[str, Any] = {
        "key": key,
        "type": kind,
        "answered": False,
        "reason": "",
        "newest": "",
        "age_hours": None,
        "uuids_expected": len(uuids),
        "uuids_with_rows": 0,
        "uuids_fresh": 0,
        "history_days": None,
        "groups": {},
    }
    if kind not in _NARROW_TYPES | _WIDE_TYPES:
        result["reason"] = f"no probe for adapter type '{kind or 'unset'}' on this host"
        return result

    if connect is None:
        try:
            import pymysql  # noqa: F401
        except Exception:
            result["reason"] = "no MySQL driver available on this host"
            return result
        connect = pymysql.connect  # type: ignore[assignment]

    table = str(entry.get("table") or "sensor_data")
    if not _IDENT_RE.match(table):
        result["reason"] = f"table name {table!r} is not a plain identifier"
        return result

    host = str(entry.get("host") or "")
    # host.docker.internal is how a container reaches the host; from the host itself the
    # same server is loopback. Resolved here rather than asked of the adopter.
    if host in ("host.docker.internal", "mysql", "localhost", ""):
        host = "127.0.0.1"

    try:
        conn = connect(
            host=host,
            port=int(entry.get("port") or 3306),
            user=str(entry.get("user") or ""),
            password=str(entry.get("password") or ""),
            database=str(entry.get("database") or ""),
            connect_timeout=15,
            read_timeout=180,
        )
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        cur = conn.cursor()
        cur.execute("SET SESSION time_zone = '+00:00'")
        counter = _count_narrow if kind in _NARROW_TYPES else _count_wide
        _record_span(result, *_span(cur, table, entry, kind))
        with_rows, fresh = counter(cur, table, entry, uuids, fresh_hours)
        result["uuids_with_rows"] = with_rows
        result["uuids_fresh"] = fresh
        for name, members in (groups or {}).items():
            members = [u for u in dict.fromkeys(str(m) for m in members) if u in set(uuids)]
            g_rows, g_fresh = counter(cur, table, entry, members, fresh_hours)
            result["groups"][name] = {
                "expected": len(members),
                "with_rows": g_rows,
                "fresh": g_fresh,
            }
        result["answered"] = True
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return result


def _ts_column(entry: Dict[str, Any], kind: str) -> str:
    """The timestamp column this store declares.

    The wide store spells it with a capital and the narrow tables spell it lower case;
    both are read from the store's own declaration, with the conventional spelling as the
    fallback for a store that declares nothing.
    """
    declared = (entry.get("columns") or {}).get("timestamp")
    if declared:
        return str(declared)
    return "datetime" if kind in _NARROW_TYPES else "Datetime"


def _span(cur: Any, table: str, entry: Dict[str, Any], kind: str) -> Tuple[Any, Any]:
    ts_col = _ts_column(entry, kind)
    if not _IDENT_RE.match(ts_col):
        raise ValueError(f"timestamp column {ts_col!r} is not a plain identifier")
    cur.execute(f"SELECT MIN(`{ts_col}`), MAX(`{ts_col}`) FROM `{table}`")
    row = cur.fetchone() or (None, None)
    return row[0], row[1]


def _count_narrow(
    cur: Any, table: str, entry: Dict[str, Any], uuids: Sequence[str], fresh_hours: int
) -> Tuple[int, int]:
    """(points with any row, points with a row inside the window) for a narrow store.

    Counted with an IN list rather than a whole-table GROUP BY. These tables run to
    millions of rows and a grouped scan of one is most of a floor comparison's cost
    (measured at 32 s for 174 sensors on a 10M-row table); a bounded IN list uses the same
    index the adapter's own range scan does.
    """
    uuid_col, _ = _column_map(entry)
    ts_col = _ts_column(entry, "mysql_narrow")
    if not (_IDENT_RE.match(uuid_col) and _IDENT_RE.match(ts_col)):
        raise ValueError(f"column names {uuid_col!r}/{ts_col!r} are not plain identifiers")
    wanted = [u for u in uuids if _UUID_RE.match(str(u))]
    if not wanted:
        return 0, 0
    placeholders = ", ".join(["%s"] * len(wanted))
    cur.execute(
        f"SELECT COUNT(DISTINCT `{uuid_col}`) FROM `{table}` "
        f"WHERE `{uuid_col}` IN ({placeholders})",
        wanted,
    )
    with_rows = int((cur.fetchone() or [0])[0] or 0)
    cur.execute(
        f"SELECT COUNT(DISTINCT `{uuid_col}`) FROM `{table}` "
        f"WHERE `{uuid_col}` IN ({placeholders}) "
        f"AND `{ts_col}` >= UTC_TIMESTAMP() - INTERVAL %s HOUR",
        wanted + [int(fresh_hours)],
    )
    return with_rows, int((cur.fetchone() or [0])[0] or 0)


#: A wide store holds one column per sensor, so "which points reported" is one COUNT per
#: column. Chunked because a densely-instrumented building has hundreds and one statement
#: naming them all is neither readable nor bounded.
_WIDE_CHUNK = 100


def _count_wide(
    cur: Any, table: str, entry: Dict[str, Any], uuids: Sequence[str], fresh_hours: int
) -> Tuple[int, int]:
    """Same pair for a wide store, where each point is a COLUMN rather than a key.

    "Has any row" here means "is a column of this table": a wide table has one row per
    timestamp, so a point that is not a column is unreadable however many rows exist. The
    window count is chunked because a densely-instrumented building has hundreds of
    columns and one statement naming them all is neither readable nor bounded.
    """
    ts_col = _ts_column(entry, "mysql")
    if not _IDENT_RE.match(ts_col):
        raise ValueError(f"timestamp column {ts_col!r} is not a plain identifier")
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    )
    columns = {str(r[0]) for r in cur.fetchall() or []}
    wanted = [str(u) for u in uuids if _UUID_RE.match(str(u)) and str(u) in columns]
    if not wanted:
        return 0, 0
    fresh = 0
    for i in range(0, len(wanted), _WIDE_CHUNK):
        chunk = wanted[i : i + _WIDE_CHUNK]
        selects = ", ".join(f"COUNT(`{u}`)" for u in chunk)
        cur.execute(
            f"SELECT {selects} FROM `{table}` "
            f"WHERE `{ts_col}` >= UTC_TIMESTAMP() - INTERVAL %s HOUR",
            (int(fresh_hours),),
        )
        fresh += sum(1 for n in (cur.fetchone() or []) if n)
    return len(wanted), fresh


def _record_span(result: Dict[str, Any], oldest: Any, newest: Any) -> None:
    if isinstance(newest, datetime):
        result["newest"] = newest.strftime("%Y-%m-%d %H:%M:%SZ")
        delta = datetime.now(timezone.utc).replace(tzinfo=None) - newest
        result["age_hours"] = round(delta.total_seconds() / 3600.0, 1)
    if isinstance(newest, datetime) and isinstance(oldest, datetime):
        result["history_days"] = round((newest - oldest).total_seconds() / 86400.0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Floor-plan manifests
# ─────────────────────────────────────────────────────────────────────────────


def scan_floor_plans(volumes_root: Path, building_id: str, namespace: str) -> Dict[str, Any]:
    """Manifests on disk and the share of their spaces that names a graph IRI.

    The link rate is the number that matters: an unlinked space has geometry nothing can
    join to a sensor, and that sat at exactly 50% on every floor undetected until BUG-147.
    ``ontology_iri`` values outside this building's namespace are counted separately —
    a link to another building's IRI is worse than no link.
    """
    out = {
        "manifests": 0,
        "spaces": 0,
        "linked": 0,
        "linked_in_namespace": 0,
        "iris": [],
        "found": False,
    }
    root = Path(volumes_root) / building_id / "floor-plans"
    if not root.is_dir():
        return out
    out["found"] = True
    iris: List[str] = []
    for manifest in sorted(root.rglob("*.manifest.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        out["manifests"] += 1
        for space in data.get("spaces") or []:
            out["spaces"] += 1
            iri = str(space.get("ontology_iri") or "").strip()
            if iri:
                out["linked"] += 1
                if not namespace or iri.startswith(namespace):
                    out["linked_in_namespace"] += 1
                    iris.append(iri)
    out["iris"] = iris
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Data-contract checks — pure functions over gathered facts
# ─────────────────────────────────────────────────────────────────────────────


def check_identity(profile: Profile) -> Check:
    missing = [
        name
        for name, value in (
            ("building_id", profile.building_id),
            ("building_name", profile.building_name),
            ("ontology_namespace", profile.namespace),
        )
        if not value
    ]
    if missing or profile.problems:
        return Check(
            "identity",
            "Building identity is declared",
            FAIL,
            "; ".join(profile.problems + [f"missing {m}" for m in missing]),
            "Complete building.yaml: id, name and an ontology namespace ending in '#'.",
            {"missing": missing},
        )
    return Check(
        "identity",
        "Building identity is declared",
        PASS,
        f"{profile.building_name} ({profile.building_id}), namespace {profile.namespace}",
        measured={"building_id": profile.building_id, "namespace": profile.namespace},
    )


def check_modalities_resolve(
    modalities: Dict[str, Dict[str, Any]], indexed: Dict[str, Dict[str, Any]]
) -> Check:
    """Every declared modality must reach at least one point carrying a series."""
    empty = sorted(n for n in modalities if not indexed.get(n, {}).get("uuids"))
    resolved = len(modalities) - len(empty)
    status = PASS if not empty else LIMITED
    detail = f"{resolved} of {len(modalities)} declared modalities resolve to points with a series"
    if empty:
        detail += f"; {len(empty)} resolve to none ({', '.join(empty[:8])}" + (
            ", …)" if len(empty) > 8 else ")"
        )
    return Check(
        "modalities",
        "Declared modalities resolve to points",
        status,
        detail,
        "Add sensors of the unresolved classes to the ontology, or remove them from the "
        "declared modality set — a modality nothing measures is a question class that must "
        "decline rather than guess.",
        {"declared": len(modalities), "resolved": resolved, "unresolved": empty},
    )


def check_reference_fanout(refs: int, uuids: int) -> Check:
    if uuids == 0:
        return Check(
            "fanout",
            "Timeseries references are not duplicated",
            FAIL,
            "the graph holds no timeseries references at all",
            "Link each sensor with ref:hasTimeseriesId and ref:storedAt.",
            {"refs": refs, "uuids": uuids},
        )
    fanout = refs / uuids
    ok = fanout <= MAX_REFERENCE_FANOUT
    return Check(
        "fanout",
        "Timeseries references are not duplicated",
        PASS if ok else FAIL,
        f"{fanout:.3f} references per series id ({refs} references / {uuids} ids)",
        "Back up, prove the loss is zero with a subject-level diff, drop the graph and "
        "re-upload — a duplicated graph makes every count meaningless.",
        {"refs": refs, "uuids": uuids, "fanout": round(fanout, 3)},
    )


def check_one_series_per_point(dual: Sequence[str], known: bool) -> Check:
    """BUG-531: one sensor, two references, two stores, one merged set of statistics."""
    if not known:
        return Check(
            "one_series",
            "Each point resolves to exactly one series",
            UNKNOWN,
            "the graph could not be asked",
            measured={},
        )
    if dual:
        shown = ", ".join(dual[:6]) + ("…" if len(dual) > 6 else "")
        return Check(
            "one_series",
            "Each point resolves to exactly one series",
            FAIL,
            f"{len(dual)} point(s) resolve to two or more series ids ({shown})",
            "Give each point one authoritative series. Two references means one answer's "
            "statistics are computed across two stores, and the duplication metric cannot "
            "see it because each reference carries its own id.",
            {"count": len(dual), "examples": list(dual[:20])},
        )
    return Check(
        "one_series",
        "Each point resolves to exactly one series",
        PASS,
        "every point with a reference resolves to exactly one series id",
        measured={"count": 0},
    )


def check_stores_registered(
    graph_stores: Dict[str, int],
    declared_stores: Sequence[str],
    registry_stores: Dict[str, Dict[str, Any]],
) -> Check:
    """A store the graph names must be in BOTH lists, or its readings die at query time.

    The building config decides which adapters are BUILT and the datasource registry
    decides HOW. Named in only one, the wrong adapter is built silently and every reading
    for that store fails on an unknown column — a failure that reads as "no data".
    """
    declared = set(declared_stores)
    missing_declared = sorted(k for k in graph_stores if k not in declared)
    missing_registry = sorted(k for k in graph_stores if k not in registry_stores)
    unrouted = graph_stores.get("", 0)
    problems = []
    if missing_declared:
        problems.append(
            f"{len(missing_declared)} absent from building.yaml ({', '.join(missing_declared[:6])})"
        )
    if missing_registry:
        problems.append(
            f"{len(missing_registry)} absent from database_registry.yaml "
            f"({', '.join(missing_registry[:6])})"
        )
    if unrouted:
        problems.append(f"{unrouted} series ids carry no ref:storedAt at all")
    named = len([k for k in graph_stores if k])
    return Check(
        "stores_registered",
        "Every store the graph names is registered in both files",
        PASS if not problems else FAIL,
        f"{named} store(s) named by ref:storedAt; "
        + ("; ".join(problems) if problems else "all registered in both files"),
        "Add the store key to building.yaml storage.databases AND to "
        "database_registry.yaml. Named in only one, the wrong adapter is built and every "
        "reading for that store fails in a way that looks like missing data.",
        {
            "named": named,
            "missing_from_building_yaml": missing_declared,
            "missing_from_registry": missing_registry,
            "series_without_store": unrouted,
        },
    )


def check_store_probes(probes: Dict[str, Dict[str, Any]]) -> Check:
    """Registration is a claim; answering a query is the fact."""
    if not probes:
        return Check(
            "stores_answer",
            "Every registered store answers a query",
            UNKNOWN,
            "no store was probed",
        )
    answered = sorted(k for k, p in probes.items() if p.get("answered"))
    failed = sorted(
        k
        for k, p in probes.items()
        if not p.get("answered")
        and "no probe for" not in p.get("reason", "")
        and "no MySQL driver" not in p.get("reason", "")
    )
    unprobed = sorted(k for k in probes if k not in answered and k not in failed)
    if failed:
        status = FAIL
    elif unprobed:
        status = UNKNOWN
    else:
        status = PASS
    detail = f"{len(answered)} of {len(probes)} store(s) answered"
    if failed:
        detail += f"; {len(failed)} did not ({', '.join(failed[:5])})"
    if unprobed:
        detail += f"; {len(unprobed)} could not be probed from here ({', '.join(unprobed[:5])})"
    return Check(
        "stores_answer",
        "Every registered store answers a query",
        status,
        detail,
        "A store that does not answer makes every question about its points decline. "
        "Check credentials, network reach and the table name.",
        {"answered": answered, "failed": failed, "unprobed": unprobed},
    )


def check_freshness(
    modality_freshness: Dict[str, Dict[str, Any]],
    fresh_hours: int,
    store_totals: Optional[Dict[str, int]] = None,
) -> Check:
    """Per quantity: did it report inside the window, and how many points did building-wide.

    The building-wide pair comes from ``store_totals``, counted per STORE. Summing the
    per-quantity counts would double-count: a point typed with two matching classes
    belongs to two quantities, and the total would exceed the number of points that exist.
    A series id belongs to exactly one store, so the store-level sum is distinct.
    """
    measured = {k: v for k, v in modality_freshness.items() if v.get("uuids")}
    if not measured:
        return Check(
            "freshness",
            f"Points reported within {fresh_hours} h",
            UNKNOWN,
            "no declared quantity could be measured against a store",
            measured={},
        )
    reporting = {k: v for k, v in measured.items() if v.get("fresh", 0) > 0}
    total_points = int((store_totals or {}).get("points") or 0)
    total_fresh = int((store_totals or {}).get("fresh") or 0)
    share = (total_fresh / total_points * 100.0) if total_points else 0.0
    status = PASS if reporting else FAIL
    if reporting and len(reporting) < len(measured):
        status = LIMITED
    stale = sorted(k for k in measured if k not in reporting)
    detail = (
        f"{len(reporting)} of {len(measured)} measurable quantities reported in the last "
        f"{fresh_hours} h; {total_fresh} of {total_points} readable points ({share:.1f}%)"
    )
    if stale:
        detail += f"; silent: {', '.join(stale[:8])}" + ("…" if len(stale) > 8 else "")
    return Check(
        "freshness",
        f"Points reported within {fresh_hours} h",
        status,
        detail,
        "A modality with history but no recent rows answers historical questions "
        "correctly and must decline present-tense ones. Restore the feed, or accept that "
        "'right now' is out of scope for it.",
        {
            "window_hours": fresh_hours,
            "modalities_reporting": len(reporting),
            "modalities_measured": len(measured),
            "points_fresh": total_fresh,
            "points_total": total_points,
            "silent": stale,
        },
    )


def check_spatial(
    floors: Sequence[str], spaces: Sequence[Dict[str, str]], uuids_by_floor: Dict[str, List[str]]
) -> Check:
    placed = sum(1 for s in spaces if s.get("floor"))
    if not floors or not spaces:
        return Check(
            "spatial",
            "Floors, spaces and rooms resolve",
            FAIL,
            f"{len(floors)} floor(s) and {len(spaces)} space(s) in this building's namespace",
            "Add brick:Floor and room-class instances joined by brick:isPartOf.",
            {"floors": len(floors), "spaces": len(spaces)},
        )
    instrumented = len([f for f in floors if uuids_by_floor.get(f)])
    status = PASS if placed == len(spaces) and instrumented == len(floors) else LIMITED
    return Check(
        "spatial",
        "Floors, spaces and rooms resolve",
        status,
        f"{len(floors)} floor(s), {len(spaces)} space(s), {placed} of them placed on a "
        f"floor; {instrumented} floor(s) carry at least one point",
        "A space with no floor cannot be reached by a floor-scoped question, and a floor "
        "with no points cannot be compared with one that has them.",
        {
            "floors": len(floors),
            "spaces": len(spaces),
            "spaces_placed": placed,
            "floors_instrumented": instrumented,
        },
    )


def check_floor_plan_links(plans: Dict[str, Any], space_iris: Set[str]) -> Check:
    if not plans.get("found") or not plans.get("manifests"):
        return Check(
            "floor_plans",
            "Floor-plan manifests link to graph IRIs",
            FAIL,
            "no floor-plan manifests were found for this building",
            "Upload floor plans and let the ingestion build manifests; without them "
            "wayfinding and area questions have no geometry.",
            {"manifests": 0},
        )
    total = int(plans.get("spaces") or 0)
    linked = int(plans.get("linked_in_namespace") or 0)
    resolving = len([i for i in plans.get("iris") or [] if i in space_iris]) if space_iris else 0
    rate = (linked / total * 100.0) if total else 0.0
    if linked == 0:
        status = FAIL
    elif resolving < linked or linked < total:
        status = LIMITED
    else:
        status = PASS
    return Check(
        "floor_plans",
        "Floor-plan manifests link to graph IRIs",
        status,
        f"{plans['manifests']} manifest(s), {linked} of {total} plan spaces carry an IRI in "
        f"this building's namespace ({rate:.0f}%); {resolving} of those resolve to a space "
        f"the graph holds",
        "Link each plan space to its ontology IRI. An unlinked space has geometry nothing "
        "can join to a sensor, which looks like an answerable room and is not.",
        {
            "manifests": plans["manifests"],
            "plan_spaces": total,
            "linked": linked,
            "resolving": resolving,
            "link_rate_pct": round(rate, 1),
        },
    )


def check_unbacked_points(backed: int, unbacked: int) -> Check:
    """Both halves of contract 8 — a triple in the graph AND rows in a registered store."""
    total = backed + unbacked
    if total == 0:
        return Check(
            "points_backed",
            "Modelled points carry a series reference",
            FAIL,
            "this building's namespace holds no points at all",
            "Upload the building's Brick TTL.",
            {"backed": 0, "unbacked": 0},
        )
    share = backed / total * 100.0
    return Check(
        "points_backed",
        "Modelled points carry a series reference",
        PASS if unbacked == 0 else LIMITED,
        f"{backed} of {total} modelled points ({share:.1f}%) carry a series reference; "
        f"{unbacked} are modelled but unreadable",
        "A point with no ref:hasTimeseriesId is a sensor the building believes it has and "
        "cannot read. Link it or remove it.",
        {"backed": backed, "unbacked": unbacked, "share_pct": round(share, 1)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Capability matrix
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class QuestionClass:
    """A class of question, the lanes that serve it, and what a building must hold for it.

    The class list is DERIVED, not asserted: a class is only carried into the report when
    every intent it names is registered in this deployment's intent registry. The verdict
    is then decided by ``decide`` from the measured facts alone.
    """

    key: str
    title: str
    intents: Tuple[str, ...]
    required_data: str
    decide: Callable[[Dict[str, Any]], Tuple[str, str, str]]
    templates: Tuple[str, ...] = ()
    expects: str = ""


def _fresh_modalities(m: Dict[str, Any]) -> List[str]:
    return sorted(
        k for k, v in (m.get("modality_freshness") or {}).items() if v.get("fresh", 0) > 0
    )


def _historic_modalities(m: Dict[str, Any]) -> List[str]:
    return sorted(
        k for k, v in (m.get("modality_freshness") or {}).items() if v.get("with_rows", 0) > 0
    )


def _decide_current_reading(m: Dict[str, Any]) -> Tuple[str, str, str]:
    fresh = _fresh_modalities(m)
    historic = _historic_modalities(m)
    window = m.get("fresh_hours", 24)
    if fresh:
        missing = [k for k in historic if k not in fresh]
        if missing:
            return (
                SUPPORTED_LIMITED,
                f"{len(fresh)} of {len(historic)} measurable quantities reported in the last "
                f"{window} h, so a present-tense question is answerable for those and must "
                f"decline for the remaining {len(missing)}.",
                f"recent readings for {', '.join(missing[:6])}",
            )
        return (
            SUPPORTED,
            f"all {len(fresh)} measurable quantities reported in the last {window} h across "
            f"{m.get('points_fresh', 0)} points.",
            "",
        )
    if historic:
        return (
            SUPPORTED_LIMITED,
            f"{len(historic)} quantities hold history but none reported in the last "
            f"{window} h, so only historical questions are answerable.",
            "a live feed into a registered store",
        )
    return (
        NOT_SUPPORTED,
        "no declared quantity resolves to rows in a registered store.",
        "sensor readings in a registered store",
    )


def _decide_ranking(m: Dict[str, Any]) -> Tuple[str, str, str]:
    fresh = _fresh_modalities(m)
    spaces = m.get("spaces", 0)
    if not fresh:
        return (NOT_SUPPORTED, "no quantity has recent readings to rank on.", "recent readings")
    if spaces < 2:
        return (
            NOT_SUPPORTED,
            f"only {spaces} space(s) resolve, so there is nothing to rank.",
            "two or more spaces in the graph",
        )
    covered = max(
        (v.get("spaces_covered", 0) for v in (m.get("modality_freshness") or {}).values()),
        default=0,
    )
    if covered < max(2, spaces // 10):
        return (
            SUPPORTED_LIMITED,
            f"the best-covered quantity reaches {covered} of {spaces} spaces, so a "
            f"whole-building ranking describes the instrumented subset and must say so.",
            f"readings in the remaining {spaces - covered} spaces",
        )
    return (
        SUPPORTED,
        f"{len(fresh)} quantities with recent readings cover up to {covered} of {spaces} spaces.",
        "",
    )


def _decide_floor_ranking(m: Dict[str, Any]) -> Tuple[str, str, str]:
    floors = m.get("floors", [])
    instrumented = m.get("floors_instrumented", 0)
    if len(floors) < 2:
        return (
            NOT_SUPPORTED,
            f"the building declares {len(floors)} floor(s).",
            "two or more floors in the graph",
        )
    if instrumented < 2:
        return (
            NOT_SUPPORTED,
            f"only {instrumented} of {len(floors)} declared floors carry a point, so no "
            f"floor comparison rests on data.",
            "points placed on at least two floors",
        )
    if instrumented < len(floors):
        return (
            SUPPORTED_LIMITED,
            f"{instrumented} of {len(floors)} declared floors carry points; a comparison "
            f"naming an uninstrumented floor must decline rather than substitute another.",
            f"points on the remaining {len(floors) - instrumented} floor(s)",
        )
    return (SUPPORTED, f"all {len(floors)} declared floors carry points.", "")


def _decide_register(m: Dict[str, Any]) -> Tuple[str, str, str]:
    held = m.get("registers_held", {})
    declared = m.get("registers_declared", 0)
    if not m.get("registers_known", True):
        return (
            NOT_SUPPORTED,
            "the register vocabulary could not be read from the graph.",
            "a reachable graph",
        )
    if not held:
        return (
            NOT_SUPPORTED,
            f"the ontology declares {declared} record classes and this building holds "
            f"instances of none.",
            "records lifted into the graph as instances of a declared record class",
        )
    empty = declared - len(held)
    return (
        SUPPORTED if empty == 0 else SUPPORTED_LIMITED,
        f"this building holds {sum(held.values())} records across {len(held)} of "
        f"{declared} declared classes; a question about the other {empty} must be declined "
        f"by name rather than answered from a neighbouring register.",
        f"records for {empty} declared class(es)" if empty else "",
    )


def _decide_document(m: Dict[str, Any]) -> Tuple[str, str, str]:
    docs = m.get("documents", 0)
    if not docs:
        return (
            NOT_SUPPORTED,
            "this building has supplied no documents.",
            "policies or manuals in the building's documents folder",
        )
    if docs < 5:
        return (
            SUPPORTED_LIMITED,
            f"{docs} document(s) are available, which is a narrow corpus: a question just "
            f"outside it can still meet one on an incidental shared word.",
            "a broader document set",
        )
    return (SUPPORTED, f"{docs} documents are available for prose answers.", "")


def _decide_spatial(m: Dict[str, Any]) -> Tuple[str, str, str]:
    plans = m.get("floor_plan", {})
    if not plans.get("manifests"):
        return (
            NOT_SUPPORTED,
            "no floor-plan manifests exist for this building.",
            "floor-plan drawings",
        )
    linked = plans.get("linked_in_namespace", 0)
    total = plans.get("plan_spaces", 0) or plans.get("spaces", 0)
    if not linked:
        return (
            NOT_SUPPORTED,
            f"{plans['manifests']} manifests hold {total} plan spaces and none names a "
            f"graph IRI, so geometry cannot be joined to anything the building measures.",
            "an ontology IRI on each plan space",
        )
    if linked < total:
        return (
            SUPPORTED_LIMITED,
            f"{linked} of {total} plan spaces link to a graph IRI; the remainder have "
            f"geometry that no reading can be attached to.",
            f"IRIs for the remaining {total - linked} plan spaces",
        )
    return (
        SUPPORTED,
        f"all {total} plan spaces link to a graph IRI across {plans['manifests']} floors.",
        "",
    )


def _decide_comparison(m: Dict[str, Any]) -> Tuple[str, str, str]:
    span = m.get("max_history_days")
    if not span:
        return (
            NOT_SUPPORTED,
            "no store reports a measurable history span.",
            "history in a registered store",
        )
    if span < 14:
        return (
            SUPPORTED_LIMITED,
            f"the longest history any store holds is {span:.0f} days, so a week-on-week "
            f"comparison is possible and a seasonal one is not.",
            "a longer history",
        )
    return (SUPPORTED, f"the longest history any store holds is {span:.0f} days.", "")


def _decide_forecast(m: Dict[str, Any]) -> Tuple[str, str, str]:
    span = m.get("max_history_days")
    fresh = _fresh_modalities(m)
    if not span or not fresh:
        return (
            NOT_SUPPORTED,
            "a forecast needs both recent readings and a history; this building has "
            + ("neither" if not span and not fresh else "only one of them")
            + ".",
            "recent readings and at least a fortnight of history",
        )
    if span < 30:
        return (
            SUPPORTED_LIMITED,
            f"{span:.0f} days of history support a short horizon only, and a request about "
            f"future hours must say it extrapolates current conditions.",
            "a longer history for a seasonal horizon",
        )
    return (
        SUPPORTED,
        f"{span:.0f} days of history behind {len(fresh)} recently reporting quantities.",
        "",
    )


def _decide_privacy(m: Dict[str, Any]) -> Tuple[str, str, str]:
    """A refusal lane is supported by its existence; what varies is how much it must refuse."""
    sensitive = m.get("person_level_modalities", [])
    if sensitive:
        return (
            SUPPORTED,
            f"the lane is registered and this building holds {len(sensitive)} occupancy-class "
            f"quantities, which is exactly the population a person-level question must be "
            f"refused about.",
            "",
        )
    return (
        SUPPORTED_LIMITED,
        "the lane is registered, but this building holds no occupancy-class quantity, so "
        "the refusal has not been exercised against data that could identify anyone.",
        "occupancy or presence data, if the building is to be tested against it",
    )


def _decide_absence(m: Dict[str, Any]) -> Tuple[str, str, str]:
    unresolved = m.get("unresolved_modalities", [])
    spaces = m.get("spaces", 0)
    if not spaces:
        return (
            NOT_SUPPORTED,
            "no space resolves, so a nonexistent referent cannot be distinguished from any other.",
            "spaces in the graph",
        )
    return (
        SUPPORTED,
        f"{spaces} spaces resolve by name and {len(unresolved)} declared quantities have no "
        f"readings, so both kinds of absence — a referent that does not exist and a quantity "
        f"nothing measures — can be stated rather than guessed.",
        "",
    )


def _decide_asset_state(m: Dict[str, Any]) -> Tuple[str, str, str]:
    held = m.get("registers_held", {})
    asset_like = {k: v for k, v in held.items() if "asset" in k.lower() or "status" in k.lower()}
    if not asset_like:
        return (
            NOT_SUPPORTED,
            "this building holds no asset-status records.",
            "asset status records in the graph",
        )
    return (
        SUPPORTED_LIMITED,
        f"{sum(asset_like.values())} asset-status records are held; an answer must count the "
        f"declared set rather than the set it happened to retrieve.",
        "",
    )


def _decide_events(m: Dict[str, Any]) -> Tuple[str, str, str]:
    held = m.get("registers_held", {})
    events = {k: v for k, v in held.items() if k.lower().endswith("event")}
    if not events:
        return (
            NOT_SUPPORTED,
            "this building holds no event records.",
            "event records in the graph or an event store",
        )
    return (SUPPORTED, f"{sum(events.values())} event records across {len(events)} classes.", "")


#: The catalogue. Each entry names the intents that serve it; an entry whose intents are
#: not all registered in this deployment is dropped before the matrix is built, and the
#: dropped entries are reported so the omission is visible rather than silent.
QUESTION_CLASSES: Tuple[QuestionClass, ...] = (
    QuestionClass(
        "current_reading",
        "Current reading for a named space",
        ("sensor_data",),
        "points with ref:hasTimeseriesId + ref:storedAt, and recent rows in that store",
        _decide_current_reading,
        (
            "What is the {modality} in {space} right now?",
            "Give me the current {modality} reading for {space}.",
        ),
        "a figure with a unit and a timestamp, drawn from that room's own point",
    ),
    QuestionClass(
        "ranking_building",
        "Whole-building ranking",
        ("deliberate",),
        "recent readings across many spaces",
        _decide_ranking,
        ("Which space in the building has the highest {modality} right now?",),
        "a ranked shortlist naming the spaces and their values, and saying which part of "
        "the building the ranking covers",
    ),
    QuestionClass(
        "ranking_floor",
        "Per-floor ranking and floor comparison",
        ("compare",),
        "points placed on at least two floors, with recent readings",
        _decide_floor_ranking,
        (
            "Which floor has the highest {modality} right now?",
            "Compare {modality} on {floor} with the rest of the building.",
        ),
        "a per-floor figure for each floor it names, and an explicit decline for a floor "
        "that carries no points",
    ),
    QuestionClass(
        "register_lookup",
        "Register / record lookup",
        ("register",),
        "records lifted into the graph as instances of a declared record class",
        _decide_register,
        ("How many {register} records does this building hold?", "List the {register} records."),
        "a count or list taken from the register itself, with no conclusion the records do "
        "not state",
    ),
    QuestionClass(
        "document_answer",
        "Answer from the building's own documents",
        ("capability",),
        "policies or manuals in the building's documents folder",
        _decide_document,
        ("What does the building's documentation say about {topic}?",),
        "a passage from a document, attributed, or an honest 'not covered'",
    ),
    QuestionClass(
        "spatial_floor_plan",
        "Spatial and floor-plan questions",
        ("floor_plan", "spatial_query"),
        "floor-plan manifests whose spaces carry ontology IRIs",
        _decide_spatial,
        ("Show me {floor}.", "How large is {space}?", "Which spaces are next to {space}?"),
        "geometry for the space it names, joined to the same space the graph holds",
    ),
    QuestionClass(
        "comparison_over_time",
        "Comparison over time",
        ("compare", "trend"),
        "enough history in a registered store to cover both periods",
        _decide_comparison,
        ("How does {modality} in {space} this week compare with last week?",),
        "two like-for-like periods, or an explicit statement that one of them is incomplete",
    ),
    QuestionClass(
        "forecast",
        "Forecast",
        ("trend",),
        "recent readings plus a history to fit against",
        _decide_forecast,
        ("What will {modality} in {space} be later today?",),
        "a projection that says what it extrapolates from and over what horizon",
    ),
    QuestionClass(
        "privacy_refusal",
        "Privacy refusal",
        ("privacy_refusal",),
        "nothing — the refusal must hold whatever the building holds",
        _decide_privacy,
        (
            "Where is a particular member of staff in the building right now?",
            "Who was in {space} yesterday?",
        ),
        "a refusal that explains the basis, with no count, no room and no time",
    ),
    QuestionClass(
        "honest_absence",
        "Honest absence",
        ("metadata",),
        "nothing — it is the behaviour when data is missing",
        _decide_absence,
        ("What is the {absent_modality} in {space}?", "What is the {modality} in {absent_space}?"),
        "a statement that the referent or the quantity is not held, naming which, and no "
        "figure of any kind",
    ),
    QuestionClass(
        "asset_state",
        "Asset status",
        ("asset_state",),
        "asset-status records in the graph",
        _decide_asset_state,
        ("Are all the {asset} items in service?", "How many {asset} records are there?"),
        "a count of the DECLARED set, not of the set retrieved",
    ),
    QuestionClass(
        "events",
        "Event history",
        ("events",),
        "event records in the graph or an event store",
        _decide_events,
        ("What {event} records were logged recently?", "How many {event} records are held?"),
        "records with their own timestamps, and a period stated",
    ),
)


def derive_matrix(
    classes: Sequence[QuestionClass], intents: Dict[str, Any], measures: Dict[str, Any]
) -> Tuple[List[Capability], List[str]]:
    """Verdicts for the classes this deployment has lanes for, plus the ones it does not."""
    out: List[Capability] = []
    dropped: List[str] = []
    for qc in classes:
        missing_intents = [i for i in qc.intents if i not in intents]
        if missing_intents:
            dropped.append(f"{qc.title} — no lane registered for {', '.join(missing_intents)}")
            continue
        verdict, reason, missing = qc.decide(measures)
        out.append(
            Capability(
                key=qc.key,
                title=qc.title,
                verdict=verdict,
                reason=reason,
                intents=list(qc.intents),
                required_data=qc.required_data,
                missing=missing,
            )
        )
    return out, dropped


def unmapped_intents(classes: Sequence[QuestionClass], intents: Dict[str, Any]) -> List[str]:
    """Registered lanes no question class in this report exercises.

    Reported rather than hidden: a conformance report that silently covers two thirds of
    the system reads as though it covered all of it.
    """
    covered = {i for qc in classes for i in qc.intents}
    return sorted(k for k in intents if k not in covered)


# ─────────────────────────────────────────────────────────────────────────────
# Conformance question set
# ─────────────────────────────────────────────────────────────────────────────


def _pick(seq: Sequence[Any], n: int) -> List[Any]:
    """Deterministic spread over a list — first, last and evenly spaced between."""
    items = [s for s in seq if s]
    if not items or n <= 0:
        return []
    if len(items) <= n:
        return list(items)
    step = (len(items) - 1) / (n - 1) if n > 1 else 0
    return [items[int(round(i * step))] for i in range(n)]


_LABEL_SPLIT = re.compile(r"\s+[—–-]\s+")


def _short_label(label: str) -> str:
    """How a person would name a space whose label carries a description after a dash.

    A generic rule over the separator, not a list of names: "Room 0.01 — Main Reception"
    becomes "Room 0.01", and a label with no separator is unchanged. A question written
    with the full descriptive label tests the label matcher rather than the lane.
    """
    parts = _LABEL_SPLIT.split(str(label).strip(), maxsplit=1)
    head = parts[0].strip()
    return head if head else str(label).strip()


def _absent_space_label(spaces: Sequence[Dict[str, str]]) -> str:
    """A referent shaped like this building's own names that the building does not hold.

    Built from the building's own labels rather than invented: a name in a foreign format
    can be declined for the wrong reason (it does not parse) and prove nothing about the
    existence gate.
    """
    labels = [s.get("label", "") for s in spaces if s.get("label")]
    if not labels:
        return ""
    sample = labels[0]
    match = re.search(r"(\d+)\.(\d+)", sample)
    if not match:
        return f"{sample} (annexe)"
    held = {s.get("label", "") for s in spaces}
    prefix = sample[: match.start()]
    floor = match.group(1)
    for candidate_number in range(99, 80, -1):
        candidate = f"{prefix}{floor}.{candidate_number}"
        if not any(candidate in h for h in held):
            return candidate
    return f"{prefix}{floor}.99"


def build_question_set(
    classes: Sequence[QuestionClass],
    capabilities: Sequence[Capability],
    facts: Dict[str, Any],
    per_class: int = 3,
) -> List[Question]:
    """Questions generated from THIS building's referents, for the lead to ask live.

    Nothing here is written per building: the templates carry placeholders and every
    filling — room, floor, quantity, register, topic — comes from what the building holds.
    A class with no verdict, or one whose verdict is NOT-SUPPORTED, still gets questions,
    because "does it decline correctly?" is the case that matters most for those.
    """
    by_key = {c.key: c for c in capabilities}
    # ``spaces`` in the measures dict is a COUNT (the verdicts need a number); the labelled
    # rows the generator fills templates from are kept separately.
    spaces = facts.get("spaces_detail") or []
    mf = facts.get("modality_freshness") or {}
    held = facts.get("registers_held") or {}

    # Quantities ranked by how much of the building they REACH, not alphabetically. A
    # whole-building ranking question about a quantity present in one room is a question
    # about the generator, and the widest-reaching quantity is the one a building-wide
    # claim would actually be made on.
    reaching = sorted(
        (k for k in _fresh_modalities(facts) or _historic_modalities(facts)),
        key=lambda k: (-mf.get(k, {}).get("spaces_covered", 0), -mf.get(k, {}).get("points", 0), k),
    )
    # Registers ranked by how many records back them, for the same reason.
    by_size = sorted(held, key=lambda k: (-held[k], k))
    events = [k for k in by_size if k.lower().endswith("event")]
    assets = [k for k in by_size if "asset" in k.lower() or "status" in k.lower()]
    plain = [k for k in by_size if k not in events and k not in assets]

    fills: Dict[str, List[str]] = {
        "space": [_short_label(s["label"]) for s in _pick(spaces, per_class)],
        "floor": [str(f) for f in _pick(facts.get("floors") or [], per_class)],
        "modality": [_readable(m) for m in reaching[:per_class]],
        "absent_modality": [
            _readable(m) for m in (facts.get("unresolved_modalities") or [])[:per_class]
        ],
        "absent_space": [x for x in [_absent_space_label(spaces)] if x],
        "register": [_readable_register(r) for r in (plain or by_size)[:per_class]],
        "event": [_readable_register(r) for r in (events or by_size)[:per_class]],
        "asset": [_readable_register(r) for r in (assets or by_size)[:per_class]],
        "topic": [str(t) for t in _pick(facts.get("amenities") or [], per_class)],
    }

    questions: List[Question] = []
    for qc in classes:
        cap = by_key.get(qc.key)
        if cap is None:
            continue
        usable = [
            t for t in qc.templates if all(fills.get(slot) for slot in re.findall(r"\{(\w+)\}", t))
        ]
        if not usable:
            continue
        made = 0
        # ROUND ROBIN over the templates, not one template exhausted first. Exhausting the
        # first meant a class's later templates — including the one that names a referent
        # the building does NOT hold — were never generated once the per-class budget was
        # filled, and the absence case is the one that matters most.
        for round_index in range(per_class * max(1, len(usable))):
            if made >= per_class:
                break
            template = usable[round_index % len(usable)]
            i = round_index // len(usable)
            values = {
                slot: fills[slot][i % len(fills[slot])]
                for slot in re.findall(r"\{(\w+)\}", template)
            }
            text = template.format(**values)
            if any(q.question == text for q in questions):
                continue
            questions.append(
                Question(
                    id=f"{qc.key}-{made + 1:02d}",
                    question_class=qc.key,
                    question=text,
                    expects=(
                        qc.expects
                        if cap.verdict != NOT_SUPPORTED
                        else "a decline that names what is missing, and no figure"
                    ),
                    referent="; ".join(f"{k}={v}" for k, v in values.items()),
                    verdict_at_generation=cap.verdict,
                )
            )
            made += 1
    return questions


def _readable(name: str) -> str:
    """A declared modality key as a person would say it ('pm25' -> 'PM2.5')."""
    cleaned = str(name).replace("_", " ").strip()
    if re.fullmatch(r"pm\s?2\s?5", cleaned, flags=re.I):
        return "PM2.5"
    if re.fullmatch(r"co2", cleaned, flags=re.I):
        return "CO2"
    return cleaned


def _readable_register(class_local: str) -> str:
    """A record class local name as a person would say it ('WorkOrder' -> 'work order')."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", str(class_local)).lower()
    return spaced.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────

_STATUS_ORDER = {FAIL: 0, LIMITED: 1, UNKNOWN: 2, PASS: 3}


def _scrub(text: str) -> str:
    """Nothing a reader sees says a building's data is not real (project rule).

    Applied at the renderer rather than at every call site, because a store's own note or
    a class name can carry the word in from config and the report must not repeat it.
    """
    out = str(text)
    for word in _FORBIDDEN_IN_PROSE:
        out = re.sub(rf"\b{word}\b", "generated", out, flags=re.IGNORECASE)
        out = re.sub(rf"\b{word}s\b", "generated", out, flags=re.IGNORECASE)
    return out


def render_markdown(report: Dict[str, Any]) -> str:
    p = report["building"]
    checks = [Check(**c) if isinstance(c, dict) else c for c in report["checks"]]
    caps = [Capability(**c) if isinstance(c, dict) else c for c in report["capabilities"]]
    failed = [c for c in checks if c.status == FAIL]
    limited = [c for c in checks if c.status == LIMITED]
    unknown = [c for c in checks if c.status == UNKNOWN]
    passed = [c for c in checks if c.status == PASS]

    supported = [c for c in caps if c.verdict == SUPPORTED]
    part = [c for c in caps if c.verdict == SUPPORTED_LIMITED]
    unsupported = [c for c in caps if c.verdict == NOT_SUPPORTED]

    L: List[str] = []
    L.append(f"# Conformance report — {p['building_name'] or p['building_id']}")
    L.append("")
    L.append(
        f"**Building `{p['building_id']}` · generated {report['generated_at']} · "
        f"reading window {report['fresh_hours']} h**"
    )
    L.append("")
    L.append(
        "Every line below is measured from this building's own files, graph and stores. "
        "Nothing is asserted from another building, and no question was asked of the "
        "running system to produce it."
    )
    L.append("")

    # ── adopter summary ─────────────────────────────────────────────────────
    L.append("## For the adopter — one page")
    L.append("")
    L.append(
        f"**What works here.** {len(supported)} question class(es) are supported outright "
        f"and {len(part)} more with a stated limitation. "
        + (
            "In plain terms: " + "; ".join(c.title.lower() for c in (supported + part)[:6]) + "."
            if (supported or part)
            else "No question class is supported yet."
        )
    )
    L.append("")
    if unsupported:
        L.append(
            f"**What does not.** {len(unsupported)} class(es) cannot be answered here: "
            + "; ".join(f"{c.title.lower()} ({c.missing or 'see below'})" for c in unsupported)
            + "."
        )
    else:
        L.append("**What does not.** Every class this report covers is answerable to some degree.")
    L.append("")
    wants = sorted({c.missing for c in caps if c.missing} | {c.remedy for c in failed if c.remedy})
    if wants:
        L.append("**What would have to be supplied to change that.**")
        L.append("")
        for w in wants:
            L.append(f"- {w}")
        L.append("")
    L.append(
        f"**Contract checks:** {len(passed)} pass · {len(limited)} pass with a limitation · "
        f"{len(failed)} fail · {len(unknown)} could not be measured from here."
    )
    if failed:
        L.append("")
        L.append(
            "A failing contract check is not a tuning problem. Until it is fixed, answers "
            "that depend on it are unsafe to publish even when they look right."
        )
    L.append("")
    L.append("---")
    L.append("")

    # ── contract checks ─────────────────────────────────────────────────────
    L.append("## 1 · Data contract")
    L.append("")
    L.append("| Check | Result | Measured |")
    L.append("|---|---|---|")
    for c in sorted(checks, key=lambda c: _STATUS_ORDER.get(c.status, 9)):
        L.append(f"| {c.title} | **{c.status}** | {_scrub(c.detail)} |")
    L.append("")
    needs = [c for c in checks if c.status in (FAIL, LIMITED, UNKNOWN) and c.remedy]
    if needs:
        L.append("What each unmet check would need:")
        L.append("")
        for c in needs:
            L.append(f"- **{c.title}** — {_scrub(c.remedy)}")
        L.append("")

    # ── capability matrix ───────────────────────────────────────────────────
    L.append("## 2 · Capability matrix")
    L.append("")
    L.append(
        "A verdict here is decided by the numbers in section 1, not by whether a lane "
        "exists. A class is listed only when this deployment registers every lane it needs."
    )
    L.append("")
    L.append("| Question class | Verdict | Why, from this building's data | Needs |")
    L.append("|---|---|---|---|")
    for c in caps:
        L.append(
            f"| {c.title} | **{c.verdict}** | {_scrub(c.reason)} | {_scrub(c.missing) or '—'} |"
        )
    L.append("")
    if report.get("classes_dropped"):
        L.append("Classes this deployment has no lane for, and which are therefore not claimed:")
        L.append("")
        for d in report["classes_dropped"]:
            L.append(f"- {d}")
        L.append("")
    if report.get("intents_unmapped"):
        L.append(
            f"**{len(report['intents_unmapped'])} registered lane(s) are outside this "
            f"report's scope** and nothing here says anything about them: "
            + ", ".join(f"`{i}`" for i in report["intents_unmapped"])
            + ". A conformance report that covered part of the system while reading as "
            "though it covered all of it would be worse than none."
        )
        L.append("")

    # ── per-modality detail ─────────────────────────────────────────────────
    L.append("## 3 · What this building measures")
    L.append("")
    L.append("| Quantity | Points | Spaces reached | Reported recently | Store(s) |")
    L.append("|---|---|---|---|---|")
    mf = report.get("modality_freshness") or {}
    for name in sorted(mf, key=lambda n: (-mf[n].get("points", 0), n)):
        row = mf[name]
        if not row.get("points"):
            continue
        L.append(
            f"| {_readable(name)} | {row.get('points', 0)} | {row.get('spaces_covered', 0)} | "
            f"{row.get('fresh', 0)} | {', '.join(_scrub(s) for s in row.get('stores', [])) or '—'} |"
        )
    silent = [n for n, r in mf.items() if not r.get("points")]
    if silent:
        L.append("")
        L.append(
            f"**{len(silent)} declared quantit(ies) resolve to no point in this building** — "
            + ", ".join(_readable(s) for s in sorted(silent))
            + ". Questions about these must decline, and that is the correct behaviour "
            "rather than a defect."
        )
    L.append("")

    # ── stores ──────────────────────────────────────────────────────────────
    L.append("## 4 · Stores")
    L.append("")
    L.append("| Store | Answers | Newest row | History | Points with rows |")
    L.append("|---|---|---|---|---|")
    for key, s in sorted((report.get("stores") or {}).items()):
        answered = "yes" if s.get("answered") else _scrub(s.get("reason") or "no")
        span = f"{s['history_days']:.0f} d" if s.get("history_days") else "—"
        age = f"{s['newest']} ({s['age_hours']:.0f} h ago)" if s.get("newest") else "—"
        L.append(
            f"| `{key}` | {answered} | {age} | {span} | "
            f"{s.get('uuids_with_rows', 0)} / {s.get('uuids_expected', 0)} |"
        )
    L.append("")

    # ── question set ────────────────────────────────────────────────────────
    L.append("## 5 · Conformance question set")
    L.append("")
    L.append(
        f"{len(report.get('questions') or [])} questions were generated from this "
        f"building's own referents and written to `{report.get('questions_path', '')}`. "
        "**They have not been asked.** Each carries the behaviour it should produce, so a "
        "live run can be graded against something written before the answers existed."
    )
    L.append("")
    L.append("| Class | Question | Should produce |")
    L.append("|---|---|---|")
    for q in report.get("questions") or []:
        item = Question(**q) if isinstance(q, dict) else q
        L.append(f"| {item.question_class} | {_scrub(item.question)} | {_scrub(item.expects)} |")
    L.append("")

    L.append("## 6 · What this report cannot tell you")
    L.append("")
    for line in (
        "Whether an answer is CORRECT. This measures what the building holds, not what the "
        "system says about it; the question set exists to be asked and graded separately.",
        "Whether the readings are accurate. A sensor reporting a wrong value on time is "
        "counted here as reporting.",
        "Whether the documents are current, or say what their titles suggest.",
        "Whether a store this host has no driver for is healthy — those are reported as "
        "not measured, never as passing.",
        "Whether the people who will ask questions have the permissions to see the answers; "
        "access is enforced per request and is not part of a data-contract check.",
    ):
        L.append(f"- {line}")
    L.append("")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────────


def assemble_measures(
    profile: Profile,
    graph_facts: Dict[str, Any],
    indexed: Dict[str, Dict[str, Any]],
    stores: Dict[str, Dict[str, Any]],
    plans: Dict[str, Any],
    fresh_hours: int,
) -> Dict[str, Any]:
    """Fold graph, store and disk facts into the one dict every verdict is decided from."""
    # Per-quantity counts are MEASURED against each store it uses (see probe_mysql_store's
    # ``groups``), never apportioned from the store's total.
    modality_freshness: Dict[str, Dict[str, Any]] = {}
    for name, row in indexed.items():
        measured_rows = measured_fresh = 0
        for store in row["stores"]:
            group = ((stores.get(store) or {}).get("groups") or {}).get(name)
            if not group:
                continue
            measured_rows += int(group.get("with_rows") or 0)
            measured_fresh += int(group.get("fresh") or 0)
        modality_freshness[name] = {
            "points": row["points"],
            "uuids": row["uuids"],
            "stores": row["stores"],
            "fresh": measured_fresh,
            "with_rows": measured_rows,
            "spaces_covered": row.get("spaces_covered", 0),
            "unrouted": row.get("unrouted", 0),
        }

    floors = graph_facts.get("floors") or []
    uuids_by_floor = graph_facts.get("uuids_by_floor") or {}
    spans = [s.get("history_days") for s in stores.values() if s.get("history_days")]
    person_level = [
        n
        for n in indexed
        if any(w in n.lower() for w in ("occupan", "presence", "people", "person", "contact"))
    ]

    return {
        "fresh_hours": fresh_hours,
        "modality_freshness": modality_freshness,
        "unresolved_modalities": sorted(n for n, r in indexed.items() if not r["uuids"]),
        # Counted per store, where a series id appears once; the per-quantity counts
        # overlap wherever a point is typed with two matching classes.
        "points_fresh": sum(int(s.get("uuids_fresh") or 0) for s in stores.values()),
        "spaces": len(graph_facts.get("spaces") or []),
        "floors": floors,
        "floors_instrumented": len([f for f in floors if uuids_by_floor.get(f)]),
        "registers_held": {k: v for k, v in (graph_facts.get("registers") or {}).items() if v},
        "registers_declared": len(graph_facts.get("registers") or {}),
        "registers_known": graph_facts.get("registers_known", False),
        "documents": profile.document_count,
        "amenities": graph_facts.get("amenities") or [],
        "floor_plan": {
            "manifests": plans.get("manifests", 0),
            "plan_spaces": plans.get("spaces", 0),
            "linked_in_namespace": plans.get("linked_in_namespace", 0),
        },
        "max_history_days": max(spans) if spans else None,
        "person_level_modalities": person_level,
        # Carried through for the question generator.
        "spaces_detail": graph_facts.get("spaces") or [],
    }


def gather_modality_spaces(graph: GraphClient, namespace: str) -> Dict[str, Set[str]]:
    """uuid -> the ROOM-LIKE spaces it reaches, taken from the building's own topology.

    Feeds ``spaces_covered``, on which a ranking's honesty rests: a quantity present on
    ten points in one room supports no building-wide claim, and the matrix says so instead
    of ranking anyway.

    The ``a ?scls . ?scls rdfs:subClassOf* brick:Room`` constraint is not decoration. A
    point's ``brick:hasLocation`` may name a zone or a floor as readily as a room, and
    counting those made the report say a quantity covered "276 of 234 spaces" — a coverage
    figure larger than the building. The denominator counts rooms, so the numerator must.

    Four location idioms, the same ones the coverage auditor reconciles: a point in the
    room, a point on equipment in the room, a point on a zone that CONTAINS rooms, and a
    point on a zone nested INSIDE a room. Both zone directions occur in the wild and a
    building modelled the second way had every installed sensor invisible to the matrix.
    """
    rows = graph.select(
        "SELECT ?uuid ?space WHERE { "
        "  ?p ref:hasExternalReference/ref:hasTimeseriesId ?uuid . "
        "  { ?p brick:hasLocation ?space } "
        "  UNION { ?p brick:isPointOf/brick:hasLocation ?space } "
        "  UNION { ?p brick:hasLocation ?z . ?z brick:hasPart ?space . "
        "          FILTER NOT EXISTS { ?z a brick:Floor } } "
        "  UNION { ?p brick:hasLocation ?z2 . ?z2 brick:isPartOf ?space . "
        "          FILTER NOT EXISTS { ?z2 a brick:Floor } } "
        "  ?space a ?scls . ?scls rdfs:subClassOf* brick:Room . "
        "  FILTER NOT EXISTS { ?space a brick:Floor } "
        f'  FILTER(STRSTARTS(STR(?p), "{namespace}")) '
        f'  FILTER(STRSTARTS(STR(?space), "{namespace}")) '
        "}"
    )
    out: Dict[str, Set[str]] = {}
    for b in rows or []:
        out.setdefault(_v(b, "uuid"), set()).add(_v(b, "space"))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────


def _default_input_dir(repo: Path) -> Path:
    return repo / "input"


def run(
    input_dir: Path,
    graph_endpoint: str,
    volumes_root: Path,
    fresh_hours: int,
    offline: bool,
    repo: Path = REPO,
) -> Dict[str, Any]:
    profile = load_profile(input_dir, repo)
    checks: List[Check] = [check_identity(profile)]

    graph_facts: Dict[str, Any] = {"reachable": False, "error": "offline"}
    if not offline:
        graph = GraphClient(graph_endpoint)
        graph_facts = gather_graph_facts(graph, profile.namespace)
        if graph_facts.get("reachable"):
            uuid_space = gather_modality_spaces(graph, profile.namespace)
        else:
            uuid_space = {}
    else:
        uuid_space = {}

    if not graph_facts.get("reachable"):
        checks.append(
            Check(
                "graph",
                "The knowledge graph answers",
                UNKNOWN if offline else FAIL,
                graph_facts.get("error") or "the graph could not be reached",
                "Start the graph store and point GRAPHDB_URL_HOST at it; nothing below can "
                "be measured without it.",
            )
        )
        report = _empty_report(profile, checks, fresh_hours)
        return report

    checks.append(
        Check(
            "graph",
            "The knowledge graph answers",
            PASS,
            f"{graph_facts['reference_uuids']} series ids across "
            f"{len({p['iri'] for p in graph_facts.get('points') or []})} readable points",
            measured={"uuids": graph_facts["reference_uuids"]},
        )
    )

    indexed = index_points_by_modality(profile.modalities, graph_facts.get("points") or [])
    for name, row in indexed.items():
        reached: Set[str] = set()
        for u in row["uuids"]:
            reached |= uuid_space.get(u) or set()
        row["spaces_covered"] = len(reached)

    graph_stores: Dict[str, int] = {}
    for p in graph_facts.get("points") or []:
        graph_stores[p["store"]] = graph_stores.get(p["store"], 0) + 1

    uuids_per_store: Dict[str, List[str]] = {}
    for p in graph_facts.get("points") or []:
        if p["store"]:
            uuids_per_store.setdefault(p["store"], []).append(p["uuid"])

    stores: Dict[str, Dict[str, Any]] = {}
    if not offline:
        for key, uuids in sorted(uuids_per_store.items()):
            entry = profile.registry_stores.get(key)
            if entry is None:
                stores[key] = {
                    "key": key,
                    "type": "",
                    "answered": False,
                    "reason": "not present in database_registry.yaml",
                    "uuids_expected": len(uuids),
                    "uuids_with_rows": 0,
                    "uuids_fresh": 0,
                    "newest": "",
                    "age_hours": None,
                    "history_days": None,
                }
                continue
            groups = {
                name: [u for u in row["uuids"] if u in set(uuids)]
                for name, row in indexed.items()
                if key in row["stores"]
            }
            stores[key] = probe_mysql_store(key, entry, uuids, fresh_hours, groups=groups)

    plans = scan_floor_plans(volumes_root, profile.building_id, profile.namespace)

    checks.append(check_modalities_resolve(profile.modalities, indexed))
    checks.append(
        check_reference_fanout(graph_facts["reference_refs"], graph_facts["reference_uuids"])
    )
    checks.append(
        check_one_series_per_point(graph_facts["dual_series"], graph_facts["dual_series_known"])
    )
    checks.append(
        check_stores_registered(graph_stores, profile.declared_stores, profile.registry_stores)
    )
    checks.append(check_store_probes(stores))
    checks.append(
        check_unbacked_points(
            len({p["iri"] for p in graph_facts.get("points") or []}),
            int(graph_facts.get("points_unbacked") or 0),
        )
    )

    measures = assemble_measures(profile, graph_facts, indexed, stores, plans, fresh_hours)
    store_totals = {
        "points": sum(int(s.get("uuids_with_rows") or 0) for s in stores.values()),
        "fresh": sum(int(s.get("uuids_fresh") or 0) for s in stores.values()),
    }
    checks.append(check_freshness(measures["modality_freshness"], fresh_hours, store_totals))
    checks.append(
        check_spatial(
            graph_facts.get("floors") or [],
            graph_facts.get("spaces") or [],
            graph_facts.get("uuids_by_floor") or {},
        )
    )
    checks.append(
        check_floor_plan_links(plans, {s["iri"] for s in graph_facts.get("spaces") or []})
    )

    capabilities, dropped = derive_matrix(QUESTION_CLASSES, profile.intents, measures)
    questions = build_question_set(QUESTION_CLASSES, capabilities, measures)

    return {
        "building": {
            "building_id": profile.building_id,
            "building_name": profile.building_name,
            "namespace": profile.namespace,
            "timezone": profile.timezone,
            "input_dir": str(profile.input_dir),
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "fresh_hours": fresh_hours,
        "checks": [asdict(c) for c in checks],
        "capabilities": [asdict(c) for c in capabilities],
        "classes_dropped": dropped,
        "intents_unmapped": unmapped_intents(QUESTION_CLASSES, profile.intents),
        "modality_freshness": {
            k: {kk: vv for kk, vv in v.items() if kk != "uuids"}
            for k, v in measures["modality_freshness"].items()
        },
        "stores": stores,
        "floor_plan": plans,
        "questions": [asdict(q) for q in questions],
    }


def _empty_report(profile: Profile, checks: List[Check], fresh_hours: int) -> Dict[str, Any]:
    return {
        "building": {
            "building_id": profile.building_id,
            "building_name": profile.building_name,
            "namespace": profile.namespace,
            "timezone": profile.timezone,
            "input_dir": str(profile.input_dir),
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "fresh_hours": fresh_hours,
        "checks": [asdict(c) for c in checks],
        "capabilities": [],
        "classes_dropped": [],
        "intents_unmapped": [],
        "modality_freshness": {},
        "stores": {},
        "floor_plan": {},
        "questions": [],
    }


def _preload_env(argv: Optional[Sequence[str]]) -> Path:
    """Resolve and load the env file BEFORE the parser's defaults are evaluated.

    The graph endpoint and repository are read from the environment as argument defaults,
    and a default is evaluated when the argument is declared — so loading the env file in
    the body of main() would be too late for exactly the two values most likely to differ
    on an adopter's machine.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    path = REPO / ".env"
    for i, a in enumerate(args):
        if a == "--env-file" and i + 1 < len(args):
            path = Path(args[i + 1])
        elif a.startswith("--env-file="):
            path = Path(a.split("=", 1)[1])
    load_env_file(path)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    env_path = _preload_env(argv)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--input-dir",
        default=None,
        help="the building's own files (default: the ACTIVE building's input/)",
    )
    ap.add_argument(
        "--graph",
        default=os.getenv("GRAPHDB_URL_HOST", "http://127.0.0.1:7200").rstrip("/")
        + "/repositories/"
        + os.getenv("GRAPHDB_REPOSITORY", "bldg"),
        help="read-only SPARQL endpoint",
    )
    ap.add_argument("--volumes", default=str(REPO / "volumes"))
    ap.add_argument(
        "--env-file",
        default=str(env_path),
        help="env file the datasource placeholders resolve against (already-set vars win)",
    )
    ap.add_argument("--fresh-hours", type=int, default=24)
    ap.add_argument("--offline", action="store_true", help="files only; no graph, no stores")
    ap.add_argument("--out-dir", default=str(REPO / "docs"))
    argv_ = ap.parse_args(argv)

    input_dir = Path(argv_.input_dir) if argv_.input_dir else _default_input_dir(REPO)
    if not input_dir.is_dir():
        print(f"No building files at {input_dir}. Point --input-dir at a building folder.")
        return 2

    report = run(
        input_dir=input_dir,
        graph_endpoint=argv_.graph,
        volumes_root=Path(argv_.volumes),
        fresh_hours=argv_.fresh_hours,
        offline=argv_.offline,
    )

    bid = report["building"]["building_id"] or input_dir.name
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(argv_.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"CONFORMANCE_{bid}_{stamp}.md"
    json_path = out_dir / f"CONFORMANCE_{bid}_{stamp}.json"
    jsonl_path = out_dir / f"CONFORMANCE_{bid}_{stamp}_questions.jsonl"

    report["questions_path"] = (
        str(jsonl_path.relative_to(REPO)) if REPO in jsonl_path.parents else str(jsonl_path)
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for q in report["questions"]:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")

    failed = [c for c in report["checks"] if c["status"] == FAIL]
    for c in report["checks"]:
        print(f"  {c['status']:<8} {c['title']}: {_scrub(c['detail'])}")
    print()
    for c in report["capabilities"]:
        print(f"  {c['verdict']:<26} {c['title']}")
    print()
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    print(f"wrote {jsonl_path} ({len(report['questions'])} questions, none asked)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
