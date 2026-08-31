# -*- coding: utf-8 -*-
"""Generate the V7 tracker from the catalogue demand analysis.

Written as a generator rather than a hand-edited CSV so every question count in the
tracker traces to `docs/V7_question_demand.csv` and `source_system_readiness.py` and can
be recomputed when either moves. Re-running overwrites the task rows and PRESERVES the
status/notes columns of any task already present, so progress is never lost to a
regeneration.

    python scripts/build_v7_tracker.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "tasks" / "V7_TRACKER.csv"
TRACKED = REPO / "docs" / "V7_TRACKER.csv"

COLUMNS = [
    "turn",
    "phase",
    "title",
    "status",
    "depends_on",
    "effort",
    "questions_unblocked",
    "objective",
    "why",
    "alternatives_rejected",
    "building_agnostic_how",
    "key_steps",
    "files",
    "acceptance_criteria",
    "verify",
    "notes",
]

AGNOSTIC_DEFAULT = (
    "No building literal. Behaviour comes from the active building's TTL, its registered "
    "datasources and its input/ files; a second building gets the same result by supplying "
    "the same artefacts, with no code change."
)

TASKS: List[Dict[str, str]] = [
    # ================= P0 — V6 carry-over. Nothing is dropped. =====================
    dict(
        turn="V7-T01",
        phase="P0-Carryover",
        effort="M",
        depends_on="",
        questions_unblocked="",
        title="Carry the 12 P12-Unanswered tasks (V6-T70..T81) into V7",
        objective="Adopt V6-T70..T81 as V7 work with their reasoning intact, re-sequenced "
        "against the catalogue evidence rather than against the 1,580-question bank "
        "alone. Four are itemised separately because the catalogue analysis changed "
        "their shape — T70 becomes part of V7-T21 (the decline can now name a "
        "specific missing SYSTEM, not just a missing fact), T71 is V7-T23, T72 is "
        "V7-T24, T75 is subsumed by the Record Document standard in V7-T18. The "
        "other eight carry across unchanged.",
        why="Those twelve were written from 243 measured failures and none of them started. "
        "They are the only part of the backlog already grounded in observed behaviour, so "
        "they lead — and V6-T70 (make the decline specific) is now a dependency of the "
        "answerability precheck rather than a standalone improvement.",
        alternatives_rejected="Re-deriving the same tasks from the catalogues would discard "
        "the measurement that produced them. Closing them as 'superseded' "
        "would lose 243 known-failing questions.",
        key_steps="Copy the twelve rows; re-point V6-T70 at V7-T21; keep docs/V6_unanswered_worklist.csv "
        "as their evidence base.",
        files="docs/V6_PLAN_EXTENSION_UNANSWERED.md; docs/V6_unanswered_worklist.csv",
        acceptance_criteria="All twelve appear in the V7 tracker with their original objective "
        "and alternatives_rejected text.",
        verify="Diff the twelve rows against tasks/V6_TRACKER.csv phase P12-Unanswered.",
    ),
    dict(
        turn="V7-T02",
        phase="P0-Carryover",
        effort="S",
        depends_on="",
        questions_unblocked="",
        title="Close or re-scope the 7 OPEN tracker rows before new work lands",
        objective="Resolve BUG-354, BUG-355, BUG-360, CAVEAT-361, CAVEAT-362, CAVEAT-363, "
        "CAVEAT-364 — each either fixed, or re-scoped into a named V7 task with the "
        "reason recorded.",
        why="Two of these are load-bearing for V7's own measurement. CAVEAT-362 (the leak "
        "grader counts numbers, so a correctly-restricted aggregate grades LEAK) and "
        "CAVEAT-363 (16 questions exceed the pipeline timeout) both distort any score V7 "
        "reports. Measuring on top of a known-broken grader is how this project produced "
        "fictitious numbers twice before.",
        alternatives_rejected="Carrying them as background noise — they are the measurement "
        "apparatus, and this project's own history is that the apparatus "
        "was wrong more often than the system.",
        key_steps="CAVEAT-362 needs the user's decision on grader semantics; CAVEAT-364 folds "
        "into V7-T18; CAVEAT-361 folds into V7-T04; the rest are fixes.",
        files="tasks/FIX_TRACKER.csv",
        acceptance_criteria="Zero rows with Status OPEN that are not explicitly re-scoped to a "
        "V7 task id.",
        verify="python - <<'EOF' reading FIX_TRACKER.csv and asserting no OPEN row lacks a V7 ref",
    ),
    dict(
        turn="V7-T03",
        phase="P0-Carryover",
        effort="M",
        depends_on="",
        questions_unblocked="",
        title="Finish the V6 in-progress rows: advisory gates, synthetic packs, sensor ABox",
        objective="Complete V6-T55 (every gate advisory and live-verified), V6-T57/T58/T60/T61 "
        "(the institutional, service, safety and pathology data packs), V6-T63 "
        "(conformance gate) and V6-T65 (instance-level sensor metadata).",
        why="V6-T65 is a prerequisite for the catalogues' commissioning gate — 2,396 mentions "
        "of commissioning and 2,473 of calibration across the 2,960 questions all require "
        "per-instance sensor metadata that does not exist yet. V7-T13 cannot be built on "
        "an empty ABox.",
        alternatives_rejected="Starting the evidence-grammar work first — it would be written "
        "against metadata that no instance carries, and would then be "
        "untestable.",
        key_steps="Finish T65 first (it blocks T13); then the packs, which supply the ABox the "
        "conformance gate checks.",
        files="tasks/V6_TRACKER.csv",
        acceptance_criteria="No V6 row remains in_progress.",
        verify="python scripts/certify_building.py --expect bldg1 --preflight-only",
    ),
    dict(
        turn="V7-T04",
        phase="P0-Carryover",
        effort="S",
        depends_on="",
        questions_unblocked="",
        title="Eight timeseries tables stopped five days ago and pm25_data is empty",
        objective="Restore continuous rows to co2_data, contact_data, humidity_data, "
        "parking_data, plant_data, submeter_data, temperature_data and "
        "waterflow_data; seed or retire pm25_data.",
        why="Measured 2026-08-31: those eight stop at 2026-08-26 while nine others are current, "
        "and pm25_data holds zero rows. Temperature and CO2 are the two most-demanded "
        "modalities in the catalogues, and PM2.5 is named directly. A present-tense "
        "question against a five-day-stale table is either a wrong answer or a decline "
        "that misattributes the cause to capability rather than to a stopped generator.",
        alternatives_rejected="Reporting V7 coverage without fixing it — every affected "
        "question would be scored against a defect in the fixture, not "
        "in the system. This is CAVEAT-361 widened from three tables to "
        "eight.",
        building_agnostic_how="The generator already reads its uuid set from the graph and its "
        "database from env; the fix is to run it on a schedule rather "
        "than to add per-building configuration.",
        key_steps="Find what writes the fresh nine and not these eight; make the narrow-table "
        "fill a service or a scheduled job rather than a one-off script.",
        files="scripts/generate_dummy_timeseries.py; docker-compose.yml",
        acceptance_criteria="All 20 tables report a MAX(time) within one publish interval; "
        "pm25_data non-empty or removed from the registry.",
        verify="Row-count and MAX(time) per table, compared before and after.",
    ),
    # ============ P1 — the evidence grammar the catalogues actually specify ==========
    dict(
        turn="V7-T10",
        phase="P1-EvidenceGrammar",
        effort="M",
        depends_on="",
        questions_unblocked="2960",
        title="The third time: carry effective_at beside observed_at and retrieved_at",
        objective="Add effective_at to EvidenceSource and EvidenceRecord, populate it wherever "
        "a source declares one, and render all three distinctly.",
        why="Every one of the 37 catalogues states the same rule: preserve effective time, "
        "observed or approved time and retrieval time SEPARATELY. OntoSage carries two of "
        "the three. The missing one is what distinguishes a policy that takes effect next "
        "Monday from one in force now, a future-dated role change from a current "
        "entitlement, and a booking made yesterday for next week. Without it, every "
        "authoritative-record answer silently collapses 'when it applies' into 'when we "
        "read it'.",
        alternatives_rejected="Reusing observed_at for effective time — it is precisely the "
        "conflation the catalogues forbid, and it would make a "
        "future-effective record read as a current fact.",
        key_steps="Extend the models; populate from ontosage:effectiveFrom/effectiveDate which "
        "the TBox already defines; surface in the dossier and the narration.",
        files="shared/models.py; orchestrator/services/evidence/assemble.py; narration.py",
        acceptance_criteria="A question about a future-effective policy states the effective "
        "date and does not present it as current.",
        verify="Live probe against a policy with ontosage:effectiveFrom in the future.",
    ),
    dict(
        turn="V7-T11",
        phase="P1-EvidenceGrammar",
        effort="M",
        depends_on="V7-T10",
        questions_unblocked="2960",
        title="Name the accountable owner of every source",
        objective="Add owner (and its authority) to EvidenceSource, resolved from the graph, "
        "and state it whenever an answer rests on an authoritative record.",
        why="Owner is the single most frequent demand in the corpus — 13,964 occurrences across "
        "the 2,960 questions, ahead of permission (6,176) and conflict (5,437). The "
        "catalogues do not ask the building to decide; they ask it to say whose record it "
        "is and to defer to that owner. An answer that cannot name the owner cannot be "
        "acted on, because the reader does not know who to go to.",
        alternatives_rejected="Treating source_tier (authoritative/measurement/inference) as "
        "sufficient — it says what KIND of thing answered, never who is "
        "accountable for it, and deferral is addressed to a person.",
        building_agnostic_how="Owner comes from ontosage:policyOwner / responsibleRole / a new "
        "recordOwner on the source's own triples, so each building "
        "declares its own owners in TTL.",
        key_steps="TBox: ontosage:recordOwner, ontosage:owningAuthority. Resolve in assemble. "
        "Render in narration for authoritative-tier answers.",
        files="ontology/ontosage_schema.ttl; shared/models.py; evidence/assemble.py",
        acceptance_criteria="Every answer whose source_tier is authoritative names an owner or "
        "declares that none is recorded.",
        verify="Probe a compliance question; assert the owner appears in the dossier.",
    ),
    dict(
        turn="V7-T12",
        phase="P1-EvidenceGrammar",
        effort="M",
        depends_on="V7-T11",
        questions_unblocked="2960",
        title="Verification state as an axis of its own: VERIFIED / PARTIAL / CONFLICTED / UNVERIFIED",
        objective="Add a verification_state to EvidenceRecord, orthogonal to AnswerStatus, "
        "computed from the gates that ran.",
        why="The catalogues require an explicit evidence state on every answer, and it is NOT "
        "the same axis as OntoSage's six-member AnswerStatus. Status says what kind of "
        "claim this is (observed, calculated, predicted); state says how well the evidence "
        "supports it. A CALCULATED answer can be verified or conflicted, and today nothing "
        "carries that distinction: 1,224 questions demand VERIFIED, 99 CONFLICTED, 84 "
        "PARTIALLY VERIFIED.",
        alternatives_rejected="Adding members to AnswerStatus — its docstring says exactly six, "
        "and merging two axes into one enum reopens the ambiguity it "
        "exists to close. CONFLICTED is not a seventh kind of claim.",
        key_steps="Derive from gates_applied/advisory/not_evaluated plus the conflicts list; "
        "never from the model's self-assessment.",
        files="shared/models.py; evidence/assemble.py; evidence/gates.py",
        acceptance_criteria="Two sources that disagree yield CONFLICTED and both values are "
        "reported, neither averaged.",
        verify="Inject a disagreeing pair; assert CONFLICTED and both values present.",
    ),
    dict(
        turn="V7-T13",
        phase="P1-EvidenceGrammar",
        effort="L",
        depends_on="V7-T03",
        questions_unblocked="2357",
        title="The five-part commissioning gate: deployment, mapping, commissioning, permission, health",
        objective="Implement the catalogues' verification gate as five per-instance checks, "
        "and mark evidence PROPOSED until all five pass.",
        why="Every catalogue repeats it verbatim: treat sensors, mappings, models and "
        "integrations as PROPOSED until deployment, mapping, commissioning, permission and "
        "current health are independently verified. 2,357 of the 2,960 questions name "
        "sensor telemetry, and every one of them is conditioned on this gate. OntoSage "
        "checks calibration and freshness; it has no notion of a point being mapped but "
        "not commissioned, or commissioned but not permitted.",
        alternatives_rejected="Folding it into the existing calibration gate — it collapses "
        "five independent failure modes into one flag, and the remedy "
        "differs for each (a mapping error is fixed in TTL, a permission "
        "gap by governance).",
        building_agnostic_how="The five states are per-instance triples authored in the "
        "building's TTL; absent metadata reads UNKNOWN, never "
        "assumed-good.",
        key_steps="TBox terms for the five states; a gate module; PROPOSED rendering.",
        files="ontology/ontosage_schema.ttl; evidence/gates.py; evidence/sensor_health.py",
        acceptance_criteria="A point with no commissioning record answers as PROPOSED and says "
        "which of the five is missing.",
        verify="Author one uncommissioned point; probe it.",
    ),
    dict(
        turn="V7-T14",
        phase="P1-EvidenceGrammar",
        effort="M",
        depends_on="V7-T11",
        questions_unblocked="1646",
        title="Owner-defined staleness thresholds per source class",
        objective="Let each source class declare its currency threshold in TTL and flag records "
        "beyond it, instead of applying one freshness rule to everything.",
        why="1,646 mentions of staleness, and the catalogues are explicit that currency is "
        "decision-specific: a CO2 reading is stale in minutes, an asbestos survey in "
        "years, a role change the moment it is superseded. A single global freshness gate "
        "either declares a valid survey stale or lets an hours-old sensor value pass as "
        "current.",
        alternatives_rejected="A per-modality constant in code — it is a building literal by "
        "another name, and the threshold belongs to the record's owner.",
        building_agnostic_how="ontosage:currencyThresholdDays on the class or the instance; the "
        "gate reads it from the graph.",
        key_steps="TBox term; extend the freshness gate to consult it; default to UNKNOWN "
        "rather than to a hard-coded window.",
        files="ontology/ontosage_schema.ttl; evidence/gates.py",
        acceptance_criteria="A two-year-old asbestos survey is current; a two-hour-old CO2 "
        "reading is stale.",
        verify="Probe both.",
    ),
    dict(
        turn="V7-T15",
        phase="P1-EvidenceGrammar",
        effort="S",
        depends_on="",
        questions_unblocked="725",
        title="The floor plan is a historical spatial reference, and must say so",
        objective="Carry a survey date and an authority on every floor-plan manifest, and label "
        "geometry answers as historical reference when the plan predates the "
        "building's current configuration.",
        why="725 occurrences of 'the May 2021 floor plan is historical spatial reference only' "
        "— the catalogues single it out more often than most sensors. bldg1's plans carry "
        "no date at all, so a room's area is presented with the same confidence as a live "
        "reading. The catalogues permit the plan for historical geometry and forbid "
        "inferring current room use from it.",
        alternatives_rejected="Hard-coding 'May 2021' — it is a bldg1 literal. The date belongs "
        "in the manifest, so bldg2's own survey date travels with it.",
        building_agnostic_how="survey_date and authority on the FloorPlanManifest, authored per "
        "building; the label is derived, not assumed.",
        key_steps="Extend the manifest; set spatial answers' source_tier and add the caveat.",
        files="shared/models.py; services/floor_plan_registry.py; evidence/spatial_facts.py",
        acceptance_criteria="An area answer states the plan's survey date; a current-use "
        "question is not answered from the plan alone.",
        verify="Probe 'how big is 2.15' and 'what is 2.15 used for'.",
    ),
    dict(
        turn="V7-T16",
        phase="P1-EvidenceGrammar",
        effort="M",
        depends_on="V7-T11",
        questions_unblocked="1012",
        title="Purpose-bound permission, not just role",
        objective="Carry the declared purpose of a request through the PDP so person-level "
        "detail is released only for a verified purpose within an authorised case.",
        why="The catalogues separate role from purpose everywhere: 'person-level detail is "
        "limited to the approved case', 'use person-level records only for a verified "
        "purpose and authorised role'. OntoSage gates on role alone, so a facility manager "
        "with a legitimate role has the same access for an idle question as for an "
        "investigation. 1,012 questions state a purpose constraint.",
        alternatives_rejected="Adding more roles — purpose is orthogonal to role and "
        "multiplying roles to encode it produces a combinatorial matrix "
        "nobody can administer.",
        key_steps="Purpose on the request; PDP consults it; default is the least-detail tier.",
        files="orchestrator/services/evidence/permission_guard.py; access_tiers.py",
        acceptance_criteria="The same role gets aggregate detail without a declared purpose and "
        "case detail with one.",
        verify="Probe the same question with and without a purpose.",
    ),
    dict(
        turn="V7-T17",
        phase="P1-EvidenceGrammar",
        effort="S",
        depends_on="V7-T11",
        questions_unblocked="3357",
        title="Record version and transformation lineage on every source",
        objective="Carry record/version id and the transformation path on EvidenceSource.",
        why="3,357 mentions of version and 1,372 of lineage. The catalogues require an answer "
        "to be reproducible against the exact record version it used, and to say what was "
        "done to the raw value. Without it a superseded record and its replacement are "
        "indistinguishable in the dossier.",
        alternatives_rejected="Relying on retrieved_at as a proxy for version — two retrievals "
        "of different versions can share a timestamp window.",
        key_steps="Fields on EvidenceSource; populate from ontosage:recordVersion; render.",
        files="shared/models.py; evidence/assemble.py",
        acceptance_criteria="The dossier names the version of each authoritative record used.",
        verify="Probe a policy question; assert the version appears.",
    ),
    # ============ P2 — the document standard: prose becomes queryable data ==========
    dict(
        turn="V7-T18",
        phase="P2-DocumentStandard",
        effort="L",
        depends_on="",
        questions_unblocked="703",
        title="The Record Document standard: front-matter plus typed tables, lifted to RDF",
        objective="Define and implement a document convention — YAML front-matter declaring "
        "record_type, owner, authority, effective_from, version, review_due, "
        "source_system and simulated; body tables whose columns are declared — and "
        "lift both into the graph at ingest.",
        why="This is the difference between PROSE and DATA, and it caps 703 of the 2,960 "
        "questions today. bldg1 holds a permit register and a booking log as Markdown: the "
        "document lane can quote them and cannot compute over them. 'Which permits are "
        "open?' and 'which outlets are overdue?' need rows, not passages. Contract 2 says "
        "a fact that can be a triple belongs in the ontology — so the document must BECOME "
        "triples rather than remain a thing to search.",
        alternatives_rejected="Extracting facts from free prose with the LLM at query time — it "
        "is the fabrication path this project guards against hardest, and "
        "it re-extracts on every question. Requiring a hand-written "
        "companion TTL per document — double authoring, and it drifts. "
        "Widening the retrieval lane to 'answer better' — it cannot "
        "aggregate, and CAVEAT-364 shows it currently pastes the passage "
        "instead of answering.",
        building_agnostic_how="One mapping file per record_type ships with the ontology, not "
        "with the building. A second building drops a document of the "
        "same shape and gets the same triples with no code change — "
        "which is contract 8 applied to documents.",
        key_steps="Define the front-matter schema; a lifting mapping per record_type; SHACL "
        "validate before insert; write into a per-document named graph so a "
        "re-ingest replaces cleanly; mark provenance as document-derived.",
        files="orchestrator/services/document_indexer.py; ontology/record_documents/*.yaml; "
        "ontology/ontosage_schema.ttl; docs/RECORD_DOCUMENT_STANDARD.md",
        acceptance_criteria="A permit register document produces queryable Permit instances; "
        "'which permits are open' answers by SPARQL COUNT, not by quoting.",
        verify="Re-ingest input/documents/permit_to_work_register.md; SPARQL the instances; "
        "probe the aggregate question.",
    ),
    dict(
        turn="V7-T19",
        phase="P2-DocumentStandard",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="703",
        title="Lifted facts carry their provenance and never outrank an authored source",
        objective="Mark every lifted triple with the document, its version and the mapping that "
        "produced it, and place document-derived facts below authored TTL in "
        "precedence.",
        why="A document is a statement about a system of record, not the record itself. Lifting "
        "makes it queryable; it must not make it authoritative. Without an explicit tier, "
        "a stale Markdown table would silently outrank a live register, which is the exact "
        "shadowing defect BUG-194 was.",
        alternatives_rejected="Treating lifted facts as equal to authored triples — it removes "
        "the reader's ability to tell a register from a note about one.",
        key_steps="Named graph per document; ontosage:derivedFromDocument; precedence tier.",
        files="services/document_indexer.py; evidence/precedence.py",
        acceptance_criteria="A conflict between a lifted fact and an authored triple reports "
        "both, authored leading.",
        verify="Author a contradicting triple; probe; assert both appear.",
    ),
    dict(
        turn="V7-T20",
        phase="P2-DocumentStandard",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="163",
        title="The document lane answers the question instead of pasting the passage",
        objective="Make the document lane compose an answer from the retrieved passage, "
        "attributed and bounded, rather than returning the passage.",
        why="MEASURED on the 111-question stakeholder probe, and far larger than CAVEAT-364 "
        "recorded: 38 of the 56 answers graded 'answered-with-data' (68%) are this lane "
        "pasting a passage, and reading them, they frequently do not address the question at "
        "all. 'Which plant can be installed, commissioned and replaced through a credible "
        "route' returned the ASBESTOS REGISTER. 'Which valves have accumulated questionable "
        "behaviour' returned the helpdesk phone number. 'Which cleaning defects keep "
        "recurring' returned the cleaning SCHEDULE. Fifteen stakeholder roles have their "
        "ENTIRE answered score made of such pastes. This is the single largest contributor to "
        "the apparent coverage figure and it is not coverage.",
        alternatives_rejected="Raising the retrieval threshold — it reduces wrong passages "
        "without making a right passage into an answer, and the failure "
        "here is relevance, not confidence. Leaving it to V7-T18 — lifting "
        "registers removes the aggregate questions but not the prose ones.",
        key_steps="Require the passage to ANSWER, not merely to match: compose from it and "
        "decline when it contains no answer. Cite the document and its effective date.",
        files="orchestrator/agents/capability_agent.py",
        acceptance_criteria="A document-answered question reads as an answer and cites the "
        "document and date.",
        verify="Probe five document questions from the worklist.",
    ),
    # ============ P3 — answerability decided before routing, not guessed ============
    dict(
        turn="V7-T21",
        phase="P3-Answerability",
        effort="L",
        depends_on="V7-T13",
        questions_unblocked="1097",
        title="Answerability precheck: resolve referent, required sources and readiness before routing",
        objective="Before a lane is chosen, resolve (a) the referent, (b) the source systems "
        "the question requires, (c) whether this building holds them — then route to "
        "a lane that can succeed, or decline naming the missing system and the step "
        "that would supply it.",
        why="This is the replacement for keyword guessing, and it is what makes a decline "
        "useful. Today 180 declines share one sentence and all route to the catch-all, so "
        "180 distinct gaps look like one problem. The readiness of a source system is a "
        "DECIDABLE fact — measured live by source_system_readiness.py — not a guess about "
        "the question's wording. A question needing a permit register can be answered, or "
        "declined with 'this building has no permit register as data; it holds one as a "
        "document', which is actionable.",
        alternatives_rejected="More routing rules in routing_contract.py — 17 ordered rules "
        "already, and each new one trades one wrong lane for another "
        "without ever telling the user what is missing. Classifying "
        "questions with the LLM alone — it would guess a source system "
        "the building may not hold and produce a confident wrong route.",
        building_agnostic_how="Readiness is probed from the active building's own graph, "
        "databases, feeds and documents. The same precheck yields "
        "different routes on bldg2 because bldg2 holds different systems.",
        key_steps="Reuse source_system_readiness as a cached service; map question to required "
        "systems via the concept resolver and the ontology, not keywords; feed the "
        "verdict to V6-T70's specific decline.",
        files="orchestrator/services/answerability.py (new); services/routing_contract.py; "
        "scripts/source_system_readiness.py",
        acceptance_criteria="Two questions declining for different missing systems produce two "
        "different sentences, each naming its system and remedy.",
        verify="Probe one question per ABSENT system; assert distinct, correct declines.",
    ),
    dict(
        turn="V7-T22",
        phase="P3-Answerability",
        effort="M",
        depends_on="V7-T21",
        questions_unblocked="2960",
        title="Declare the operation, and check the lane can perform it",
        objective="Classify each question into the seven-member Operation taxonomy and refuse a "
        "lane that cannot perform the declared operation.",
        why="The catalogues label every question with its operation — comparison 1,486, lookup "
        "1,215, observation 1,153, recommendation 1,098, calculation 846, estimate 832, "
        "forecast 714, diagnosis 577 — so the bank carries 2,960 labelled examples. That is "
        "a supervised signal, not a heuristic, and a forecast question routed to a lookup "
        "lane returns a current value dressed as a prediction. It also exposes a gap: the "
        "Operation enum's docstring says its seven members came from 'all six catalogues' — "
        "six of thirty-seven — and the 31 unread ones make COMPARISON the most frequent "
        "operation in the corpus, with no member. It survives only as comparison_baseline, "
        "an attribute of a record rather than an act, so a comparison is currently labelled "
        "as whatever computed it, and the catalogues' 'compare like versions and like "
        "periods' boundary is checked by nothing.",
        alternatives_rejected="Inferring operation from the answer after the fact — too late to "
        "route, and it lets the lane define what the question was. Mapping "
        "comparison onto CALCULATION — it is how the gap arose, and it "
        "erases the like-for-like constraint that makes a comparison valid.",
        key_steps="Add COMPARISON to the Operation enum with its like-for-like check; extract the "
        "operation label from Analysis_Required into the bank; use it as the routing "
        "test set; assert lane capability.",
        files="orchestrator/services/routing_contract.py; tasks/smart_building_questions.csv",
        acceptance_criteria="Routing accuracy measured against 2,960 declared operations, "
        "reported per operation.",
        verify="Offline scoring run over the bank.",
    ),
    dict(
        turn="V7-T23",
        phase="P3-Answerability",
        effort="M",
        depends_on="V7-T21",
        questions_unblocked="29",
        title="The spatial lane raises an error instead of answering or declining (V6-T71)",
        objective="Make every spatial failure either an answer or a named decline.",
        why="29 measured questions end in an exception. An error hides which component failed "
        "and cannot be triaged by the person reading it.",
        alternatives_rejected="Catching and returning the generic decline — it loses the "
        "diagnosis the exception carried.",
        key_steps="Carried from V6-T71.",
        files="orchestrator/agents/spatial_agent.py",
        acceptance_criteria="Zero SPATIAL_ERROR rows on re-ask.",
        verify="Re-ask the 29.",
    ),
    dict(
        turn="V7-T24",
        phase="P3-Answerability",
        effort="M",
        depends_on="V7-T21",
        questions_unblocked="16",
        title="Breadth questions cost more than the timeout allows (V6-T72, CAVEAT-363)",
        objective="Aggregate in SQL before fetching, bound the candidate set, then raise the "
        "timeout and re-measure.",
        why="16 of 1,580 cannot finish in 150 s. Raising the timeout alone admits them while "
        "making the user wait minutes and moves the ceiling rather than the cost — the "
        "sql_agent currently coarsens AFTER fetching, which is the expensive half.",
        alternatives_rejected="Dropping the 16 from the bank — 1.0% unanswerable by COST rather "
        "than by capability is a finding worth reporting.",
        key_steps="Carried from V6-T72.",
        files="orchestrator/agents/sql_agent.py",
        acceptance_criteria="All 16 answer within the new budget; p99 does not regress.",
        verify="Re-ask the 16; compare p50/p99.",
    ),
    # ============ P4 — onboard the missing systems, biggest blocker first ===========
    dict(
        turn="V7-T30",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="543",
        title="Bookings as data, not as a Markdown log",
        objective="Author ontosage:Booking instances (room, period, organiser role, status, "
        "effective/observed times) via the Record Document standard, and register the "
        "booking source.",
        why="The single largest blocker: 543 questions are capped at PROSE by bookings alone. "
        "The class already exists in the TBox with zero instances, and precedence.py "
        "already names bookings as the authoritative source for availability — the "
        "machinery is built and has nothing to read. 'A room with nobody in it is not an "
        "available room' is unenforceable while the booking register is prose.",
        alternatives_rejected="Inferring occupancy from sensors — precedence.py exists "
        "specifically to forbid it, and the catalogues repeat that "
        "telemetry cannot override the booking system.",
        building_agnostic_how="A booking record document with the declared shape; bldg2 supplies "
        "its own and needs no code.",
        key_steps="Mapping for record_type: booking; convert input/documents/room_bookings.md; "
        "backdated and forward-dated entries so effective_at is exercised.",
        files="ontology/record_documents/booking.yaml; input/documents/room_bookings.md",
        acceptance_criteria="'Is 2.15 free at 14:00 Thursday' answers from the register; a "
        "sensor disagreement is reported, not resolved.",
        verify="Probe availability, turnaround and no-show questions.",
    ),
    dict(
        turn="V7-T31",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="413",
        title="Contracts, warranties and service levels",
        objective="Add ontosage:Contract / Warranty / ServiceLevel with scope, dates, provider, "
        "obligations, and author bldg1's set as synthetic records.",
        why="413 questions blocked, and 23 of the 37 roles touch it — the second-largest gap. "
        "Warranty status changes the correct answer to a maintenance question ('is this "
        "chargeable?'), and no amount of routing recovers it.",
        alternatives_rejected="Folding warranties into the asset register — they have their own "
        "owner, dates and precedence and are frequently in conflict with "
        "it, which is itself an answer the catalogues want reported.",
        key_steps="TBox terms; record document; synthetic backdated set with expiries either "
        "side of today.",
        files="ontology/ontosage_schema.ttl; input/documents/contracts_and_warranties.md",
        acceptance_criteria="'Is the AHU still under warranty' answers with dates and provider.",
        verify="Probe five contract questions.",
    ),
    dict(
        turn="V7-T32",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="257",
        title="Project handover, as-built and O&M records",
        objective="Add ontosage:HandoverRecord and link commissioning records, as-built "
        "revisions and O&M manuals to the assets they describe.",
        why="257 questions. It is also the source the commissioning gate (V7-T13) reads from: "
        "'commissioned' is a claim that must rest on a handover record, not on a flag "
        "somebody set.",
        alternatives_rejected="A flat document folder — it cannot answer 'which assets have no "
        "handover record', which is the question actually asked.",
        key_steps="TBox; record document; link to brick:Equipment instances.",
        files="ontology/ontosage_schema.ttl; input/documents/handover_register.md",
        acceptance_criteria="'Which plant has no O&M manual' returns a computed list.",
        verify="SPARQL the complement; probe the question.",
    ),
    dict(
        turn="V7-T33",
        phase="P4-SourceOnboarding",
        effort="S",
        depends_on="V7-T18",
        questions_unblocked="160",
        title="Permits to work as data",
        objective="Lift the existing permit register document into ontosage:Permit instances.",
        why="160 questions, and the document already exists — this is the cheapest PROSE-to-DATA "
        "conversion in the plan and the best test of the standard, because the register is "
        "already tabular.",
        alternatives_rejected="Leaving it as prose — 'which permits are open in this zone' "
        "cannot be answered by retrieval.",
        key_steps="record_type: permit; map the existing table.",
        files="ontology/record_documents/permit.yaml; input/documents/permit_to_work_register.md",
        acceptance_criteria="Open-permit counts by zone answer by SPARQL.",
        verify="Probe; compare against the document by hand once.",
    ),
    dict(
        turn="V7-T34",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="119",
        title="Energy cost: a registered tariff source, never a constant",
        objective="Add ontosage:Tariff with rate, standing charge, validity window and "
        "authority; compute cost only when one is registered.",
        why="119 questions. Submeter data exists and money does not, so cost questions decline "
        "today — correctly. The danger is the obvious shortcut: an invented unit rate "
        "produces a confident wrong number, which is the failure mode this project guards "
        "against hardest.",
        alternatives_rejected="A default tariff constant in config — a building literal AND a "
        "fabrication. Either a tariff is registered or the question "
        "declines naming it.",
        key_steps="TBox; record document; cost recipe reads the tariff or declines.",
        files="ontology/ontosage_schema.ttl; config/recipes.yaml",
        acceptance_criteria="With no tariff the answer declines naming it; with one it computes "
        "and cites rate, window and authority.",
        verify="Probe both states.",
    ),
    dict(
        turn="V7-T35",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T16",
        questions_unblocked="103",
        title="Identity and affiliation: the minimum that answers, and nothing more",
        objective="Model roles, affiliations and entitlements at the level the questions "
        "actually need — never person records.",
        why="103 questions, and the most privacy-sensitive gap in the plan. The catalogues are "
        "emphatic in both directions: they ask about entitlements and prerequisites, and "
        "they forbid exposing protected person or credential records beyond an authorised "
        "case. The answerable form is 'this role requires these prerequisites', not 'this "
        "person holds this credential'.",
        alternatives_rejected="Importing a person directory — it would create the exact "
        "disclosure surface the catalogues prohibit, for questions that "
        "do not need it.",
        building_agnostic_how="Role and entitlement classes; no personal data in any building's "
        "TTL.",
        key_steps="Entitlement and prerequisite classes; purpose-bound access from V7-T16.",
        files="ontology/ontosage_schema.ttl; evidence/permission_guard.py",
        acceptance_criteria="Role-level questions answer; person-level questions decline citing "
        "the authorised-case rule.",
        verify="Probe both shapes.",
    ),
    dict(
        turn="V7-T36",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T18",
        questions_unblocked="99",
        title="Condition surveys and the built fabric",
        objective="Add ontosage:ConditionSurvey plus asset age, expected life and fabric "
        "attributes (U-values, ceiling heights, roof ages).",
        why="99 questions, and Brick models systems and spaces rather than asset age or fabric "
        "performance — no amount of routing reaches it. This is the clearest case in the "
        "corpus for extending the OntoSage schema rather than reusing Brick.",
        alternatives_rejected="Forcing it into brick:Equipment properties — Brick has no "
        "vocabulary for condition grade or remaining life.",
        key_steps="TBox; record document; synthetic survey with mixed grades.",
        files="ontology/ontosage_schema.ttl; input/documents/condition_survey.md",
        acceptance_criteria="'Which assets are beyond expected life' returns a computed list.",
        verify="Probe.",
    ),
    dict(
        turn="V7-T37",
        phase="P4-SourceOnboarding",
        effort="S",
        depends_on="V7-T18",
        questions_unblocked="79",
        title="Training, competency and authorisation records",
        objective="Add ontosage:CompetencyRecord at role level, linked to restricted areas and "
        "tasks.",
        why="79 questions, mostly prerequisites for access and permits — it is the missing half "
        "of both V7-T33 and V7-T35.",
        alternatives_rejected="Person-level training records, for the reason in V7-T35.",
        key_steps="TBox; record document.",
        files="ontology/ontosage_schema.ttl",
        acceptance_criteria="'What competency does this restricted area require' answers.",
        verify="Probe.",
    ),
    dict(
        turn="V7-T38",
        phase="P4-SourceOnboarding",
        effort="S",
        depends_on="V7-T18",
        questions_unblocked="27",
        title="Sustainability targets and risk assessments",
        objective="Populate ontosage:SustainabilityTarget (class exists, zero instances) and add "
        "ontosage:RiskAssessment.",
        why="21 and 6 questions — the smallest gaps, done last. SustainabilityTarget costs "
        "almost nothing because the class is already defined.",
        alternatives_rejected="Skipping them — they are cheap and they complete the source "
        "inventory, which is what the readiness report certifies.",
        key_steps="Author instances; record document for risk.",
        files="ontology/ontosage_schema.ttl; input/documents/",
        acceptance_criteria="Both report DATA in the readiness probe.",
        verify="python scripts/source_system_readiness.py",
    ),
    dict(
        turn="V7-T39",
        phase="P4-SourceOnboarding",
        effort="M",
        depends_on="V7-T24",
        questions_unblocked="",
        title="The refusal's own suggested remedy times out",
        objective="Make the coarse, aggregated form that a k-floor refusal recommends actually "
        "complete inside the request budget.",
        why="Measured live 2026-08-31. A single-room reading is refused above the k-floor with "
        "'ask the same thing across at least 14 sensors / 7 spaces — e.g. the floor average "
        "instead of one room'. Asking for the floor average then exceeds the 150 s timeout. "
        "A refusal that hands the user an impossible remedy is worse than one that stops at "
        "'no': it costs them a second wait to learn the same nothing, and it makes a correct "
        "privacy decision look like a broken system.",
        alternatives_rejected="Softening the k-floor so the single-room question answers — the "
        "floor is the privacy guarantee, and the fault is in the cost of "
        "the compliant path, not in the policy. Removing the suggestion — "
        "it is the most useful sentence in the refusal when it works.",
        key_steps="Depends on the SQL-side aggregation in V7-T24; then assert every remedy the "
        "refusal offers is itself answerable within budget.",
        files="orchestrator/agents/sql_agent.py; orchestrator/services/privacy/enforcement.py",
        acceptance_criteria="For each refusal template, the remedy it names answers within the "
        "budget; a remedy that cannot is not offered.",
        verify="Probe the refusal, then probe its own suggestion, and time both.",
    ),
    # ============ P5 — measure it, and prove nothing was lost ======================
    dict(
        turn="V7-T40",
        phase="P5-Measurement",
        effort="M",
        depends_on="",
        questions_unblocked="",
        title="The regression floor: the 1,580 golden baseline must not move backwards",
        objective="Run baseline_regression_gate against the 2026-08-28 golden baseline after "
        "every phase; zero unexplained regressions is the merge condition.",
        why="The user's constraint is explicit: extend capability WITHOUT losing what works. "
        "V6 built the gate and the baseline exactly for this, and the gate distinguishes an "
        "intended tightening (a gate fired and named itself) from a regression (the answer "
        "got worse and nothing claims responsibility). Every P1 task tightens evidence "
        "rules, so tightenings WILL occur and must be told apart from breakage.",
        alternatives_rejected="Measuring only the new corpus — it would let the catalogue work "
        "silently break the 1,580 that already pass.",
        key_steps="Gate per phase, not per task; record intended tightenings with the task id.",
        files="scripts/baseline_regression_gate.py; tasks/V6_baseline_20260828_185823.csv",
        acceptance_criteria="Zero REGRESSION rows at each phase boundary.",
        verify="python scripts/baseline_regression_gate.py --current <capture>",
    ),
    dict(
        turn="V7-T41",
        phase="P5-Measurement",
        effort="M",
        depends_on="V7-T40",
        questions_unblocked="",
        title="Extend the golden baseline to all 4,060 questions",
        objective="Capture the full bank — 1,100 v5 + 480 supervisor + 2,480 catalogue — as the "
        "V7 baseline, with the evidence record persisted per turn.",
        why="The bank is now 4,060 and only 1,580 have ever been captured. Without a baseline "
        "over the catalogue questions there is nothing to regress against, and the V7 "
        "claim 'these questions are now answerable' has no before.",
        alternatives_rejected="Sampling — a stratified sample measures the population but "
        "cannot serve as a per-question regression baseline.",
        key_steps="Budget: 1,580 took 9.9 h, so 4,060 is roughly a day; run per phase, resume "
        "supported.",
        files="scripts/corpus_replay.py; scripts/outputs/",
        acceptance_criteria="4,060 rows captured with zero invalid rows.",
        verify="Row count and quarantine count.",
    ),
    dict(
        turn="V7-T42",
        phase="P5-Measurement",
        effort="M",
        depends_on="V7-T41",
        questions_unblocked="",
        title="Per-stakeholder scorecard across all 37 roles",
        objective="Report coverage, evidence state and decline quality per role, not just in "
        "aggregate.",
        why="The roles fail differently and are fixed by different work — measured before any "
        "V7 task: Architects, External maintenance contractors and Waste-management teams "
        "are 100% blocked by an absent system, while Prospective students are 86% blocked "
        "but almost entirely at PROSE rather than ABSENT. One aggregate number hides both "
        "facts and would rank the wrong work first.",
        alternatives_rejected="A single coverage percentage — it is what the V5 and V6 "
        "scorecards reported, and it cannot tell which stakeholder is "
        "unserved.",
        key_steps="Group the capture by Stakeholder_Role; report the three-valued readiness "
        "ceiling beside measured outcome so prediction and reality can be compared.",
        files="scripts/build_v7_scorecard.py (new)",
        acceptance_criteria="A table of 37 roles with measured coverage and predicted ceiling.",
        verify="Compare predicted ceiling against measured outcome; investigate any role where "
        "measured beats predicted (the prediction is then wrong, and worth knowing).",
    ),
    dict(
        turn="V7-T43",
        phase="P5-Measurement",
        effort="S",
        depends_on="V7-T30",
        questions_unblocked="",
        title="Prove it on a second building before calling it building-agnostic",
        objective="Run the readiness probe and a role-stratified replay on bldg2 with the same "
        "record documents supplied, and no code change.",
        why="Every task here claims building-agnosticism and the claim is only worth what a "
        "second building demonstrates. This project's own history is that the source fix "
        "and the deployed fix diverge (BUG-343), and that tests passed while the lane was "
        "never invoked (BUG-237).",
        alternatives_rejected="Asserting agnosticism from code review — the failure modes above "
        "were all invisible to review.",
        key_steps="Swap to bldg2; supply its own record documents; re-run.",
        files="scripts/source_system_readiness.py; scripts/corpus_replay.py",
        acceptance_criteria="bldg2 reports its own readiness and answers its own questions with "
        "zero code diff.",
        verify="git diff --stat must be empty for orchestrator/ and shared/ across the run.",
    ),
    dict(
        turn="V7-T44",
        phase="P5-Measurement",
        effort="M",
        depends_on="",
        questions_unblocked="",
        title="Every privacy trap must run as at least two roles, in both orders",
        objective="Re-run the PROTECT trap bank with two roles per trap, asking the same "
        "question in both orders, and treat a cross-role difference as the assertion.",
        why="BUG-368 was a live cross-role disclosure — an occupant served a facility manager's "
        "room-level reading — and no test could have caught it, because every PROTECT trap "
        "runs as a SINGLE user. A certified '0.0% leak' was measured through that blind "
        "spot. A privacy property is about the DIFFERENCE between what two people see, and "
        "a one-user harness cannot observe a difference.",
        alternatives_rejected="Adding more single-user traps — more of them cannot see across "
        "users, which is where the whole class of defect lives. Auditing "
        "the code instead — the defect was a missing key component, "
        "invisible to review and obvious in one paired probe.",
        building_agnostic_how="Roles come from the building's own policy TTL, so a building that "
        "declares different roles is tested against those.",
        key_steps="Two fixture accounts per applicable role; run each trap in both orders; "
        "assert the lower-privilege answer is never a superset of its own solo answer.",
        files="scripts/certify_building.py; scripts/grade_privacy_traps.py",
        acceptance_criteria="Every trap runs at two privilege levels in both orders; the leak "
        "rate is reported per ordered pair, not per question.",
        verify="Re-run certification; confirm BUG-368's exact sequence is now a failing trap "
        "before the fix and a passing one after.",
    ),
    dict(
        turn="V7-T45",
        phase="P5-Measurement",
        effort="M",
        depends_on="",
        questions_unblocked="",
        title="Separate a computed answer from a quoted passage before any coverage number is reported",
        objective="Split the replay grader's single 'answered-with-data' outcome into "
        "computed-answer, document-quoted and refusal, and judge whether the response "
        "addresses the question rather than whether it has the shape of an answer.",
        why="MEASURED: on the 111-question probe the grader reported 55.4% data-backed, and 38 of "
        "those 56 answers were pasted passages — several of which answered a different "
        "question entirely. The honest figure is 17.8% computed. Every V7 coverage number "
        "taken from this grader would be unusable, and this is the same weak-heuristic class "
        "as BUG-191, where 'any digit means it answered' turned refusals into a spurious "
        "39/39.",
        alternatives_rejected="Grading a quote as a failure — for a genuinely prose question a "
        "quote with its source IS the right answer. The defect is summing "
        "it with computed answers into one figure, not the quoting.",
        key_steps="Three outcomes, reported separately; relevance judged against the question, "
        "not the response shape; re-score the existing captures before comparing anything.",
        files="scripts/corpus_replay.py; scripts/l7_grader.py",
        acceptance_criteria="A pasted passage that does not address the question is never "
        "counted as a computed answer; the scorecard reports all three.",
        verify="Re-score v7probe2.csv and reproduce the 18 / 38 / 38 split by hand on a sample.",
    ),
]


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Preserve progress on regeneration.
    previous: Dict[str, Dict[str, str]] = {}
    if out.is_file():
        with out.open(encoding="utf-8-sig") as fh:
            previous = {r["turn"]: r for r in csv.DictReader(fh)}

    rows: List[Dict[str, str]] = []
    for task in TASKS:
        row = {c: "" for c in COLUMNS}
        row.update(task)
        row.setdefault("status", "")
        old = previous.get(task["turn"], {})
        row["status"] = old.get("status") or "todo"
        row["notes"] = old.get("notes") or task.get("notes", "")
        if not row["building_agnostic_how"]:
            row["building_agnostic_how"] = AGNOSTIC_DEFAULT
        rows.append(row)

    for target in (out, TRACKED):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    phases: Dict[str, int] = {}
    for row in rows:
        phases[row["phase"]] = phases.get(row["phase"], 0) + 1
    print(f"{len(rows)} tasks written to {out.relative_to(REPO)} and {TRACKED.relative_to(REPO)}")
    for phase in sorted(phases):
        print(f"  {phase:<24}{phases[phase]:>3}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
