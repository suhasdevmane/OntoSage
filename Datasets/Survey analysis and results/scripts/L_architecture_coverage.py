#!/usr/bin/env python3
"""
L_architecture_coverage.py
==========================

Exhaustive crosswalk of the master table's `architecture` + `pipeline_stages` +
`data_sources` columns against (a) existing OntoSage components and (b) the
turns in tasks/implementation_tracker.csv.

Purpose: prove (or disprove) that IMPLEMENTATION_PLAN_V3 covers every
capability the 5,604 real user questions require — and name what it misses.

Outputs (to tasks/):
  architecture_coverage_crosswalk.csv   component, mentions, rows, status, covered_by, examples
  architecture_unmapped_fragments.csv   residual fragments no rule caught (audit tail)

Usage:
    python "paper/Survey analysis and results/scripts/L_architecture_coverage.py"
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SURVEY_ROOT = HERE.parent
REPO_ROOT = SURVEY_ROOT.parent.parent
INPUT = SURVEY_ROOT / "outputs" / "tables" / "complexity_master_table.csv"
OUTDIR = REPO_ROOT / "tasks"

# --------------------------------------------------------------------------- #
# Canonical component taxonomy.
# Ordered rules — FIRST match wins. status:
#   EXISTING        already implemented in OntoSage today
#   PLANNED:<turns> covered by tracker turn(s)
#   NEEDED          not covered -> must extend the tracker
# --------------------------------------------------------------------------- #
RULES = [
    # ---------- existing pipeline components ----------
    ("dialogue / intent / clarification", "EXISTING", "",
     r"^dialogue$|intent (classification|routing|detection)|sensor_data intent|clarif|co-?reference|conversation (memory|context)|context (injection|management)|multi-?turn|resolve (current )?(room|location|area|zone|floor|user|scope)|entity (resolution|extraction)"),
    ("verifier / grounding", "EXISTING", "", r"verif|grounding|fact.?check"),
    ("recommendation engine", "EXISTING", "", r"recommend"),
    ("report intake (fault/complaint)", "EXISTING", "",
     r"report[- ]intake|complaint|fault (report|log)|issue (intake|report)|feedback intake"),
    ("LLM answer / response formatting", "EXISTING", "",
     r"^llm\b|llm answer|llm \(|^response$|response (formatting|generation|node)|answer (synthesis|generation)|summari[sz]"),
    ("ontology / knowledge graph / SPARQL", "EXISTING", "",
     r"ontolog|knowledge graph|sparql|graphdb|topology (query|lookup)|brick (model|schema|class)|metadata lookup|building ontology"),
    ("time-series store / retrieval", "EXISTING", "",
     r"time-?series|mysql|sql (query|retrieval)|sensor (data )?retrieval|telemetry retrieval|historical (data|readings)|data store"),
    ("analytics sandbox (stats/corr/anomaly)", "EXISTING", "",
     r"analytic|statistic|correlat|anomal|aggregat|comparison|compare engine|trend analysis|threshold check|baseline"),
    ("forecasting (ARIMA/ETS)", "EXISTING", "",
     r"forecast|arima|\bets\b|predictive model|prediction model"),
    ("agentic RAG fallback", "EXISTING", "", r"\brag\b|agentic rag|semantic (fallback|search)"),
    ("capability KB (Qdrant)", "EXISTING", "",
     r"capability (kb|knowledge|check|intent)|qdrant|amenity|hvac zoning|add(ed)? to (the )?kb|knowledge base"),
    ("live floor-5 streams (existing data)", "EXISTING", "", r"floor[ -]?5\b|live sensor stream"),
    ("floor-plan / spatial reasoning", "EXISTING", "",
     r"floor[ -]?plans?|spatial|dwg|adjacen|area (calc|comput)|room (count|locat)"),
    ("visualisation", "EXISTING", "", r"visuali[sz]|chart|plot\b|graph generation|heatmap|report/visuals"),
    ("report / document generation / export", "EXISTING", "",
     r"report (generation|builder|formatting)|multi-?section report|document generation|export|csv output|pdf (output|report)|\breport\b"),
    ("RBAC / auth", "EXISTING", "", r"rbac|auth|permission|access control(?! system)"),
    ("LangGraph orchestration / planner", "EXISTING", "",
     r"langgraph|orchestrat|planner|multi-?step plan|workflow engine"),
    ("response cache", "EXISTING", "", r"\bcache\b"),
    ("personas", "EXISTING", "", r"persona"),
    ("multilingual handling", "EXISTING", "", r"translat|multilingual|language detect"),
    ("general LLM knowledge (excluded scope)", "EXISTING", "", r"general (llm )?knowledge"),

    # ---------- named gaps -> planned turns ----------
    ("HBCO concept layer / lay-term mapping", "PLANNED", "T01-T06",
     r"concept (layer|mapping)|lay term|vocabulary mapping|comfort (model|concept)|add(ed)? to ontology|ontology extension|new (class|property)"),
    ("metadata enrichment (capacity/function/tenant)", "PLANNED", "T07",
     r"capacity|tenant|quiet.?zone|room (function|metadata|purpose)|unit mapping|facade|window metadata|study-?space metadata|material"),
    ("document KB (policies/SOPs/manuals)", "PLANNED", "T08",
     r"policy|regulation|governance|sop\b|standard operating|manual|procedure doc|guideline|lease|insurance|certification doc"),
    ("directory / contacts", "PLANNED", "T08",
     r"directory|contact (info|details|list)|staff (list|contact)|who to (call|contact)|emergency contact"),
    ("idempotent TTL / graph hygiene", "PLANNED", "T09", r"named graph|ttl upload|graph hygiene"),
    ("live streams floors 0-4", "PLANNED", "T10-T11",
     r"floors? ?0[-–]4|floor ?0\b|live (stream|temp|co2|humidit|data) (for|on)? ?floors?"),
    ("generic external-feed framework", "PLANNED", "T12-T13",
     r"external (api|feed|data source)|new (data source|sensor feed|feed)|api integration|data ingestion pipeline|stream ingestion"),
    ("weather feed", "PLANNED", "T14", r"weather|outdoor (temp|condition)|meteo"),
    ("calendar / booking / events feed", "PLANNED", "T15",
     r"calendar|booking|timetable|schedul|event (feed|data|api)|class (times|schedule)"),
    ("tariff / cost data", "PLANNED", "T15", r"tariff|price|cost (data|api)|billing"),
    ("occupancy sensing", "PLANNED", "T16",
     r"occupan|footfall|people.?count|headcount|motion|\bpir\b|presence|crowd|busy"),
    ("energy metering", "PLANNED", "T17", r"energy|submeter|power|electricit|kwh|consumption meter"),
    ("carbon / ESG accounting", "PLANNED", "T17", r"carbon|co2e|emission|esg|sustainab|footprint"),
    ("extended IAQ (PM/VOC/NO2)", "PLANNED", "T18",
     r"air quality|pm2|pm10|voc|particulate|pollutant|radon|ozone|\bno2\b|\biaq\b|fresh.?air metric"),
    ("noise / acoustic sensing", "PLANNED", "T18", r"noise|acoustic|sound|decibel"),
    ("lighting sensing / control", "PLANNED", "T18", r"light|lux|illumina|daylight"),
    ("water metering / leak", "PLANNED", "T18", r"water|leak|plumbing"),
    ("long-tail feed playbook", "PLANNED", "T19",
     r"\bgas\b|fridge|refrigerat|freezer|vending|battery|\bups\b|outage|utility api|parking|\bev\b|charger|waste|recycl|solar|photovolta|\bpv\b|renewable|window (contact|state|sensor)|door (state|contact|sensor)|wi-?fi|network monitor|av (status|system)|appliance|inventory|asset (list|registry)|desk|seat|plant inventory|green (roof|wall)|irrigat"),
    ("ECA rules / standing alerts", "PLANNED", "T20-T22",
     r"rule engine|event-?condition|standing (rule|alert)|alert|automat(ed|ic) (trigger|monitor)|watchdog|continuous monitor|^monitor(ing)?( service| feedback)?$"),
    ("BMS actuation / write-back", "PLANNED", "T23-T25",
     r"bms|write-?back|actuat|^control( service| node)?$|control (api|loop|command|point|sequence|intent)|setpoint|valve|damper|hvac (control|adjust)|switch (on|off)|turn (on|off)|adjust (temperature|hvac|setting)"),
    ("goal decomposition / autonomy", "PLANNED", "T26-T27",
     r"goal (decomposition|planning)|kpi|optimi[sz]ation strategy|self-?manage|strategy (engine|synthesis)|continuous improvement"),
    ("maintenance / CMMS records", "PLANNED", "T36",
     r"maintenance|cmms|work.?order|inspection|service (record|history)|calibrat|asset history|repair log"),
    ("equipment condition / predictive maintenance", "PLANNED", "T36",
     r"vibration|acceleromet|voltage|current sensor|equipment (health|condition|telemetry|status)|lift telemetry|elevator|escalator|ahu (status|telemetry)|pump|motor|runtime|fault detect|fdd\b|degradation|remaining useful life"),
    ("access / security systems", "PLANNED", "T19",
     r"access (system|log|badge)|security|cctv|camera|badge|intrusion|visitor log"),
    ("fire / life-safety feed", "PLANNED", "T19",
     r"fire|life.?safety|alarm panel|smoke|sprinkler|emergency (system|feed|alarm)|evacuation status"),
    ("occupant surveys / subjective feedback", "PLANNED", "T19",
     r"satisfaction|survey|wellbeing|productivity (data|survey)|comfort feedback|vote|poll"),

    # ---------- suspected NOT-covered categories ----------
    ("wayfinding / route guidance", "NEEDED", "",
     r"wayfind|route (computation|planning|guidance)|navigat|directions|shortest path|how (do i|to) get"),
    ("benchmarking vs peers/standards", "NEEDED", "",
     r"benchmark|comparable building|peer (building|comparison)|industry (average|standard)|portfolio comparison|rating scheme|breeam|leed"),
    ("notification / comms dispatch", "NEEDED", "",
     r"notification (dispatch|service|channel)|notify (the|manager|staff|user)|email (it|report|dispatch|to)|sms|push notification|escalat|broadcast|announce"),
    ("what-if / scenario simulation", "NEEDED", "",
     r"what-?if|simulat|scenario (analysis|model)|digital twin|impact estimate|would happen|hypothetical"),
    ("personalised preferences", "NEEDED", "",
     r"preference|personali[sz]|user profile|remember (my|that i)|my (settings|comfort)"),
]
COMPILED = [(name, status, turns, re.compile(pat)) for name, status, turns, pat in RULES]

_SPLIT = re.compile(r"[;>]|->")
_GENERIC = re.compile(
    r"^(\[new\] ?)?(data |telemetry |stream |generic )?(retrieval|ingestion|lookup|query|fetch|api|processing|integration)$"
)


def classify(frag: str):
    f = frag.lower().strip().strip(".,)(")
    f = re.sub(r"^\[new\]\s*", "", f)
    if not f or len(f) < 3 or _GENERIC.match(f):
        return None
    for name, status, turns, rx in COMPILED:
        if rx.search(f):
            return (name, status, turns)
    return ("__UNMAPPED__", "?", f)


def main() -> None:
    df = pd.read_csv(INPUT, dtype=str).fillna("")
    df = df[df["answer_basis"] != "general-knowledge"].copy()  # user: GK out of scope
    n_rows = len(df)

    comp_mentions: Counter = Counter()
    comp_rows: defaultdict = defaultdict(set)
    comp_examples: defaultdict = defaultdict(list)
    unmapped: Counter = Counter()

    for idx, row in df.iterrows():
        blob = " ; ".join((row["architecture"], row["data_sources"], row["pipeline_stages"]))
        seen_in_row = set()
        for frag in _SPLIT.split(blob):
            res = classify(frag)
            if res is None:
                continue
            name, status, turns = res
            if name == "__UNMAPPED__":
                unmapped[turns[:70]] += 1
                continue
            comp_mentions[name] += 1
            if name not in seen_in_row:
                comp_rows[name].add(idx)
                if len(comp_examples[name]) < 2:
                    comp_examples[name].append(row["question"][:90])
                seen_in_row.add(name)

    meta = {name: (status, turns) for name, status, turns, _ in COMPILED}
    out_rows = []
    for name, mentions in comp_mentions.most_common():
        status, turns = meta[name]
        out_rows.append({
            "component": name,
            "status": status,
            "covered_by": turns or ("already implemented" if status == "EXISTING" else "EXTEND TRACKER"),
            "mentions": mentions,
            "rows_touched": len(comp_rows[name]),
            "pct_of_nonGK_rows": round(100 * len(comp_rows[name]) / n_rows, 1),
            "example_questions": " || ".join(comp_examples[name]),
        })

    OUTDIR.mkdir(exist_ok=True)
    with (OUTDIR / "architecture_coverage_crosswalk.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    with (OUTDIR / "architecture_unmapped_fragments.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fragment", "mentions"])
        for frag, c in unmapped.most_common():
            w.writerow([frag, c])

    total_mentions = sum(comp_mentions.values()) + sum(unmapped.values())
    by_status = Counter()
    for name, m in comp_mentions.items():
        by_status[meta[name][0]] += m
    print(f"non-GK rows: {n_rows}")
    print(f"component mentions classified: {sum(comp_mentions.values())} "
          f"| unmapped residual: {sum(unmapped.values())} "
          f"({100*sum(unmapped.values())/total_mentions:.1f}% of mentions)")
    for s in ("EXISTING", "PLANNED", "NEEDED"):
        print(f"  {s:9s}: {by_status[s]:6d} mentions")
    print("\nNEEDED components (rows touched):")
    for r in out_rows:
        if r["status"] == "NEEDED":
            print(f"  {r['rows_touched']:5d} rows  {r['component']}")
    print("\nTop 15 unmapped fragments:")
    for frag, c in unmapped.most_common(15):
        print(f"  {c:4d}  {frag}")


if __name__ == "__main__":
    main()
