# -*- coding: utf-8 -*-
"""The six-bucket stakeholder answer grader (scripts/grade_stakeholder_answers.py).

EVERY FIXTURE IS A REAL ANSWER. They are copied verbatim (or, where marked, as a verbatim
excerpt) from the 2026-09-15 stakeholder runs (scripts/outputs/stakeholder_run{1,2,3}_*.md.jsonl,
cited as R<run>-<row>) and from the 2026-09-17 Phase 0 baseline (docs/phase0/, cited as P-<row>).
Those files are gitignored, so the text lives here. A grader test written against imagined
answers measures the imagination (tests/test_grader_does_not_mistake_hedging_for_a_decline.py).

What these pin, beyond one fixture per bucket:
* an honest decline is NOT a failure -- including when the catalogue boundary says refuse;
* the precedence between buckets (add-data beats a decline; a weak remediation footer does not
  beat a non-answer template);
* a digit is never evidence of an answer (lessons #20-22, BUG-191);
* the report reader and the CLI, through the real entry point (lessons #21).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "grade_stakeholder_answers.py"


def _load():
    spec = importlib.util.spec_from_file_location("_grade_stakeholder_answers", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_grade_stakeholder_answers"] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load()

# ── real answers ─────────────────────────────────────────────────────────────────────────

# R3-6
Q_WASTE = (
    "Where is the current approved collection point for batteries, WEEE, sharps or other "
    "special waste I may encounter?"
)
A_WASTE = (
    "The building’s records show three collection points that are relevant to batteries, WEEE, "
    "sharps or other special waste:\n\n**Batteries & WEEE**  \n• **Waste compound and bin store** "
    "– *WCP‑017*  \n  - Status: **active** (next collection 25 Sep 2026)  \n  - Aperture: "
    "Restricted opening, 60 L capacity, 25 % full  \n\n**Sharps (clinical)**  \n• **Room 2.01 – "
    "Research Laboratory** – *WCP‑023*  \n  - Status: **active** (next collection 18 Sep 2026)  \n"
    "  - Aperture: Restricted opening, 20 L capacity, 55 % full  \n\n• **Room 3.01 – Research "
    "Laboratory** – *WCP‑024*  \n  - Status: **overdue** (missed collection 18 Aug 2026, next due "
    "18 Sep 2026)  \n  - Aperture: Restricted opening, 20 L capacity, 40 % full  \n\n**Summary**  \n"
    "- 1 active point for batteries/WEEE  \n- 1 active point for sharps  \n- 1 overdue point for "
    "sharps (still a collection location but the scheduled collection is past due)  \n\nThese are "
    "the only approved collection points for the special waste types you asked about.\n\n---\n"
    "**You might also ask:** Who owns these records? | Which of these are on floor 3? | Show the "
    "full register?"
)

# R2-19
Q_CHANGING_PLACES = (
    "Is a Changing Places toilet available in or near Abacws, and what are the current verified "
    "access arrangements?"
)
A_CHANGING_PLACES = (
    "The records do not indicate the presence of a Changing Places toilet in or near Abacws. They "
    "only contain information about access permission groups, including each group’s status, "
    "effective dates, owners, and the openings they control.\n\n---\n**You might also ask:** Show "
    "current readings for these sensors? | Compare zones? | Generate a report?"
)

# R2-57
Q_BADGE = "Can my manager see when I badge in and out?"
A_PRIVACY = (
    "**I can't answer that.** The system explains the building; it never tracks individuals. "
    "Denied for every role; aggregate alternatives are offered.\n\nYou can instead:\n- ask for room "
    "or floor level counts and conditions (never individuals)\n- ask about spaces you are assigned "
    "to, at full detail\n\n_Policy: `policy_inference_individual_pattern`._"
)

# P-40 and its catalogue boundary (FS-077, as stored in docs/phase0/phase0_bank.jsonl)
Q_INCIDENT_MESSAGES = (
    "Which approved incident messages were sent, by which channel and at what time, and what "
    "delivery or acknowledgement evidence exists?"
)
A_INCIDENT_MESSAGES = (
    "The records do not contain any information about approved incident messages, the channels "
    "they were sent on, the times they were sent, or any delivery or acknowledgement evidence.\n\n"
    "---\n**You might also ask:** Who owns these records? | Which of these are on floor 3? | Show "
    "the full register?"
)
B_FS077 = (
    "Do not compose, send, repeat or modify incident messages, issue evacuation commands, infer "
    "understanding or contact recipients. Do not expose recipient identities, phone numbers, radio "
    "channels or message content beyond authorised roles. Do not disclose personal emergency "
    "evacuation plans, identitie"
)

# P-1 and its boundary (AO-031)
Q_DESK = "Is this shared desk officially available to me now, or does it only appear unoccupied?"
A_DESK = (
    "The records do not contain any information about shared desk availability. They record "
    "operating regimes for HVAC and lighting systems in the building.\n\n---\n**You might also "
    "ask:** Who owns these records? | Which of these are on floor 3? | Show the full register?"
)
B_AO031 = (
    "Do not identify the current user, disclose reservation details or grant use. If eligibility, "
    "permission, room or served-zone coverage, calibration/health, time alignment or comparator "
    "evidence is missing, stale or conflicting, ask for clarification, return confirmed facts only "
    "or mark the result not"
)

# R2-40
Q_CAPITAL = "Which capital project this year had the best measured outcome?"
A_NOT_ON_RECORD = (
    "I don't have that specific information on record for **Abacws Building**. For "
    "building-specific queries please contact your building's facilities / estates management "
    "team."
)
A_CAPITAL = (
    A_NOT_ON_RECORD
    + "\n\nYou can add it — no code changes needed:\n1. **Describe it in the ontology** — upload a "
    "TTL naming the entity and its relationships (Admin portal → *Ontology* → upload, or drop the "
    "`.ttl` into the active building's input folder and restart).\n2. **Point it at its readings** "
    "— give each sensor a `ref:hasExternalReference` → `ref:hasTimeseriesId` (the column/uuid) "
    "plus `ref:storedAt` (a key from `database_registry.yaml`).\n3. **Register the database** "
    "holding those rows (Admin portal → *Databases*).\nOnce both halves exist, questions about this "
    "are answered live — the pipeline needs nothing else."
)

# R3-65
Q_PREVENT = "how does building prevent this space?"
A_DOCS = (
    "**Abacws Building's documents do not answer this.** I searched Workspace Profile Register; "
    "they are the closest material and none of them contains the answer.\n\nIf the answer should "
    "be in a document, add or update it — a document carrying record-document front-matter is also "
    "lifted into queryable data on ingest. Otherwise the owner of that record holds it."
)

# R3-66, verbatim excerpt (paragraph 1, paragraph 3 and the source line)
Q_ENERGY = "can you provide energy saving suggestion?"
A_ENERGY_ADVICE = (
    "**Energy‑saving recommendations for the six‑floor building**\n\n1. **Target the floor with "
    "the highest average consumption – Floor 4**  \n   *Why:* Floor 4’s mean is 3.56 kWh, the "
    "highest of all floors (Floor 3 is 3.59, Floor 5 3.52, Floor 2 3.43, Floor 1 3.31, Floor 0 "
    "3.33).  \n   *Action:* Pull the latest kWh reading from the Floor 4 meter (currently 4 kWh) "
    "and compare it to the other floors. If the spike is due to a single large appliance or HVAC "
    "unit, schedule a maintenance check or consider a more efficient replacement. A 10 % reduction "
    "on this floor would save ~0.35 kWh per hour, translating to ~8 kWh per day.\n\n3. **Implement "
    "daylight‑sensing lighting controls on floors with high night‑time lighting**  \n   *Why:* "
    "Floors 3 and 4 have the highest night‑time averages (2.54 and 2.56 kWh). This suggests lights "
    "remain on longer than needed.  \n   *Action:* Install or enable existing daylight sensors so "
    "that lights dim or turn off when natural light is sufficient. A 20 % reduction on these floors "
    "would save ~0.5 kWh per night.\n\n---\n*Sources: `Building Ontology` `Energy Metering System · "
    "simulated`*"
)

# R1-3
Q_ROUTES = (
    "How do observed route lengths, waits and hand-offs compare with the workflow and adjacency "
    "assumptions used in the design?"
)
A_COMPARE_TEMPLATE = (
    "Comparing observed_route_lengths, observed_waits, observed_handoffs requires sensors with "
    "linked time-series data. Floor-level energy or zone comparison works best when referencing "
    "specific zone IDs — e.g. *'Compare temperature in Zone 5.01 vs Zone 5.28 last month'* or "
    "*'Which floor had higher average CO2 this week?'*  I can pull data for any sensor zone once a "
    "specific zone or sensor ID is provided.\n\n**Boundary: not declared.** I can't say what this "
    "figure covers — the meter behind it has no `ontosage:meterServes` in the ontology. Declaring "
    "the meter's boundary and allocation method would let every energy answer state it.\n\n---\n"
    "**You might also ask:** Plot the comparison? | Export results? | Check for anomalies?\n\n---\n"
    "*Sources: `Building Ontology`*"
)

# R1-59
Q_TOILETS = "Where can I isolate the water supply for the second-floor toilets?"
A_TOILETS = (
    "Here is what I found for **Abacws Building**:\n\n\n**Toilet facility — Room 0.04 — Mechanical "
    "Plant Room** — Toilet facility in Room 0.04 — Mechanical Plant Room (floor Floor0). There is a "
    "toilet facility in Room 0.04 — Mechanical Plant Room on floor Floor0.\n\n**Toilet facility — "
    "Room 1.07 — Computer Laboratory** — Toilet facility in Room 1.07 — Computer Laboratory (floor "
    "Floor1). There is a toilet facility in Room 1.07 — Computer Laboratory on floor Floor1.\n\n"
    "**Toilet facility — Room 3.02 — Research Laboratory** — Toilet facility in Room 3.02 — "
    "Research Laboratory (floor Floor3). There is a toilet facility in Room 3.02 — Research "
    "Laboratory on floor Floor3.\n\n\n*Answered live from the building ontology (triples).*"
)

# R1-55
Q_DRAINS = "Which drains have needed jetting more than twice this year?"
A_REPORT_LOGGED = (
    "✅ Thank you — your **maintenance request** has been logged as **REP-452756**.\n\n- "
    "**Category:** Maintenance request\n- **Priority:** NORMAL\n- **Status:** OPEN\n\nAn "
    "administrator has been notified and will review it. You can check progress any time by asking "
    "*\"what's the status of REP-452756\"*.\n\n📍 I couldn't tell **where** this is. If you reply "
    "with the room, floor or area, I'll attach it — that is what lets the building notice when the "
    "same problem keeps coming back in the same place.\n\n**One thing missing:** Which room, floor "
    "or piece of equipment is affected? Reply with the room, floor or equipment and I'll add it to "
    "this report — otherwise whoever picks it up won't know where to go."
)

# R2-15, verbatim excerpt (heading and first rows of the table)
Q_SERVER_ROOM = (
    "If the primary server room, communications room or core-network area is unavailable, which "
    "services have a verified alternative location, path and operating capacity?"
)
A_LAB_LISTING = (
    "## Lab\n\n**21** space(s) found:\n\n| Floor | Zone | Label | Type | Area (m²) |\n|-------|------|"
    "-------|------|-----------|\n| 0 | `0Z013` | 41P Collab S | lab | 102.2 |\n| 1 | `1Z01` | 1Z01 "
    "16P Collab Sp 1Z01 | lab | — |\n| 1 | `1Z011` | 4P Collab Space | lab | 10.4 |"
)

# R1-41
Q_RANK = "Rank the glazing, roof, and AHU replacements by comfort improvement per pound."
A_COULD_NOT = (
    "I understood the question but could not put an answer together for it.\n\n- I read it as a "
    "**recommend** question about **Glazing_Replacement, Roof_Replacement, AHU_Replacement**.\n- "
    "The ontology lane ran, but returned nothing to report.\n\nThat is a gap on my side, not a "
    "statement that the building has no such data. Rephrasing with a specific room, floor or date "
    'range often reaches a lane that can answer — or ask *"what can you tell me about this '
    "building?\"* to see what is connected.\n\n**Evidence time: unknown.** I can't tell you how old "
    "these readings are, so treat the recommendation as unverified rather than current. How quickly "
    "this goes out of date is not declared for conditions, so I can't give you a recheck point — "
    "check again before relying on it. Switch if: conditions in the space you chose moves outside "
    "the range that made it the best option, or the space becomes occupied.\n\n---\n*Sources: "
    "`Building Ontology`*"
)

# R1-0
Q_PERIOD = (
    "Which remaining period today has the best supported balance of temperature, ventilation, "
    "light and quiet for concentrated work?"
)
A_BUDGET = (
    "That question reaches **288 sensors** — more than I can read and summarise in one request "
    "without either timing out or quietly answering from a fraction of them.\n\nNarrow it and I can "
    "answer directly:\n- one floor, or one room\n- one measurement at a time (temperature, or CO₂ — "
    "not both)\n- a shorter period\n\nI would rather say this than report a figure without telling "
    "you which part of the building it came from.\n\n---\n*Sources: `Building Ontology`*"
)

# R1-27
Q_RECOVERY = (
    "Which dependency-aware recovery order should incident leaders adopt to restore priority "
    "services safely with the people and resources currently available?"
)
A_TOO_LONG = (
    "Your request took too long to process. Please try a simpler question or try again later."
)

# R1-45, verbatim excerpt (first paragraph and source line)
Q_BOOTHS = "Whats the best empty room to convert into two phone booths, by demand?"
A_SENSOR_PROXY = (
    "**Recommendation**\n\nBased on the sensor‑count data you provided, the area with the highest "
    "activity is **Floor 5** – it has **28 sensors** compared with 8–11 on the other floors.  \nIf "
    "you’re looking for an empty room that could be turned into two phone booths, the best bet is "
    "to pick a room on Floor 5 that currently has no sensors installed (or that can be cleared of "
    "its existing equipment). Converting a room on this busy floor will most likely meet the "
    "highest demand for private, quiet spaces.\n\n---\n*Sources: `Building Ontology`*"
)

# R1-53 and R2-53
Q_EARLIER = "You mentioned a sensor fault earlier - has it been fixed yet?"
A_PLAYS_ALONG = (
    "The “Air Quality Level Sensor 5.14” (measured in **index**) is still operating normally.  \n"
    "In the most recent 10 readings taken between 01:34 and 01:37 on 2026‑09‑15, the sensor "
    "reported a mix of “FreshAir,” “low,” “medium,” and “high” levels—no single error or stuck "
    "value.  \n\nSo, the earlier fault has been resolved and the sensor is functioning correctly."
    "\n\n---\n*Sources: `Building Ontology` `Unknown Source`*"
)
A_NO_EARLIER_TURN = (
    "I haven't said anything earlier in this conversation — this is its first message to me — so "
    "I have nothing to follow up on. If you tell me which sensor, room or fault you mean, I can "
    "check its current state or look for reports about it."
)

# R1-50
Q_DAYLIGHT = "Whats the daylight hour count in the deepest workstation this December?"
A_DAYLIGHT_FIGURE = (
    "The deepest workstation recorded **269 daylight hours** during December.  \n\n- **Key "
    "takeaway:** 269 daylight hours is the total count for that period.  \n\nIf you’d like more "
    "details—such as how this compares to other workstations or the exact dates—just let me know!"
    "\n\n---\n*Sources: `Building Ontology`*"
)

# P-31
Q_MANUAL_TEST = (
    "Which next manual test would best distinguish the remaining plausible fault locations while "
    "minimising intrusive work?"
)
A_BARE = (
    "Thermographic survey\n\n---\n*From Abacws Building's documents: Asset Engineering Register, "
    "Maintenance Log. For the current version, contact facility management.*"
)

# R3-14
Q_FIRST_AID = (
    "Is the approved first-aid cover and equipment provision suitable for the declared occupancy, "
    "activities, hazards and operating period?"
)
A_BOLD_NOT = (
    "the building's data do **not** contain any information about first-aid cover or equipment "
    "provision. They record hazard-control details such as:\n\n- Hazard type (e.g., local exhaust "
    "ventilation, COSHH substance, asbestos, water system)  \n- Current status (active, defective, "
    "overdue)  \n- Location and label of the controlled item  \n- Owner, last test date, next due "
    "date, and control measures  \n\nSince first-aid information is not present in these 12 "
    "hazard-control records, I cannot assess its suitability for the building's occupancy, "
    "activities, hazards or operating period.\n\n---\n**You might also ask:** Who owns these "
    "records? | Which of these are on floor 3? | Show the full register?"
)


def grade(q, a, status="OK", boundary=""):
    return G.grade(q, a, status, boundary)


# ── one real fixture per bucket ──────────────────────────────────────────────────────────


def test_answered():
    v = grade(Q_WASTE, A_WASTE)
    assert (v.bucket, v.confidence) == (G.ANSWERED, G.HIGH), v


def test_honest_decline():
    v = grade(Q_CHANGING_PLACES, A_CHANGING_PLACES)
    assert (v.bucket, v.confidence) == (G.HONEST_DECLINE, G.HIGH), v


def test_add_data_instruction():
    v = grade(Q_CAPITAL, A_CAPITAL)
    assert (v.bucket, v.confidence) == (G.ADD_DATA, G.HIGH), v
    assert "You can add it" in v.reason


def test_wrong_lane_floor_mismatch():
    v = grade(Q_TOILETS, A_TOILETS)
    assert (v.bucket, v.confidence, v.rule) == (G.WRONG_LANE, G.HIGH, "lane.floor_mismatch"), v


def test_wrong_lane_question_logged_as_a_report():
    v = grade(Q_DRAINS, A_REPORT_LOGGED)
    assert (v.bucket, v.rule) == (G.WRONG_LANE, "lane.report_intake"), v


def test_wrong_lane_space_listing_for_an_unrelated_question():
    v = grade(Q_SERVER_ROOM, A_LAB_LISTING)
    assert (v.bucket, v.rule) == (G.WRONG_LANE, "lane.space_listing"), v


@pytest.mark.parametrize(
    "q,a,rule",
    [
        (Q_RANK, A_COULD_NOT, "incomplete.could_not_put_together"),
        (Q_PERIOD, A_BUDGET, "incomplete.fetch_budget"),
        (Q_RECOVERY, A_TOO_LONG, "incomplete.too_long"),
    ],
)
def test_incomplete_templates(q, a, rule):
    v = grade(q, a)
    assert (v.bucket, v.rule) == (G.INCOMPLETE, rule), v


def test_transport_failure_is_incomplete_and_named():
    v = grade(Q_RECOVERY, "", status="TIMEOUT")
    assert (v.bucket, v.rule) == (G.INCOMPLETE, "transport"), v
    assert "TIMEOUT" in v.reason


def test_invented_sensor_count_proxy_is_low_confidence():
    v = grade(Q_BOOTHS, A_SENSOR_PROXY)
    assert (v.bucket, v.confidence, v.rule) == (G.INVENTED, G.LOW, "invented.sensor_count_proxy"), v


def test_invented_prior_turn_but_an_honest_disclaimer_is_a_decline():
    assert grade(Q_EARLIER, A_PLAYS_ALONG).bucket == G.INVENTED
    v = grade(Q_EARLIER, A_NO_EARLIER_TURN)
    assert (v.bucket, v.confidence) == (G.HONEST_DECLINE, G.HIGH), v


# ── an honest decline is not a failure ───────────────────────────────────────────────────


def test_privacy_refusal_is_an_honest_decline():
    v = grade(Q_BADGE, A_PRIVACY)
    assert (v.bucket, v.confidence, v.rule) == (G.HONEST_DECLINE, G.HIGH, "decline.privacy_policy")


def test_boundary_says_refuse_and_the_answer_declines():
    with_boundary = grade(Q_INCIDENT_MESSAGES, A_INCIDENT_MESSAGES, boundary=B_FS077)
    assert (with_boundary.bucket, with_boundary.confidence) == (G.HONEST_DECLINE, G.HIGH)
    assert "boundary" in with_boundary.reason
    # The boundary only ever adds support; without it the decline is still a decline.
    assert grade(Q_INCIDENT_MESSAGES, A_INCIDENT_MESSAGES).bucket == G.HONEST_DECLINE


def test_boundary_sanctioned_decline_from_an_unrelated_store_is_not_scored_a_failure():
    v = grade(Q_DESK, A_DESK, boundary=B_AO031)
    assert v.bucket == G.HONEST_DECLINE, v
    assert v.bucket not in G.WEIRD
    # ...but it is surfaced for a human: it read HVAC regimes for a desk question.
    assert v.confidence == G.LOW
    assert "decline_cites_unrelated_source" in v.flags


def test_bold_negation_is_still_a_decline():
    v = grade(Q_FIRST_AID, A_BOLD_NOT)
    assert v.bucket == G.HONEST_DECLINE, v


# ── precedence ───────────────────────────────────────────────────────────────────────────


def test_add_data_beats_the_decline_it_is_attached_to():
    # The same real answer without its instruction block is a plain honest decline, so it is
    # the instruction -- not the decline -- that moves the bucket.
    assert grade(Q_CAPITAL, A_NOT_ON_RECORD).bucket == G.HONEST_DECLINE
    assert grade(Q_CAPITAL, A_CAPITAL).bucket == G.ADD_DATA


def test_add_data_beats_a_template_decline():
    v = grade(Q_PREVENT, A_DOCS)
    assert (v.bucket, v.rule) == (G.ADD_DATA, "add.add_or_update"), v


def test_a_weak_remediation_footer_does_not_override_a_non_answer():
    v = grade(Q_ROUTES, A_COMPARE_TEMPLATE)
    assert v.bucket == G.INCOMPLETE, v
    assert "remediation_footer" in v.flags


def test_energy_advice_to_install_sensors_is_not_an_add_data_instruction():
    v = grade(Q_ENERGY, A_ENERGY_ADVICE)
    assert v.bucket == G.ANSWERED, v


def test_invented_is_never_high_confidence():
    cases = [
        (Q_BOOTHS, A_SENSOR_PROXY),
        (Q_EARLIER, A_PLAYS_ALONG),
        (Q_DAYLIGHT, A_DAYLIGHT_FIGURE),
    ]
    for q, a in cases:
        v = grade(q, a)
        assert v.bucket == G.INVENTED and v.confidence == G.LOW, (q, v)


# ── digits are not answers (lessons #20-22, BUG-191) ─────────────────────────────────────


@pytest.mark.parametrize(
    "q,a",
    [
        (Q_DAYLIGHT, A_DAYLIGHT_FIGURE),  # a bolded figure with nothing behind it
        (Q_DAYLIGHT, "269"),  # a bare number
        (Q_CAPITAL, "2 3 4 bldg2 0.65"),  # nothing but digit-bearing tokens
    ],
    ids=["bolded_figure", "bare_number", "digit_tokens"],
)
def test_a_digit_only_answer_is_not_graded_answered(q, a):
    assert grade(q, a).bucket != G.ANSWERED


def test_a_bare_phrase_is_not_a_high_confidence_answer():
    v = grade(Q_MANUAL_TEST, A_BARE)
    assert not (v.bucket == G.ANSWERED and v.confidence == G.HIGH), v


def test_digits_in_a_decline_do_not_turn_it_into_an_answer():
    padded = A_CHANGING_PLACES.replace("Abacws.", "Abacws (bldg2, 12 records, 0.65 hr).")
    assert grade(Q_CHANGING_PLACES, padded).bucket == G.HONEST_DECLINE


def test_floors_are_read_only_from_labels_never_from_bare_numbers():
    assert G.floors_named("bldg2 averaged 0.65 hr at £0.3102 over 269 hours") == set()
    assert G.floors_named("the second-floor toilets") == {2}
    assert G.floors_named("Room 3.02 on Floor0 and level 4") == {3, 0, 4}


# ── every verdict is exactly one bucket with a stated reason ─────────────────────────────

ALL = [
    (Q_WASTE, A_WASTE),
    (Q_CHANGING_PLACES, A_CHANGING_PLACES),
    (Q_BADGE, A_PRIVACY),
    (Q_INCIDENT_MESSAGES, A_INCIDENT_MESSAGES),
    (Q_DESK, A_DESK),
    (Q_CAPITAL, A_CAPITAL),
    (Q_PREVENT, A_DOCS),
    (Q_ENERGY, A_ENERGY_ADVICE),
    (Q_ROUTES, A_COMPARE_TEMPLATE),
    (Q_TOILETS, A_TOILETS),
    (Q_DRAINS, A_REPORT_LOGGED),
    (Q_SERVER_ROOM, A_LAB_LISTING),
    (Q_RANK, A_COULD_NOT),
    (Q_PERIOD, A_BUDGET),
    (Q_RECOVERY, A_TOO_LONG),
    (Q_BOOTHS, A_SENSOR_PROXY),
    (Q_EARLIER, A_PLAYS_ALONG),
    (Q_EARLIER, A_NO_EARLIER_TURN),
    (Q_DAYLIGHT, A_DAYLIGHT_FIGURE),
    (Q_MANUAL_TEST, A_BARE),
    (Q_FIRST_AID, A_BOLD_NOT),
]


@pytest.mark.parametrize("q,a", ALL, ids=[f"case{i}" for i in range(len(ALL))])
def test_every_verdict_has_one_bucket_a_confidence_and_a_reason(q, a):
    v = grade(q, a)
    assert v.bucket in G.BUCKETS
    assert v.confidence in (G.HIGH, G.LOW)
    assert v.rule and v.reason.strip()


# ── reading the report, and the real entry point ─────────────────────────────────────────


def _report_md(rows):
    """The exact shape scripts/ask_questions.py --out writes."""
    lines = ["# Live asks — 2026-09-17 12:00", "", "## Answers", ""]
    for r in rows:
        lines += [
            f"### {r['q']} — run {r['run']} ({r['secs']:.1f} s, {r['status']})",
            "",
            "```",
            r["answer"][:4000],
            "```",
            "",
        ]
    return "\n".join(lines)


def _row(q, a, secs=9.0, status="OK"):
    return {"q": q, "run": 1, "secs": secs, "status": status, "answer": a, "flushed": True}


def test_markdown_report_is_parsed_back_exactly():
    rows = [_row(Q_CHANGING_PLACES, A_CHANGING_PLACES), _row(Q_RECOVERY, "", 300.0, "TIMEOUT")]
    parsed = G.parse_markdown_report(_report_md(rows))
    assert [(p["q"], p["answer"], p["status"]) for p in parsed] == [
        (r["q"], r["answer"], r["status"]) for r in rows
    ]


def test_load_prefers_the_complete_jsonl_and_skips_earlier_appended_rows(tmp_path):
    md = tmp_path / "baseline.md"
    md.write_text(_report_md([_row(Q_CAPITAL, A_CAPITAL)]), encoding="utf-8")
    sibling = tmp_path / "baseline.md.jsonl"
    stale = _row(Q_WASTE, A_WASTE)  # left by an earlier run with the same --out
    sibling.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in (stale, _row(Q_CAPITAL, A_CAPITAL))),
        encoding="utf-8",
    )
    rows, note = G.load_answers(md)
    assert [r["q"] for r in rows] == [Q_CAPITAL]
    assert "ignored 1" in note


def test_cli_through_the_real_entry_point(tmp_path):
    rows = [_row(Q_WASTE, A_WASTE), _row(Q_CAPITAL, A_CAPITAL), _row(Q_TOILETS, A_TOILETS)]
    md = tmp_path / "run.md"
    md.write_text(_report_md(rows), encoding="utf-8")
    bank = tmp_path / "bank.jsonl"
    bank.write_text(
        "\n".join(
            json.dumps(b)
            for b in (
                {
                    "question": Q_WASTE,
                    "id": "WM-1",
                    "stakeholder": "Waste managers",
                    "category": "",
                    "source": "stakeholder_catalogue_37",
                    "boundary": "",
                },
                {
                    "question": Q_CAPITAL,
                    "id": "Q1",
                    "stakeholder": "",
                    "category": "Cost & finance",
                    "source": "v5_synthetic_bank",
                    "boundary": "",
                },
            )
        ),
        encoding="utf-8",
    )
    out = tmp_path / "graded" / "run"
    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(md), "--bank", str(bank), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    assert res.returncode == 0, res.stderr
    verdicts = [
        json.loads(x)
        for x in (tmp_path / "graded" / "run.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [v["bucket"] for v in verdicts] == [G.ANSWERED, G.ADD_DATA, G.WRONG_LANE]
    assert [v["stakeholder"] for v in verdicts] == [
        "Waste managers",
        "(no stakeholder in bank)",
        "(not in bank)",
    ]
    report = (tmp_path / "graded" / "run.md").read_text(encoding="utf-8")
    for heading in (
        "## Per stakeholder role",
        "## Per category",
        "## Every weird answer",
        "## Low-confidence verdicts",
    ):
        assert heading in report
