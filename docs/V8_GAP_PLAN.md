# V8 — what to build next, measured

Derived from the first ever capture of the 2,480 stakeholder-catalogue questions
(`scripts/outputs/baseline/baseline_20260903_152449.csv`), joined to
`docs/V7_question_demand.csv` and live readiness. Regenerate with
`python scripts/analyse_stakeholder_capture.py`.

## Where the system stands

| outcome | share |
|---|---:|
| **Computed** — figures from the building | **36.4%** |
| Quoted — a passage, not a calculation | 20.5% |
| Honest decline — correct where data is absent | 31.0% |
| Failed / wrong | 8.7% |
| Unmeasured (timeout) | 3.4% |

87.9% of questions get an acceptable response and 8.7% genuinely fail. The interesting
number is not the failure rate — it is that **only 36.4% compute**.

## Why the rest do not compute, and it is not what V7 assumed

V7 recorded the remaining gap as *routing*: "99 of 111 questions have every source they
need as DATA and only 33% compute". Measured across 2,393 questions that reads the same way
at first — 1,113 non-computed questions name only systems marked DATA — **and the
classification is wrong, because readiness measures presence, not sufficiency.**

`access_control` is marked DATA on **7 instances**. Those seven are physical readers and a
turnstile. The 277 non-computed questions naming it ask about credentials, permission
groups, enrolment, stock reconciliation and containment after a lost card — the *management*
layer, of which the ontology holds nothing. The lane declines, correctly and honestly:

> *"I don't have that specific information on record for Abacws Building."*

That is not a routing defect. It is a **depth** defect, and the fix is the mechanism V7
already built: a Record Document, lifted to queryable RDF at ingest, needing no code.

## The ranking

Questions-per-instance is the shallowness signal: high demand against a token presence.
Counts overlap, because a question names several systems.

| source system | readiness | instances | non-computed Qs | Qs/instance |
|---|---|---:|---:|---:|
| `timetable` | WIRED | 0 | 119 | ∞ |
| `hr_identity` | ABSENT | 0 | 100 | ∞ |
| `weather_external` | WIRED | 0 | 79 | ∞ |
| `access_control` | DATA | 7 | **277** | 39.6 |
| `it_network` | DATA | 8 | **286** | 35.8 |
| `accessibility` | DATA | 8 | **241** | 30.1 |
| `finance_cost` | DATA | 4 | 101 | 25.2 |
| `contract_warranty` | DATA | 8 | 184 | 23.0 |
| `project_handover` | DATA | 9 | 185 | 20.6 |
| `cmms_work` | DATA | 6 | 116 | 19.3 |
| `policy_governance` | DATA | 15 | **283** | 18.9 |
| `fire_life_safety` | DATA | 9 | 168 | 18.7 |
| `booking` | DATA | 16 | 252 | 15.8 |
| `permit_control` | DATA | 15 | 234 | 15.6 |

## The work, in order

Each register is three files and no code: a mapping in `ontology/record_documents/`, a
document in `input/documents/`, and the class in Module R of `ontology/ontosage_schema.ttl`
with its `ontosage:layTerms`. That is the standard V7-T18 built and ten registers already
use.

1. **`it_network` register** — 286 questions. Network coverage, wireless cells, ports,
   outages, service owners.
2. **`policy_governance` deepening** — 283 questions. 15 instances against questions about
   approval routes, exceptions, review cycles and accountable owners.
3. **`access_control` register** — 277 questions. Credentials, permission groups, reader
   estate, enrolment, stock reconciliation, containment steps.
4. **`booking` deepening** — 252 questions. 16 bookings exist; questions ask about release
   status, cancellation, conflicting holds.
5. **`accessibility` register** — 241 questions. Routes, equipment, PEEPs, provisions.
6. **`permit_control` deepening** — 234 questions.
7. **`hr_identity` at ROLE level only** — 100 questions. V7-T35 holds person records
   deliberately and the catalogues forbid exposing who holds what; role templates,
   entitlements and affiliations carry no person data and answer the questions asked.
8. **`timetable` feed** — 119 questions. NOTE-413: the feed is enabled, its CSV is 55 KB,
   and it has never written a row.

## A calibration: not every non-computed question should compute

`policy_governance` ranks third by demand (283 questions), and inspecting them changes what
that number means. Excluding the access-control role, 243 of them read like this:

> *"Where should public, shared, controlled and restricted zones begin and end?"*
> *"Which conflicts between user experience, operations, maintenance, security, cost and
> programme requirements should the design resolve?"*

Those belong to architects and designers, and they ask for **judgement**, not for a figure.
A register cannot answer them and should not pretend to; a reasoned synthesis over declared
constraints, or an honest decline naming what the building can offer instead, is the correct
outcome. Counting them as a coverage gap would push the system toward confident answers to
questions that have no data answer — the exact failure contract 4 forbids.

So the ranking is a demand signal, not a work order. Each row needs its questions read
before it becomes a task, which is why the three registers built first
(`cleaning_task`, `public_event`, `access_permission`) were chosen from the questions of the
worst-served ROLES rather than from the top of the system table.

## Built so far

| register | records | questions it targets | verified |
|---|---:|---|---|
| `cleaning_task` | 30 | cleaning and caretaking, 19% computed | shift task lists, suspensions, handovers |
| `public_event` | 12 | visitors and event attendees, 16% | admission, check-in, entrance, venue changes |
| `access_permission` | 20 | access-control administrators, 20% | permission groups, inheritance, overrides |
| `accessible_route` | 16 | accessibility users, 34% | verified routes, rests, doors, lifts, quiet options |

All four went live with **no code change** — mapping, document, TBox class — once BUG-417
stopped a hardcoded Python tuple from deciding which record classes the building was allowed
to hold.

## Result: the four registers, re-measured

Same 320 questions, same grader, same model (`local/gpt-oss:20b`). Full report in
`docs/V8_REMEASURE.md`.

| role | n | computed before | computed after | change |
|---|---:|---:|---:|---:|
| Access-control administrators | 80 | 20% | **66%** | +46 pts |
| Visitors and event attendees | 80 | 19% | **59%** | +40 pts |
| People with mobility, sensory or other needs | 80 | 34% | **52%** | +19 pts |
| Cleaning and caretaking teams | 80 | 20% | **44%** | +24 pts |
| **all four** | **320** | **23%** | **55%** | **+32 pts** |

**115 questions began computing.** Twelve were reported as regressions and reading all
twelve leaves at most six: four are the grader marking a computed answer as an honest
decline because it carries a qualifying sentence (CAVEAT-418), two are the referent gate
reading "verified corridor" as a place name (CAVEAT-419), and three are genuine failures
including one empty answer.

So **+32 points is a floor, not a ceiling** — the grader currently under-counts computed
answers, which is the safer direction to be wrong in.

Every point of that came from four documents, four mappings and four TBox classes. No lane
was rewritten. What made it possible was BUG-417: until a hardcoded Python tuple stopped
deciding which record classes the building was allowed to hold, none of it was reachable.

## Not to be done

- Person records, under any register. V7-T35, and the catalogues are explicit.
- Re-extracting the six occupant catalogues: they are already in the bank under
  `supervisor_catalogue_2026-08` (CAVEAT-416, corrected).
