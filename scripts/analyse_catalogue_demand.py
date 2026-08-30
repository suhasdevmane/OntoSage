# -*- coding: utf-8 -*-
"""What the 37 stakeholder catalogues require, and which source systems supply it.

The catalogues do not merely ask questions. Each one DECLARES, in its own words, the
systems whose records are authoritative for it ("Primary authority: the current CAFM or
EAM asset register"), the evidence it needs, the operation to perform and the boundary
the answer must not cross. This script reads those declarations rather than inferring
intent from the question text — a distinction that matters, because a keyword read of
"which room did the marketing team use" lands on "team" and files it as a people
question when it is booking history.

Two outputs:

    docs/V7_demand_by_source_system.csv    per source system: questions, roles, example
    docs/V7_question_demand.csv            per question: the systems it names

Run:
    python scripts/analyse_catalogue_demand.py
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
BANK = REPO / "tasks" / "smart_building_questions.csv"
CATALOGUE_SOURCES = ("stakeholder_catalogue_37", "supervisor_catalogue_2026-08")

#: Source systems the catalogues name, with the wordings each is written in.
#:
#: Matched against the catalogue's OWN "authoritative sources" and "sensors and
#: telemetry" declarations — never against the question. Every entry is a system of
#: record whose absence is a concrete onboarding task rather than an abstract
#: capability, which is what makes the resulting gap list actionable.
SOURCE_SYSTEMS: Dict[str, Tuple[str, ...]] = {
    "sensor_telemetry": (
        "sensor",
        "telemetry",
        "ndir",
        "co2",
        "particulate",
        "illuminance",
        "acoustic",
        "occupancy count",
        "temperature",
        "humidity",
    ),
    "bms_plant": (
        "bms",
        "bems",
        "building management system",
        "ahu",
        "air-handling",
        "damper",
        "supply-air",
        "plant telemetry",
        "setpoint",
    ),
    "meter_energy": (
        "meter",
        "submeter",
        "sub-meter",
        "energy management",
        "half-hourly",
        "consumption data",
        "metering",
    ),
    "timetable": (
        "timetable",
        "timetabling",
        "scheduled class",
        "teaching schedule",
        "curriculum schedule",
    ),
    "booking": ("booking", "reservation", "room-booking", "organiser"),
    "asset_register": (
        "cafm",
        "eam",
        "asset register",
        "asset master",
        "asset information",
        "asset scope",
        "plant register",
        "equipment inventory",
    ),
    "cmms_work": (
        "cmms",
        "work order",
        "maintenance record",
        "planned maintenance",
        "reactive maintenance",
        "work history",
        "job record",
        "helpdesk ticket",
    ),
    "hr_identity": (
        "hr ",
        "student records",
        "identity and access",
        "iam",
        "identity platform",
        "affiliation",
        "directory",
        "sponsor",
    ),
    "access_control": (
        "access control",
        "access-control",
        "credential",
        "reader",
        "controller",
        "permission group",
        "entitlement",
        "door schedule",
    ),
    "security_incident": (
        "security owns",
        "incident log",
        "patrol",
        "cctv",
        "alarm log",
        "security policy",
        "guarding",
    ),
    "fire_life_safety": (
        "fire",
        "evacuation",
        "alarm zone",
        "sprinkler",
        "extinguisher",
        "means of escape",
        "refuge",
    ),
    "statutory_compliance": (
        "legionella",
        "asbestos",
        "coshh",
        "loler",
        "puwer",
        "gas safety",
        "electrical installation condition",
        "statutory record",
        "certificate",
        "inspection record",
        "assurance",
    ),
    "permit_control": (
        "permit",
        "isolation",
        "lock-off",
        "hot work",
        "confined space",
    ),
    "policy_governance": (
        "policy",
        "procedure",
        "governance",
        "code of practice",
        "standard operating",
        "terms of reference",
    ),
    "accessibility": (
        "accessibility",
        "peep",
        "step-free",
        "mobility",
        "assistive",
        "reasonable adjustment",
        "access statement",
    ),
    "finance_cost": (
        "finance",
        "general ledger",
        "budget",
        "cost centre",
        "actuals",
        "encumbrance",
        "procurement",
        "invoice",
        "tariff",
        "unit rate",
    ),
    "contract_warranty": (
        "contract",
        "warranty",
        "service level",
        "sla",
        "supplier",
        "framework agreement",
        "defects liability",
    ),
    "project_handover": (
        "handover",
        "as-built",
        "bim",
        "cde",
        "commissioning record",
        "manual",
        "project record",
        "design intent",
    ),
    "space_inventory": (
        "space inventory",
        "room purpose",
        "tenure",
        "occupancy type",
        "net internal area",
        "space register",
        "floor plan",
        "room profile",
    ),
    "cleaning_waste": (
        "cleaning",
        "caretaking",
        "waste",
        "recycling",
        "janitorial",
        "housekeeping",
    ),
    "it_network": (
        "network",
        "server",
        "itsm",
        "service desk",
        "gateway",
        "wi-fi",
        "wifi",
        "switch",
        "patch",
        "ip address",
    ),
    "weather_external": ("weather", "outdoor reference", "met office", "external conditions"),
    "survey_condition": (
        "condition survey",
        "survey",
        "walk-down",
        "inspection survey",
        "measured survey",
        "asset condition",
    ),
    "risk_insurance": ("insurer", "risk assessor", "risk register", "insurance", "loss adjuster"),
    "training_competency": (
        "training",
        "competency",
        "induction",
        "qualification",
        "authorised person",
    ),
    "sustainability": (
        "carbon",
        "decarbonisation",
        "emission",
        "epc",
        "breeam",
        "net zero",
        "sustainability",
    ),
    "user_reports": ("complaint", "feedback", "user-reported", "helpdesk report"),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").lower()


def systems_named(row: Dict[str, str]) -> Set[str]:
    """The source systems this question's own evidence declarations name."""
    declared = _norm(f"{row.get('Authoritative_Sources', '')} {row.get('Sensors_Required', '')}")
    return {name for name, terms in SOURCE_SYSTEMS.items() if any(t in declared for t in terms)}


def load_rows() -> List[Dict[str, str]]:
    csv.field_size_limit(10**7)
    with BANK.open(encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if r.get("Source") in CATALOGUE_SOURCES]


def main(argv: List[str]) -> int:
    rows = load_rows()
    per_system: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    per_question: List[Dict[str, str]] = []
    counts: Counter = Counter()

    for row in rows:
        named = systems_named(row)
        counts[len(named)] += 1
        for system in named:
            per_system[system].append(row)
        per_question.append(
            {
                "ID": row["ID"],
                "Stakeholder_Role": row.get("Stakeholder_Role", ""),
                "Question": row["Question"],
                "source_systems": "|".join(sorted(named)),
                "n_systems": str(len(named)),
                "Complexity_L": row.get("Complexity_L", ""),
                "Readiness_R": row.get("Readiness_R", ""),
            }
        )

    out_q = REPO / "docs" / "V7_question_demand.csv"
    with out_q.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(per_question[0].keys()))
        writer.writeheader()
        writer.writerows(per_question)

    out_s = REPO / "docs" / "V7_demand_by_source_system.csv"
    with out_s.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["source_system", "questions", "share_pct", "distinct_roles", "example_question"]
        )
        for system, questions in sorted(per_system.items(), key=lambda kv: -len(kv[1])):
            writer.writerow(
                [
                    system,
                    len(questions),
                    f"{100 * len(questions) / len(rows):.1f}",
                    len({q.get("Stakeholder_Role", "") for q in questions}),
                    questions[0]["Question"][:160],
                ]
            )

    print(f"catalogue questions analysed: {len(rows)}")
    print("systems named per question: " + ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())))
    print(f"\n  {'source system':<22}{'questions':>10}{'share':>8}{'roles':>7}")
    for system, questions in sorted(per_system.items(), key=lambda kv: -len(kv[1])):
        roles = len({q.get("Stakeholder_Role", "") for q in questions})
        print(
            f"  {system:<22}{len(questions):>10}"
            f"{100 * len(questions) / len(rows):>7.1f}%{roles:>7}"
        )
    print(f"\nwrote {out_q.relative_to(REPO)}")
    print(f"wrote {out_s.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
