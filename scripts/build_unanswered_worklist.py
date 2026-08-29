# -*- coding: utf-8 -*-
"""Turn a golden-baseline capture into a worklist of what the building cannot answer.

The point is NOT to count declines. It is to separate the two reasons a question goes
unanswered, because they call for completely different work:

* **the data is not there** -- no sensor, no document, no source. The fix is onboarding:
  drop in a TTL, register a database, upload a manual. No code changes.
* **the data IS there and the question never reached it** -- a routing, authoring or
  memory gap. The fix is in the system.

Measured on the 2026-08-28 capture, all 180 "I don't have that specific information on
record" answers routed to ONE lane, ``capability`` -- the catch-all. Several are plainly
answerable: "give me a report on the anomalies this week" has an events lane, "when was
this data last updated?" has freshness metadata, "where is the facility manager's office?"
has a floor plan. Those are not missing data; they are misrouted.

**The triage column is a FIRST PASS, not a diagnosis.** It is keyword-driven, it says so,
and anything it cannot place is marked UNTRIAGED rather than guessed at. Confirm a row
before acting on it -- this file exists to ORDER the work, not to conclude it.

    python scripts/build_unanswered_worklist.py
    python scripts/build_unanswered_worklist.py --capture tasks/V6_baseline_....csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]

#: The honest-decline text the capability lane emits when it holds nothing.
DECLINE_PREFIX = "I don't have that specific information on record"

#: Other shapes in the same capture that also failed to answer. Kept in the same file and
#: labelled, because a worklist that omitted 29 outright ERRORS in favour of 180 polite
#: declines would put the easy work first and hide the broken part.
_OTHER_SHAPES: List[Tuple[str, str]] = [
    ("SPATIAL_ERROR", "I encountered an error analysing the spatial data"),
    ("DOC_NOT_FOUND", "I could not find a passage in"),
]

#: Proposed triage. ORDER MATTERS -- first match wins, so specific signals come before
#: general ones. Each entry is (bucket, why, action, pattern).
_TRIAGE: List[Tuple[str, str, str, re.Pattern]] = [
    (
        "CONTROL-SUBSCRIPTION",
        "asks the system to ACT or keep sending, not to answer",
        "control lane: decline honestly and name what it can do instead",
        re.compile(
            r"\bsend me\b|\btext me\b|\be-?mail me\b|\bnotify me\b|\balert me\b"
            r"|\bevery (?:monday|morning|week|day)\b|\bsubscribe\b|\bremind me\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ROOM-EQUIPMENT",
        "asks what equipment a room contains -- not modelled per room",
        "author room equipment (whiteboard, AV, HDMI, projector) as Brick equipment triples",
        re.compile(
            r"\bwhiteboard\b|\bhdmi\b|\bvideo ?conferenc|\bprojector\b"
            r"|\bheight[- ]adjustable\b|\bstanding desks?\b|\bair purifier",
            re.IGNORECASE,
        ),
    ),
    (
        "AMENITY-INVENTORY",
        "asks whether a facility exists -- an Amenity the building has not declared",
        "author ontosage:Amenity triples (first-aid, eyewash, microwave, ATM, charging, cloakroom)",
        re.compile(
            r"\bfirst[- ]aid\b|\bwellness room\b|\beyewash\b|\bmicrowaves?\b|\bcash machine\b"
            r"|\batm\b|\bcharge my\b|\bcharging\b|\bcloakroom\b|\bshowers?\b|\bprayer\b"
            r"|\bquiet room\b|\bvending\b|\bwater fountain\b|\block(?:er|ers)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ACCESS-RULES",
        "asks about permission, access rights or what is allowed",
        "author the rule as a KnowledgeTopic; check it is not a privacy/RBAC question first",
        re.compile(
            r"\bam i allowed\b|\ballowed\b|\bcan i (?:take|bring|use|go|park)\b"
            r"|\bneed (?:an? )?(?:escort|key|permit|pass)\b|\bpermit[- ]to[- ]work\b"
            r"|\bwork alone\b|\bmy pass\b|\baccess (?:rights|restrictions)\b|\bdogs?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "PLANT-BMS",
        "asks about plant or BMS operation -- points may exist but are not reached",
        "check bldg1_plant_points.ttl; route to the plant/BMS lane rather than capability",
        re.compile(
            r"\bboiler|\bchiller|\bahu\b|\bsetback\b|\bvalve\b|\bthermostat"
            r"|\bradiator\b|\bplant room\b|\bpumps?\b|\bdamper\b|\bcorridor lights\b",
            re.IGNORECASE,
        ),
    ),
    (
        "WORK-ORDERS",
        "asks about maintenance history, tickets or backlog",
        "onboard the work-order source (V6-T60), or answer from user_reports where it overlaps",
        re.compile(
            r"\btickets?\b|\bbacklog\b|\bwork orders?\b|\bmaintenance (?:history|record)"
            r"|\bby trade\b|\breported (?:this|last)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ANALYTICS-COMPARATIVE",
        "LIKELY ANSWERABLE from sensor history -- a comparison over time or space",
        "confirm the modality exists, then route to analytics/compare instead of capability",
        re.compile(
            r"\b(?:warmer|colder|cooler|quieter|noisier|brighter|darker|cleaner|busier)\b"
            r"|\bwhich side\b|\bcompared with\b|\bversus\b|\bsince (?:monday|last)\b"
            r"|\bwhat time does\b|\bconsistently (?:under|over|above|below)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "CLARIFY",
        "too vague to route -- no referent, no modality",
        "clarification lane: ask what they mean rather than declining",
        re.compile(
            r"^\s*(?:is everything ok|is it ok|how are things|anything wrong|all good)",
            re.IGNORECASE,
        ),
    ),
    (
        "MEMORY",
        "refers to an earlier turn or a previous session",
        "conversation memory / co-reference: resolve the referent before classifying",
        re.compile(
            r"\bsame as (?:last|before)\b|\blast time\b|\bpreviously\b|\bearlier\b"
            r"|\byou (?:showed|said|told)\b|\bas (?:above|before)\b|\bthat one\b"
            r"|\bwhatever you showed\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ROUTING-ANOMALY",
        "an anomaly/diagnosis lane exists and holds this data",
        "route to events/anomaly instead of capability",
        re.compile(
            r"\banomal|\bfaults?\b|\bfaulty\b|\bunusual\b|\bnot working\b|\bbroken\b"
            r"|\bdrift|\bshould(?:n't| not) trust\b|\bmiscalibrat|\bsuspect\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ROUTING-WAYFINDING",
        "a floor plan and spatial lane exist for this",
        "route to floor_plan/spatial_query; check the referent resolves",
        re.compile(
            r"\bwhere(?:'s| is| are| can i find)\b|\bhow do i get to\b|\bwhich floor\b"
            r"|\bnearest\b|\broutes?\b|\bdirections?\b|\blocate\b|\bdirectly above\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ROUTING-FORECAST",
        "a forecast lane exists; the question is forward-looking",
        "route to trend/forecast; confirm the modality is forecastable",
        re.compile(
            r"\bpredict|\bforecast|\btomorrow\b|\bnext week\b|\btonight\b"
            r"|\bwill (?:it|we|there|the)\b|\bexpected\b|\blikely\b|\bgoing to be\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ROUTING-SELF",
        "asks what the system itself knows or how fresh it is",
        "self-description / coverage lane -- answerable from the graph and the registry",
        re.compile(
            r"\bwhat (?:don't|do) you (?:have|know|hold)\b|\bdata last updated\b"
            r"|\bhow (?:current|fresh|old) (?:is|are)\b|\bwhat can you\b|\bcoverage\b"
            r"|\bwhich sensors do you\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DOCUMENT",
        "answerable from a document nobody has uploaded",
        "upload the manual/policy/assessment into input/documents/ and reindex",
        re.compile(
            r"\bmanuals?\b|\bpolic(?:y|ies)\b|\bprocedures?\b|\bcertificates?\b"
            r"|\bwarrant(?:y|ies)\b|\bdatasheets?\b|\bhandbook\b|\bo&m\b"
            r"|\bcommissioning\b|\brisk assessment\b|\blegionella\b|\bassessments?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATA-COST",
        "financial data is not modelled in this building at all",
        "out of scope until a cost/contract source is onboarded -- or decline honestly",
        re.compile(
            r"\bcosts?\b|\bprices?\b|\btariffs?\b|\bbill(?:s|ing)?\b|\bcontracts?\b"
            r"|\bbudget\b|\bspend\b|\benergy contract\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATA-PEOPLE",
        "asks about staff, roles or a named person's whereabouts",
        "check this is not a privacy refusal first; if legitimate, needs an HR/directory source",
        re.compile(
            r"\bwho (?:is|are|should|do i)\b|\bstaff\b|\bfacility manager\b"
            r"|\bcontacts?\b|\bresponsible\b|\bteam\b|\bwarden\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATA-SAFETY",
        "safety/compliance state is not sourced",
        "onboard alarm/compliance state, or author it as knowledge triples",
        re.compile(
            r"\bsafe to (?:be|work)\b|\bfire\b|\balarms?\b|\bevacuat|\bcompliance\b"
            r"|\bregulation|\binspections?\b|\bincidents?\b|\bnear[- ]miss"
            r"|\bstorm\b|\bemergency\b",
            re.IGNORECASE,
        ),
    ),
    (
        "DATA-SCHEDULE",
        "timetable, booking or event data is not sourced for this",
        "onboard the institutional layer (timetable/bookings) -- V6-T57",
        re.compile(
            r"\bbooked\b|\bbookings?\b|\btimetable\b|\bschedules?\b|\bclass(?:es)?\b"
            r"|\blectures?\b|\bevents?\b|\bmeetings?\b|\bwho's using\b|\bconference\b"
            r"|\bfree at\b|\bgiving a talk\b",
            re.IGNORECASE,
        ),
    ),
    (
        "AUTHORING",
        "a knowledge topic or amenity would answer this",
        "author ontosage:KnowledgeTopic / Amenity triples via the admin GUI",
        re.compile(
            r"\bwi-?fi\b|\bparking\b|\bbikes?\b|\brecycl|\bcatering\b|\bcafes?\b"
            r"|\btoilets?\b|\bposts?\b|\bdeliver|\blost property\b|\bopening hours\b"
            r"|\bplants?\b|\bphotos?\b",
            re.IGNORECASE,
        ),
    ),
]


def triage(question: str) -> Tuple[str, str, str]:
    """(bucket, why, action) -- a PROPOSAL, not a verdict."""
    for bucket, why, action, pattern in _TRIAGE:
        if pattern.search(question or ""):
            return bucket, why, action
    return (
        "UNTRIAGED",
        "no pattern matched -- read it and decide",
        "classify by hand; do not assume it is missing data",
    )


def _qid(row: Dict[str, str]) -> str:
    return row.get("﻿qid") or row.get("qid") or ""


def collect(capture: Path) -> List[Dict[str, str]]:
    rows = list(csv.DictReader(capture.open(encoding="utf-8")))
    out: List[Dict[str, str]] = []

    for r in rows:
        status = (r.get("status") or "OK").strip()
        answer = (r.get("answer") or "").lstrip()
        group: Optional[str] = None

        if status != "OK":
            # The pipeline never produced an answer. A different problem from a decline:
            # unanswerable by COST, not by missing data (CAVEAT-363).
            group = "TIMEOUT"
        elif answer.startswith(DECLINE_PREFIX):
            group = "DECLINE"
        else:
            for name, marker in _OTHER_SHAPES:
                if marker.lower() in answer.lower()[:400]:
                    group = name
                    break

        if group is None:
            continue

        question = r.get("question") or ""
        bucket, why, action = triage(question)
        if group == "TIMEOUT":
            bucket, why, action = (
                "COST-TIMEOUT",
                "exceeded the 150s pipeline timeout; breadth, not absence of data",
                "aggregate in SQL / bound the candidate set, or raise the timeout",
            )
        elif group == "SPATIAL_ERROR":
            bucket, why, action = (
                "DEFECT-SPATIAL",
                "the spatial lane raised an ERROR rather than answering or declining",
                "debug the spatial lane -- an error is not an honest decline",
            )

        out.append(
            {
                "qid": _qid(r),
                "group": group,
                "proposed_bucket": bucket,
                "why_unanswered": why,
                "proposed_action": action,
                "question": question,
                "routed_intent": r.get("intent") or "",
                "answer_status": r.get("answer_status") or "",
                "category": r.get("category") or "",
                "stakeholder_role": r.get("stakeholder_role") or "",
                "complexity_l": r.get("complexity_l") or "",
                "source": r.get("source") or "",
                "elapsed_s": r.get("elapsed_s") or "",
                "answer": " ".join((r.get("answer") or "").split()),
                "fixed": "",  # fill in as work lands, then re-run to measure progress
                "notes": "",
            }
        )
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--capture",
        default=str(REPO / "tasks" / "V6_baseline_20260828_185823.csv"),
        help="a golden-baseline capture CSV",
    )
    ap.add_argument("--out", default=str(REPO / "tasks" / "V6_unanswered_worklist.csv"))
    args = ap.parse_args(argv)

    capture = Path(args.capture)
    if not capture.is_file():
        print(f"capture not found: {capture}")
        return 1

    rows = collect(capture)
    if not rows:
        print("nothing unanswered in this capture")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"wrote {out}  ({len(rows)} rows)\n")
    print("by group:")
    for k, v in Counter(r["group"] for r in rows).most_common():
        print(f"  {k:16s} {v:4d}")
    print("\nby proposed bucket (FIRST PASS -- confirm before acting):")
    for k, v in Counter(r["proposed_bucket"] for r in rows).most_common():
        print(f"  {k:22s} {v:4d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
