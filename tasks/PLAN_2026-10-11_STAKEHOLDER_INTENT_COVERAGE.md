# Plan — stakeholder intent coverage for bldg1 (11 Oct 2026, ~20 h autonomous)

**Owner's brief (paraphrased):** any building user, with or without technical knowledge, can ask
anything about Abacws and get a correct answer through Open WebUI; fewer honest declines, by adding
the data those questions need (TTL, registers, synthetic series topped up by scripts); keep every
existing facility; work alone, use my recommendations; the owner reviews and commits afterwards,
then the study (30 participants) and the article begin.

## Constraints that do not move

- Nothing is committed, pushed or tagged. bldg1 stays running.
- **Study protection.** No data or TTL change touches a study referent, and no historical rewrite of
  the windows study forms read (real Floor 5 data 1 Jan – 9 Mar 2025; generated 2026 data before
  3 Oct 2026). New data goes forward from now, or into registers/points no study form reads. Code
  changes are general capabilities, verified on development forms S1-D…S4-D and my own questions,
  never on a study form. The repo is public: no study room, date, wording or answer anywhere.
- Bank questions (`docs/smart_building_questions.csv`, 2,960 catalogue + 1,100 synthetic) are never
  printed: counts, lanes and answers only. The catalogue is a development input, never evidence.
- QA accounts only (e.g. `facility03@example.com`); never the study accounts.
- Every routing or vocabulary rule is measured on the 4,060 bank (moves counted) and on the 56 study
  texts (counts only) before it is kept.
- The regression gate and the unit suite run alone. Python source is written with the file tools,
  never a heredoc. Format only files that were black-clean at HEAD, or new files.

## Measures

| Measure | What it says | Baseline | After |
|---|---|---|---|
| M1 role-stratified bank sample (4 per catalogue role + 60 synthetic = 208, seed 20261011, excludes bank samples v1-v3) | decline rate by stakeholder group (includes CORRECT declines) | **50/208 = 24.0%**, 0 errors, median 15.2 s (`outputs/qa_probe/m1_baseline.jsonl`) | — |
| M2 own pools per stakeholder group (written here, hand-read) | correct / honest decline / false decline / wrong | — | r7: 142 q, 23 flagged; hand-read wrong answers listed in the probe record, 7 fixed, 6 deferred (study) |
| M3 conversation batteries (r5, r6, r7) | follow-up defects | r5 10/20, r6 7 | — |
| M4 regression gate (51) | nothing that worked broke | 51/51 in substance | **50/51 recorded, 51/51 in substance** (#37 the known fresh-chat recall case), 08:50, alone |
| M5 unit suite (active) | code health | 15,583 / 2 / 30 (known set) | **15,746 pass / 7 fail / 30 error / 79 skip** (63 min, alone): 2 + 30 the known state-dependent set, **5 caused by this round and fixed** (re-run 200/200 green; the full suite was NOT re-run after) |
| M6 dev forms S1-D…S4-D | study-shaped questions still right | all correct (10 Oct) | — |

## Work items (status kept here)

| ID | Item | Status |
|---|---|---|
| W1 | Baseline M1 + decline clustering (from answer text: what is missing) | done: diagnosis 6/6 declined (BUG-1636), compare/trend on records 8 (BUG-1638), a false 'no energy sensors' (BUG-1631), 'StudyArea' as a room (BUG-1632), anonymous series (BUG-1639); 5 are correct 'which room is this?' clarifications |
| W2 | Artifacts in Open WebUI: charts, floor plans, reports/exports load on this machine and by LAN | done on this machine: charts (PNG), floor plans now INLINE (PNG render + PDF link, no IRI), CSV/PDF/Word exports written and LINKED (BUG-1644/1645). LAN/tunnel still needs STATIC_BASE_URL (CAVEAT-1527) |
| W3 | Weekday / day-month without year resolved deterministically (CAVEAT-1616), general | done, verified live (solar on Wednesday 31 kWh; CO2 on 7 October) |
| W4 | Data for honest declines, by cluster: TTL / registers / documents / synthetic points + publisher | water meter series + totals + COST (TODO-1633/1646, verified live); kitchens with the catering topic's microwaves (TODO-1634); tariff rate units (TTL); lockers/vending/UPS left to owner (NOTE-1635) |
| W5 | Own pools per stakeholder group (13 groups x ~12), read, fix routing / intent classes | todo |
| W6 | Conversation battery r7 per stakeholder group | todo |
| W7 | Open caveats from rounds 5-6: 1617, 1618, 1619, 1627, 1628, 1629, 1630 | all seven fixed; 1617/1619/1628/1629 verified live; 1618 partial live (toilets listed, baby changing not recorded) |
| W8 | Re-measure M1-M6, tracker, docs (probe record, CLAUDE.md, work log), memory | todo |

## Stakeholder groups (from the 37 catalogue roles)

1. Students and academics (UG, PGT, PhD, research staff, lecturers, office occupants)
2. Visitors, prospective students, event attendees
3. Accessibility and well-being (people with access needs, inclusion teams)
4. Facilities, estates and asset management, external contractors
5. BMS/HVAC operators, mechanical and electrical engineers
6. Energy, carbon and sustainability; leadership and owners; finance and procurement
7. Safety and security (H&S, fire safety, emergency coordinators and responders, security, access control)
8. Cleaning, caretaking and waste
9. Space and timetabling (room booking, timetabling, space planning, AV support, professional services)
10. IT, network and server infrastructure
11. Researchers and data scientists
12. Assurance (auditors, certification, compliance, insurers)
13. Architects and designers

## Log

(appended as work proceeds)

- **M1 baseline** (before any of today's fixes were deployed): 50/208 declined. By group: IT 3/5, BMS/M&E 5/11,
  facilities 7/22, space/timetabling 8/24, students/academics 10/37, visitors 3/14, accessibility 2/9,
  energy/finance 4/18, cleaning/waste 2/12, safety/security 3/28, researchers 1/8, assurance 1/12,
  architects 0/4. By lane: sparql/metadata 15/112, capability 6/29, deliberate 5/18, diagnosis 6/6.
- **Not authored, on purpose:** printers, lockers, vending machines, a UPS (NOTE-1635). A location invented
  for a real building is a plausible wrong answer someone can walk to; the owner supplies them.
- **Deployed 05:15 (local)**: orchestrator restart (4 TTLs uploaded: schema, hbco mappings, water meter,
  kitchenettes; the map gave the water meter its shape), publisher image rebuilt, four caches flushed.

- **Batches 2-5 (05:30-07:15 local)**, each restarted, flushed and re-asked live:
  - water: building meter bound alone (BUG-1640: it had been summed with its 18 floor meters);
    modality `water_usage` declares `Building_Water_Meter`; volume totals summed like energy ->
    "3,449 L (3.4 m³)" yesterday, week on week "66,882 L against 66,494 L" (BUG-1647 units);
  - cost: `utility_cost` prices a metered total at the tariff in force -> water £130.09 last week,
    electricity £699.79 yesterday (incl. standing charge), "rates exclude VAT";
  - referent gate: step-asides no longer read as "check did not complete" (BUG-1643); "the glass
    atrium" is BOUND to Room 1.04 with a footnote (CAVEAT-1629);
  - routing: diagnosis without a quantity -> metadata (BUG-1636); compare/trend of records ->
    metadata (BUG-1638; its first version misfired on meters and was fixed the same hour); a
    readings question naming a file format -> export; metered day/week cost -> analytics.
    **Rules now 68 parse + 4 post + 8 concept.**
  - exports: linked, in the named format, sensors named, documents carry figures (BUG-1644).
- **Boot halted three times** on a new TTL missing `@prefix bldg:` (validator HARD_FAIL). Rule
  from now on: run `ttl_validator.validate_building_ttls` offline before any restart that adds a TTL.
- r7 pool: first 44 answers on the pre-batch build kept as `r7_pool_partial_pre_b5`; full pool
  re-run on the batch-5 build.
- **Afternoon (local 10:40-12:40)**: the 13 stakeholder conversations (`docs/phase0/conversations_r7/`)
  re-run on the batch-5 build and read in full. First turns mostly right; **follow-ups broke**.
  Fixed and re-asked live: an energy total dated in an invented year (BUG-1664, P1 — the aggregate
  lane now sums a completed period; a narration year its sources do not hold is corrected); "compare
  with the week before" and "which floor used the most?" resolved deterministically from the user's
  own earlier question (BUG-1665/1666); "for last week" is the calendar week (BUG-1667, 3 bank
  questions move); "how long has CO2 been recorded?" answered from the stores with its gaps
  (TODO-1668, `services/record_span.py`); "due this month" reads the due date (BUG-1660); a rewrite's
  restated period no longer leaks as an unrecorded word (BUG-1663); the class a question names
  outranks a rarer one (BUG-1662, server room temperature had been answered with humidity); topic
  answers quote sentences, not a chunk (BUG-1661); a visitor's arrival question answers from the
  visitor policy (BUG-1669); energy comparisons name floors and compare totals (BUG-1670).
  Open: TODO-1672 (AHU supply/return "normal"), CAVEAT-1673 (125 m² restroom polygon), TODO-1674,
  TODO-1675.
