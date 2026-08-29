# -*- coding: utf-8 -*-
"""Author the statutory and compliance document pack (V6-T75).

45 questions in the unanswered worklist ask for records that live in documents, not in
sensors: a legionella assessment, an asbestos register, permit registers, COSHH
examinations, contractor inductions, a hazardous-materials inventory. 18 of them already
return "I could not find a passage in this building's documents" -- the document lane
WORKS and has nothing to read.

**These are SYNTHETIC records for a real building, and every one says so in its own first
line.** The user asked for them deliberately, to demonstrate that the pipeline works end
to end once the documents exist. The banner is not a hedge against that decision, it
carries it: a legionella assessment for a real building is the kind of document somebody
could later act on, and one that does not announce itself as fictional is a hazard sitting
in a repository. The same reasoning stopped the provisioner minting potability statements.

Dates are backdated against a fixed anchor so the records read as a real compliance
history -- an assessment from eighteen months ago with reviews since, permits across
recent months, examinations with due dates that have and have not passed. Deterministic:
re-running produces the same dates, so a capture can be compared with an earlier one.

**No named individuals.** Real compliance packs name people -- PEEP holders, permit
signatories, inducted contractors. Those are personal data, and a PEEP names a person's
disability. The pack below carries the PROCEDURE and aggregate counts instead, which is
what the questions actually need and what the system should be willing to answer.

    python scripts/generate_compliance_documents.py
    python scripts/generate_compliance_documents.py --building-id bldg2 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]

#: Every date is derived from this, so a re-run is byte-identical and two captures stay
#: comparable. Chosen as the day the pack was authored.
ANCHOR = date(2026, 8, 29)

#: ONE LINE, deliberately. The first version was a five-line block quote, and because the
#: retriever returns the OPENING chunk it consumed the first ~350 characters of every
#: document answer — a question about grease traps came back leading with four lines of
#: disclaimer before reaching the date. The warning still has to survive INTO the answer,
#: because a reader may never open the file, so it cannot simply move to the footer.
#: One line does both jobs.
BANNER = (
    "_**Synthetic demonstration record** — fictional history, " "not a real compliance document._\n"
)


def _d(days_ago: int) -> str:
    return (ANCHOR - timedelta(days=days_ago)).isoformat()


def _ahead(days: int) -> str:
    return (ANCHOR + timedelta(days=days)).isoformat()


def _doc(title: str, building: str, body: str) -> str:
    return f"# {title} — {building}\n\n{BANNER}\n{body.strip()}\n"


def documents(building_name: str) -> Dict[str, str]:
    """filename -> full markdown. Each answers named questions from the worklist."""
    docs: Dict[str, str] = {}

    # ── water hygiene / legionella ───────────────────────────────────────────
    docs["water_hygiene_legionella.md"] = _doc(
        "Water Hygiene and Legionella Control",
        building_name,
        f"""
## Risk assessment

- **Assessment date:** {_d(541)} (L8 / HSG274 written scheme)
- **Last review:** {_d(176)} · **Next review due:** {_ahead(189)}
- **Assessor:** Estates Water Safety Group (contracted)
- **Overall risk rating:** LOW, with control measures in place

## Written scheme of control

| control | frequency | last completed | next due |
|---|---|---|---|
| Cold water storage tank inspection | 6 monthly | {_d(97)} | {_ahead(85)} |
| Calorifier temperature check | monthly | {_d(19)} | {_ahead(11)} |
| Sentinel outlet temperatures | monthly | {_d(19)} | {_ahead(11)} |
| Little-used outlet flushing | weekly | {_d(4)} | {_ahead(3)} |
| Shower head descale and disinfect | quarterly | {_d(63)} | {_ahead(28)} |
| Microbiological sampling | quarterly | {_d(41)} | {_ahead(50)} |

## Shower outlets

Shower outlets serve the ground-floor changing area adjacent to the cycle store. All are
on the weekly flushing register. Heads were descaled and disinfected on {_d(63)}.

## Sampling history and remediation

| date | outlet | result | action |
|---|---|---|---|
| {_d(41)} | All sampled points | Satisfactory | None |
| {_d(132)} | Outlet 14 (Level 2 kitchenette) | **Fail — TVC above action level** | Remediation protocol invoked; see below |
| {_d(125)} | Outlet 14 (resample) | Satisfactory | Returned to normal monitoring |

### Remediation protocol for a failed sample

1. Take the outlet out of service and label it.
2. Notify the Water Safety Group within one working day.
3. Thermal disinfection at 60 °C for a minimum of five minutes, or chemical disinfection
   where thermal is impracticable.
4. Resample after seven days.
5. Return to service only on a satisfactory resample; record both results in the logbook.
6. If a second sample fails, escalate to the responsible person and review the written
   scheme for that branch.

## Logbook entries — Q2

| date | entry |
|---|---|
| {_d(151)} | Monthly sentinel temperatures — all within range |
| {_d(139)} | Weekly flushing completed, 14 little-used outlets |
| {_d(132)} | Outlet 14 sample FAIL — outlet isolated, remediation started |
| {_d(125)} | Outlet 14 resample satisfactory — returned to service |
| {_d(120)} | Monthly sentinel temperatures — all within range |
| {_d(108)} | Calorifier flow/return check — satisfactory |
| {_d(97)} | Cold water storage tank inspection — no ingress, lid secure |
""",
    )

    # ── asbestos ─────────────────────────────────────────────────────────────
    docs["asbestos_register.md"] = _doc(
        "Asbestos Register and Management Plan",
        building_name,
        f"""
## Survey

- **Management survey:** {_d(714)} · **Refurbishment survey (Level 5 works):** {_d(288)}
- **Register reviewed:** {_d(84)} · **Next review:** {_ahead(281)}
- **Duty holder:** Estates Compliance Team

## Asbestos-containing materials identified

| location | material | condition | risk | action |
|---|---|---|---|---|
| Level 1 ceiling void, grid E4–E7 | Asbestos insulating board (AIB) ceiling tiles | Good, undamaged | Low | Manage in place; label and inspect annually |
| Level 2 ceiling void above corridor C2 | AIB service riser lining | Good | Low | Manage in place |
| Basement plant room, pipe runs | Chrysotile pipe lagging (encapsulated) | Good, sealed | Low | Manage in place; permit required for any disturbance |
| Level 3 ceiling void, grid B2 | Textured coating to soffit | Good | Very low | Manage in place |
| Roof plant enclosure | Cement sheet panels | Weathered but sound | Low | Inspect at each roof access |

**Ceiling voids flagged as containing ACMs: Level 1 (grid E4–E7), Level 2 (corridor C2
riser), Level 3 (grid B2).** No ACMs identified in Level 4, Level 5 or Level 0 voids.

## Before any work above a ceiling

1. Consult this register before opening any void.
2. Where an ACM is listed, a permit to work is required and the Estates Compliance Team
   must be notified.
3. Contractors must confirm asbestos awareness training before access is granted.
4. Any suspected material not listed here: stop work, do not disturb, report immediately.
""",
    )

    # ── permits to work ──────────────────────────────────────────────────────
    docs["permit_to_work_register.md"] = _doc(
        "Permit to Work Register",
        building_name,
        f"""
## When a permit is required

A permit to work is required for: **hot works**, **roof access**, **confined space
entry**, **work on or above ceilings where asbestos is registered**, **electrical
isolation above 230 V**, and **work at height requiring anchor points**.

Hot works are controlled by permit **without exception**. A hot work permit requires a
fire watch during the work and for 60 minutes after completion.

## Roof access

Roof access requires a permit issued by the Estates Compliance Team on the day of the
work. A **harness permit** is required in addition wherever work takes place outside the
guarded walkway. Anchor points must be within certification (see the fall-arrest section).

## Last ten permits issued

| permit | type | date | area | status |
|---|---|---|---|---|
| PTW-2026-0412 | Hot works | {_d(6)} | Level 3 riser — pipe brazing | Closed, fire watch completed |
| PTW-2026-0411 | Roof access + harness | {_d(11)} | Roof plant enclosure — AHU filter change | Closed |
| PTW-2026-0410 | Electrical isolation | {_d(18)} | Basement distribution board | Closed |
| PTW-2026-0409 | Ceiling void (ACM) | {_d(24)} | Level 2 corridor C2 — cable pull | Closed |
| PTW-2026-0408 | Hot works | {_d(31)} | Basement plant room — welding | Closed, fire watch completed |
| PTW-2026-0407 | Roof access | {_d(38)} | Gutter clearance | Closed |
| PTW-2026-0406 | Work at height | {_d(45)} | Atrium light replacement (MEWP) | Closed |
| PTW-2026-0405 | Confined space | {_d(52)} | Cold water storage tank inspection | Closed |
| PTW-2026-0404 | Hot works | {_d(59)} | Level 1 — pipework repair | Closed, fire watch completed |
| PTW-2026-0403 | Roof access + harness | {_d(67)} | Abseil anchor inspection | Closed |

## Fall-arrest anchor points

| anchor set | location | last certified | next due | certified for abseil |
|---|---|---|---|---|
| A1–A6 | Roof parapet, north elevation | {_d(103)} | {_ahead(262)} | Yes |
| A7–A12 | Roof parapet, south elevation | {_d(103)} | {_ahead(262)} | Yes |
| A13–A16 | Atrium rooflight surround | {_d(392)} | **{_d(27)} — OVERDUE** | **No — do not use** |

Anchor sets A1–A12 are certified for the window-cleaning abseil. **A13–A16 are out of
certification and must not be used** until re-tested.
""",
    )

    # ── COSHH and LEV ────────────────────────────────────────────────────────
    docs["coshh_and_lev.md"] = _doc(
        "COSHH, Fume Cupboards and Local Exhaust Ventilation",
        building_name,
        f"""
## Thorough examination and test (TExT)

LEV plant, including fume cupboards, is examined at intervals not exceeding 14 months
(COSHH Regulation 9).

| unit | location | last TExT | next due | face velocity at test |
|---|---|---|---|---|
| FC-201 | Lab 2 | {_d(198)} | {_ahead(228)} | 0.52 m/s — within spec |
| FC-202 | Lab 2 | {_d(198)} | {_ahead(228)} | 0.49 m/s — within spec |
| FC-305 | Lab 3 | {_d(233)} | {_ahead(193)} | 0.47 m/s — within spec |
| FC-410 | Lab 4 | {_d(401)} | **{_ahead(25)}** | 0.51 m/s — within spec |
| LEV-B1 | Workshop bench extract | {_d(150)} | {_ahead(276)} | 0.8 m/s capture |

**Specification:** face velocity 0.4–0.7 m/s at the working sash height. A reading
outside that band takes the unit out of service until adjusted and re-tested.

The next fume cupboard examination due is **FC-410, {_ahead(25)}**.

## Hazardous materials held on site

| substance | location | quantity held | control |
|---|---|---|---|
| Ethanol (absolute) | Lab 2 flammables cabinet | 20 L | Flammables cabinet, COSHH assessment CA-014 |
| Acetone | Lab 3 flammables cabinet | 10 L | Flammables cabinet, CA-021 |
| Hydrochloric acid 37% | Lab 3 acid cabinet | 5 L | Acid cabinet, CA-009 |
| Sodium hydroxide pellets | Lab 3 | 2 kg | Sealed container, CA-011 |
| Liquid nitrogen | Level 4 cryostore | 160 L dewar | Oxygen depletion monitor, CA-030 |
| Compressed nitrogen | Level 4 gas store | 4 × 50 L cylinders | Chained, restricted access |
| Compressed CO₂ | Level 4 gas store | 2 × 50 L cylinders | Chained, restricted access |
| Diesel (generator) | External bunded tank | 990 L | Bunded, CA-002 |

Quantities are the maximum permitted holdings. The oxygen depletion monitor in the Level
4 cryostore is interlocked to the extract fan.
""",
    )

    # ── evacuation procedure, PEEPs (no personal data) ───────────────────────
    docs["evacuation_and_peeps.md"] = _doc(
        "Evacuation Procedure and Personal Emergency Evacuation Plans",
        building_name,
        f"""
## Personal Emergency Evacuation Plans (PEEPs)

A PEEP is prepared for any occupant who cannot evacuate unaided. Each plan names a
designated buddy and a refuge point, and is reviewed annually or on any change of
circumstance.

**This document does not list PEEP holders.** A PEEP identifies a named individual and
their disability; that is personal data, and it is held by the Estates Compliance Team
under restricted access, not in a building document. Aggregate figures only:

| | |
|---|---|
| Active PEEPs | 7 |
| With a designated buddy assigned | 7 |
| Reviewed within the last 12 months | 6 |
| Overdue review | 1 (Estates notified {_d(12)}) |

To ask about a specific plan, contact the Estates Compliance Team directly. A request for
the list of PEEP holders should be refused by any system holding this document.

## Refuge points

| refuge | location | comms | capacity |
|---|---|---|---|
| R1 | Level 1 stair core A landing | EVC handset | 2 wheelchair spaces |
| R2 | Level 2 stair core A landing | EVC handset | 2 wheelchair spaces |
| R3 | Level 3 stair core A landing | EVC handset | 2 wheelchair spaces |
| R4 | Level 4 stair core A landing | EVC handset | 2 wheelchair spaces |
| R5 | Level 5 stair core A landing | EVC handset | 2 wheelchair spaces |

Evacuation chairs are stationed at R2 and R4. Both were inspected on {_d(88)}.

## Enforcement history

No enforcement notices have been served on this building in the last five years. The most
recent fire authority audit was {_d(319)}, outcome **satisfactory**, with two advisory
items (signage refresh at the Level 0 rear exit, completed {_d(290)}; and a
recommendation to increase drill frequency, adopted).

## Drills

| date | type | evacuation time | outcome |
|---|---|---|---|
| {_d(58)} | Full unannounced | 4 min 20 s | Satisfactory |
| {_d(212)} | Full unannounced | 5 min 05 s | Satisfactory, sweep delay on Level 5 |
| {_d(392)} | Full announced | 4 min 48 s | Satisfactory |
""",
    )

    # ── contractor control ───────────────────────────────────────────────────
    docs["contractor_control.md"] = _doc(
        "Contractor Control and Site Induction",
        building_name,
        f"""
## Induction requirement

Every contractor working in the building holds a site safety induction valid for 12
months. Induction covers: fire procedure and assembly point, asbestos register awareness,
permit-to-work requirements, and reporting of incidents and near misses.

Access is refused where an induction has expired.

## Induction status — current contractors

| trade | firm reference | inducted | expires | status |
|---|---|---|---|---|
| Mechanical services | CTR-014 | {_d(96)} | {_ahead(269)} | Valid |
| Electrical | CTR-021 | {_d(141)} | {_ahead(224)} | Valid |
| Lift maintenance | CTR-008 | {_d(203)} | {_ahead(162)} | Valid |
| Fire alarm | CTR-032 | {_d(88)} | {_ahead(277)} | Valid |
| Cleaning | CTR-005 | {_d(310)} | {_ahead(55)} | Valid |
| Window cleaning (abseil) | CTR-041 | {_d(378)} | **{_d(13)}** | **EXPIRED** |
| Grounds and biodiversity | CTR-052 | {_d(160)} | {_ahead(205)} | Valid |
| Water hygiene | CTR-003 | {_d(119)} | {_ahead(246)} | Valid |

**One contractor induction is expired: the abseil window-cleaning firm (CTR-041), expired
{_d(13)}.** Access should not be granted until re-induction, which also matters for the
anchor-point permit in the permit register.

## Reporting

Near misses and incidents are reported to the Estates Compliance Team the same day. See
the incident and near-miss log for the current quarter.
""",
    )

    # ── planned maintenance and service schedules ────────────────────────────
    docs["service_schedules.md"] = _doc(
        "Planned Maintenance and Service Schedules",
        building_name,
        f"""
## Cleaning

| task | frequency | last completed | next due |
|---|---|---|---|
| Office and corridor cleaning | daily, overnight | {_d(1)} | {_ahead(1)} |
| Washroom servicing | twice daily | {_d(1)} | {_ahead(1)} |
| Carpet deep clean — Level 1 and 2 | 6 monthly | {_d(174)} | **{_ahead(8)}** |
| Carpet deep clean — Level 3 and 4 | 6 monthly | {_d(96)} | {_ahead(86)} |
| Carpet deep clean — Level 5 | 6 monthly | {_d(41)} | {_ahead(141)} |
| Window cleaning (external, abseil) | quarterly | {_d(71)} | {_ahead(20)} |
| Atrium glazing (internal) | 6 monthly | {_d(120)} | {_ahead(62)} |

**Carpets due deep cleaning this month: Levels 1 and 2 ({_ahead(8)}).**

## Drainage and catering

| asset | frequency | last | next |
|---|---|---|---|
| Grease trap, ground-floor cafe | quarterly | {_d(69)} | **{_ahead(22)}** |
| Kitchen extract duct clean | annual | {_d(281)} | {_ahead(84)} |
| Surface water gullies | 6 monthly | {_d(112)} | {_ahead(70)} |

**The grease trap is next due for emptying {_ahead(22)}.**

## Building services

| asset | frequency | last | next |
|---|---|---|---|
| AHU filter change (all units) | quarterly | {_d(11)} | {_ahead(80)} |
| Boiler service | annual | {_d(238)} | {_ahead(127)} |
| Chiller service | annual | {_d(150)} | {_ahead(215)} |
| Lift LOLER examination | 6 monthly | {_d(74)} | {_ahead(109)} |
| Emergency lighting duration test | annual | {_d(196)} | {_ahead(169)} |
| Fire alarm weekly test | weekly | {_d(3)} | {_ahead(4)} |
| PAT testing | annual | {_d(263)} | {_ahead(102)} |
""",
    )

    # ── building policies people actually ask about ──────────────────────────
    docs["building_policies.md"] = _doc(
        "Building Policies and House Rules",
        building_name,
        f"""
## Scented products

The building operates a **scent-aware policy**. Occupants are asked to avoid strong
fragrances, plug-in air fresheners and scented cleaning products in shared and
open-plan areas, in consideration of colleagues with asthma and chemical sensitivity.
Cleaning contractors use low-odour, fragrance-free products under contract CTR-005.
Concerns are raised with the building manager, who may ask a specific product to be
withdrawn from an area.

Adopted {_d(421)}, reviewed {_d(56)}.

## Animals in the building

Assistance dogs are welcome throughout the building, including laboratories where the
handler's risk assessment permits. Pet animals are not permitted, other than at
authorised events. No prior notice is required for an assistance dog.

## Photography and filming

Personal photography is permitted in public areas including the atrium. Photography is
not permitted in laboratories, of whiteboards or screens showing unpublished work, or of
people without their agreement. Commercial or press filming requires prior approval from
the building manager.

## Signage and language

Permanent building signage is in **English and Welsh**, in line with the Welsh Language
Standards. Fire and emergency signage uses pictograms to ISO 7010 in addition to text.
A **translation card** is held at reception covering fire evacuation, first aid and
accessible route instructions in Arabic, Mandarin, Polish and Spanish. Additional
languages can be arranged with notice through the reception team.

## Working alone

Lone working on Level 6 plant areas and in laboratories outside 08:00–18:00 requires
sign-in with Security and a check-call arrangement. Security holds the check-call
register and will escalate if a call is missed.

## Access outside core hours

Core hours are 07:00–19:00 on weekdays. Outside those hours the building is on card
access at the **main entrance only**; other entrances are locked and will not read a
card. Access to Level 4 laboratories outside core hours requires a laboratory-specific
permission on the card, arranged through the lab manager.
""",
    )

    # ── incidents and near misses ────────────────────────────────────────────
    docs["incident_and_near_miss_log.md"] = _doc(
        "Incident and Near-Miss Log",
        building_name,
        f"""
## This quarter

| date | location | type | description | status |
|---|---|---|---|---|
| {_d(9)} | Level 4 corridor | Near miss | Trip hazard — trailing cable from temporary AV rig | Closed, cable trunked |
| {_d(23)} | Ground-floor entrance | Near miss | Slip on wet floor, no warning sign | Closed, signage restocked |
| {_d(34)} | Level 2 kitchenette | Incident | Minor scald from hot tap | Closed, thermostatic valve adjusted |
| {_d(47)} | Loading bay | Near miss | Reversing delivery vehicle, no banksman | Closed, banksman now required |
| {_d(58)} | Level 5 stair core | Near miss | Fire door propped open during drill | Closed, retraining |
| {_d(66)} | Level 1 corridor | Near miss | Trip hazard — lifted carpet edge grid D3 | Closed, carpet repaired |
| {_d(78)} | Loading bay | Near miss | Delivery vehicle overheight for the entrance | Closed, height restriction signage added |
| {_d(81)} | Level 4 laboratory | Near miss | Chemical spill contained in tray | Closed, decant procedure revised |

**Clustering:** the loading bay accounts for two of the eight (both vehicle movement),
and Level 4 laboratories for one. Trip hazards account for three, in different locations.

## Service entrance

The service entrance has a **height restriction of 3.4 metres**, signed at the approach
and at the entrance itself. The near miss on {_d(78)} involved a vehicle at 3.6 m which
was turned away; additional advance signage was installed at the Maindy Road approach.
""",
    )

    return docs


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--building-id", default="")
    ap.add_argument("--name", default="", help="building name for the document headings")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    active = REPO / "input"
    if not (active / "building.yaml").is_file():
        print("no active building (input/ absent) — activate one first")
        return 1

    name = args.name
    if not name:
        try:
            import yaml

            cfg = yaml.safe_load((active / "building.yaml").read_text(encoding="utf-8")) or {}
            name = str(cfg.get("building_name") or cfg.get("building_id") or "this building")
        except Exception:
            name = "this building"

    out_dir = active / "documents"
    docs = documents(name)

    print(f"{len(docs)} compliance documents for {name!r} -> {out_dir}")
    for fname, text in sorted(docs.items()):
        print(f"  {fname:36s} {len(text):6d} chars")
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / fname).write_text(text, encoding="utf-8")

    if args.dry_run:
        print("\nDRY RUN — nothing written")
        return 0
    print(f"\nwritten. Restart the orchestrator (or POST a reindex) to index them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
