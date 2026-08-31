# -*- coding: utf-8 -*-
"""Author the record documents that make the catalogue questions answerable (V7-P4).

Seven systems of record bldg1 does not hold, written as record documents so the lifter
turns each into queryable triples. Ordered by how many catalogue questions each unblocks:
contracts 413, handover 257, tariffs 119, condition survey 99, competency 79, bookings
543 (which has its own document already) and risk 6.

**Every one is synthetic and says so**, in the document and in the front-matter
(`simulated: true`), which the lifter carries onto every triple. bldg1 is a real building
and inventing records for it without saying so would be the fabrication this project
guards against hardest.

The dates are anchored so a regeneration is reproducible, and deliberately span *both*
sides of the anchor: a register in which nothing is open, expiring or overdue cannot
demonstrate the questions it exists to answer — the permit register was written that way
first and had to be redone.

    python scripts/generate_record_documents.py            # write into input/documents
    python scripts/generate_record_documents.py --out DIR  # or somewhere else
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "input" / "documents"

#: Fixed so a regeneration produces the same document, and so "expires in six months" is
#: a stable question rather than one whose answer drifts with the wall clock.
ANCHOR = date(2026, 8, 31)

BANNER = (
    "_**Synthetic demonstration record** — fictional history, " "not a real compliance document._\n"
)


def d(offset_days: int) -> str:
    return (ANCHOR + timedelta(days=offset_days)).isoformat()


def front(
    record_type: str,
    owner: str,
    authority: str,
    source: str,
    version: str,
    table: str,
    maps_to: str,
) -> str:
    return (
        "---\n"
        f"record_type: {record_type}\n"
        f'owner: "{owner}"\n'
        f'authority: "{authority}"\n'
        f'source_system: "{source}"\n'
        f"effective_from: {d(-365)}\n"
        f'version: "{version}"\n'
        f"review_due: {d(365)}\n"
        "simulated: true\n"
        "tables:\n"
        f'  - name: "{table}"\n'
        f"    maps_to: {maps_to}\n"
        "---\n\n"
    )


def table(header: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out) + "\n"


# ── the documents ──────────────────────────────────────────────────────────────────


def contracts() -> str:
    rows = [
        [
            "CON-2023-014",
            "Lift maintenance and 24h callout — passenger lifts 1 and 2",
            "Vertical Transport Services Ltd",
            d(-980),
            d(115),
            "Active",
            "Estates Mechanical",
        ],
        [
            "CON-2024-002",
            "BMS support and out-of-hours plant response",
            "Meridian Controls",
            d(-610),
            d(55),
            "Active",
            "Estates Controls",
        ],
        [
            "CON-2024-019",
            "Water hygiene monitoring and legionella sampling",
            "Severn Water Hygiene",
            d(-520),
            d(210),
            "Active",
            "Estates Compliance",
        ],
        [
            "CON-2025-003",
            "Cleaning and washroom services",
            "Clearview Facilities",
            d(-300),
            d(65),
            "Notice served",
            "Facilities",
        ],
        [
            "CON-2025-011",
            "Fire alarm and emergency lighting servicing",
            "Cambrian Fire Systems",
            d(-240),
            d(490),
            "Active",
            "Estates Compliance",
        ],
        [
            "CON-2022-041",
            "Grounds and external areas",
            "Taff Valley Grounds",
            d(-1300),
            d(-120),
            "Expired",
            "Facilities",
        ],
        [
            "CON-2024-027",
            "Waste collection and recycling",
            "Cardiff Waste Partners",
            d(-430),
            d(28),
            "Active",
            "Facilities",
        ],
        [
            "CON-2023-036",
            "AV support and lecture-capture maintenance",
            "Stagecraft AV",
            d(-800),
            d(-40),
            "Expired",
            "Teaching Support",
        ],
    ]
    return (
        front(
            "contract",
            "Estates Contracts Manager",
            "Cardiff University Estates",
            "Contract Register",
            "3.2",
            "Contract register",
            "contracts",
        )
        + "# Contract Register — Abacws Building\n\n"
        + BANNER
        + "\n## Scope\n\nService, maintenance and supply agreements covering the building. A contract is "
        "bought;\na warranty accompanies an asset. Where the two disagree about who is liable for a "
        "repair,\nboth are reported and the Contracts Manager resolves it — the register never picks "
        "one.\n\n"
        + "## Contract register\n\n"
        + table(["reference", "scope", "provider", "start", "end", "status", "owner_role"], rows)
        + "\n## Notice and renewal\n\nA contract under notice remains in force until its end date. "
        "Renewal decisions sit with\nthe Contracts Manager and the budget holder, never with this "
        "service.\n"
    )


def warranties() -> str:
    rows = [
        [
            "WTY-AHU01-2024",
            "AHU-01 — roof plant enclosure",
            "Meridian Mechanical Ltd",
            d(-700),
            d(30),
            "Active",
        ],
        [
            "WTY-AHU02-2024",
            "AHU-02 — roof plant enclosure",
            "Meridian Mechanical Ltd",
            d(-700),
            d(30),
            "Active",
        ],
        [
            "WTY-CHILL-2022",
            "Chiller 1 — basement plant room",
            "Coldstream Refrigeration",
            d(-1450),
            d(-350),
            "Expired",
        ],
        [
            "WTY-LIFT1-2021",
            "Passenger lift 1",
            "Vertical Transport Services Ltd",
            d(-1800),
            d(-700),
            "Expired",
        ],
        [
            "WTY-BMS-2024",
            "BMS head end and field controllers",
            "Meridian Controls",
            d(-610),
            d(120),
            "Active",
        ],
        ["WTY-PV-2025", "Roof PV array and inverters", "Brecon Solar", d(-260), d(1200), "Active"],
        ["WTY-GEN-2023", "Standby generator", "Powerline Generation", d(-900), d(-170), "Void"],
    ]
    return (
        front(
            "warranty",
            "Estates Asset Information",
            "Cardiff University Estates",
            "Warranty Register",
            "2.4",
            "Warranty register",
            "warranties",
        )
        + "# Warranty Register — Abacws Building\n\n"
        + BANNER
        + "\n## Why this matters to a work order\n\nWhether a repair is chargeable depends on whether "
        "the asset is in warranty. WTY-GEN-2023\nis recorded **void**: the generator was serviced "
        "outside the approved regime in 2025 and\nthe manufacturer withdrew cover. A void warranty is "
        "not an expired one and the register\nkeeps them distinct.\n\n"
        + "## Warranty register\n\n"
        + table(["reference", "asset", "provider", "start", "end", "status"], rows)
        + "\n## Claims\n\nClaims are raised by the Estates Asset Information owner. This service reports "
        "warranty\nstate; it never asserts that a claim will be accepted.\n"
    )


def handover() -> str:
    rows = [
        [
            "HO-AHU01-OM",
            "AHU-01 — roof plant enclosure",
            "O&M manual",
            d(-700),
            "Meridian Mechanical Ltd",
            "Held",
        ],
        [
            "HO-AHU02-OM",
            "AHU-02 — roof plant enclosure",
            "O&M manual",
            d(-700),
            "Meridian Mechanical Ltd",
            "Held",
        ],
        [
            "HO-BMS-COMM",
            "BMS head end and field controllers",
            "Commissioning certificate",
            d(-600),
            "Meridian Controls",
            "Held",
        ],
        [
            "HO-CHILL-OM",
            "Chiller 1 — basement plant room",
            "O&M manual",
            d(-1450),
            "Coldstream Refrigeration",
            "Outstanding",
        ],
        [
            "HO-LIFT1-LOLER",
            "Passenger lift 1",
            "Thorough examination record",
            d(-120),
            "Vertical Transport Services Ltd",
            "Held",
        ],
        [
            "HO-PV-ASBUILT",
            "Roof PV array and inverters",
            "As-built drawing set",
            d(-250),
            "Brecon Solar",
            "Held",
        ],
        [
            "HO-GEN-OM",
            "Standby generator",
            "O&M manual",
            d(-900),
            "Powerline Generation",
            "Outstanding",
        ],
        [
            "HO-FIRE-CERT",
            "Fire alarm system",
            "Commissioning certificate",
            d(-230),
            "Cambrian Fire Systems",
            "Held",
        ],
        ["HO-SPRINK-OM", "Sprinkler system", "O&M manual", d(-1600), "Unknown", "Outstanding"],
    ]
    return (
        front(
            "handover",
            "Estates Asset Information",
            "Cardiff University Estates",
            "Handover and O&M Register",
            "1.8",
            "Handover register",
            "handover",
        )
        + "# Project Handover and O&M Register — Abacws Building\n\n"
        + BANNER
        + "\n## What a handover record is for\n\nA claim that a system is *commissioned* must rest on a "
        "record, not on a flag somebody\nset. Three assets below are marked **outstanding**: no "
        "handover documentation is held for\nthem, so any commissioning claim about those assets is "
        "unverified, and the register says\nso rather than staying silent.\n\n"
        + "## Handover register\n\n"
        + table(["reference", "asset", "document_kind", "issued", "issued_by", "status"], rows)
        + "\n## Retrieval\n\nHeld documents are filed with Estates Asset Information. An outstanding "
        "record is chased\nfrom the original installer where one can still be identified; "
        "HO-SPRINK-OM predates the\ncurrent register and its installer is not recorded.\n"
    )


def tariffs() -> str:
    rows = [
        [
            "TAR-ELEC-2026",
            "Electricity",
            "0.2847",
            "0.6120",
            "GBP",
            d(-243),
            d(122),
            "Cardiff University Energy Framework",
        ],
        [
            "TAR-GAS-2026",
            "Gas",
            "0.0691",
            "0.3410",
            "GBP",
            d(-243),
            d(122),
            "Cardiff University Energy Framework",
        ],
        [
            "TAR-WATER-2026",
            "Water",
            "1.9450",
            "0.0000",
            "GBP",
            d(-243),
            d(122),
            "Dwr Cymru Welsh Water",
        ],
        [
            "TAR-ELEC-2025",
            "Electricity",
            "0.3102",
            "0.5880",
            "GBP",
            d(-608),
            d(-244),
            "Cardiff University Energy Framework",
        ],
    ]
    return (
        front(
            "tariff",
            "Energy and Sustainability Manager",
            "Cardiff University Estates",
            "Energy Tariff Register",
            "2026.1",
            "Tariff register",
            "tariffs",
        )
        + "# Energy Tariff Register — Abacws Building\n\n"
        + BANNER
        + "\n## How cost is computed\n\nA cost answer is metered consumption multiplied by the unit rate "
        "**of the tariff in force\nfor that period**, plus the standing charge for the days covered. "
        "Where no tariff covers a\nperiod, no cost is stated — an assumed rate produces a confident "
        "wrong number, and the\nprevious year's rate is not this year's.\n\n"
        "Rates are shown per kWh for electricity and gas, and per cubic metre for water. All\nrates "
        "exclude VAT.\n\n"
        + "## Tariff register\n\n"
        + table(
            [
                "reference",
                "utility",
                "unit_rate",
                "standing_charge",
                "currency",
                "start",
                "end",
                "supplier",
            ],
            rows,
        )
        + "\n## Authority\n\nRates are set by the university energy framework and are not negotiated at "
        "building level.\nThe Energy and Sustainability Manager owns this register.\n"
    )


def condition_survey() -> str:
    rows = [
        [
            "CS-2026-001",
            "AHU-01 — roof plant enclosure",
            d(-60),
            "B",
            "9.0",
            "Hafod Building Surveyors",
            "Bearings noted for monitoring",
        ],
        [
            "CS-2026-002",
            "AHU-02 — roof plant enclosure",
            d(-60),
            "B",
            "9.0",
            "Hafod Building Surveyors",
            "",
        ],
        [
            "CS-2026-003",
            "Chiller 1 — basement plant room",
            d(-60),
            "D",
            "0.0",
            "Hafod Building Surveyors",
            "Beyond economic repair; replacement recommended",
        ],
        [
            "CS-2026-004",
            "Passenger lift 1",
            d(-60),
            "C",
            "2.5",
            "Hafod Building Surveyors",
            "Controller obsolete, parts availability limited",
        ],
        ["CS-2026-005", "Passenger lift 2", d(-60), "B", "7.0", "Hafod Building Surveyors", ""],
        [
            "CS-2026-006",
            "Roof covering — main roof",
            d(-60),
            "C",
            "4.0",
            "Hafod Building Surveyors",
            "Localised ponding above Level 5",
        ],
        [
            "CS-2026-007",
            "Curtain walling — south elevation",
            d(-60),
            "B",
            "14.0",
            "Hafod Building Surveyors",
            "Seal replacement due mid-life",
        ],
        [
            "CS-2026-008",
            "Standby generator",
            d(-60),
            "D",
            "-1.0",
            "Hafod Building Surveyors",
            "Life expired; on the replacement programme",
        ],
        [
            "CS-2026-009",
            "Roof PV array and inverters",
            d(-60),
            "A",
            "19.0",
            "Hafod Building Surveyors",
            "",
        ],
        ["CS-2026-010", "Fire alarm system", d(-60), "B", "8.0", "Hafod Building Surveyors", ""],
    ]
    return (
        front(
            "condition_survey",
            "Estates Asset Information",
            "Cardiff University Estates",
            "Condition Survey",
            "2026.1",
            "Condition survey",
            "surveys",
        )
        + "# Asset Condition Survey — Abacws Building\n\n"
        + BANNER
        + "\n## Grades\n\n**A** as new · **B** satisfactory · **C** poor · **D** end of life. Remaining "
        "life is the\nsurveyor's ESTIMATE at the survey date, so any answer using it is a calculation "
        "and not an\nobservation. A negative remaining life means the asset is already past its "
        "expected life.\n\n"
        + "## Condition survey\n\n"
        + table(
            ["reference", "asset", "surveyed", "grade", "remaining_life_years", "surveyor", "note"],
            rows,
        )
        + "\n## Use\n\nGrades inform the replacement programme. They do not authorise expenditure and "
        "they are not\na safety judgement — a D-grade asset is not necessarily unsafe, and a competent "
        "person\ndecides that.\n"
    )


def competency() -> str:
    rows = [
        [
            "CMP-ROOF",
            "Roof and roof plant enclosure",
            "Working at height, harness and rescue",
            "contractor",
            "36",
            "Estates Compliance",
            d(-365),
        ],
        [
            "CMP-HV",
            "Basement HV switchroom",
            "Authorised Person (HV) appointment",
            "operator",
            "24",
            "Estates Electrical",
            d(-365),
        ],
        [
            "CMP-CONF",
            "Cold water storage tanks and risers",
            "Confined space entry",
            "contractor",
            "36",
            "Estates Compliance",
            d(-365),
        ],
        [
            "CMP-ACM",
            "Ceiling voids where asbestos is registered",
            "Asbestos awareness (Category A)",
            "contractor",
            "12",
            "Estates Compliance",
            d(-365),
        ],
        [
            "CMP-PLANT",
            "Basement plant room",
            "Site induction and plant room awareness",
            "contractor",
            "12",
            "Facilities",
            d(-365),
        ],
        [
            "CMP-LAB",
            "Level 3 and 4 research laboratories",
            "Laboratory induction and COSHH awareness",
            "researcher",
            "24",
            "School Safety Officer",
            d(-365),
        ],
        [
            "CMP-LIFT",
            "Lift motor rooms",
            "Lift engineer competency and permit briefing",
            "contractor",
            "36",
            "Estates Mechanical",
            d(-365),
        ],
    ]
    return (
        front(
            "competency",
            "Estates Compliance Team",
            "Cardiff University Estates",
            "Competency Requirements",
            "1.5",
            "Competency requirements",
            "competencies",
        )
        + "# Competency and Authorisation Requirements — Abacws Building\n\n"
        + BANNER
        + "\n## What this register does and does not hold\n\nIt records what a restricted area "
        "**requires**. It deliberately does not record who holds\nwhat: a question about an "
        "individual's training is answered by the training record owner,\nnot by this building.\n\n"
        + "## Competency requirements\n\n"
        + table(
            [
                "reference",
                "area",
                "requirement",
                "applies_to_role",
                "valid_for_months",
                "authority",
                "effective_from",
            ],
            rows,
        )
        + "\n## Relationship to permits\n\nNo permit is issued for these areas without the competency "
        "above evidenced and in date.\nThe permit register records the permit; this register records "
        "the precondition.\n"
    )


def risk_assessments() -> str:
    rows = [
        [
            "RA-2025-004",
            "Working at height — roof plant access",
            "Roof plant enclosure",
            d(-400),
            d(-35),
            "Estates Compliance",
            "Overdue",
        ],
        [
            "RA-2026-001",
            "Legionella — domestic water services",
            "Whole building",
            d(-210),
            d(155),
            "Estates Compliance",
            "Current",
        ],
        [
            "RA-2026-002",
            "Manual handling — waste and deliveries",
            "Loading bay and bin store",
            d(-180),
            d(185),
            "Facilities",
            "Current",
        ],
        [
            "RA-2026-003",
            "Lone working — out of hours",
            "Whole building",
            d(-150),
            d(20),
            "Security",
            "Due",
        ],
        [
            "RA-2025-009",
            "Electrical safety — HV switchroom",
            "Basement HV switchroom",
            d(-330),
            d(35),
            "Estates Electrical",
            "Due",
        ],
        [
            "RA-2026-004",
            "Laboratory chemicals — COSHH",
            "Level 3 and 4 laboratories",
            d(-90),
            d(275),
            "School Safety Officer",
            "Current",
        ],
    ]
    return (
        front(
            "risk_assessment",
            "Health and Safety Officer",
            "Cardiff University Estates",
            "Risk Assessment Register",
            "2026.2",
            "Risk assessment register",
            "risks",
        )
        + "# Risk Assessment Register — Abacws Building\n\n"
        + BANNER
        + "\n## Review\n\nAn assessment is **due** within 30 days of its review date and **overdue** "
        "after it. Status\nis recorded by the owner and is not inferred from the date alone — an "
        "assessment reviewed\nearly is current whatever the calendar says.\n\n"
        + "## Risk assessment register\n\n"
        + table(
            ["reference", "hazard", "area", "assessed", "review_due", "assessor_role", "status"],
            rows,
        )
        + "\n## Escalation\n\nRA-2025-004 is overdue and is escalated to the Health and Safety Officer. "
        "This service\nreports the state; it does not clear it.\n"
    )


def bookings() -> str:
    """Room bookings, spanning both sides of the anchor.

    The rooms are bldg1's real bookable spaces, read from the graph rather than invented,
    so an availability answer names somewhere that exists.

    **Organisers are ROLES, never people.** The previous version of this document listed
    named individuals, and every one of the 37 catalogues limits person-level detail to an
    authorised case. An availability question does not need a name, so the record does not
    carry one — the mapping's `booked_by_role` is the whole point.
    """
    rooms = [
        "Room 5.15 — Seminar / Conference Room",
        "Room 5.16 — Seminar / Conference Room",
        "Room 5.17 — Meeting Room",
        "Room 5.18 — Meeting Room",
        "Room 5.01 — Research Laboratory",
        "Room 5.04 — Research Laboratory",
    ]
    roles = [
        "Research group (Smart Buildings)",
        "Graduate School",
        "Teaching Team",
        "Industry Liaison",
        "Estates Compliance",
        "School Office",
    ]
    sizes = [18, 12, 8, 30, 6, 24]
    statuses = ["Confirmed", "Confirmed", "Confirmed", "Provisional", "Confirmed", "Cancelled"]
    rows: List[List[str]] = []
    n = 0
    for day in (-7, -3, -1, 0, 1, 2, 5, 9):
        for slot, (start, end) in enumerate(((9, 11), (14, 16))):
            room = rooms[n % len(rooms)]
            n += 1
            rows.append(
                [
                    f"BK-2026-{n:04d}",
                    room,
                    f"{d(day)}T{start:02d}:00:00",
                    f"{d(day)}T{end:02d}:00:00",
                    roles[n % len(roles)],
                    str(sizes[n % len(sizes)]),
                    statuses[n % len(statuses)],
                ]
            )
    return (
        front(
            "booking",
            "Room Booking Team",
            "Cardiff University Timetabling",
            "Room Booking System",
            "2026.34",
            "Booking register",
            "bookings",
        )
        + "# Room Booking Register — Abacws Building\n\n"
        + BANNER
        + "\n## What this register decides\n\nThe booking register is the AUTHORITATIVE source for "
        "whether a room is available. A room\nwith nobody in it is not an available room, and an "
        "occupancy sensor cannot tell the\ndifference — where the two disagree, both are reported "
        "and the room owner resolves it.\n\n"
        "Organisers are recorded as roles or teams. This register holds no personal data, and a\n"
        "question about who is in a room is answered by neither this register nor the sensors.\n\n"
        + "## Booking register\n\n"
        + table(
            ["reference", "room", "start", "end", "booked_by_role", "expected_attendees", "status"],
            rows,
        )
        + "\n## Changes\n\nBookings are created and cancelled in the booking system. This service "
        "reports them; it\ncannot create, change or cancel one, and a cancelled booking is kept "
        "rather than deleted\nso that a no-show can be told from a room that was never booked.\n"
    )


DOCUMENTS = {
    "room_bookings.md": bookings,
    "contract_register.md": contracts,
    "warranty_register.md": warranties,
    "handover_register.md": handover,
    "energy_tariffs.md": tariffs,
    "condition_survey.md": condition_survey,
    "competency_requirements.md": competency,
    "risk_assessment_register.md": risk_assessments,
}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, build in DOCUMENTS.items():
        text = build()
        (out / name).write_text(text, encoding="utf-8")
        rows = text.count("\n| ") - text.count("\n|---")
        print(f"  {name:<32} {len(text):>6} chars")
    print(f"\n{len(DOCUMENTS)} record documents written to {out}")
    print("All declare simulated: true — the lifter carries that onto every triple.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
