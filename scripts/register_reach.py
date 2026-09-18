# -*- coding: utf-8 -*-
"""Register and amenity REACH, measured offline against the schema file on disk.

What this measures, and why it has to exist before any vocabulary is changed
---------------------------------------------------------------------------
A lay term is a corpus-wide change (lessons.md #38): adding one word changes how every
question containing it is routed. So a vocabulary edit is measured on two sets at once:

* RECALL — the 2,960 stakeholder-catalogue questions in ``docs/smart_building_questions.csv``:
  which register each would select, which absent register it would be declined as, and
  which amenity KIND its class-level vocabulary reaches.
* PRECISION — ``docs/phase0/guard_set.jsonl``, derived MECHANICALLY from the regression
  probe, the demo script and the traps named in the code's own docstrings. A change that
  makes a guard question newly select a register, select a different one, or lose the one
  it passes on today is a failure however much recall it buys.

Nothing here restates the router's logic. The scoring functions are IMPORTED from
``orchestrator/services/record_registry.py`` and ``capability_graph_resolver.py``; this
script only supplies them with what they would read from GraphDB, taken from:

* the schema TTL, parsed with rdflib — so an edit is measured without an upload;
* ONE read-only SPARQL snapshot of the live repository (instance counts per record class,
  and the amenity instances with their own lay terms), cached to JSON. A class the building
  holds no records of is therefore treated as ABSENT, exactly as the router treats it.

Usage
-----
    python scripts/register_reach.py --snapshot            # refresh the GraphDB snapshot
    python scripts/register_reach.py --save before.json    # recall + guard, keep the rows
    python scripts/register_reach.py --compare before.json --sample 40
    python scripts/register_reach.py --derive-guard        # ONLY before a vocabulary change

Exit status is 1 when the guard set has a violation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: The scorer builds one regex per declared term per question, ~900 distinct patterns, and
#: Python's pattern cache holds 512: measured, 88% of the run was spent RECOMPILING patterns
#: it had evicted (37 s per 300 questions, 3.9 s with this). Semantics are unchanged; only the
#: cache size is. The router pays the same cost live — see the report that came with this file.
re._MAXCACHE = max(getattr(re, "_MAXCACHE", 512), 50000)

SCHEMA = REPO / "ontology" / "ontosage_schema.ttl"
CORPUS = REPO / "docs" / "smart_building_questions.csv"
GUARD = REPO / "docs" / "phase0" / "guard_set.jsonl"
PROBE = REPO / "scripts" / "regression_cases.json"
DEMO = REPO / "docs" / "demo_script_questions.txt"
SNAPSHOT = REPO / "scripts" / "outputs" / "register_reach_snapshot.json"

ONTO = "http://ontosage.org/capabilities#"
CORPUS_SOURCE = "stakeholder_catalogue_37"
DEFAULT_ENDPOINT = "http://127.0.0.1:7200/repositories/bldg"

#: Classes that say only "this is a capability" and name no KIND of thing. An amenity match
#: through one of these carries no information about which kind a question is about.
GENERIC_CAPABILITY_CLASSES = frozenset(
    {"Capability", "Amenity", "KnowledgeTopic", "InformationTopic", "Policy", "Procedure"}
)


# ── the router's own code, loaded by path ───────────────────────────────────────────────


def _load(relpath: str, name: str) -> ModuleType:
    """Import a module by file path, so the orchestrator package's heavy __init__ is skipped.

    The module is still the real one — same source, same functions — only loaded without
    pulling in every service the package imports on start-up (eight seconds, and a floor-plan
    warning, for two pure functions).
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def record_registry() -> ModuleType:
    """orchestrator/services/record_registry.py."""
    return _load("orchestrator/services/record_registry.py", "_reach_record_registry")


def capability_resolver() -> ModuleType:
    """orchestrator/services/capability_graph_resolver.py."""
    return _load("orchestrator/services/capability_graph_resolver.py", "_reach_capability_resolver")


# ── the schema ──────────────────────────────────────────────────────────────────────────


def load_schema(path: Path = SCHEMA):
    """The schema TTL as an rdflib graph."""
    from rdflib import Graph

    graph = Graph()
    graph.parse(str(path), format="turtle")
    return graph


def _local(iri: str) -> str:
    return str(iri).rsplit("#", 1)[-1]


def _spaced(name: str) -> str:
    """The class-name seed record_registry uses: CamelCase split into words."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


def schema_record_classes(graph) -> List[str]:
    """Record classes the schema declares, found with the router's OWN discovery query."""
    rr = record_registry()
    return sorted({_local(row[0]) for row in graph.query(rr._DISCOVER_QUERY)})


def class_vocabulary(graph, names: Iterable[str]) -> Dict[str, Tuple[str, str, Tuple[str, ...]]]:
    """{class: (label, lay terms joined by '|', qualifier terms)} as GraphDB would hand them over."""
    from rdflib import RDFS, Namespace, URIRef

    o = Namespace(ONTO)
    out: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {}
    for name in names:
        cls = URIRef(ONTO + name)
        labels = sorted(str(v) for v in graph.objects(cls, RDFS.label))
        lays = sorted({str(v) for v in graph.objects(cls, o.layTerms)})
        quals = tuple(
            sorted({str(v).strip().lower() for v in graph.objects(cls, o.qualifierTerms)})
        )
        out[name] = (labels[0] if labels else name, "|".join(lays), quals)
    return out


def amenity_kind_terms(graph) -> Dict[str, List[str]]:
    """{capability kind: its class-level lay phrases} — every Capability subclass that has any."""
    from rdflib import Namespace, URIRef

    o = Namespace(ONTO)
    query = (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        f"PREFIX o: <{ONTO}>\n"
        "SELECT DISTINCT ?kind WHERE { ?kind rdfs:subClassOf+ o:Capability }"
    )
    out: Dict[str, List[str]] = {}
    for (kind,) in graph.query(query):
        phrases = split_phrases(str(v) for v in graph.objects(URIRef(str(kind)), o.layTerms))
        if phrases:
            out[_local(kind)] = phrases
    return out


def split_phrases(values: Iterable[str]) -> List[str]:
    """Lay-term literals into phrases, the way the capability resolver splits them."""
    seen: List[str] = []
    for value in values:
        for part in re.split(r"[,|]", value or ""):
            part = part.strip().lower()
            if part and part not in seen:
                seen.append(part)
    return seen


# ── the one live read ───────────────────────────────────────────────────────────────────

_COUNT_QUERY = """
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX o: <http://ontosage.org/capabilities#>
SELECT ?cls (COUNT(DISTINCT ?i) AS ?n) WHERE {
  VALUES ?root { o:Record o:IntervalRecord }
  ?cls rdfs:subClassOf+ ?root .
  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#"))
  OPTIONAL { ?i a ?cls }
} GROUP BY ?cls
"""

_AMENITY_LAY_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?a ?lay WHERE {
  { ?a a o:Amenity } UNION { ?a a o:KnowledgeTopic }
  OPTIONAL { ?a o:layTerms ?lay }
}
"""

_AMENITY_TYPE_QUERY = """
PREFIX o: <http://ontosage.org/capabilities#>
SELECT DISTINCT ?a ?cls WHERE {
  { ?a a o:Amenity } UNION { ?a a o:KnowledgeTopic }
  ?a a ?cls .
  FILTER(STRSTARTS(STR(?cls), "http://ontosage.org/capabilities#"))
}
"""


def _select(endpoint: str, query: str) -> List[Dict[str, str]]:
    """A read-only SPARQL SELECT. Never an update: this runs beside live measurements."""
    body = urllib.parse.urlencode({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - local GraphDB
        data = json.loads(response.read().decode("utf-8"))
    return [
        {k: v.get("value", "") for k, v in row.items()}
        for row in data.get("results", {}).get("bindings", [])
    ]


def take_snapshot(endpoint: str = DEFAULT_ENDPOINT) -> dict:
    """Instance counts per record class and the amenity instances, read once."""
    counts = {_local(r["cls"]): int(r.get("n") or 0) for r in _select(endpoint, _COUNT_QUERY)}
    amenities: Dict[str, dict] = {}
    for row in _select(endpoint, _AMENITY_LAY_QUERY):
        entry = amenities.setdefault(_local(row["a"]), {"lays": [], "classes": []})
        if row.get("lay") and row["lay"] not in entry["lays"]:
            entry["lays"].append(row["lay"])
    for row in _select(endpoint, _AMENITY_TYPE_QUERY):
        entry = amenities.setdefault(_local(row["a"]), {"lays": [], "classes": []})
        if _local(row["cls"]) not in entry["classes"]:
            entry["classes"].append(_local(row["cls"]))
    for entry in amenities.values():
        entry["lays"].sort()
        entry["classes"].sort()
    return {
        "endpoint": endpoint,
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record_counts": dict(sorted(counts.items())),
        "amenities": dict(sorted(amenities.items())),
    }


def parse_counts(pairs: Sequence[str]) -> Dict[str, int]:
    """CLASS=N pairs into a dict."""
    out: Dict[str, int] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        out[name.strip()] = int(value)
    return out


def with_counts(snapshot: dict, overrides: Dict[str, int]) -> dict:
    """A copy of the snapshot with some instance counts replaced — to measure a load before it."""
    if not overrides:
        return snapshot
    copy = dict(snapshot)
    copy["record_counts"] = {**snapshot.get("record_counts", {}), **overrides}
    return copy


def load_snapshot(path: Path = SNAPSHOT, endpoint: str = DEFAULT_ENDPOINT) -> dict:
    """The cached snapshot, taken first if there is none."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    snap = take_snapshot(endpoint)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    return snap


# ── the events store (BUG-670) ──────────────────────────────────────────────────────────

EVENT_SERVICE = REPO / "orchestrator" / "services" / "event_query_service.py"


def declared_event_kinds(path: Path = EVENT_SERVICE) -> Tuple[str, Tuple[str, ...]]:
    """(EVENTS_STORE_KEY, the kinds `_KIND_RES` declares), read from the service's SOURCE.

    Parsed rather than imported, for the reason `_load` gives: the service pulls in the whole
    orchestrator package. What the router uses at run time is the same two names, imported.
    """
    import ast

    key, kinds = "", []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        name = getattr(target, "id", "")
        value = getattr(node, "value", None)
        if name == "EVENTS_STORE_KEY" and isinstance(value, ast.Constant):
            key = str(value.value)
        elif name == "_KIND_RES" and isinstance(value, ast.List):
            kinds = [
                elt.elts[0].value
                for elt in value.elts
                if isinstance(elt, ast.Tuple) and isinstance(elt.elts[0], ast.Constant)
            ]
    return key, tuple(kinds)


def events_store_registered(input_dir: Path, store_key: str) -> bool:
    """Whether the building in ``input_dir`` registers the events store, from its two configs.

    Both halves are required, as the adapter registry requires them: the key in building.yaml's
    storage list, and a database_registry.yaml entry of an events type under that key.
    """
    import yaml

    key = store_key.rsplit(":", 1)[-1]
    building = input_dir / "building.yaml"
    registry = input_dir / "database_registry.yaml"
    if not (building.is_file() and registry.is_file()):
        return False
    b = yaml.safe_load(building.read_text(encoding="utf-8")) or {}
    r = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    listed = key in ((b.get("storage") or {}).get("databases") or [])
    entry = (r.get("databases") or {}).get(key) or {}
    return listed and "events" in str(entry.get("type", "")).lower()


def event_store_classes_from_config(names: Iterable[str], input_dir: Path) -> Tuple[str, ...]:
    """The classes record_registry would treat as held in the events store for this building."""
    key, kinds = declared_event_kinds()
    if not events_store_registered(input_dir, key):
        return ()
    return tuple(sorted(record_registry().event_store_record_classes(tuple(names), kinds)))


# ── the model the router would build ────────────────────────────────────────────────────


class Reach:
    """Everything the router reads for one question, built from the schema and a snapshot."""

    def __init__(self, graph, snapshot: dict, event_store_classes: Sequence[str] = ()):
        rr = record_registry()
        #: Record classes a registered events store answers (BUG-670). Empty by default, which
        #: is how the guard set was derived; ``--events-store`` models the active building's.
        self.event_store_classes = tuple(event_store_classes)
        cgr = capability_resolver()
        self._rr = rr
        self._cgr = cgr
        counts: Dict[str, int] = snapshot.get("record_counts", {})
        names = sorted(
            set(schema_record_classes(graph)) | set(counts) | set(rr._FALLBACK_RECORD_CLASSES)
        )
        vocab = class_vocabulary(graph, names)

        # Held path — record_classes(): classes with instances, terms from label + lay terms.
        self.held = []
        for name in names:
            n = int(counts.get(name, 0))
            if n <= 0:
                continue
            label, lays, quals = vocab[name]
            self.held.append(
                rr.RecordClass(name, label, n, rr._terms_for(name, label, lays), qualifiers=quals)
            )

        # Absent path — load_lay_terms(): every class, seeded from the spaced class name.
        rr._ALL_CLASS_TERMS.clear()
        for name in names:
            rr._ALL_CLASS_TERMS[name] = rr._terms_for(
                name, _spaced(name), vocab[name][1], include_head_words=False
            )
        rr._LAY_LOADED = True

        self.kind_terms = amenity_kind_terms(graph)
        self.amenities: Dict[str, dict] = snapshot.get("amenities", {})

    # registers
    def register(self, question: str) -> dict:
        """The held register, a second register, and the absent class a decline would name."""
        held = self._rr.held_record_class(question, self.held)
        second = self._rr.second_record_class(question, self.held, held) if held else None
        absent = (
            None
            if held
            else self._rr.absent_record_class(
                question, self.held, stored_elsewhere=self.event_store_classes
            )
        )
        return {
            "held": held.local_name if held else None,
            "second": second.local_name if second else None,
            "absent": absent,
        }

    def matched_terms(self, question: str, class_name: str) -> List[str]:
        """Which of a held class's terms this question contains — for reading over-capture."""
        low = f" {(question or '').lower()} "
        for record in self.held:
            if record.local_name == class_name:
                quals = set(record.qualifiers)
                return sorted(
                    t
                    for t in record.terms
                    if (
                        self._rr._qualifier_score(t, low)
                        if t in quals
                        else self._rr._term_score(t, low)
                    )
                    > 0
                )
        return []

    # amenities
    def amenity_instances(self, question: str, with_class_terms: bool) -> List[Tuple[int, str]]:
        """Amenity instances the resolver would match, as (score, instance), best first.

        Mirrors CapabilityGraphResolver: one row per declared lay literal, each scored by the
        resolver's own `_score`; with class terms, the instance's kinds add their phrases.
        """
        low = (question or "").lower()
        split = getattr(self._cgr, "_phrases", None) or (lambda v: split_phrases([v]))
        out: List[Tuple[int, str]] = []
        for iri, entry in self.amenities.items():
            extra: List[str] = []
            if with_class_terms:
                for cls in entry.get("classes", []):
                    for p in self.kind_terms.get(cls, []):
                        if p not in extra:
                            extra.append(p)
            best = 0
            for lay in entry.get("lays") or [""]:
                own = split(lay)
                phrases = own + [p for p in extra if p not in own]
                best = max(best, self._cgr._score(low, phrases))
            if best >= self._cgr._MIN_SCORE:
                out.append((best, iri))
        return sorted(out, key=lambda pair: (-pair[0], pair[1]))

    def amenity_kinds(self, instances: Sequence[str]) -> List[str]:
        """The specific kinds of the matched instances, or ['Amenity'] when none is specific."""
        kinds = set()
        generic = False
        for iri in instances:
            classes = self.amenities.get(iri, {}).get("classes", [])
            specific = [c for c in classes if c not in GENERIC_CAPABILITY_CLASSES]
            kinds.update(specific)
            generic = generic or not specific
        if not kinds and generic:
            return ["(generic)"]
        return sorted(kinds)

    def amenity_kind_only(self, question: str) -> Optional[str]:
        """The amenity kind a building with NO instance vocabulary would reach, if any."""
        low = (question or "").lower()
        scored = [
            (self._cgr._score(low, phrases), kind) for kind, phrases in self.kind_terms.items()
        ]
        scored = [s for s in scored if s[0] >= self._cgr._MIN_SCORE]
        if not scored:
            return None
        return sorted(scored, key=lambda s: (-s[0], s[1]))[0][1]

    def evaluate(self, question: str) -> dict:
        """One question, every reading of it."""
        before = [i for _, i in self.amenity_instances(question, with_class_terms=False)]
        after = [i for _, i in self.amenity_instances(question, with_class_terms=True)]
        row = self.register(question)
        row.update(
            {
                "amenity_kinds_instance_terms": self.amenity_kinds(before) if before else [],
                "amenity_kinds_with_class_terms": self.amenity_kinds(after) if after else [],
                "amenity_kind_only": self.amenity_kind_only(question),
            }
        )
        return row


# ── the corpora ─────────────────────────────────────────────────────────────────────────


def recall_questions(path: Path = CORPUS) -> List[Tuple[str, str]]:
    """(id, question) for the 37 stakeholder catalogues."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            (row["ID"], row["Question"])
            for row in csv.DictReader(handle)
            if row.get("Source") == CORPUS_SOURCE and (row.get("Question") or "").strip()
        ]


#: Questions the code's own docstrings and comments name as traps, VERBATIM, with the outcome
#: the comment says is right (`doc_expect`) or wrong (`doc_forbid`). Transcribed, not chosen:
#: every row cites the place it was read from.
TRAPS: Tuple[dict, ...] = (
    {
        "question": "how many permits are open?",
        "doc_expect": {"held": "Permit"},
        "cite": "record_registry.py module docstring (opening times swallowed permits)",
    },
    {
        "question": "what competency is required for the roof?",
        "doc_expect": {"held": "CompetencyRecord"},
        "cite": "record_registry._terms_for (roof access permit -> bare 'roof')",
    },
    {
        "question": "what is the procedure for hot works?",
        "doc_forbid": {"absent": "WorkOrder"},
        "cite": "record_registry._terms_for and _ALL_CLASS_TERMS (bare 'work')",
    },
    {
        "question": "which systems started late against today's approved schedule",
        "doc_forbid": {"held": "ApprovalRecord"},
        "cite": "record_registry._qualifier_score (BUG-545)",
    },
    {
        "question": "which zones lack confirmed fire-warden coverage",
        "doc_forbid": {"held": "ApprovalRecord"},
        "cite": "record_registry._qualifier_score (BUG-545)",
    },
    {
        "question": (
            "what proportion of spend is planned, reactive, statutory, contract-fixed or "
            "demand-led"
        ),
        "doc_expect": {"held": "CostLine"},
        "cite": "record_registry._COMPOUND_WEIGHT",
    },
    {
        "question": "which unresolved exceptions require a call-out in this shift handover",
        "doc_forbid": {"held": "HandoverRecord"},
        "cite": "ontosage_schema.ttl HandoverRecord comment; record_registry.held_record_class",
    },
    {
        "question": "Which transition needs the larger travel and setup time?",
        "doc_expect": {"held": "CirculationTime", "second": "WorkspaceProfile"},
        "cite": "record_registry.second_record_class (CAVEAT-432)",
    },
    {
        "question": "Which assets are beyond their expected life?",
        "doc_expect": {"held": "ConditionSurvey"},
        "cite": "ontosage_schema.ttl Module R.4 header; record_registry._COMMENT_QUERY",
    },
    {
        "question": "when was the fire alarm last tested?",
        "doc_expect": {"held": "FireSafetyAsset"},
        "cite": "record_registry.absent_record_class (fire alarm vs alarm)",
    },
    {
        "question": "Have there been any alarms this week?",
        "doc_forbid": {"held": "PublicEvent"},
        "cite": "record_registry.load_lay_terms (W3-4); lessons.md TODO-490",
    },
    {
        "question": "Show me the anomaly events",
        "doc_forbid": {"held": "PublicEvent"},
        "cite": "record_registry.load_lay_terms (anomaly answered from public events)",
    },
    {
        "question": "Which contracts expire in the next six months?",
        "doc_expect": {"held": "Contract"},
        "cite": "record_registry.absent_record_class and schema_hint",
    },
    {
        "question": "is the standby generator under warranty?",
        "doc_expect": {"held": "Warranty"},
        "cite": "record_registry.schema_hint (void is not expired)",
    },
    {
        "question": "I'm pregnant and overheating - where's the coolest place to work today?",
        "doc_forbid": {},
        "cite": "dialogue_agent register short-circuit (BUG-557) - gated, recorded for drift",
    },
    {
        "question": "find a room for 12 with a projector",
        "doc_expect": {"held": "WorkspaceProfile"},
        "cite": "ontosage_schema.ttl WorkspaceProfile CAPACITY PHRASING comment",
    },
    {
        "question": "which HVAC assets operate beyond approved service windows, and is each "
        "exception justified?",
        "doc_expect": {"held": "OperatingRegime"},
        "cite": "ontosage_schema.ttl OperatingRegime rdfs:comment",
    },
    {
        "question": "Are the lifts working?",
        "doc_forbid": {},
        "cite": "dialogue_agent V6-T58/T60 (asset state answered from documents)",
    },
    {
        "question": "where can I fill my water bottle?",
        "doc_forbid": {},
        "cite": "capability_graph_resolver._MAX_FACTS (BUG-337)",
    },
    {
        "question": "Where can I isolate the water supply for the second-floor toilets?",
        "doc_forbid": {},
        "cite": "capability_graph_resolver.leftover_content_words (BUG-601)",
    },
)


def guard_sources() -> List[dict]:
    """Every guard question with where it came from — nothing selected by hand."""
    rows: List[dict] = []
    for i, case in enumerate(json.loads(PROBE.read_text(encoding="utf-8")), 1):
        rows.append(
            {
                "id": f"probe-{i:02d}",
                "source": "scripts/regression_cases.json",
                "question": case["question"],
                "group": case.get("group"),
                "expect_intent": case.get("expect_intent"),
                "forbid_intent": case.get("forbid_intent"),
            }
        )
    n = 0
    for line in DEMO.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        n += 1
        rows.append(
            {"id": f"demo-{n:02d}", "source": "docs/demo_script_questions.txt", "question": text}
        )
    for i, trap in enumerate(TRAPS, 1):
        row = {"id": f"trap-{i:02d}", "source": trap["cite"], "question": trap["question"]}
        for key in ("doc_expect", "doc_forbid"):
            if trap.get(key):
                row[key] = trap[key]
        rows.append(row)
    return rows


# ── the guard ───────────────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def derive_guard(reach: Reach, snapshot: dict, path: Path = GUARD) -> List[dict]:
    """Write the guard set: every source question with what the CURRENT schema selects for it.

    The expectation is today's behaviour because every source question passes today — the
    probe is green and the demo script was rehearsed — so today's selection is the lane each
    one passes on. The snapshot is written into the file so the check runs with no GraphDB.
    """
    rows = guard_sources()
    for row in rows:
        row["expect"] = reach.evaluate(row["question"])
    meta = {
        "_meta": {
            "derived_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema_sha256_at_derivation": _sha256(SCHEMA),
            "rule": (
                "expect = what the schema selected when this file was derived, for questions "
                "that pass today. A later schema that changes held/second/absent, makes an "
                "amenity match appear, disappear or change kind, or reaches an amenity kind "
                "through class terms that the building's own vocabulary did not, is a "
                "violation - unless the row's doc_expect/doc_forbid says the new outcome is "
                "the documented right one."
            ),
            "snapshot": snapshot,
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def read_guard(path: Path = GUARD) -> Tuple[dict, List[dict]]:
    """(meta, rows) from the guard file."""
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    meta = lines[0].get("_meta", {}) if lines and "_meta" in lines[0] else {}
    rows = [x for x in lines if "_meta" not in x]
    return meta, rows


def _doc_satisfied(row: dict, now: dict) -> bool:
    """True when the row documents an outcome and the current one is it."""
    expect = row.get("doc_expect") or {}
    forbid = row.get("doc_forbid") or {}
    if not expect and not forbid:
        return False
    ok_expect = all(now.get(k) == v for k, v in expect.items())
    ok_forbid = all(now.get(k) != v for k, v in forbid.items())
    return ok_expect and ok_forbid


def guard_violations(reach: Reach, rows: Sequence[dict]) -> List[dict]:
    """Every guard question whose reading changed, and how."""
    out: List[dict] = []
    for row in rows:
        was = row["expect"]
        now = reach.evaluate(row["question"])
        problems: List[str] = []
        for key in ("held", "second", "absent"):
            if was.get(key) != now.get(key):
                kind = "NEW" if not was.get(key) else ("LOST" if not now.get(key) else "CHANGED")
                problems.append(f"{key}:{kind} {was.get(key)} -> {now.get(key)}")
        was_am = was.get("amenity_kinds_with_class_terms") or []
        now_am = now.get("amenity_kinds_with_class_terms") or []
        if bool(was_am) != bool(now_am) or (was_am and now_am and set(was_am) != set(now_am)):
            problems.append(f"amenity(bldg instances): {was_am} -> {now_am}")
        was_kind = was.get("amenity_kind_only")
        now_kind = now.get("amenity_kind_only")
        if now_kind and now_kind != was_kind:
            # A building with no instance vocabulary would now claim this question for a kind.
            # Acceptable only when this building's own vocabulary already agrees it is that.
            own = set(was.get("amenity_kinds_instance_terms") or [])
            specific = own - {"(generic)"}
            agrees = bool(own) and (not specific or now_kind in specific)
            if not agrees:
                problems.append(f"amenity(kind only): {was_kind} -> {now_kind}")
        if problems:
            doc_ok = _doc_satisfied(row, now)
            out.append(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "problems": problems,
                    "status": "FIXED_PER_DOC" if doc_ok else "VIOLATION",
                }
            )
    return out


def doc_disagreements(reach: Reach, rows: Sequence[dict]) -> List[dict]:
    """Trap rows whose CURRENT outcome contradicts what their citation says is right."""
    out = []
    for row in rows:
        if not (row.get("doc_expect") or row.get("doc_forbid")):
            continue
        now = reach.evaluate(row["question"])
        if not _doc_satisfied(row, now):
            out.append({"id": row["id"], "question": row["question"], "now": now})
    return out


# ── reporting ───────────────────────────────────────────────────────────────────────────


def summarise(results: Dict[str, dict]) -> dict:
    """Shares over the recall corpus."""
    n = len(results) or 1
    held = Counter(r["held"] for r in results.values() if r["held"])
    absent = Counter(r["absent"] for r in results.values() if r["absent"])
    kind_only = Counter(r["amenity_kind_only"] for r in results.values() if r["amenity_kind_only"])
    no_register = sum(1 for r in results.values() if not r["held"] and not r["absent"])
    no_held = sum(1 for r in results.values() if not r["held"])
    nothing = sum(
        1
        for r in results.values()
        if not r["held"] and not r["absent"] and not r["amenity_kind_only"]
    )
    held_total = sum(held.values()) or 1
    return {
        "questions": len(results),
        "no_held_register_share": round(no_held / n, 4),
        "no_register_share": round(no_register / n, 4),
        "nothing_reached_share": round(nothing / n, 4),
        "held_selections": sum(held.values()),
        "absent_declines": sum(absent.values()),
        "top_held_share_of_selections": [
            (k, v, round(v / held_total, 4)) for k, v in held.most_common(12)
        ],
        "held_counts": dict(held.most_common()),
        "absent_counts": dict(absent.most_common()),
        "amenity_kind_only_counts": dict(kind_only.most_common()),
    }


def _print_summary(title: str, s: dict) -> None:
    print(f"\n== {title} ({s['questions']} questions) ==")
    print(f"  no held register selected : {s['no_held_register_share']:.1%}")
    print(f"  no register (held|absent) : {s['no_register_share']:.1%}")
    print(f"  nothing reached at all    : {s['nothing_reached_share']:.1%}  (incl. amenity kinds)")
    print(f"  held selections {s['held_selections']}, absent declines {s['absent_declines']}")
    print("  top held classes (count, share of held selections):")
    for name, count, share in s["top_held_share_of_selections"]:
        print(f"    {name:26s} {count:5d}  {share:.1%}")
    if s["absent_counts"]:
        print(f"  absent: {s['absent_counts']}")
    if s["amenity_kind_only_counts"]:
        print(f"  amenity kind only: {s['amenity_kind_only_counts']}")


def _selection(r: dict) -> str:
    if r.get("held"):
        return r["held"]
    if r.get("absent"):
        return f"ABSENT:{r['absent']}"
    if r.get("amenity_kind_only"):
        return f"AMENITY:{r['amenity_kind_only']}"
    return "-"


def compare(
    reach: Reach,
    before: Dict[str, dict],
    after: Dict[str, dict],
    questions: Dict[str, str],
    sample: int,
    seed: int,
) -> None:
    """What moved between two runs, with a random sample of the moves to READ."""
    moves = Counter()
    moved: List[Tuple[str, str, str]] = []
    for qid, now in after.items():
        was = before.get(qid)
        if not was:
            continue
        a, b = _selection(was), _selection(now)
        if a != b:
            moves[(a, b)] += 1
            moved.append((qid, a, b))
    print(f"\n== moves: {len(moved)} questions changed selection ==")
    for (a, b), count in moves.most_common(40):
        print(f"  {count:4d}  {a} -> {b}")
    if sample and moved:
        rng = random.Random(seed)
        print(f"\n== random sample of {min(sample, len(moved))} moves (seed {seed}) ==")
        for qid, a, b in rng.sample(moved, min(sample, len(moved))):
            target = after[qid].get("held")
            terms = reach.matched_terms(questions[qid], target) if target else []
            print(f"  [{qid}] {a} -> {b} {terms}\n      {questions[qid]}")


def run_recall(reach: Reach) -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Every recall question, evaluated."""
    questions = dict(recall_questions())
    return {qid: reach.evaluate(q) for qid, q in questions.items()}, questions


def main(argv: Optional[List[str]] = None) -> int:
    """CLI."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--schema", default=str(SCHEMA))
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--snapshot", action="store_true", help="refresh the GraphDB snapshot first")
    ap.add_argument("--derive-guard", action="store_true", help="(re)write the guard set")
    ap.add_argument("--force", action="store_true", help="allow --derive-guard to overwrite")
    ap.add_argument("--save", help="write per-question recall results to this JSON file")
    ap.add_argument("--compare", help="a --save file from an earlier run")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--class-detail", help="print questions a held class captures + the terms")
    ap.add_argument(
        "--count",
        action="append",
        default=[],
        metavar="CLASS=N",
        help="override one instance count, e.g. before a load: --count AlarmEvent=271",
    )
    ap.add_argument(
        "--events-store",
        nargs="?",
        const=str(REPO / "input"),
        default=None,
        metavar="INPUT_DIR",
        help="model the events store a building registers (BUG-670); default dir: input/",
    )
    args = ap.parse_args(argv)

    if args.snapshot:
        snap = take_snapshot(args.endpoint)
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    snapshot = load_snapshot(SNAPSHOT, args.endpoint)
    overrides = parse_counts(args.count)
    snapshot = with_counts(snapshot, overrides)

    graph = load_schema(Path(args.schema))
    stored = ()
    if args.events_store:
        stored = event_store_classes_from_config(
            set(schema_record_classes(graph)) | set(snapshot.get("record_counts", {})),
            Path(args.events_store),
        )
        print(f"events store ({args.events_store}): answers {list(stored) or 'nothing'}")
    reach = Reach(graph, snapshot, stored)
    print(
        f"schema {args.schema}: {len(reach.held)} held record classes (snapshot "
        f"{snapshot.get('taken_at')}), {len(reach.kind_terms)} capability kinds with class terms"
    )

    if args.derive_guard:
        if GUARD.exists() and not args.force:
            print(f"{GUARD} exists; derive it only BEFORE a vocabulary change (--force)")
            return 2
        rows = derive_guard(reach, snapshot)
        print(f"wrote {len(rows)} guard rows to {GUARD}")

    results, questions = run_recall(reach)
    _print_summary("recall: stakeholder catalogues", summarise(results))
    if args.class_detail:
        hits = [
            (qid, q) for qid, q in questions.items() if results[qid]["held"] == args.class_detail
        ]
        print(f"\n== {args.class_detail}: {len(hits)} questions ==")
        term_counts = Counter()
        for qid, q in hits:
            terms = reach.matched_terms(q, args.class_detail)
            term_counts.update(terms)
        for term, count in term_counts.most_common():
            print(f"  {count:4d}  {term}")
    if args.save:
        Path(args.save).write_text(json.dumps(results, indent=0), encoding="utf-8")
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        _print_summary("recall BEFORE (from --compare file)", summarise(before))
        compare(reach, before, results, questions, args.sample, args.seed)

    if not GUARD.exists():
        print("no guard set yet: run with --derive-guard before changing vocabulary")
        return 0
    meta, rows = read_guard()
    guard_reach = Reach(graph, with_counts(meta.get("snapshot", snapshot), overrides), stored)
    if overrides:
        print(f"\n(guard evaluated with instance counts overridden: {overrides})")
    violations = guard_violations(guard_reach, rows)
    hard = [v for v in violations if v["status"] == "VIOLATION"]
    print(f"\n== guard set: {len(rows)} questions, {len(hard)} violations ==")
    for v in violations:
        print(f"  {v['status']:14s} [{v['id']}] {v['question']}")
        for p in v["problems"]:
            print(f"      {p}")
    disagree = doc_disagreements(guard_reach, rows)
    if disagree:
        print(
            f"\n== {len(disagree)} trap rows where the current outcome contradicts the citation =="
        )
        for d in disagree:
            print(f"  [{d['id']}] {d['question']}\n      now {d['now']}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
