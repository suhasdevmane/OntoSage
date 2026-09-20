# -*- coding: utf-8 -*-
"""What does each question in the tuning pool REACH, measured offline, with no LLM and no service.

Why this exists
---------------
One GPU gives ~30 s per answer, so ~10,000 questions cannot be asked live. But most of what decides
whether an answer can be right is decided BEFORE any model runs: does the question's vocabulary
reach a concept, a register, an amenity; does the place it names exist; which routing rules fire.
Those are deterministic functions of the question text and the building's ontology, so they can be
scored for every question in minutes on a CPU. This report does that and ranks the gaps.

REACH IS NOT CORRECTNESS. A question that reaches a concept can still be answered wrongly, and a
question that reaches nothing can still be answered by the model. What a reach report can say is
where the deterministic layer has NO purchase on the question at all, which is where an answer is
least likely to be grounded and where a vocabulary or data change would move most questions.

What is measured, and by whose code (nothing is re-implemented)
--------------------------------------------------------------
* CONCEPT   ``concept_resolver.ConceptResolver.resolve`` over the HBCO lay terms in
            ``ontology/hbco_core.ttl`` + ``hbco_mappings.ttl`` on DISK (so an edit is measured
            without an upload), loaded with the resolver's own SPARQL and ``_parse_bindings``.
* REFERENT  ``referent_resolver.ReferentResolver.resolve`` itself, with its five graph lookups
            answered from a read-only snapshot of the building's entities instead of GraphDB.
            The control flow (which token, which kind, what counts as not found) is the gate's.
* REGISTER, AMENITY  ``scripts/register_reach.py``'s ``Reach``: the router's own scorers in
            ``record_registry`` and ``capability_graph_resolver`` fed the schema TTL on disk and a
            read-only snapshot of instance counts and amenity instances.
* ROUTING   ``routing_contract.apply_contract`` at all three stages, from several starting
            intents, exactly as ``dialogue_agent`` sequences them (parse, post, then concept with
            the concepts resolved above). Skipped, with the reason, if the orchestrator package
            cannot be imported.
* SOURCE    the data source each question's own record says it needs: the catalogue's declared
            evidence (``analyse_catalogue_demand.systems_named``) and the synthetic bank's
            ``Required_Data_Sources``. NOTE: ``Required_Data_Sources`` is blank on all 2,960
            catalogue rows; it is filled on the 1,100 synthetic ones.

What it does NOT model: the LLM classifier (so no intent, no entities), the intents a gate is
restricted to (``GATED_INTENTS``), retrieval quality, or whether a lane's answer is right.

The holdout stays out: the pool is ``master_bank.Bank.tuning()`` and nothing else.

Usage
-----
    python scripts/reach_report.py --snapshot --holdout-hashes H.txt   # read GraphDB once, then run
    python scripts/reach_report.py --holdout-hashes H.txt               # from the cached snapshot
    python scripts/reach_report.py --holdout-hashes H.txt --json out.json --md docs/REACH.md
    python scripts/reach_report.py --holdout-hashes H.txt --sample 500 --seed 3   # a quick look
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import logging
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: The scorers build one regex per declared term per question; Python's pattern cache holds 512
#: and there are ~1,500 distinct patterns, so without this most of the run recompiles them.
re._MAXCACHE = max(getattr(re, "_MAXCACHE", 512), 50000)

SNAPSHOT = REPO / "scripts" / "outputs" / "reach_snapshot.json"
DEFAULT_MD = REPO / "docs" / "REACH_2026-09-19.md"
DEFAULT_ENDPOINT = "http://127.0.0.1:7200/repositories/bldg"
CONCEPT_TTLS = (REPO / "ontology" / "hbco_core.ttl", REPO / "ontology" / "hbco_mappings.ttl")
START_INTENTS = ("general", "capability", "sensor_data", "analytics", "metadata")

#: The flags a question can carry. ``nothing`` is exclusive; the others may overlap.
FLAGS = (
    "concept",
    "register",
    "amenity",
    "referent",
    "routed",
    "topic_only",
    "decline_only",
    "nothing",
)
FLAG_TITLES = {
    "concept": "concept",
    "register": "register",
    "amenity": "amenity",
    "referent": "existing referent",
    "routed": "rule-routed",
    "topic_only": "topic only",
    "decline_only": "decline only",
    "nothing": "nothing",
}


# ── loading the code being measured ─────────────────────────────────────────────────────


def _load_script(relpath: str, name: str) -> ModuleType:
    """Import a repo file by path under a private name (cached), skipping package __init__ work."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / relpath)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def master_bank() -> ModuleType:
    """scripts/master_bank.py."""
    return _load_script("scripts/master_bank.py", "_reach_report_master_bank")


def register_reach() -> ModuleType:
    """scripts/register_reach.py (its scorers are the router's own)."""
    return _load_script("scripts/register_reach.py", "_reach_report_register_reach")


def catalogue_demand() -> ModuleType:
    """scripts/analyse_catalogue_demand.py (``systems_named`` reads a row's declared evidence)."""
    return _load_script("scripts/analyse_catalogue_demand.py", "_reach_report_demand")


def concept_module() -> ModuleType:
    """orchestrator/services/concept_resolver.py."""
    return _load_script("orchestrator/services/concept_resolver.py", "_reach_concept_resolver")


def referent_module() -> ModuleType:
    """orchestrator/services/referent_resolver.py."""
    return _load_script("orchestrator/services/referent_resolver.py", "_reach_referent_resolver")


def grounding_module() -> ModuleType:
    """orchestrator/services/grounding_guard.py."""
    return _load_script("orchestrator/services/grounding_guard.py", "_reach_grounding_guard")


_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run(coro: Any) -> Any:
    """Drive a coroutine to completion on a private loop (the resolvers are async, never suspend)."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


@contextlib.contextmanager
def quiet_logging() -> Iterator[None]:
    """Silence every logger for the duration: the orchestrator logs a line per rule applied."""
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


# ── the read-only snapshot ──────────────────────────────────────────────────────────────


def active_namespace(input_dir: Path = REPO / "input") -> str:
    """The active building's ontology namespace, from its building.yaml ('' when none is active)."""
    path = input_dir / "building.yaml"
    if not path.is_file():
        return ""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return str(data.get("ontology_namespace") or "")


def _entity_queries(namespace: str) -> Dict[str, str]:
    """The four read-only SELECTs the referent gate's lookups reduce to."""
    if not re.fullmatch(r"[A-Za-z0-9:/._#-]+", namespace):
        raise ValueError("namespace contains characters that may not reach a SPARQL literal")
    scope = f'FILTER(STRSTARTS(STR(?s), "{namespace}"))'
    rdfs = "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    return {
        "subjects": f"SELECT DISTINCT ?s WHERE {{ ?s a ?c . {scope} }}",
        "labels_typed": rdfs
        + f"SELECT DISTINCT ?l WHERE {{ ?s a ?c . ?s rdfs:label ?l . {scope} }}",
        "labels_any": rdfs + f"SELECT DISTINCT ?l WHERE {{ ?s rdfs:label ?l . {scope} }}",
        "classes": f"SELECT DISTINCT ?c WHERE {{ ?s a ?c . {scope} }}",
    }


def take_snapshot(endpoint: str, namespace: str) -> Dict[str, Any]:
    """One read-only pass over GraphDB: register/amenity facts plus the entities the gate checks."""
    rr = register_reach()
    entities: Dict[str, List[str]] = {}
    for name, query in _entity_queries(namespace).items():
        rows = rr._select(endpoint, query)
        key = {"subjects": "s", "labels_typed": "l", "labels_any": "l", "classes": "c"}[name]
        entities[name] = sorted({row[key] for row in rows if row.get(key)})
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "namespace": namespace,
        "register": rr.take_snapshot(endpoint),
        "entities": entities,
    }


def load_snapshot(
    path: Path = SNAPSHOT,
    endpoint: str = DEFAULT_ENDPOINT,
    namespace: str = "",
    refresh: bool = False,
) -> Dict[str, Any]:
    """The cached snapshot; taken (read-only) first when asked to, or when there is none."""
    if path.is_file() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    snap = take_snapshot(endpoint, namespace or active_namespace())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


# ── concepts ────────────────────────────────────────────────────────────────────────────


def load_concept_map(paths: Sequence[Path] = CONCEPT_TTLS) -> Dict[str, Dict[str, Any]]:
    """{concept uri: entry} from TTL on disk, through the resolver's own query and parser."""
    from rdflib import RDF, Graph, URIRef

    cr = concept_module()
    graph = Graph()
    for path in paths:
        if Path(path).is_file():
            graph.parse(str(path), format="turtle")
    # GraphDB infers hbco:CompositeConcept rdfs:subClassOf hbco:Concept (ontosage_schema.ttl);
    # rdflib does not, so 13 composites ('air quality', 'co2', 'temperature'...) were unreachable.
    hbco = "http://ontosage.org/hbco#"
    for sub in list(graph.subjects(RDF.type, URIRef(hbco + "CompositeConcept"))):
        graph.add((sub, RDF.type, URIRef(hbco + "Concept")))
    rows: List[Dict[str, Dict[str, str]]] = []
    for result in graph.query(cr._SPARQL_LOAD_CONCEPTS):
        binding: Dict[str, Dict[str, str]] = {}
        for key, value in zip(("concept", "layTerm", "brickClass", "recipe", "confidence"), result):
            if value is not None:
                binding[key] = {"value": str(value)}
        rows.append(binding)
    return cr._parse_bindings(rows)


def offline_concept_resolver(concept_map: Dict[str, Dict[str, Any]]) -> Any:
    """The real ConceptResolver with its map handed to it instead of read from Redis/GraphDB."""
    cr = concept_module()

    class _OfflineConceptResolver(cr.ConceptResolver):
        async def _load_concept_map(self) -> Dict[str, Dict[str, Any]]:
            return concept_map

    return _OfflineConceptResolver()


# ── referents ───────────────────────────────────────────────────────────────────────────


class ReferentModel:
    """The building's entity names, answering the five lookups ``ReferentResolver`` makes.

    Each lookup in the gate is ``CONTAINS`` over a lowercased field, so a set of distinct field
    values answers it exactly: which subject carries which label makes no difference to whether
    SOME subject does. Fields are joined into one string per kind so a single-term test is one C
    scan.
    """

    def __init__(self, entities: Dict[str, Sequence[str]], namespace: str):
        self.namespace = namespace
        subjects = [str(s) for s in entities.get("subjects", [])]
        cut = len(namespace)
        self.iris = sorted({s.lower() for s in subjects})
        locals_ = sorted({s[cut:].lower() for s in subjects if s.startswith(namespace)})
        labels = sorted({str(x).lower() for x in entities.get("labels_typed", [])})
        classes = sorted(
            {re.sub(r"^.*[#/]", "", str(c)).lower() for c in entities.get("classes", [])}
        )
        self._fields: List[List[str]] = [locals_, labels, classes]
        self._joined = ["\x00".join(f) for f in self._fields]
        self._labels_any = "\x00".join(
            sorted({str(x).lower() for x in entities.get("labels_any", [])})
        )
        self._iris_joined = "\x00".join(self.iris)
        self._terms_cache: Dict[Tuple[str, ...], bool] = {}
        self._ids_cache: Dict[str, Set[str]] = {}

    def exists_terms(self, terms: Sequence[str]) -> bool:
        """True if ONE field value of ONE subject holds every term (``_exists_terms``)."""
        cleaned = tuple(t.lower().strip() for t in terms if t and t.strip())
        if not cleaned:
            return True
        if cleaned in self._terms_cache:
            return self._terms_cache[cleaned]
        found = False
        for joined, field in zip(self._joined, self._fields):
            if not all(t in joined for t in cleaned):
                continue  # necessary condition: every term occurs somewhere in this field
            if len(cleaned) == 1 or any(all(t in v for t in cleaned) for v in field):
                found = True
                break
        self._terms_cache[cleaned] = found
        return found

    def exists_whole_word(self, terms: Sequence[str]) -> bool:
        """True if ONE field value holds every term as a whole word (letters on both sides refuse).

        ``exists_terms`` is the gate's own substring test, and it lets a short word through
        because it sits inside a longer one: "on" is in "carbon", "what" in nothing at all but
        "pollutant" in "Air_Pollutant_..." . This is the stricter question the report asks of a
        RESOLVED typed referent: is the thing named an actual word somewhere in the building?
        """
        cleaned = tuple(t.lower().strip() for t in terms if t and t.strip())
        if not cleaned:
            return True
        key = ("word",) + cleaned
        if key in self._terms_cache:
            return self._terms_cache[key]
        patterns = [re.compile(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])") for t in cleaned]
        found = False
        for joined, field in zip(self._joined, self._fields):
            if not all(p.search(joined) for p in patterns):
                continue
            if len(patterns) == 1 or any(all(p.search(v) for p in patterns) for v in field):
                found = True
                break
        self._terms_cache[key] = found
        return found

    def exists_token(self, token: str) -> bool:
        """A label or a typed subject's IRI contains the token (``_exists``)."""
        t = token.lower()
        return t in self._labels_any or t in self._iris_joined

    def matching_ids(self, token: str) -> Set[str]:
        """Distinct dotted ids, from subjects containing the token, that contain it (``_matching_ids``)."""
        t = token.lower()
        if t in self._ids_cache:
            return self._ids_cache[t]
        rr = referent_module()
        ids: Set[str] = set()
        if t in self._iris_joined:
            for iri in self.iris:
                if t in iri:
                    ids.update(
                        m.group(0) for m in rr._DOTTED_ID_RE.finditer(iri) if t in m.group(0)
                    )
        self._ids_cache[t] = ids
        return ids


def offline_referent_resolver(model: ReferentModel) -> Any:
    """The real ReferentResolver whose graph lookups read ``model`` (its control flow is used as is)."""
    rm = referent_module()

    async def _never(_query: str) -> dict:
        raise RuntimeError("the offline resolver must not run SPARQL")

    class _OfflineReferentResolver(rm.ReferentResolver):
        def __init__(self) -> None:
            super().__init__(_never)

        async def _exists(self, token: str, namespace: str) -> bool:
            return model.exists_token(token)

        async def _matching_ids(self, token: str, namespace: str) -> set:
            return model.matching_ids(token)

        async def _exists_terms(self, terms: List[str], namespace: str) -> bool:
            return model.exists_terms(terms)

        async def _exists_whole_words(self, terms: List[str], namespace: str) -> bool:
            return model.exists_whole_word(terms)  # the gate's whole-word test for short quantities

        async def _suggest(self, token: str, namespace: str) -> List[str]:
            return []

        async def _suggest_terms(
            self, terms: List[str], namespace: str, kind: str = ""
        ) -> List[str]:
            return []

        @staticmethod
        def _typed_clarification(*_args: Any, **_kwargs: Any) -> str:  # wording is not measured
            return ""

    return _OfflineReferentResolver()


def resolve_referent(resolver: Any, model: ReferentModel, question: str) -> Dict[str, Any]:
    """What the gate would do with this question: kind, phrase, status, and whether the kind exists."""
    rm = referent_module()
    entities: List[str] = []  # the classifier's entity list is not modelled
    token = rm.detect_referent(question, entities)
    typed = None if token else rm.detect_typed_referent(question)
    kind = "id" if token else (typed.kind if typed else "")
    result = _run(resolver.resolve(question, entities, model.namespace, "this building"))
    phrase = (result.referent or "") if result.status != rm.NO_REFERENT else ""
    head_exists: Optional[bool] = None
    if typed is not None and result.status == rm.NOT_FOUND:
        head_exists = model.exists_terms([typed.head])
    # A RESOLVED word-shaped token ("room IS ...") is the gate's own weakest case: it exists in
    # the graph because the word is short. Only identifier-shaped tokens and typed referents count,
    # and a typed referent counts only when it is a whole word somewhere in the building.
    weak = False
    if result.status == rm.RESOLVED:
        if token:
            weak = not re.search(r"\d", token)
        elif typed is not None and typed.head not in rm.ReferentResolver._BUILDING_FAMILY:
            weak = not model.exists_whole_word(typed.token.split("|"))
    return {
        "kind": kind,
        "phrase": phrase.lower(),
        "status": result.status,
        "head_exists": head_exists,
        "weak": weak,
    }


# ── routing contract ────────────────────────────────────────────────────────────────────


class ContractRunner:
    """``apply_contract`` sequenced as the dialogue agent sequences it, from several intents."""

    def __init__(self, start_intents: Sequence[str] = START_INTENTS):
        with quiet_logging():
            from orchestrator.services import routing_contract as rc  # heavy: the whole package
        self.rc = rc
        self.start_intents = tuple(start_intents)
        self.stages: Dict[str, List[str]] = {
            "parse": [r.name for r in rc.PARSE_STAGE_RULES],
            "post": [r.name for r in rc.POST_STAGE_RULES],
            "concept": [r.name for r in rc.CONCEPT_STAGE_RULES],
        }

    @property
    def rule_names(self) -> List[str]:
        """Every rule, in precedence order across the three stages."""
        return [n for names in self.stages.values() for n in names]

    def run(self, question: str, concepts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """{start intent: {rules applied, final intent}} for one question."""
        out: Dict[str, Dict[str, Any]] = {}
        for start in self.start_intents:
            normalized: Dict[str, Any] = {
                "intent": start,
                "analytics": False,
                "general": start == "general",
                "entities": [],
            }
            self.rc.apply_contract(question, normalized, stage="parse")
            self.rc.apply_contract(question, normalized, stage="post")
            concept_state: Dict[str, Any] = {
                "intent": normalized["intent"],
                "concepts": concepts,
                "entities": [],
            }
            self.rc.apply_contract(question, concept_state, stage="concept")
            rules = list(normalized.get("routing_rules_applied", [])) + list(
                concept_state.get("routing_rules_applied", [])
            )
            out[start] = {"rules": rules, "final": concept_state["intent"]}
        return out


# ── the model bundle and the per-question evaluation ────────────────────────────────────


class Models:
    """Everything a question is scored against, built once."""

    def __init__(
        self,
        snapshot: Dict[str, Any],
        concept_map: Dict[str, Dict[str, Any]],
        contract: Optional[ContractRunner],
        contract_skipped: str = "",
        events_store: bool = True,
    ):
        rr = register_reach()
        graph = rr.load_schema(Path(rr.SCHEMA))
        reg_snapshot = snapshot.get("register", {})
        stored: Tuple[str, ...] = ()
        if events_store and (REPO / "input" / "building.yaml").is_file():
            stored = rr.event_store_classes_from_config(
                set(rr.schema_record_classes(graph)) | set(reg_snapshot.get("record_counts", {})),
                REPO / "input",
            )
        self.events_store_classes = stored
        self.reach = rr.Reach(graph, reg_snapshot, stored)
        self.concept_map = concept_map
        self.concepts = offline_concept_resolver(concept_map)
        self.namespace = str(snapshot.get("namespace", ""))
        self.referent_model = ReferentModel(snapshot.get("entities", {}), self.namespace)
        self.referents = offline_referent_resolver(self.referent_model)
        # The gate defers a quantity the lay vocabulary explains; production publishes it from the
        # concept resolver, but this tool loads the gate under a private name, so publish it here.
        publish = getattr(referent_module(), "register_concept_terms", None)
        if publish:
            publish(t for e in concept_map.values() for t in e.get("lay_terms", []))
        self.contract = contract
        self.contract_skipped = contract_skipped
        self.grounding = grounding_module()
        self.demand = catalogue_demand()

    def concepts_for(self, question: str) -> List[Any]:
        """ConceptMatch list for one question."""
        return _run(self.concepts.resolve(question))


def _amenity_split(kinds: Sequence[str]) -> Tuple[bool, bool]:
    """(specific amenity kind reached, only a generic knowledge topic reached)."""
    specific = [k for k in kinds if k != "(generic)"]
    return bool(specific), bool(kinds) and not specific


def implied_sources(question: Any, models: Optional[Models]) -> List[str]:
    """The data sources the question's own record says it needs.

    Catalogue rows: the source systems named by the row's declared evidence (its own
    ``Required_Data_Sources`` is blank). Synthetic rows: the ``Required_Data_Sources`` tokens.
    """
    primary = question.primary
    if primary == "stakeholder_catalogue_37" and models is not None:
        row = dict(question.evidence)
        return sorted(models.demand.systems_named(row))
    if primary == "synthetic":
        raw = question.tags.get("required_data_sources", "")
        return sorted({t.strip() for t in raw.split(";") if t.strip()})
    return []


def flags_for(row: Dict[str, Any]) -> Dict[str, bool]:
    """The reach flags of one evaluated question."""
    amenity, topic = _amenity_split(row["amenity_kinds"])
    concept = bool(row["concepts"])
    register = bool(row["register"]["held"])
    ref = row["referent"]
    referent = ref["status"] == "resolved" and not ref["weak"]
    decline = bool(row["register"]["absent"]) or ref["status"] in ("not_found", "ambiguous")
    routed = bool(row["contract"].get("general", {}).get("rules"))
    grounded = concept or register or amenity or referent or routed
    return {
        "concept": concept,
        "register": register,
        "amenity": amenity,
        "referent": referent,
        "routed": routed,
        "topic_only": topic and not grounded,
        "decline_only": decline and not grounded and not topic,
        "nothing": not (grounded or topic or decline),
    }


def evaluate(models: Models, question: Any) -> Dict[str, Any]:
    """Every reading of one bank question."""
    text = question.text
    matches = models.concepts_for(text)
    concept_dicts = [m.to_dict() for m in matches]
    reg = models.reach.evaluate(text)
    row: Dict[str, Any] = {
        "id": question.id,
        "source": question.primary,
        "group": question.group,
        "asked_before": question.asked_before,
        "text": text,
        "concepts": [m.concept_id for m in matches][:5],
        "measurand": models.grounding.has_measurand_concept(concept_dicts),
        "register": {"held": reg["held"], "second": reg["second"], "absent": reg["absent"]},
        "amenity_kinds": reg["amenity_kinds_with_class_terms"],
        "amenity_kind_only": reg["amenity_kind_only"],
        "referent": resolve_referent(models.referents, models.referent_model, text),
        "implied_sources": implied_sources(question, models),
    }
    row["contract"] = models.contract.run(text, concept_dicts) if models.contract else {}
    row["flags"] = flags_for(row)
    return row


def evaluate_all(
    models: Models, questions: Sequence[Any], progress: bool = False
) -> List[Dict[str, Any]]:
    """Evaluate every question, in order."""
    started = time.time()
    rows: List[Dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        rows.append(evaluate(models, question))
        if progress and index % 1000 == 0:
            print(f"  {index}/{len(questions)} ({time.time() - started:.0f}s)", file=sys.stderr)
    return rows


# ── aggregation ─────────────────────────────────────────────────────────────────────────

_STOP = frozenset(
    """a about above after again all also am an and any are aren as at be because been before being
    below between both but by can cannot could did do does doing don down during each few for from
    further get gets getting give given go had has have having he her here hers him his how i if in
    into is isn it its just let like made make many may me might more most much must my need needs
    no nor not now of off on once one only or other our out over own per please same shall she
    should so some such than that the their them then there these they this those through to too
    under until up us use used using very want was we were what when where which while who whom
    whose why will with within without would you your yours yourself building buildings abacws
    tell show know find see say said ask asked asking give right currently current today tonight
    there's it's what's whats thats i'm i've you're we're they're isnt dont cant wont didnt also
    able whether either anything something someone somewhere everyone everything really quite
    """.split()
)
_WORD = re.compile(r"[a-z][a-z0-9]+")


def content_terms(text: str) -> Set[str]:
    """Unigrams and adjacent bigrams that carry content: no stop words, at least 3 letters."""
    words = _WORD.findall(text.lower().replace("'", ""))
    terms: Set[str] = set()
    for i, w in enumerate(words):
        if w not in _STOP and len(w) >= 3 and not w.isdigit():
            terms.add(w)
            if i + 1 < len(words):
                nxt = words[i + 1]
                if nxt not in _STOP and len(nxt) >= 3 and not nxt.isdigit():
                    terms.add(f"{w} {nxt}")
    return terms


def rate_table(rows: Sequence[Dict[str, Any]], key: Any) -> List[Dict[str, Any]]:
    """One record per key: n and the share of questions carrying each flag."""
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[key(row)].append(row)
    out = []
    for name, members in buckets.items():
        n = len(members)
        record: Dict[str, Any] = {"key": name, "n": n}
        for flag in FLAGS:
            count = sum(1 for r in members if r["flags"][flag])
            record[flag] = count
            record[f"{flag}_pct"] = round(100.0 * count / n, 1)
        out.append(record)
    return out


def _order_sources(names: Iterable[str]) -> List[str]:
    order = list(master_bank().SOURCE_ORDER)
    return sorted(names, key=lambda s: (order.index(s) if s in order else len(order), s))


def ngram_ranking(
    rows: Sequence[Dict[str, Any]],
    target: Any,
    limit: int = 40,
    min_count: int = 3,
    lift_margin: float = 0.15,
    examples: int = 2,
) -> List[Dict[str, Any]]:
    """Terms that occur far more often in questions matching ``target`` than in the pool as a whole.

    A term must occur in ``target`` questions at a rate at least ``lift_margin`` above the rate of
    ``target`` in the whole pool. Without that, every frequent word ("room", "floor") qualifies
    whenever most questions are in ``target``, and the ranking is a word-frequency list.
    """
    in_target: Counter = Counter()
    overall: Counter = Counter()
    where: Dict[str, List[str]] = defaultdict(list)
    hits = [target(row) for row in rows]
    base = sum(hits) / len(rows) if rows else 0.0
    min_share = min(0.95, base + lift_margin)
    for row, hit in zip(rows, hits):
        for term in content_terms(row["text"]):
            overall[term] += 1
            if hit:
                in_target[term] += 1
                if len(where[term]) < examples:
                    where[term].append(row["text"])
    ranked = [
        {
            "term": term,
            "questions": count,
            "of_all": overall[term],
            "share": round(count / overall[term], 2),
            "examples": where[term],
        }
        for term, count in in_target.items()
        if count >= min_count and count / overall[term] >= min_share
    ]
    # Unigrams that only appear inside a listed bigram add nothing: keep the more specific one.
    ranked.sort(key=lambda r: (-r["questions"], -len(r["term"]), r["term"]))
    kept: List[Dict[str, Any]] = []
    for record in ranked:
        if " " not in record["term"] and any(
            record["term"] in k["term"].split() and k["questions"] >= record["questions"] * 0.8
            for k in kept
        ):
            continue
        kept.append(record)
        if len(kept) >= limit:
            break
    return kept


def _examples(rows: Sequence[Dict[str, Any]], n: int, seed: int = 13) -> List[str]:
    ordered = sorted(rows, key=lambda r: r["id"])
    rng = random.Random(seed)
    return [r["text"] for r in rng.sample(ordered, min(n, len(ordered)))]


def summarise(
    rows: Sequence[Dict[str, Any]], models: Optional[Models], contract_note: str = ""
) -> Dict[str, Any]:
    """Every table and ranked list the report prints."""
    sources = _order_sources({r["source"] for r in rows})
    by_source = {rec["key"]: rec for rec in rate_table(rows, lambda r: r["source"])}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for source in sources:
        members = [r for r in rows if r["source"] == source]
        table = rate_table(members, lambda r: r["group"])
        groups[source] = sorted(table, key=lambda t: (-t["nothing_pct"], -t["n"], t["key"]))

    # (ii) absent registers
    absent_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    held_counts: Counter = Counter()
    concept_counts: Counter = Counter()
    kind_counts: Counter = Counter()
    for row in rows:
        if row["register"]["absent"]:
            absent_rows[row["register"]["absent"]].append(row)
        if row["register"]["held"]:
            held_counts[row["register"]["held"]] += 1
        for cid in row["concepts"][:1]:
            concept_counts[cid] += 1
        for kind in row["amenity_kinds"]:
            kind_counts[kind] += 1
    second_counts = Counter(r["register"]["second"] for r in rows if r["register"]["second"])
    registers: List[Dict[str, Any]] = []
    if models is not None:
        for record in models.reach.held:
            registers.append(
                {
                    "register": record.local_name,
                    "instances": record.instances,
                    "questions": held_counts.get(record.local_name, 0),
                    "as_second": second_counts.get(record.local_name, 0),
                }
            )
        registers.sort(key=lambda r: (-r["questions"], r["register"]))
    defined_absent: List[str] = []
    if models is not None:
        held_names = {r.local_name for r in models.reach.held} | set(models.events_store_classes)
        defined_absent = sorted(n for n in models.reach._rr._ALL_CLASS_TERMS if n not in held_names)
    absent = [
        {
            "register": name,
            "questions": len(absent_rows.get(name, [])),
            "by_source": dict(
                Counter(m["source"] for m in absent_rows.get(name, [])).most_common()
            ),
            "examples": _examples(absent_rows.get(name, []), 3),
        }
        for name in sorted(set(absent_rows) | set(defined_absent))
    ]
    absent.sort(key=lambda r: (-r["questions"], r["register"]))

    # (iii) referents not in the graph
    missing: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    weak_resolved = 0
    for row in rows:
        ref = row["referent"]
        if ref["status"] == "not_found":
            missing[(ref["kind"], ref["phrase"])].append(row)
        weak_resolved += 1 if ref["weak"] else 0
    missing_list = [
        {
            "kind": kind,
            "referent": phrase,
            "questions": len(members),
            "kind_exists_in_graph": members[0]["referent"]["head_exists"],
            "examples": _examples(members, 2),
        }
        for (kind, phrase), members in missing.items()
    ]
    missing_list.sort(key=lambda r: (-r["questions"], r["kind"], r["referent"]))

    # (i) lay terms reaching no concept; (iv) questions reaching nothing
    families = {
        "survey": [r for r in rows if r["source"] == "survey"],
        "synthetic and curated": [r for r in rows if r["source"] not in ("survey", "stakeholder_catalogue_37")],
        "stakeholder_catalogue_37": [r for r in rows if r["source"] == "stakeholder_catalogue_37"],
    }
    no_concept = {
        name: ngram_ranking(members, lambda r: not r["flags"]["concept"], limit=25)
        for name, members in families.items()
        if members
    }
    nothing_rows = [r for r in rows if r["flags"]["nothing"]]
    nothing_terms = ngram_ranking(rows, lambda r: r["flags"]["nothing"], limit=30)
    nothing_by_source = {
        s: {
            "n": sum(1 for r in nothing_rows if r["source"] == s),
            "examples": _examples([r for r in nothing_rows if r["source"] == s], 5),
        }
        for s in sources
    }

    # (d) routing
    routing = summarise_routing(rows, models.contract if models else None, contract_note)

    # (e) implied data source
    implied: Dict[str, List[Dict[str, Any]]] = {}
    for source in ("stakeholder_catalogue_37", "synthetic"):
        members = [r for r in rows if r["source"] == source]
        exploded: List[Dict[str, Any]] = []
        for row in members:
            for tag in row["implied_sources"] or ["(none declared)"]:
                exploded.append({**row, "_tag": tag})
        table = rate_table(exploded, lambda r: r["_tag"])
        implied[source] = sorted(table, key=lambda t: (-t["n"], t["key"]))

    return {
        "n": len(rows),
        "sources": sources,
        "by_source": [by_source[s] for s in sources],
        "overall": rate_table(rows, lambda r: "all")[0] if rows else {},
        "groups": groups,
        "lay_terms_no_concept": no_concept,
        "registers": registers,
        "absent_registers": absent,
        "missing_referents": missing_list,
        "weak_resolved_word_tokens": weak_resolved,
        "reach_nothing": {
            "n": len(nothing_rows),
            "by_source": nothing_by_source,
            "terms": nothing_terms,
        },
        "top_concepts": concept_counts.most_common(20),
        "top_registers": held_counts.most_common(20),
        "amenity_kinds": kind_counts.most_common(15),
        "routing": routing,
        "implied_source": implied,
    }


def summarise_routing(
    rows: Sequence[Dict[str, Any]], contract: Optional[ContractRunner], note: str = ""
) -> Dict[str, Any]:
    """Which rules fire on the question alone, and where a weak classification would end up."""
    if contract is None or not any(r["contract"] for r in rows):
        return {"available": False, "note": note or "routing contract not evaluated"}
    starts = contract.start_intents
    fire: Dict[str, Counter] = {s: Counter() for s in starts}
    final: Dict[str, Counter] = {s: Counter() for s in starts}
    for row in rows:
        for start in starts:
            entry = row["contract"].get(start)
            if not entry:
                continue
            fire[start].update(set(entry["rules"]))
            final[start][entry["final"]] += 1
    any_fire: Counter = Counter()
    for row in rows:
        names = {n for entry in row["contract"].values() for n in entry["rules"]}
        any_fire.update(names)
    stage_of = {n: st for st, names in contract.stages.items() for n in names}
    records = [
        {
            "rule": name,
            "stage": stage_of.get(name, "?"),
            "from_general": fire["general"][name] if "general" in fire else 0,
            "from_any_start": any_fire[name],
        }
        for name in contract.rule_names
    ]
    return {
        "available": True,
        "start_intents": list(starts),
        "rules": records,
        "never_fire": [r["rule"] for r in records if r["from_any_start"] == 0],
        "final_intent": {s: dict(final[s].most_common()) for s in starts},
    }


# ── rendering ───────────────────────────────────────────────────────────────────────────


def _pct(count: int, n: int) -> str:
    return f"{100.0 * count / n:.1f}%" if n else "-"


def _md_table(headers: Sequence[str], body: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in body:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _clip(text: str, limit: int = 150) -> str:
    text = " ".join(text.split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rate_rows(records: Sequence[Dict[str, Any]], label: str = "key") -> List[List[Any]]:
    return [[r[label], r["n"]] + [f"{r[f'{flag}_pct']:.1f}%" for flag in FLAGS] for r in records]


def render_markdown(summary: Dict[str, Any], meta: Dict[str, Any]) -> str:
    """The report."""
    out: List[str] = []
    add = out.append
    add(f"# Reach report — {meta['date']}")
    add("")
    add(
        "What each question in the tuning pool **reaches**, measured offline with no LLM and no "
        "service call: which concept, register, amenity and existing place its words hit, and which "
        "routing rules fire on the question alone. Generated by `scripts/reach_report.py`; "
        "re-running it is the only way to change a number here."
    )
    add("")
    add(
        "**Reach is not correctness.** A question that reaches a concept can still be answered "
        "wrongly; one that reaches nothing can still be answered by the model. This says where the "
        "deterministic layer has no purchase on a question, and which single vocabulary or data "
        "change would give it purchase on the most questions."
    )
    add("")
    add("## 1. The pool")
    add("")
    bank = meta["bank"]
    add(
        f"* **{summary['n']:,} questions evaluated** — the tuning pool "
        f"({bank['unique_questions']:,} unique across nine sources, of which "
        f"{bank['holdout_matched_in_bank']} matched a held-out digest and were excluded; "
        f"{bank['holdout_hashes']} digests given, {bank['holdout_hashes_not_in_bank']} matched no "
        "bank text). No held-out question is printed, counted in a table, or sampled here."
    )
    add(f"* Raw rows by source: {bank['raw_rows_by_source']}")
    add(
        f"* Graph snapshot: `{meta['snapshot_taken_at']}` from `{meta['endpoint']}`, namespace "
        f"`{meta['namespace']}`; {meta['entity_counts']}."
    )
    add(
        f"* Concepts: {meta['concepts']} concepts / {meta['concept_terms']} lay terms from "
        f"`{', '.join(meta['concept_files'])}` **on disk** (not the uploaded copy)."
    )
    add(
        f"* Registers: {meta['held_registers']} held record classes; events-store classes modelled "
        f"as answered elsewhere: {meta['events_store_classes'] or 'none'}."
    )
    add(f"* Run: {meta['seconds']:.0f} s on CPU.")
    add("")
    add("Flag definitions (a question can carry several, except **nothing**):")
    add("")
    add("| flag | means |")
    add("|---|---|")
    for flag_name, meaning in FLAG_DOCS:
        add(f"| {flag_name} | {meaning} |")
    add("")

    add("## 2. Reach by source")
    add("")
    headers = ["source", "n"] + [FLAG_TITLES[f] for f in FLAGS]
    body = _rate_rows(summary["by_source"])
    if summary["overall"]:
        overall = dict(summary["overall"])
        overall["key"] = "ALL"
        body.append(_rate_rows([overall])[0])
    add(_md_table(headers, body))
    add("")
    for source in summary["sources"]:
        table = summary["groups"][source]
        if len(table) < 2:
            continue
        add(f"### 2.{summary['sources'].index(source) + 1} {source} — by group (worst reach first)")
        add("")
        add(_md_table(["group", "n"] + [FLAG_TITLES[f] for f in FLAGS], _rate_rows(table)))
        add("")

    add("## 3. Ranked gaps")
    add("")
    add("### 3.1 Lay terms reaching no concept")
    add("")
    add(
        "Words and word pairs that occur far more often in questions where the concept resolver "
        "found **no** concept than in the pool as a whole (at least 15 points above the family's "
        "own no-concept rate, in at least 3 questions), ranked by how many such questions contain "
        "them. Adding a real lay term to `ontology/mining/concept_terms_raw.csv` is what would give "
        "those questions a concept. Ranked per family because the families speak differently: "
        "**survey** questions are real people's words, **catalogue** questions are formal "
        "stakeholder prose whose vocabulary is mostly governance jargon, not measurands. Read "
        "before adding: many terms here name records, not quantities."
    )
    add("")
    for family, ranking in summary["lay_terms_no_concept"].items():
        add(f"**{family}**")
        add("")
        add(
            _md_table(
                ["#", "term", "no-concept questions", "of all containing it", "example"],
                [
                    [i, f"`{r['term']}`", r["questions"], r["of_all"], _clip(r["examples"][0], 110)]
                    for i, r in enumerate(ranking, start=1)
                ],
            )
        )
        add("")
    add("### 3.2 Registers: absent ones, and demand against what is held")
    add("")
    add(
        "Record classes the ontology defines and the building holds no records of, named by a "
        "question (`absent_record_class`). Today each such question is declined by name. "
        "'Unlock' is an upper bound: loading the register lets the register lane answer, "
        "not that the answer is right."
    )
    add("")
    add(
        "**Held registers: demand against instances.** Questions that select each held record "
        "class (as first choice, and as second), against the records the graph holds. A register "
        "with many questions and few records is the cheapest data to add; one with records and no "
        "questions is data nobody in this pool asks about."
    )
    add("")
    regs = summary.get("registers", [])
    add(
        _md_table(
            ["register", "instances", "questions (first)", "questions (second)"],
            [[f"`{r['register']}`", r["instances"], r["questions"], r["as_second"]] for r in regs],
        )
        if regs
        else "_Not available._"
    )
    add("")
    named = [r for r in summary["absent_registers"] if r["questions"]]
    silent = [r["register"] for r in summary["absent_registers"] if not r["questions"]]
    add(
        _md_table(
            ["#", "absent register", "questions", "by source", "example"],
            [
                [
                    i,
                    f"`{r['register']}`",
                    r["questions"],
                    ", ".join(f"{k} {v}" for k, v in r["by_source"].items()),
                    _clip(r["examples"][0], 110),
                ]
                for i, r in enumerate(named[:30], start=1)
            ],
        )
        if named
        else "_No question in the pool names an absent register._"
    )
    add("")
    add(
        f"Absent classes the ontology defines that **no** question in the pool names "
        f"({len(silent)}): " + (", ".join(f"`{n}`" for n in silent) or "none") + "."
    )
    add("")
    add("### 3.3 Referents that do not exist in the graph")
    add("")
    add(
        "A floor, named space, piece of equipment, measured quantity or dotted room id the "
        "question names that the building's graph does not hold. `kind exists` says whether the "
        "building has ANY entity of that kind (e.g. it has floors, just not floor 7). These are "
        "the GATE's detections, false ones included: a `measurand` is any word before 'level(s)' "
        "or 'concentration' (so `what`, `verified`, `appropriate`), and a `location` is "
        "'building/block/tower <word>' (so `building a green roof` reads as a building A). The "
        "list therefore mixes genuine gaps (`solar panel`, `cafeteria`, `gym`, `escalator`) with "
        "gate over-reach; the second kind is a defect in the gate, not a gap in the building."
    )
    add("")
    add(
        _md_table(
            ["#", "kind", "referent", "questions", "kind exists", "example"],
            [
                [
                    i,
                    r["kind"],
                    f"`{r['referent']}`",
                    r["questions"],
                    {True: "yes", False: "no", None: "-"}[r["kind_exists_in_graph"]],
                    _clip(r["examples"][0], 110),
                ]
                for i, r in enumerate(summary["missing_referents"][:30], start=1)
            ],
        )
        if summary["missing_referents"]
        else "_None._"
    )
    add("")
    add("### 3.4 Questions that reach nothing at all")
    add("")
    nothing = summary["reach_nothing"]
    add(
        f"**{nothing['n']:,} of {summary['n']:,} questions "
        f"({_pct(nothing['n'], summary['n'])})** reach no concept, register, amenity, topic, "
        "existing referent or decline route. Five examples per source (seeded, not the first five):"
    )
    add("")
    for source in summary["sources"]:
        info = nothing["by_source"][source]
        if not info["n"]:
            continue
        add(f"**{source}** — {info['n']} questions")
        add("")
        for text in info["examples"]:
            add(f"* {_clip(text, 200)}")
        add("")
    add("What those questions are about (terms occurring mostly among them):")
    add("")
    add(
        _md_table(
            ["#", "term", "questions reaching nothing", "of all containing it"],
            [
                [i, f"`{r['term']}`", r["questions"], r["of_all"]]
                for i, r in enumerate(nothing["terms"], start=1)
            ],
        )
    )
    add("")

    add("## 4. What is reached, when something is")
    add("")
    add("**Concepts** (the first concept resolved, most frequent 20):")
    add("")
    add(_md_table(["concept", "questions"], summary["top_concepts"]))
    add("")
    add("**Held registers selected** (most frequent 20):")
    add("")
    add(_md_table(["register", "questions"], summary["top_registers"]))
    add("")
    add("**Amenity kinds matched** (`(generic)` = a bare Capability/KnowledgeTopic instance):")
    add("")
    add(_md_table(["kind", "questions"], summary["amenity_kinds"]))
    add("")

    add("## 5. Routing rules that fire on the question alone")
    add("")
    routing = summary["routing"]
    if not routing.get("available"):
        add(f"_Not evaluated: {routing.get('note', '')}_")
    else:
        add(
            "`apply_contract` at the parse, post and concept stages, sequenced as the dialogue "
            "agent does, from a **neutral starting intent** because the classifier is not modelled. "
            f"Starting intents: {', '.join(routing['start_intents'])}. `from general` counts "
            "questions the rule claims when the classifier said nothing useful; `from any start` "
            "counts questions it claims from at least one of the starting intents."
        )
        add("")
        add(
            _md_table(
                ["stage", "rule", "from general", "from any start"],
                [
                    [r["stage"], f"`{r['rule']}`", r["from_general"], r["from_any_start"]]
                    for r in routing["rules"]
                    if r["from_any_start"]
                ],
            )
        )
        add("")
        add(
            f"Rules that fire on **no** question in the pool ({len(routing['never_fire'])}): "
            + (", ".join(f"`{n}`" for n in routing["never_fire"]) or "none")
            + ". A rule that fires on nothing here is either narrow by design, guarding a shape this "
            "pool never asks, or dead; the pool cannot say which."
        )
        add("")
        add("Where the contract alone leaves each starting intent (final intent, questions):")
        add("")
        finals = routing["final_intent"]
        intents = sorted({i for counts in finals.values() for i in counts})
        add(
            _md_table(
                ["final intent"] + [f"from {s}" for s in routing["start_intents"]],
                [[i] + [finals[s].get(i, 0) for s in routing["start_intents"]] for i in intents],
            )
        )
    add("")

    add("## 6. The data source each question's own record says it needs")
    add("")
    add(
        "Catalogue rows: the source systems named by the row's declared evidence "
        "(`Authoritative_Sources` + `Sensors_Required`, via `analyse_catalogue_demand.systems_named`); "
        "the catalogue's `Required_Data_Sources` column is blank on every one of its rows. "
        "Synthetic rows: their `Required_Data_Sources` tokens. A row can name several, so the "
        "counts overlap. This is the demand side: a source system with low reach is one the "
        "questions need and the deterministic layer cannot see."
    )
    add("")
    for source in ("stakeholder_catalogue_37", "synthetic"):
        table = summary["implied_source"].get(source) or []
        if not table:
            continue
        add(f"### {source}")
        add("")
        add(
            _md_table(["declared source", "n"] + [FLAG_TITLES[f] for f in FLAGS], _rate_rows(table))
        )
        add("")

    add("## 7. Method, and what limits it")
    add("")
    for line in METHOD_NOTES:
        add(f"* {line}")
    add("")
    add("## 8. Reproduce")
    add("")
    add("```")
    add("python scripts/reach_report.py --snapshot --holdout-hashes <hash file>   # refresh + run")
    add("python scripts/reach_report.py --holdout-hashes <hash file> --json reach.json")
    add("python scripts/master_bank.py --holdout-hashes <hash file> --stats")
    add("```")
    add("")
    return "\n".join(out)


FLAG_DOCS: Tuple[Tuple[str, str], ...] = (
    ("concept", "`ConceptResolver.resolve` returns at least one HBCO concept"),
    ("register", "a held record class is selected (`held_record_class`)"),
    (
        "amenity",
        "an amenity instance matches and at least one is of a specific kind "
        "(not a bare Capability/KnowledgeTopic)",
    ),
    (
        "existing referent",
        "the gate finds a named place, floor, piece of equipment, measured quantity or id AND it "
        'exists in the graph (a bare word such as "is" after "room", or a short word that only '
        "sits inside a longer one, is NOT counted; see 7)",
    ),
    (
        "rule-routed",
        "at least one routing-contract rule claims the question from a neutral `general` start, "
        "with no classifier (section 5); never set when the contract pass was skipped",
    ),
    (
        "topic only",
        "reaches only a generic knowledge topic and nothing above (one shared word is enough for "
        "a topic match, so this is weak)",
    ),
    (
        "decline only",
        "reaches only a decline route: an ABSENT register named, or a referent the gate reports "
        "not found or ambiguous",
    ),
    (
        "nothing",
        "none of the above: no concept, register, amenity, topic, referent, routing rule or "
        "decline route",
    ),
)

METHOD_NOTES: Tuple[str, ...] = (
    "**No LLM, no service.** GraphDB is read once (SELECT only) into `scripts/outputs/reach_snapshot.json`; "
    "everything else is the schema and concept TTL on disk plus the code being measured.",
    "**Concepts come from the TTL on disk, not from GraphDB**, so a vocabulary edit is measured "
    "without an upload. The live concept map may lag the files.",
    "**The referent gate's control flow is the real one** (`ReferentResolver.resolve`); only its "
    "five graph lookups are answered from the snapshot. `_matching_ids` is unbounded here (the "
    "live query has `LIMIT 200`), so an ambiguity can be reported that the live gate would miss.",
    "**The classifier is not modelled.** No intent and no entity list are supplied, so the gate sees "
    "the question alone and `GATED_INTENTS` is not applied: a question reported 'not found' is "
    "declined live only if its intent is one the gate covers.",
    "**A bare word after 'room', 'zone', 'space' or 'area' that exists somewhere in the graph "
    "resolves trivially** (it is a substring of some label or IRI). Those are counted separately "
    "as `weak` and excluded from 'existing referent'.",
    "**Amenity matching is lexical and lenient** (one shared word clears `_MIN_SCORE`); the live "
    "lane filters candidates on topic afterwards, which is not modelled. 'topic only' is the weak "
    "tier for that reason.",
    "**Register selection is the router's scorer**, fed instance counts from the snapshot; a class "
    "with zero instances is absent exactly as the router treats it. The events-store registration "
    "is read from `input/` when a building is active.",
    "**Routing is evaluated from five starting intents**; which one the classifier would give is "
    "unknown, so read `from general` as the deterministic claim and `from any start` as an upper bound.",
    "**The pool is bank-shaped.** It contains what the project has authored (survey, catalogues, "
    "synthetic, and the hand-written sets), not a sample of what a stranger will ask.",
)


# ── driver ──────────────────────────────────────────────────────────────────────────────


def build_models(
    snapshot: Dict[str, Any], use_contract: bool = True, events_store: bool = True
) -> Models:
    """Load the concept map and the router's scorers; import the routing contract if allowed."""
    concept_map = load_concept_map()
    contract: Optional[ContractRunner] = None
    skipped = ""
    if use_contract:
        try:
            contract = ContractRunner()
        except Exception as exc:  # any import failure: report it, do not hide it
            skipped = f"{type(exc).__name__}: {exc}"
    else:
        skipped = "disabled with --no-contract"
    return Models(snapshot, concept_map, contract, skipped, events_store)


def run(
    questions: Sequence[Any],
    snapshot: Dict[str, Any],
    use_contract: bool = True,
    events_store: bool = True,
    progress: bool = False,
) -> Tuple[List[Dict[str, Any]], Models]:
    """Evaluate ``questions``; returns the rows and the models used."""
    models = build_models(snapshot, use_contract, events_store)
    with quiet_logging():
        rows = evaluate_all(models, questions, progress)
    return rows, models


def make_meta(
    bank: Any, snapshot: Dict[str, Any], models: Models, seconds: float
) -> Dict[str, Any]:
    """Facts about the run the report quotes."""
    mb = master_bank()
    info = mb.stats(bank)
    entities = snapshot.get("entities", {})
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "bank": info,
        "snapshot_taken_at": snapshot.get("taken_at", "?"),
        "endpoint": snapshot.get("endpoint", "?"),
        "namespace": snapshot.get("namespace", "?"),
        "entity_counts": ", ".join(f"{len(entities.get(k, []))} {k}" for k in sorted(entities)),
        "concepts": len(models.concept_map),
        "concept_terms": sum(len(e["lay_terms"]) for e in models.concept_map.values()),
        "concept_files": [_rel(p) for p in CONCEPT_TTLS],
        "held_registers": len(models.reach.held),
        "events_store_classes": list(models.events_store_classes),
        "contract_note": models.contract_skipped,
        "seconds": seconds,
    }


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def select_pool(bank: Any, sources: Sequence[str], sample: int = 0, seed: int = 1) -> List[Any]:
    """The questions to evaluate: tuning only, whatever the arguments. A held-out one is an error."""
    mb = master_bank()
    if sample:
        questions = mb.sample(bank, sample, seed, sources)
    else:
        questions = [q for q in bank.tuning() if not sources or set(sources) & set(q.sources)]
    if any(q.holdout for q in questions):
        raise RuntimeError("a held-out question reached the evaluation pool")
    return list(questions)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--holdout-hashes", help="file of sha1 digests of held-out questions")
    ap.add_argument(
        "--snapshot", action="store_true", help="refresh the read-only GraphDB snapshot"
    )
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--namespace", default="", help="override the active building's namespace")
    ap.add_argument("--no-contract", action="store_true", help="skip the routing-contract pass")
    ap.add_argument("--no-events-store", action="store_true")
    ap.add_argument("--source", default="", help="comma list of sources to evaluate")
    ap.add_argument("--sample", type=int, default=0, help="evaluate a seeded stratified sample")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--md", default=str(DEFAULT_MD), help="markdown report path ('' to skip)")
    ap.add_argument("--json", default="", help="write per-question rows and the summary here")
    args = ap.parse_args(argv)

    started = time.time()
    mb = master_bank()
    try:
        bank = mb.load_bank(args.holdout_hashes, require_holdout=True)
    except (mb.HoldoutHashesMissing, mb.HeldOutPathError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    questions = select_pool(bank, sources, args.sample, args.seed)

    print(f"evaluating {len(questions)} tuning questions", file=sys.stderr)
    snapshot = load_snapshot(SNAPSHOT, args.endpoint, args.namespace, refresh=args.snapshot)
    rows, models = run(
        questions,
        snapshot,
        use_contract=not args.no_contract,
        events_store=not args.no_events_store,
        progress=True,
    )
    summary = summarise(rows, models, models.contract_skipped)
    meta = make_meta(bank, snapshot, models, time.time() - started)
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(render_markdown(summary, meta), encoding="utf-8")
        print(f"wrote {args.md}", file=sys.stderr)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps({"meta": meta, "summary": summary, "rows": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {args.json}", file=sys.stderr)
    overall = summary["overall"]
    if overall:
        print(
            f"n={overall['n']}  concept {overall['concept_pct']}%  register {overall['register_pct']}%"
            f"  amenity {overall['amenity_pct']}%  referent {overall['referent_pct']}%"
            f"  nothing {overall['nothing_pct']}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
