# -*- coding: utf-8 -*-
"""Replay the absence second chance over every stored, hand-labelled answer (row 2D-18).

Why this exists
---------------
The second chance decides from the question, the decline and the building's own registers and
prose, with no model call, so it can be measured offline on answers that were already given and
already labelled by hand. Two numbers matter and they pull against each other:

* of the answers a reader labelled a false absence, how many does the probe find a place to look for;
* of the answers a reader labelled a good decline or a good answer, how many would it wrongly reopen
  (the target is zero) or reword.

No lane is called. The probe reads what the live one reads (the registers and the prose on the
building's records), taken from ONE read-only snapshot of GraphDB cached to JSON, so a re-run needs
no service. Hand labels are read from ``docs/phase0/*_read.jsonl``; nothing named ``tail_D*`` is opened.

Usage
-----
    python scripts/absence_second_chance_replay.py --snapshot     # refresh the GraphDB snapshot
    python scripts/absence_second_chance_replay.py                 # replay from the snapshot
    python scripts/absence_second_chance_replay.py --details out.jsonl --show FALSE_ABSENCE
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The orchestrator package builds its settings at import; this script never talks to a service.
os.environ.setdefault("STRICT_SECRETS", "false")
os.environ.setdefault("PIPELINE_API_KEY", "sk-replay-not-a-key")
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:9")

SNAPSHOT = REPO / "scripts" / "outputs" / "absence_second_chance_snapshot.json"
GOLD = REPO / "scripts" / "absence_second_chance_gold.json"
PHASE0 = REPO / "docs" / "phase0"
ENDPOINT = "http://127.0.0.1:7200/repositories/bldg"
ONTO = "http://ontosage.org/capabilities#"

_FALSE_EVIDENCE = re.compile(
    r"false absence|no information|does not record|doesn.t keep a record|not record|no locks|"
    r"no weekday|lists only|records do not|denies|no record|not find|holds? no|no data",
    re.IGNORECASE,
)


# ── the snapshot ────────────────────────────────────────────────────────────────────────────────


def _select(query: str, endpoint: str) -> List[Dict[str, Any]]:
    request = urllib.request.Request(
        endpoint,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - local GraphDB
        return json.load(response)["results"]["bindings"]


def take_snapshot(endpoint: str, namespace: str, path: Path) -> None:
    """Read the register rows and the prose literals once, read-only, into ``path``."""
    from orchestrator.services import absence_second_chance as sc

    classes = _select(
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        f"PREFIX o: <{ONTO}>\n"
        "SELECT DISTINCT ?cls (SAMPLE(?lbl) AS ?label) (COUNT(DISTINCT ?i) AS ?n)\n"
        '  (GROUP_CONCAT(DISTINCT ?lay; SEPARATOR="|") AS ?lays) WHERE {\n'
        " VALUES ?root { o:Record o:IntervalRecord }\n"
        " ?cls rdfs:subClassOf+ ?root . ?i a ?cls .\n"
        " OPTIONAL{?cls rdfs:label ?lbl} OPTIONAL{?cls o:layTerms ?lay}\n"
        "} GROUP BY ?cls",
        endpoint,
    )
    quals = {
        r["cls"]["value"].rsplit("#", 1)[-1]: r["q"]["value"]
        for r in _select(
            f'PREFIX o: <{ONTO}>\nSELECT ?cls (GROUP_CONCAT(DISTINCT ?q; SEPARATOR="|") AS ?q) '
            "WHERE { ?cls o:qualifierTerms ?q } GROUP BY ?cls",
            endpoint,
        )
    }
    tables: Dict[str, Any] = {}
    for row in classes:
        local = row["cls"]["value"].rsplit("#", 1)[-1]
        count = int(row["n"]["value"])
        entry: Dict[str, Any] = {
            "label": row.get("label", {}).get("value", local),
            "n": count,
            "lays": row.get("lays", {}).get("value", ""),
            "quals": quals.get(local, ""),
            "rows": [],
        }
        if count <= 120:
            triples = _select(
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
                f"PREFIX o: <{ONTO}>\n"
                f"SELECT ?record ?p ?v WHERE {{ ?record a o:{local} ; ?p ?v . "
                "FILTER(?p != rdf:type) } ORDER BY ?record LIMIT 6000",
                endpoint,
            )
            pivot: Dict[str, Dict[str, str]] = {}
            for b in triples:
                col = b["p"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                rec = pivot.setdefault(b["record"]["value"], {"record": b["record"]["value"]})
                value = b["v"]["value"]
                rec[col] = f"{rec[col]}, {value}" if col in rec else value
            entry["rows"] = list(pivot.values())
        tables[local] = entry
    preds = " ".join(f"<{p}>" for p in sc.PROSE_PREDICATES)
    prose = _select(
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
        f"SELECT ?s ?label ?p ?text WHERE {{ VALUES ?p {{ {preds} }}\n"
        f'  ?s ?p ?text . FILTER(isLiteral(?text) && STRSTARTS(STR(?s), "{namespace}"))\n'
        "  OPTIONAL { ?s rdfs:label ?label } } LIMIT 20000",
        endpoint,
    )
    texts = [
        {
            "subject": r["s"]["value"],
            "label": r.get("label", {}).get("value", ""),
            "predicate": r["p"]["value"],
            "text": r["text"]["value"],
        }
        for r in prose
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tables": tables, "text": texts, "namespace": namespace}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"snapshot: {len(tables)} register classes, {len(texts)} prose literals -> {path}")


class SnapshotReach:
    """The live probe's three reads, answered from the snapshot by the same rules."""

    def __init__(self, data: Dict[str, Any]) -> None:
        from orchestrator.services import absence_second_chance as sc
        from orchestrator.services import record_registry as rr

        self._sc = sc
        self.record_classes = [
            rr.RecordClass(
                name,
                e["label"],
                e["n"],
                rr._terms_for(name, e["label"], e["lays"]),
                tuple(q for q in e["quals"].lower().split("|") if q),
            )
            for name, e in data["tables"].items()
        ]
        self._rows = {name: e["rows"] for name, e in data["tables"].items()}
        self._texts = [
            sc.TextHit(t["subject"], t["label"], t["predicate"], t["text"]) for t in data["text"]
        ]
        self._namespace = data.get("namespace", "")
        self._binding_cache: Dict[str, Any] = {}
        self._topic_cache: Dict[str, Any] = {}
        self.sensors_on = False
        self._concept_map_loaded = False
        self.endpoint = ENDPOINT

    async def _run(self, query: str) -> Dict[str, Any]:
        """The binder's RunQuery, read-only over HTTP, off the event loop."""
        return await asyncio.to_thread(
            lambda: {"results": {"bindings": _select(query, self.endpoint)}}
        )

    async def classes(self) -> List[Any]:
        return self.record_classes

    async def rows(self, names: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        # The live reach fetches at most MAX_PROBE_ROWS per register; the snapshot is capped the
        # same way, so a register too large to read whole is partial in the replay as it is live.
        cap = self._sc.MAX_PROBE_ROWS
        return {n: (self._rows.get(n) or [])[:cap] for n in names if self._rows.get(n)}

    async def text_hits(self, topic: Sequence[str]) -> List[Any]:
        stems = sorted({self._sc.fold(t) for t in topic if len(t) >= 4})[:12]
        if len(stems) < 2:
            return []
        scored = []
        for hit in self._texts:
            low = hit.text.lower()
            n = sum(1 for s in stems if s in low)
            if n >= 2:
                scored.append((-n, hit.subject, hit))
        return [h for _n, _s, h in sorted(scored)[:40]]

    async def topics(self, question: str) -> List[Any]:
        """The capability resolver over the read-only graph, once per distinct question.

        Off unless the sensor arm is on: like it, this reads the live graph, and the offline
        default must stay offline.
        """
        if not self.sensors_on:
            return []
        if question not in self._topic_cache:
            from orchestrator.services.capability_graph_resolver import CapabilityGraphResolver

            try:
                resolver = CapabilityGraphResolver(self._run)
                self._topic_cache[question] = await resolver.resolve(question)
            except Exception:
                self._topic_cache[question] = []
        return self._topic_cache[question]

    async def measurable(self, question: str, results: Dict[str, Any]) -> Any:
        """The REAL binder, against the read-only graph, cached per question.

        Not a fixture: what the binder makes of a question is the measurement, and a snapshot of
        my own idea of it would measure this script instead. One bind per distinct question — the
        1,355 stored answers repeat 361 questions, and re-binding each repeat would say nothing
        new at six times the cost.
        """
        if not self.sensors_on:
            return None
        if question in self._binding_cache:
            return self._binding_cache[question]
        from orchestrator.services.concept_resolver import concept_resolver
        from orchestrator.services.sensor_binder import bind_sensors

        if not self._concept_map_loaded:
            # The resolver caches its concept map in Redis, which this script has no business
            # starting; without it the map is re-read from the graph for EVERY question. Loaded
            # once here and held, which is what the cache would have done.
            cached = await concept_resolver._load_concept_map()

            async def _held() -> Dict[str, Any]:
                return cached

            concept_resolver._load_concept_map = _held  # type: ignore[assignment]
            self._concept_map_loaded = True
        try:
            matches = await concept_resolver.resolve(question) or []
            concepts = [m.to_dict() if hasattr(m, "to_dict") else m for m in matches]
            # The live reach's arguments exactly, allow_population included: a harness that binds
            # differently from the product measures the harness.
            binding = await bind_sensors(
                question, [], concepts, self._run, self._namespace, "bldg1", True
            )
            if not self._sc.binding_is_about_question(question, concepts, binding):
                binding = None
        except Exception as exc:  # a bind that cannot run is not a candidate
            print(f"  ! bind failed for {question[:60]!r}: {type(exc).__name__}: {exc}")
            binding = None
        self._binding_cache[question] = binding
        return binding


# ── the labelled answers ────────────────────────────────────────────────────────────────────────


def _load(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _answer_file(read_file: Path) -> Optional[Path]:
    stem = read_file.name[: -len("_read.jsonl")]
    names = [f"{stem}.jsonl", f"{stem}.md.jsonl", f"{stem}_combined.jsonl"]
    if stem == "phase0":
        names = ["phase0_baseline.md.jsonl"]
    for name in names:
        if (read_file.parent / name).exists():
            return read_file.parent / name
    return None


def labelled_rows() -> List[Dict[str, Any]]:
    """Every (question, answer, lane, verdict, ...) that has both an answer and a hand label."""
    rows: List[Dict[str, Any]] = []
    for read_file in sorted(PHASE0.glob("*_read.jsonl")):
        # DEVELOPMENT sets only. `dev_tail_D_final` is development and is read; a bare `tail_D`,
        # `tail_E` or `tail_F` is held out, and a held-out set read here would stop being one.
        name = read_file.name
        if any(h in name for h in ("tail_E", "tail_F")) or (
            "tail_D" in name and not name.startswith("dev_")
        ):
            continue
        answer_file = _answer_file(read_file)
        if answer_file is None:
            continue
        answers = {a["q"]: a for a in _load(answer_file) if a.get("q")}
        for read in _load(read_file):
            ans = answers.get(read.get("question"))
            if not ans or not ans.get("answer"):
                continue
            causes = read.get("causes") or []
            evidence = str(read.get("evidence") or "")
            weird = read.get("verdict") == "WEIRD"
            false_absence = weird and (
                "FALSE_ABSENCE" in causes
                or str(read.get("class") or "") in {"C9", "C4"}
                or bool(_FALSE_EVIDENCE.search(evidence))
            )
            rows.append(
                {
                    "file": read_file.name[: -len("_read.jsonl")],
                    "question": read["question"],
                    "answer": ans["answer"],
                    "lane": ans.get("lane"),
                    "verdict": read.get("verdict"),
                    "group": "FALSE_ABSENCE" if false_absence else str(read.get("verdict")),
                    "evidence": evidence,
                }
            )
    return rows


# ── the replay ──────────────────────────────────────────────────────────────────────────────────


def already_read(answer: str, classes: Sequence[Any]) -> List[str]:
    """Registers the stored answer itself says it read ("the work-order register contains 24 …").

    The live probe reads this from ``_prov_stores``, which these stored answers do not carry. The
    answer's own words are the evidence available offline, and they are evidence: a lane that read
    the work-order register says so. Assuming instead that the top-ranked register was the one read
    would hand the probe the result it is being measured on.
    """
    body = re.sub(r"[-‐-―]", " ", (answer or "").lower())
    found = []
    for record in classes:
        label = re.sub(r"[-‐-―]", " ", (record.label or "").lower()).strip()
        if label and re.search(rf"\b{re.escape(label)}s?\b", body):
            found.append(record.local_name)
    return found


async def replay(reach: SnapshotReach, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from orchestrator.services import absence_second_chance as sc

    today = date(2026, 9, 19)
    out: List[Dict[str, Any]] = []
    for row in rows:
        # Older answer files carry no lane; the false absences were overwhelmingly metadata.
        lane = row["lane"] or "metadata"
        shape = sc.detect_absence_shape(row["answer"])
        rec = dict(row, shape=shape.kind if shape else None, skip=None, best=None, tier=None)
        if shape is not None:
            # THE PRODUCT'S OWN GATES, in the product's order. The replay calls `probe` directly
            # rather than `absence_second_chance`, so without these it would measure a module that
            # does not exist: an absence that merely qualifies an answer is skipped, and only one
            # that OPENS an answer may have that answer replaced.
            rec["skip"] = sc.skip_reason({}, lane, row["question"], row["answer"]) or (
                "the absence qualifies an answer" if not shape.leads else None
            )
        if shape is not None and not rec["skip"]:
            used = already_read(row["answer"], reach.record_classes)
            rec["used"] = used
            found = await sc.probe(
                row["question"],
                shape,
                {"_prov_stores": [{"source_id": f"ontosage:{u}"} for u in used]},
                reach,
                lane,
                today,
            )
            if found:
                best = found[0]
                # The live answerers are pure functions of the rows and the prose, so the REOPEN
                # itself is replayed, not guessed: a tier-A candidate whose lane declines to compose
                # changes nothing, and counting intentions instead would overstate both the wins and
                # the harm.
                reopen = ""
                if best.tier == "A" and best.kind == "register" and shape.opens:
                    reopen = sc.register_answer(best, row["question"], today)
                elif best.tier == "A" and best.kind == "text" and shape.opens:
                    reopen = sc.text_answer(best, row["question"])
                elif best.tier == "A" and best.kind == "topic" and shape.opens:
                    reopen = sc.topic_answer(best)
                # A SENSOR CANDIDATE'S HANDOFF IS NOT REPLAYED. It goes to the readings lane,
                # which reads the time-series stores; running that here would measure this
                # script's ability to stand up an adapter registry, not the probe. It is
                # counted separately and the caveat is printed with the numbers.
                rec.update(
                    best=f"{best.kind}:{best.label}",
                    tier=best.tier,
                    candidate_evidence=best.evidence,
                    shared=list(best.shared),
                    reopened=bool(reopen) and sc.acceptable(reopen),
                    sensor_tier_a=best.tier == "A" and best.kind == "sensor",
                    reopen_text=reopen[:400],
                    would_reword=bool(sc.reword_absence(row["answer"], shape, found[:2])),
                    cands=[
                        f"{c.kind}:{c.name.rsplit('#', 1)[-1].rsplit('/', 1)[-1]}:{c.tier}"
                        for c in found[:3]
                    ],
                )
        out.append(rec)
    return out


def summarise(rec: List[Dict[str, Any]]) -> None:
    """Per hand-labelled group, counted by DISTINCT QUESTION.

    By question, not by answer row: the same question appears in up to six runs, so counting rows
    weights a question by how often it was re-asked and makes a single repeated case look like a
    trend. A question counts as detected/reopened if ANY of its stored answers is.
    """
    by: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rec:
        by[r["group"]][r["question"]].append(r)
    print(
        "group                questions  absence-shaped  skipped  candidate  reopened  "
        "sensorA  reworded"
    )
    for group in ("FALSE_ABSENCE", "GOOD_DECLINE", "GOOD_ANSWER", "WEIRD"):
        qs = by.get(group, {})
        det = [q for q, rs in qs.items() if any(r["shape"] for r in rs)]
        skipped = [q for q in det if all(r["skip"] for r in qs[q] if r["shape"])]
        cand = [q for q in det if any(r.get("tier") for r in qs[q])]
        reop = [q for q in det if any(r.get("reopened") for r in qs[q])]
        word = [q for q in det if any(r.get("would_reword") for r in qs[q])]
        sensa = [q for q in det if any(r.get("sensor_tier_a") for r in qs[q])]
        print(
            f"{group:<20}{len(qs):>10}{len(det):>16}{len(skipped):>9}{len(cand):>11}"
            f"{len(reop):>10}{len(sensa):>9}{len(word):>10}"
        )
    print(
        f"({len(rec)} stored answers over {len({r['question'] for r in rec})} distinct questions)"
    )


def gold_report(rec: List[Dict[str, Any]]) -> None:
    """Recall against the hand-assigned sources: does the probe point where the data is?"""
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["cases"]
    total = reachable = top1 = top3 = tier_a = tier_a_right = 0
    print("\nGOLD (hand-assigned false absences; a register or a record's own text is reachable):")
    for case in gold:
        rows = [r for r in rec if case["key"].lower() in r["question"].lower()]
        if not rows:
            continue
        holds = [h for h in case["holds"] if h.startswith(("register:", "text:"))]
        total += 1
        reachable += bool(holds)
        best = max(rows, key=lambda r: (bool(r["cands"] if "cands" in r else 0), r["tier"] == "A"))
        cands = best.get("cands") or []
        names = [c.rsplit(":", 1)[0] for c in cands]
        hit1 = bool(names) and any(names[0].split(":")[1] in h for h in holds)
        hit3 = any(n.split(":")[1] in h for n in names for h in holds)
        top1 += hit1 and bool(holds)
        top3 += hit3 and bool(holds)
        a = [c for c in cands if c.endswith(":A")]
        tier_a += bool(a)
        tier_a_right += bool(a) and any(a[0].rsplit(":", 1)[0].split(":")[1] in h for h in holds)
        flag = "reachable" if holds else "not reachable (sensor / semantic)"
        print(f"  [{'HIT' if hit3 else '   '}] {case['key'][:52]:<52} {flag:<34} {cands[:3]}")
    print(
        f"gold cases {total}; reachable by a register or text probe {reachable}; "
        f"top-1 correct {top1}; correct within top 3 {top3}; tier A fired {tier_a} "
        f"(right {tier_a_right}, wrong {tier_a - tier_a_right})"
    )


def show(rec: List[Dict[str, Any]], group: str, tier: Optional[str]) -> None:
    seen = set()
    for r in rec:
        if r["group"] != group or (tier and r["tier"] != tier) or not r["shape"]:
            continue
        key = (r["question"], r["best"])
        if key in seen:
            continue
        seen.add(key)
        print(f"- [{r['file']}] {r['question'][:110]}")
        print(
            f"    lane={r['lane']} shape={r['shape']} skip={r['skip']} best={r['best']} tier={r['tier']}"
        )
        if r["best"]:
            print(f"    {r.get('evidence')} shared={r.get('shared')}")
        print(f"    label: {r['evidence'][:110] if group != 'FALSE_ABSENCE' else ''}")


async def false_existence_replay(
    reach: SnapshotReach, rows: List[Dict[str, Any]], namespace: str
) -> List[Dict[str, Any]]:
    """Replay the false-existence check: which stored sentences deny something the graph holds.

    ``holds`` is the LIVE one, run against the read-only graph, once per distinct claimed-missing
    subject. A GOOD_DECLINE that gains a rescue here is a false rescue and the target is zero.
    """
    from orchestrator.services import absence_second_chance as sc

    graph = sc.GraphReach(reach._run, namespace, "bldg1")

    async def classes() -> List[Any]:
        return reach.record_classes

    graph.classes = classes  # type: ignore[assignment]
    cache: Dict[str, Any] = {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        claims = sc.find_lack_claims(row["answer"])
        if not claims:
            continue
        # The product's own gates: a typed lane's text is never examined.
        lane = row["lane"] or "metadata"
        if lane in sc._NEVER_REWRITTEN_LANES or sc._PRIVATE_ASK_RE.search(row["question"]):
            continue
        if sc._NOT_MEASURED_RE.search(sc.plain_prose(row["answer"])):
            continue
        for claim in claims:
            if claim.subject not in cache:
                try:
                    cache[claim.subject] = await graph.holds(claim.subject)
                except Exception as exc:
                    print(f"  ! holds failed for {claim.subject!r}: {type(exc).__name__}")
                    cache[claim.subject] = None
            held = cache[claim.subject]
            out.append(
                dict(
                    row,
                    subject=claim.subject,
                    sentence=claim.segment[:160],
                    held=None if held is None else f"{held.kind}:{held.label}",
                    rewrite=None if held is None else sc.scoped_lack(claim, held)[:200],
                )
            )
    return out


def summarise_false_existence(rec: List[Dict[str, Any]]) -> None:
    by: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rec:
        by[r["group"]][r["question"]].append(r)
    print()
    print("FALSE EXISTENCE (a sentence that says the building lacks X), by distinct question")
    print("group                questions-with-a-claim  rescued (X is held)")
    for group in ("FALSE_ABSENCE", "GOOD_DECLINE", "GOOD_ANSWER", "WEIRD"):
        qs = by.get(group, {})
        rescued = [q for q, rs in qs.items() if any(r["held"] for r in rs)]
        print(f"{group:<20}{len(qs):>12}{len(rescued):>26}")
    for group in ("GOOD_DECLINE", "GOOD_ANSWER", "WEIRD", "FALSE_ABSENCE"):
        seen = set()
        for r in rec:
            if r["group"] == group and r["held"] and (r["question"], r["subject"]) not in seen:
                seen.add((r["question"], r["subject"]))
                print(f"  [{group}] {r['question'][:70]}")
                print(f"      claim: {r['sentence'][:110]}")
                print(f"      held : {r['held']}  ->  {r['rewrite'][:120]}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", action="store_true", help="refresh the GraphDB snapshot")
    parser.add_argument(
        "--false-existence",
        action="store_true",
        help="also replay the 'the building lacks X' rewrite (binds against the read-only graph)",
    )
    parser.add_argument(
        "--sensors",
        action="store_true",
        help="run the sensor arm too: binds each question against the read-only graph (slower)",
    )
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--namespace", default="")
    parser.add_argument("--details", type=Path, help="write one JSON line per row")
    parser.add_argument("--show", choices=["FALSE_ABSENCE", "GOOD_DECLINE", "GOOD_ANSWER", "WEIRD"])
    parser.add_argument("--tier", choices=["A", "B"])
    args = parser.parse_args(argv)
    if args.snapshot:
        namespace = args.namespace
        if not namespace:
            from shared.config import settings

            namespace = settings.BUILDING_NAMESPACE
        take_snapshot(args.endpoint, namespace, SNAPSHOT)
    reach = SnapshotReach(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
    reach.sensors_on = bool(args.sensors)
    reach.endpoint = args.endpoint
    if args.false_existence:
        namespace = args.namespace or json.loads(SNAPSHOT.read_text(encoding="utf-8")).get(
            "namespace", ""
        )
        found = asyncio.run(false_existence_replay(reach, labelled_rows(), namespace))
        summarise_false_existence(found)
        return 0
    records = asyncio.run(replay(reach, labelled_rows()))
    summarise(records)
    gold_report(records)
    if args.show:
        show(records, args.show, args.tier)
    if args.details:
        args.details.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
