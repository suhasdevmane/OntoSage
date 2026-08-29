# -*- coding: utf-8 -*-
"""Append the unanswered-question workstream to tasks/V6_TRACKER.csv (V6-T70..T81).

Written as a script rather than hand-edited into the CSV so the rows are quoted
correctly, the append is idempotent, and the reasoning behind each task lives beside the
task instead of in a chat log.

The design decision behind the ordering: the 243 unanswered questions are NOT one
problem. They divide into work that costs nothing but authoring, work that needs a new
data source, and work that is a defect in code — and the cheapest, highest-yield item is
none of those. It is that all 180 declines say the SAME generic sentence. Making the
decline specific helps every one of them before a single new source is onboarded.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER = REPO / "tasks" / "V6_TRACKER.csv"

FIELDS = [
    "turn",
    "phase",
    "title",
    "status",
    "depends_on",
    "effort",
    "objective",
    "why",
    "alternatives_rejected",
    "building_agnostic_how",
    "key_steps",
    "files",
    "input_files",
    "acceptance_criteria",
    "verify",
    "notes",
]

PHASE = "P12-Unanswered"

ROWS = [
    {
        "turn": "V6-T70",
        "title": "Make the decline SPECIFIC — say what is missing and what is held",
        "depends_on": "",
        "effort": "S",
        "objective": (
            "Replace the one generic sentence every declined question receives with a decline "
            "that names the thing that was not found, names what the building DOES hold nearby, "
            "and says how to add it."
        ),
        "why": (
            "All 180 declines in the 2026-08-28 capture are byte-identical: 'I don't have that "
            "specific information on record for Abacws Building.' That sentence is honest and "
            "useless. It cannot be triaged, it teaches the asker nothing, and it makes 180 very "
            "different failures look like one. This is the cheapest item on the list and it "
            "improves every one of them BEFORE any new data source is onboarded — which is why "
            "it is first."
        ),
        "alternatives_rejected": (
            "Waiting until the data lands and letting the decline stay generic in the meantime — "
            "rejected because most of these questions will still be declined after the data work, "
            "just fewer of them, and the asker deserves to know which case they are in."
        ),
        "building_agnostic_how": (
            "The 'what this building does hold' half is computed from the live graph (nearest "
            "amenities/topics by lay term, the modality census), never from a per-building list."
        ),
        "key_steps": (
            "1) capability_agent: when nothing scores, report the SUBJECT it looked for. "
            "2) Add the nearest-neighbour hits it rejected and why (below threshold, wrong floor). "
            "3) Name the onboarding route that would fix it (TTL, document, datasource). "
            "4) Keep it short — three sentences, not a lecture."
        ),
        "files": "orchestrator/agents/capability_agent.py; services/capability_graph_resolver.py",
        "input_files": "",
        "acceptance_criteria": (
            "No two declines in a fresh capture are byte-identical unless the questions are. "
            "Each names a subject and at least one thing the building does hold."
        ),
        "verify": "Re-ask 20 of the 180 and read the replies; they must differ and be actionable.",
        "notes": "From the V6_unanswered_worklist (243 rows). Highest yield per hour of work.",
    },
    {
        "turn": "V6-T71",
        "title": "The spatial lane raises an ERROR instead of answering or declining",
        "depends_on": "",
        "effort": "M",
        "objective": (
            "29 questions returned 'I encountered an error analysing the spatial data. Please try "
            "again.' Find the exception, fix it, and make the failure path an honest decline."
        ),
        "why": (
            "An error is not a decline. It tells the user nothing, it hides which component "
            "failed, and it is indistinguishable from a system that is simply broken. These 29 "
            "are the clearest defect in the whole worklist and they are not a data problem."
        ),
        "alternatives_rejected": (
            "Catching the exception and returning the generic decline — that would hide a real "
            "defect behind an honest-looking sentence, which is worse than the error."
        ),
        "building_agnostic_how": "The failing path is code; reproduce on bldg1 and confirm on bldg2.",
        "key_steps": (
            "1) Replay the 29 with a trace and capture the exception. "
            "2) Fix the cause. "
            "3) Whatever remains unanswerable becomes a decline naming the missing geometry."
        ),
        "files": "orchestrator/agents/spatial_agent.py; services/floor_plan_registry.py",
        "input_files": "",
        "acceptance_criteria": "Zero 'I encountered an error' replies in a fresh capture.",
        "verify": "Re-ask all 29; none returns an error string.",
        "notes": "group=SPATIAL_ERROR in the worklist.",
    },
    {
        "turn": "V6-T72",
        "title": "Breadth questions cost more than the 150s timeout allows",
        "depends_on": "",
        "effort": "M",
        "objective": (
            "16 questions exhaust REQUEST_TIMEOUT_SECS. Make breadth cheap enough to answer, and "
            "raise the ceiling only as far as the work actually needs."
        ),
        "why": (
            "CAVEAT-363. These are not missing data — they are cross-joins, month- and year-long "
            "windows, and multi-step planning. Answered questions already reach p99 96.4s against "
            "a 150s limit, so the tail is close to the ceiling for ordinary work too."
        ),
        "alternatives_rejected": (
            "Raising the timeout ALONE — rejected. It admits the questions while making a user "
            "wait minutes, and it leaves the p99 creeping toward whatever the new ceiling is. The "
            "timeout raise is the unblock; the aggregation is the fix. "
            "Dropping them from the bank — rejected: 1.0% of the corpus unanswerable by COST "
            "rather than by capability is a finding, not an embarrassment to hide."
        ),
        "building_agnostic_how": "Aggregation pushed into the adapter layer, so every backend benefits.",
        "key_steps": (
            "1) Aggregate in SQL (GROUP BY time bucket / space) instead of fetching rows into "
            "Python — the sql_agent already coarsens AFTER the fetch, which is the expensive half. "
            "2) Bound the candidate set for multi-space questions. "
            "3) THEN raise REQUEST_TIMEOUT_SECS to 300 and re-measure the tail. "
            "4) Record the new p99 in the QA doc."
        ),
        "files": "orchestrator/agents/sql_agent.py; services/adapters/*; shared/config.py",
        "input_files": "",
        "acceptance_criteria": "All 16 answer within the timeout; p99 for the whole bank does not rise.",
        "verify": "Re-ask the 16 by ID; each returns an answer, and the bank's p99 is re-measured.",
        "notes": "The 16 are listed in docs/V6_Implementation_QA.md §4 with their IDs.",
    },
    {
        "turn": "V6-T73",
        "title": "The capability lane is a catch-all — route what other lanes can answer",
        "depends_on": "V6-T70",
        "effort": "L",
        "objective": (
            "All 180 declines routed to ONE intent: capability. Send the ones another lane already "
            "serves to that lane instead."
        ),
        "why": (
            "'Give me a report on the anomalies this week' has an events lane. 'When was this data "
            "last updated?' has freshness metadata. 'Where is the facility manager's office?' has "
            "a floor plan. 'Give me the sensor readings around 2.15 for the past hour' is a plain "
            "sensor_data question. None of these is missing data; the question never reached the "
            "lane that holds it. This is the largest recoverable group in the worklist."
        ),
        "alternatives_rejected": (
            "Widening the capability lane to answer them itself — rejected: it would duplicate "
            "four lanes inside the catch-all and put the evidence record on the wrong lane."
        ),
        "building_agnostic_how": (
            "Rules go in services/routing_contract.py, whose precedence order is pinned by a test; "
            "no building literals."
        ),
        "key_steps": (
            "1) Take the worklist's ROUTING-* buckets (anomaly, wayfinding, forecast, self) plus "
            "the ANALYTICS-COMPARATIVE rows. "
            "2) For each, confirm the target lane can actually answer BEFORE adding a rule — a "
            "rule that routes to a lane with no data trades a decline for a worse decline. "
            "3) Add rules to the contract, update the pinned precedence test in the same commit. "
            "4) Re-ask and compare against the golden baseline via the regression gate."
        ),
        "files": "orchestrator/services/routing_contract.py; tests/test_routing_contract.py",
        "input_files": "",
        "acceptance_criteria": (
            "Each rule added is justified by a live probe showing the target lane answers. "
            "Regression gate: zero regressions against baseline_20260828_185823."
        ),
        "verify": "Re-ask the affected qids; routed_intent changes and the answer is substantive.",
        "notes": "~40 rows. Do NOT batch-add rules without probing each target lane first.",
    },
    {
        "turn": "V6-T74",
        "title": "Expose the provenance the evidence record already holds",
        "depends_on": "",
        "effort": "S",
        "objective": (
            "Answer the questions that ask how the system knows what it knows: sources used, how "
            "recent, what is simulated, how confident, what is weakest."
        ),
        "why": (
            "'Are any of the numbers you show simulated rather than measured? How would I know?', "
            "'Why should I trust this answer, and can you show me the sources?', 'What's the "
            "sampling interval and timestamp convention for the archive?' — V6 BUILT the machinery "
            "these ask for. The EvidenceRecord carries status, operation, sources and freshness; "
            "ontosage:isSimulated marks generated data; archivalIntervalS holds 1,994 measured "
            "cadences. None of it is reachable by asking."
        ),
        "alternatives_rejected": (
            "Answering from the LLM's impression of its own confidence — rejected outright. The "
            "whole point of the evidence record is that provenance is recorded, not narrated."
        ),
        "building_agnostic_how": "Reads the evidence record and the graph; nothing per-building.",
        "key_steps": (
            "1) A provenance intent that renders the CURRENT turn's evidence record in plain words. "
            "2) A simulated-vs-measured answer from ontosage:isSimulated and datasource nature. "
            "3) A cadence/freshness answer from archivalIntervalS. "
            "4) Collect it in _response_node — the step that is always forgotten."
        ),
        "files": "orchestrator/services/evidence/*; workflow/_orchestrator.py; intent_definitions.yaml",
        "input_files": "",
        "acceptance_criteria": "The five provenance questions answer from the record, not from prose.",
        "verify": "Ask each; the answer must name a real source and a real timestamp.",
        "notes": "High value for the thesis: it demonstrates the evidence layer end to end.",
    },
    {
        "turn": "V6-T75",
        "title": "Document pack — compliance, statutory and O&M records",
        "depends_on": "",
        "effort": "L",
        "objective": (
            "Onboard the documents ~45 questions need: water hygiene logbook, permits (hot work, "
            "roof/harness), asbestos register, COSHH and fume-cupboard examinations, PEEPs, "
            "contractor inductions, fire strategy, O&M manuals, lease/base-build schedules."
        ),
        "why": (
            "18 questions returned 'I could not find a passage in this building's documents' — the "
            "document lane WORKS and has nothing to read. Another ~25 asked for the same class of "
            "record and fell to the generic decline. This is pure onboarding: drop files into "
            "input/documents/ and reindex, no code."
        ),
        "alternatives_rejected": (
            "Authoring the answers as knowledge triples instead — rejected for this class. A "
            "logbook entry or a permit is a RECORD with a date and an author; flattening it into a "
            "hand-written sentence loses the provenance that makes it worth citing."
        ),
        "building_agnostic_how": "input/documents/ + the existing SHA-idempotent indexer; per building.",
        "key_steps": (
            "1) List the documents each of the 43 questions needs (the worklist's DOCUMENT rows "
            "plus the asset/compliance UNTRIAGED ones). "
            "2) Obtain or synthesise them — SYNTHETIC ONLY where the building is synthetic; bldg1 "
            "is real and a fabricated compliance record about a real building is not acceptable. "
            "3) Upload, reindex, re-ask."
        ),
        "files": "services/document_indexer.py; agents/capability_agent.py",
        "input_files": "input/documents/*",
        "acceptance_criteria": "The 18 DOC_NOT_FOUND questions find a passage, or say which document is absent.",
        "verify": "Re-ask the 18 plus a sample of the compliance questions.",
        "notes": (
            "DECISION NEEDED FROM THE USER for bldg1: real compliance documents, or an explicit "
            "'not held' answer. Do not invent a legionella record for a real building."
        ),
    },
    {
        "turn": "V6-T76",
        "title": "Amenity and room-equipment inventory",
        "depends_on": "",
        "effort": "M",
        "objective": (
            "Author the amenities and per-room equipment ~20 questions ask for: first-aid and "
            "wellness rooms, eyewash, microwaves, lockers, showers, ATMs, charging points, "
            "cloakrooms; and whiteboards, HDMI, video conferencing, height-adjustable desks."
        ),
        "why": (
            "These are Amenity and Brick equipment triples the building has simply never declared. "
            "The lane that answers them already works — bldg2's refill points prove it — so this "
            "is authoring, not engineering."
        ),
        "alternatives_rejected": (
            "A sidecar YAML inventory — rejected by the TTL-first contract. If it can be a triple "
            "it belongs in the ontology."
        ),
        "building_agnostic_how": "Authored via the admin Capabilities GUI / OCBV TBox, per building.",
        "key_steps": (
            "1) Extract the amenity and equipment nouns from the worklist rows. "
            "2) Author them for each building with its own values (never copied between buildings). "
            "3) Re-ask; check the out-of-service exclusion still applies."
        ),
        "files": "services/capability_admin.py; scripts/generate_building_context.py",
        "input_files": "input/<id>_capabilities.ttl; input/<id>_context.ttl",
        "acceptance_criteria": "Each authored amenity answers on the building that declares it, and only there.",
        "verify": "generate_building_context.py --probe on every building.",
        "notes": "AMENITY-INVENTORY + ROOM-EQUIPMENT + AUTHORING buckets, ~20 rows.",
    },
    {
        "turn": "V6-T77",
        "title": "Asset register and built-fabric records",
        "depends_on": "V6-T75",
        "effort": "L",
        "objective": (
            "A source for the physical building itself: roof and plant ages, end-of-life dates, "
            "U-values, ceiling heights, service-entrance limits, anchor points, buried services, "
            "finishes and paint specs."
        ),
        "why": (
            "~16 questions ask about the fabric rather than about readings. Brick models systems "
            "and spaces, not asset age or a curtain-wall U-value. Nothing in the current model can "
            "answer them, and no amount of routing will change that."
        ),
        "alternatives_rejected": (
            "Stretching Brick to carry asset-management data — rejected: it is the wrong ontology "
            "for it, and BUG-179 established this project does not invent terms in Brick's "
            "namespace. Declare OntoSage terms or onboard an asset register as a datasource."
        ),
        "building_agnostic_how": "A datasource registered like any other, or OCBV terms in the shared TBox.",
        "key_steps": (
            "1) Decide: OCBV terms, or an external asset register as a datasource. "
            "2) Model the minimum that answers the 16. "
            "3) Author for the synthetic buildings; for bldg1 use only records the owner supplies."
        ),
        "files": "ontology/ontosage_schema.ttl; input/database_registry.yaml",
        "input_files": "input/<id>_assets.ttl (new)",
        "acceptance_criteria": "The 16 fabric questions answer, or decline naming the absent register.",
        "verify": "Re-ask the 16.",
        "notes": "Largest genuinely-new-data item. Consider deferring behind T70-T74.",
    },
    {
        "turn": "V6-T78",
        "title": "Energy, cost and contract source",
        "depends_on": "",
        "effort": "L",
        "objective": (
            "Onboard tariffs, invoices and contracted capacity so the ~15 energy and cost questions "
            "can be answered or honestly refused with a named gap."
        ),
        "why": (
            "'How much did it cost to run this building last month?', 'Reconcile the last 12 "
            "electricity invoices against metered consumption', 'Are we hitting our contracted "
            "maximum demand?' The submeter data EXISTS; money does not. Half of these become "
            "answerable the moment a tariff is registered."
        ),
        "alternatives_rejected": (
            "Estimating cost from consumption and a hardcoded unit rate — rejected: an invented "
            "tariff produces a confident wrong number, which is the failure mode this project "
            "guards against hardest."
        ),
        "building_agnostic_how": "A registered datasource plus recipe entries; no building literals.",
        "key_steps": (
            "1) Register a tariff/invoice source. "
            "2) Recipes for cost-from-consumption, invoice reconciliation, demand headroom. "
            "3) Anything still unsourced declines naming the missing source."
        ),
        "files": "input/database_registry.yaml; config/recipes.yaml; services/recipe_registry.py",
        "input_files": "input/<id>_tariff.* (new)",
        "acceptance_criteria": "Cost questions answer with a cited tariff, or name the missing source.",
        "verify": "Re-ask the DATA-COST rows.",
        "notes": "Check against the paper's claims before promising invoice reconciliation.",
    },
    {
        "turn": "V6-T79",
        "title": "Executive summary and narrative reporting",
        "depends_on": "V6-T74",
        "effort": "M",
        "objective": (
            "Answer 'one slide: how is the building performing this quarter?', 'in one line, how "
            "is the building doing?', 'what grades would you give?' from data the system already "
            "holds."
        ),
        "why": (
            "~6 questions ask for a synthesis rather than a fact. Every input exists — coverage, "
            "anomalies, comfort, energy — but nothing composes them. This is the shape a director "
            "or board member actually asks in, and the survey corpus has several."
        ),
        "alternatives_rejected": (
            "Letting the LLM free-narrate a summary — rejected: it would produce confident prose "
            "over unverified aggregates. The summary must be assembled from evidence-bearing "
            "results, each traceable."
        ),
        "building_agnostic_how": "Composes existing lanes; nothing building-specific.",
        "key_steps": (
            "1) Define the KPI set from what the building actually measures. "
            "2) Compose per-pillar results with their evidence records. "
            "3) Render short, and refuse to grade what was not measured."
        ),
        "files": "workflow/_orchestrator.py; services/goal_planner.py",
        "input_files": "",
        "acceptance_criteria": "Every number in the summary traces to an evidence record.",
        "verify": "Ask the six; check each figure against its source.",
        "notes": "Depends on T74 so the summary can cite provenance rather than assert.",
    },
    {
        "turn": "V6-T80",
        "title": "Scenario and what-if questions — decide the scope, then hold it",
        "depends_on": "",
        "effort": "S",
        "objective": (
            "Decide explicitly whether OntoSage answers 'if power fails, how long do the lab "
            "freezers stay safe?' — and make the answer consistent either way."
        ),
        "why": (
            "~7 questions ask for simulation of a state the building has never been in. The system "
            "has no thermal model and no failure model. Today they get a generic decline, which "
            "reads as 'no data' when the truth is 'this system does not do that'."
        ),
        "alternatives_rejected": (
            "Answering from the LLM's physical intuition — rejected absolutely. A confident "
            "freezer-safety estimate with no model behind it is the most dangerous class of answer "
            "this system could produce."
        ),
        "building_agnostic_how": "A capability boundary, not a per-building fact.",
        "key_steps": (
            "1) Decide the boundary WITH the user. "
            "2) Make the decline name the boundary: what it would take, what is held instead. "
            "3) Where a bounded answer IS defensible (rate of change from history), say so and "
            "show the evidence."
        ),
        "files": "services/grounding_guard.py; agents/capability_agent.py",
        "input_files": "",
        "acceptance_criteria": "Scenario questions decline consistently, naming the boundary.",
        "verify": "Ask the seven; no two decline in different terms.",
        "notes": "DECISION NEEDED FROM THE USER on where the boundary sits.",
    },
    {
        "turn": "V6-T81",
        "title": "Re-ask all 243 and measure what actually moved",
        "depends_on": "V6-T70,V6-T71,V6-T72,V6-T73,V6-T74,V6-T75,V6-T76,V6-T77,V6-T78,V6-T79,V6-T80",
        "effort": "M",
        "objective": (
            "Re-capture the full 1,580-question bank, run the regression gate against "
            "baseline_20260828_185823, and rebuild the worklist to see which rows cleared."
        ),
        "why": (
            "The point of the whole workstream. Without the re-measure, every task above is a "
            "claim. The baseline and the gate exist precisely so improvement can be shown rather "
            "than asserted — and so that a fix which improved one question while breaking another "
            "is caught."
        ),
        "alternatives_rejected": (
            "Re-asking only the 243 — rejected. A change that fixes 40 declines and breaks 15 "
            "working answers would look like a win. The gate needs the whole bank."
        ),
        "building_agnostic_how": "Same harness, any building.",
        "key_steps": (
            "1) capture_golden_baseline.py (full 1,580, ~10h). "
            "2) baseline_regression_gate.py --current <new> — regressions must be ZERO. "
            "3) build_unanswered_worklist.py --capture <new> — compare the counts. "
            "4) Update docs/V6_Implementation_QA.md with before/after."
        ),
        "files": "scripts/capture_golden_baseline.py; baseline_regression_gate.py; build_unanswered_worklist.py",
        "input_files": "",
        "acceptance_criteria": (
            "Zero regressions. The 243 falls, and every row that did NOT clear has a named reason."
        ),
        "verify": "The gate's own report, plus the rebuilt worklist beside the old one.",
        "notes": "Run on bldg1 for comparability with the 2026-08-28 baseline.",
    },
]


def main() -> int:
    if not TRACKER.is_file():
        print(f"tracker not found: {TRACKER}")
        return 1

    existing = list(csv.DictReader(TRACKER.open(encoding="utf-8")))
    have = {r.get("turn") for r in existing}
    new = [r for r in ROWS if r["turn"] not in have]
    if not new:
        print("all rows already present — nothing appended")
        return 0

    with TRACKER.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        for r in new:
            w.writerow({**{k: "" for k in FIELDS}, **r, "phase": PHASE, "status": "todo"})

    print(f"appended {len(new)} rows to {TRACKER.relative_to(REPO)}")
    for r in new:
        print(f"  {r['turn']}  [{r['effort']}]  {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
