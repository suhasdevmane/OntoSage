---
record_type: stakeholder_group
owner: "Head of Estates Operations"
authority: "Cardiff University Estates - Abacws Building Management"
source_system: "Stakeholder Group Register"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Stakeholder group register"
    maps_to: stakeholder_groups
---

# Stakeholder Group Register - Abacws Building

## What this register records, and what it deliberately does not

Every other register in this building says what the building HOLDS. This one says who it is
FOR. The question bank is organised entirely around stakeholder groups, and questions of the
form *"which groups are affected by this, and who tells them?"* previously had nowhere to be
answered from.

Each row is a **group**, and a group is the finest grain this register goes to. No person is
named, no headcount is given and no individual attribute is recorded - identity is held at
role level throughout OntoSage, and a register of people would be the easiest possible place
to breach that.

Three columns carry most of the weight:

- **served_by** is a department code, not a name. It joins to the department directory, so a
  stakeholder question inherits a contact route, a response target and an out-of-hours route
  without restating any of them. Restating them would guarantee the two registers disagree
  within a year.
- **accountable_for** is deliberately **blank** for groups the building serves rather than
  groups that run it. That asymmetry is the point: *"who is accountable for this?"* must not
  return an answer for a visitor.
- **access_tier** is **advisory framing, not permission**. It says how far a group's access
  normally reaches so an answer can be pitched correctly. The PDP decides what is actually
  released, and a field in a document must never be mistaken for an access-control decision.

Both naming schemes are present. The building's question bank uses 37 current group names
and 45 earlier ones for the same functions, so the earlier labels are kept as their own rows
and marked in the note. Collapsing them would leave questions tagged with the old name
unmatched.

## Stakeholder group register

| code | name | category | primary_need | served_by | accountable_for | access_tier | presence | data_needs | status | note |
|---|---|---|---|---|---|---|---|---|---|---|
| SH-01 | Undergraduate students | Occupant | Finding somewhere suitable to study between classes | DEP-20 |  | Occupant | Term weekdays 09:00-18:00, peaks in assessment weeks | Study space availability, opening hours, quiet areas, power and Wi-Fi, travel time between levels | Active | Largest group by headcount; almost every question is about space, not systems |
| SH-02 | Taught postgraduate students | Occupant | Longer blocks of focused study and group work | DEP-20 |  | Occupant | Term weekdays and some weekends, long sessions | Bookable rooms, quiet study, group space, opening hours, environmental comfort | Active | Ask for whole days rather than gaps between classes |
| SH-03 | PhD students | Occupant | A reliable, quiet base and space for remote supervision | DEP-19 |  | Occupant | Most weekdays, irregular hours, some evenings | Quiet workspace, bookable rooms for calls, network reliability, environmental stability | Active | The only occupant group asking about environmental change over a term |
| SH-04 | Research staff | Occupant | Confidential calls and uninterrupted analysis time | DEP-19 | Their own research equipment and data | Staff | Weekdays, project-driven peaks | Bookable private rooms, network quality, equipment status, lab access | Active | Confidentiality is the recurring requirement, not comfort |
| SH-05 | Lecturers and tutors | Occupant | Teaching rooms that work, and time to move between them | DEP-08 | Delivery of scheduled teaching | Staff | Teaching weeks, fixed timetable slots | Room readiness, AV status, travel time between rooms, room conditions before class | Active | Need a readiness answer BEFORE a class, not a diagnosis after it |
| SH-06 | Academic office occupants | Occupant | A workable office environment | DEP-01 |  | Staff | Weekdays 08:00-18:00 | Temperature, ventilation, noise, lighting, local fault reporting | Active |  |
| SH-07 | Professional-services staff | Occupant | Getting administrative work done and supporting others | DEP-01 | Their service area | Staff | Weekdays 09:00-17:00 | Room bookings, building notices, contact routes, service status | Active |  |
| SH-08 | New starter | Occupant | Orientation: where things are and how things work | DEP-18 |  | Occupant | First weeks, weekdays | Wayfinding, amenities, access, who to contact, local procedure | Active | Every question assumes no prior knowledge of the building |
| SH-09 | Student | Occupant | General student use of the building | DEP-20 |  | Occupant | Term weekdays | Study space, amenities, timetable, procedures | Active | Earlier, coarser label for SH-01 to SH-03 |
| SH-10 | Occupant | Occupant | Day-to-day comfort and amenity | DEP-01 |  | Occupant | Weekdays | Comfort, amenities, wayfinding, how-to procedures | Active | Earlier general label retained because questions are tagged with it |
| SH-11 | Facilities managers | Operations | Keeping the building running and deciding what to fix first | DEP-01 | Building operation and service delivery | Operational | Weekdays, on call for escalations | Fault history, asset status, complaint clustering, plant performance, cost | Active | Ask diagnostic questions that span rooms, plant and complaints at once |
| SH-12 | Facility manager | Operations | Building operation and priority decisions | DEP-01 | Building operation | Operational | Weekdays | Readings, trends, anomalies, maintenance state | Active | Earlier singular label for SH-11 |
| SH-13 | BMS-HVAC operators | Operations | Keeping plant within its operating envelope | DEP-02 | HVAC control strategy and setpoints | Operational | Weekdays, remote alarm response | Setpoints, control loops, plant status, alarm history, zone conditions | Active |  |
| SH-14 | Mechanical and electrical engineers | Specialist | Understanding what plant was designed for and what it delivers | DEP-02 | Plant integrity and safe isolation | Operational | Weekdays, planned works out of hours | Design duty, commissioned duty, isolation points, service routes, asset tags across systems | Active | The gap here is engineering depth, not access |
| SH-15 | Maintenance technician | Operations | Completing jobs safely and correctly | DEP-02 | Work carried out | Operational | Shift-based weekdays | Work orders, asset location, isolation, permits, spares | Active |  |
| SH-16 | Cleaning and caretaking teams | Operations | Knowing the round, the standard and what changed | DEP-04 | Cleanliness and readiness of assigned zones | Operational | Early and late shifts, Mon-Fri 05:00-20:00 | Zone task lists, standards, suspensions, room resets, waste points | Active |  |
| SH-17 | Cleaner | Operations | The round for this shift | DEP-04 | Assigned zone | Operational | Early shift | Task list, zone, standard | Active | Earlier singular label for SH-16 |
| SH-18 | Porter | Operations | Moves, deliveries and setups | DEP-01 | Items moved | Operational | Weekdays | Room setups, delivery points, access, lift availability | Active |  |
| SH-19 | Grounds staff | Operations | External areas and approaches | DEP-01 | External grounds | Operational | Weekday mornings | External routes, bin store, gritting, external lighting | Occasional |  |
| SH-20 | Security officers | Operations | Knowing what is happening now and who may be where | DEP-03 | Building security and incident response | Restricted | 24/7 shifts | Door state, alarm activations, patrol checkpoints, incident log, camera coverage | Active | The only group present at every hour |
| SH-21 | Security | Operations | Security operations | DEP-03 | Security | Restricted | 24/7 | Access events, alarms, patrols | Active | Earlier label for SH-20 |
| SH-22 | Access-control administrators | Operations | Granting the smallest access that does the job | DEP-03 | Permission groups and credential lifecycle | Restricted | Weekdays | Permission groups, role templates, inheritance, overrides, expiry, approval routes | Active | Ask about the management layer, not the physical readers |
| SH-23 | Receptionist | Operations | Directing visitors and handling arrivals | DEP-18 | Visitor reception | Staff | Weekdays 07:30-18:00 | Visitor expectations, wayfinding, room locations, contact routes, deliveries | Active |  |
| SH-24 | Waste-management teams | Operations | Right stream, right point, collected on time | DEP-12 | Waste streams and duty of care | Operational | Weekday mornings | Collection points, fill levels, stream conflicts, collection schedule, contractor performance | Active |  |
| SH-25 | Room-booking team | Operations | Allocating bookable space without conflict | DEP-10 | Bookable room allocation | Staff | Weekdays 09:00-17:00 | Bookings, room attributes, capacity, clashes, no-shows | Active |  |
| SH-26 | Timetabling team | Operations | Fitting teaching into rooms that suit it | DEP-09 | Teaching room allocation | Staff | Weekdays, semester peaks | Timetabled sessions, room capacity and attributes, clash detection, utilisation | Active | Reduced cover outside term |
| SH-27 | Teaching and audiovisual support team | Operations | Rooms ready to teach in | DEP-08 | AV and teaching technology readiness | Operational | Weekdays 08:00-18:00, teaching weeks | AV component state, evidence of last check, hearing loops, lecture capture, fault history | Active | One-hour response target during teaching weeks |
| SH-28 | IT, network, and server-infrastructure teams | Specialist | Network and server-room reliability | DEP-07 | Network, Wi-Fi and server room environment | Operational | Weekdays, on-call out of hours | Switch and AP status, server room temperature and power, cabling routes, capacity | Active | Server-room environmental alarms come here before Estates |
| SH-29 | IT manager | Specialist | IT service delivery in the building | DEP-07 | IT services | Operational | Weekdays | Network status, server room conditions, incidents | Active | Earlier label for SH-28 |
| SH-30 | Health and safety officers | Specialist | Evidence that the building is operated safely | DEP-05 | Risk assessment and safe systems of work | Operational | Weekdays | Risk assessments, incidents, near misses, COSHH, LEV, contractor controls, permits | Active |  |
| SH-31 | Safety officer | Specialist | Safety oversight | DEP-05 | Safety | Operational | Weekdays | Air quality, occupancy limits, alarms, incident reports | Active | Earlier label for SH-30 |
| SH-32 | Fire-safety personnel | Specialist | Fire precautions demonstrably in working order | DEP-06 | Fire precautions and evacuation readiness | Operational | Weekdays, drills scheduled | Alarm tests, detection coverage, doors and compartmentation, extinguisher service, drills, PEEPs | Active | A missed weekly alarm test is reportable |
| SH-33 | Emergency coordinators | Specialist | Knowing the building is ready before anything happens | DEP-16 | Incident coordination and continuity | Restricted | On call 24/7 | Coordination roles, activation criteria, fallback arrangements, refuge points, roll call | Active |  |
| SH-34 | Emergency responders | External | A fast, accurate picture on arrival | DEP-03 |  | Restricted | On incident only | Access routes, riser and shaft locations, isolation points, occupancy, refuge points, hazards | Active | Need the answer in seconds, and only the load-bearing facts |
| SH-35 | Fire service liaison | External | Pre-planning and site familiarity | DEP-06 |  | Restricted | Scheduled visits | Building layout, access, hydrants, risers, hazards, compartmentation | Occasional |  |
| SH-36 | Accessibility, inclusion, and well-being teams | Specialist | A building usable by everyone in it | DEP-13 | Reasonable adjustments and inclusive access | Staff | Weekdays | Step-free routes, lift status, hearing loops, accessible facilities, PEEPs, sensory conditions | Active |  |
| SH-37 | Accessibility officer | Specialist | Accessibility compliance and adjustments | DEP-13 | Accessibility | Staff | Weekdays | Routes, adjustments, verified accessibility features | Active | Earlier label for SH-36 |
| SH-38 | People with mobility, sensory, or other accessibility requirements | Occupant | Getting where they need to go, reliably | DEP-13 |  | Occupant | Whenever the building is open | Step-free routes, lift state, door operation, hearing loops, rest points, quiet routes | Active | A route that is usually step-free is not the same as one that is step-free now |
| SH-39 | Energy, carbon, and sustainability teams | Specialist | Reducing consumption and evidencing progress | DEP-11 | Energy and carbon performance | Staff | Weekdays | Meter data, tariffs, consumption trends, carbon targets, baselines, project savings | Active | Advisory: faults go to M and E, not here |
| SH-40 | Energy manager | Specialist | Energy performance | DEP-11 | Energy | Staff | Weekdays | Consumption, tariffs, trends | Active | Earlier label for SH-39 |
| SH-41 | Sustainability officer | Specialist | Carbon and efficiency | DEP-11 | Sustainability targets | Staff | Weekdays | Consumption, carbon, comparisons | Active | Earlier label for SH-39 |
| SH-42 | Space-planning teams | Specialist | Using space well and planning change | DEP-15 | Space allocation standards | Staff | Weekdays | Areas, capacity, occupancy, utilisation, adjacency, move planning | Active |  |
| SH-43 | Space planner | Specialist | Space allocation | DEP-15 | Space standards | Staff | Weekdays | Area, occupancy, utilisation | Active | Earlier label for SH-42 |
| SH-44 | University estates and asset-management teams | Specialist | Asset condition and lifecycle decisions | DEP-01 | Asset register and lifecycle | Staff | Weekdays | Condition surveys, remaining life, replacement cost, criticality, backlog | Active |  |
| SH-45 | Asset manager | Specialist | Asset lifecycle | DEP-01 | Assets | Staff | Weekdays | Condition, life, cost | Active | Earlier label for SH-44 |
| SH-46 | Researchers and data scientists | Specialist | Data good enough to draw a conclusion from | DEP-19 | Their own study design | Staff | Weekdays, project-driven | Sensor coverage, sampling interval, gaps, calibration, comparable rooms, operating regimes | Active | Ask about the DATA's fitness, not the building's state |
| SH-47 | Researcher | Specialist | Querying the building's data | DEP-19 |  | Staff | Weekdays | Raw readings, ontology, classes | Active | Earlier label for SH-46 |
| SH-48 | Lab manager | Specialist | Safe, compliant laboratory operation | DEP-19 | Laboratory operation | Operational | Weekdays | LEV test state, COSHH, equipment status, access control, environmental limits | Active |  |
| SH-49 | BMS engineer | Specialist | Control system configuration and diagnosis | DEP-02 | Control strategy | Operational | Weekdays | Points, loops, schedules, alarms, trends | Active |  |
| SH-50 | Commissioning agent | External | Proving systems perform as designed | DEP-02 | Commissioning evidence | Operational | Project phases | Design intent, commissioning results, witness records, setpoints, acceptance criteria | Occasional |  |
| SH-51 | Retrofit consultant | External | Finding and sizing improvement opportunities | DEP-11 | Retrofit recommendations | Staff | Project phases | Fabric performance, consumption baselines, plant efficiency, occupancy patterns | Occasional |  |
| SH-52 | Architects and building designers | External | Understanding what exists before changing it | DEP-15 | Design proposals | Staff | Project phases | Geometry, areas, services routes, structural constraints, survey dates and authority | Occasional | Need to know how OLD the record is, not just what it says |
| SH-53 | Regulatory and institutional compliance teams | Governance | Evidence that obligations are met | DEP-17 | Statutory compliance evidence | Staff | Weekdays | Inspection records, certificates, due dates, overdue items, evidence references | Active |  |
| SH-54 | Auditors and certification assessors | Governance | A traceable evidence chain, not an assertion | DEP-17 |  | Staff | Scheduled audits | Evidence references, dates, authority, approval routes, exceptions and their justification | Occasional | Ask what PROVES a claim, not what the claim is |
| SH-55 | Auditor | Governance | Audit evidence | DEP-17 |  | Staff | Scheduled audits | Records, evidence, exceptions | Occasional | Earlier label for SH-54 |
| SH-56 | Insurers and risk assessors | Governance | Where loss would concentrate and what is unwatched | DEP-17 |  | Staff | Annual and on claim | Asset value concentration, criticality, inspection intervals, blind spots, temporary exposures | Occasional | Ask about what is NOT observed as much as what is |
| SH-57 | Insurance assessor | Governance | Risk and claim assessment | DEP-17 |  | Staff | On claim | Asset value, condition, incident history | Occasional | Earlier label for SH-56 |
| SH-58 | School leadership, university leadership, and building owners | Governance | Whether the building is serving its purpose | DEP-20 | Strategic decisions about the building | Staff | Weekdays | Utilisation, cost, carbon, condition, risk, headline performance | Active | Want the decision-relevant summary, not the readings |
| SH-59 | Executive | Governance | Headline performance | DEP-20 | Strategic decisions | Staff | Weekdays | KPIs, summaries | Active | Earlier label for SH-58 |
| SH-60 | Finance and procurement teams | Governance | Controlling spend and honouring contracts | DEP-14 | Budgets, contracts and payment | Staff | Weekdays | Cost lines, budgets, commitments, contract terms, supplier performance, variances | Active |  |
| SH-61 | Finance | Governance | Budget control | DEP-14 | Budget | Staff | Weekdays | Costs, budgets, spend | Active | Earlier label for SH-60 |
| SH-62 | Tenant representative | Governance | Service and cost for the space they occupy | DEP-01 | Their occupied space | Staff | Weekdays | Service charge, condition, service performance, planned works | Occasional |  |
| SH-63 | Staff representative | Governance | Working conditions for the people they represent | DEP-05 |  | Staff | Weekdays | Environmental conditions, incidents, consultation on change | Occasional |  |
| SH-64 | HR / wellbeing | Governance | Conditions that affect people's wellbeing | DEP-05 |  | Staff | Weekdays | Environmental comfort, quiet space, accessibility, incident patterns | Occasional |  |
| SH-65 | External maintenance contractors | External | Doing the work safely under someone else's rules | DEP-02 | Work they carry out | Operational | Scheduled visits | Permits, isolation points, asset location, site rules, induction, access windows | Active | Governed by permit; access is time-bounded |
| SH-66 | Contractor | External | Carrying out contracted work | DEP-02 | Contracted work | Operational | Scheduled visits | Permits, access, site rules | Active | Earlier label for SH-65 |
| SH-67 | Visitors and event attendees | Visitor | Getting in, finding the room, and knowing what changed | DEP-18 |  | Visitor | Event-driven | Entrance to use, opening times, step-free route, registration, event changes, amenities | Active | Have no prior knowledge and no account |
| SH-68 | Visitor | Visitor | Wayfinding and access | DEP-18 |  | Visitor | Occasional | Entrance, route, amenities | Active | Earlier label for SH-67 |
| SH-69 | Prospective students and family members | Visitor | Deciding whether this is the right place | DEP-18 |  | Public | Open days and tours | Facilities, study space, accessibility, opening hours, what the building is for | Occasional | Ask evaluative questions, not operational ones |
| SH-70 | Journalist | External | A factual account for publication | DEP-18 |  | Public | Occasional | Published facts, official position, named contact | Occasional | Answered from published material and the official channel only |
| SH-71 | Delivery driver | External | Getting the delivery to the right place | DEP-18 |  | Visitor | Weekday mornings | Delivery point, access hours, contact, lift availability | Active |  |
| SH-72 | Catering staff | External | Running catering for events and daily service | DEP-01 | Catering operation | Staff | Event-driven and weekday service | Kitchen extract state, grease trap schedule, waste streams, event schedule, access | Active |  |
| SH-73 | Event coordinator | External | An event that runs without surprises | DEP-10 | Event delivery | Staff | Event-driven | Room capacity, AV readiness, access, registration, entrances, contingency | Active |  |
| SH-74 | Exam invigilator | External | Exam conditions that hold for the whole session | DEP-09 | Exam session conduct | Staff | Exam periods | Room conditions, noise, clock, access control, incident escalation | Occasional |  |
| SH-75 | Curator | External | Display and exhibition conditions | DEP-01 | Exhibits | Staff | Exhibition periods | Environmental stability, lighting, security, access | Occasional |  |
| SH-76 | Comms team | External | Accurate, timely information to the right audiences | DEP-18 | Published information | Staff | Weekdays | Confirmed status, official position, affected groups, timing | Active |  |
| SH-77 | Executive assistant | External | Arranging things on someone else's behalf | DEP-10 |  | Staff | Weekdays | Room bookings, access for guests, event logistics | Occasional |  |
| SH-78 | Waste contractor | External | Collecting the right streams on schedule | DEP-12 | Collection and disposal | Visitor | Scheduled collections | Collection points, streams, access windows, duty of care documentation | Active |  |
| SH-79 | Window cleaner | External | Safe external access | DEP-01 | Work carried out | Visitor | Quarterly | Abseil anchor points, permits, access windows, weather constraints | Occasional |  |
| SH-80 | Pest control | External | Monitoring and treatment | DEP-04 | Treatment carried out | Visitor | Scheduled visits | Bait point locations, activity records, access, food areas | Occasional |  |
| SH-81 | Car park attendant | External | Managing vehicle access | DEP-03 | Car park operation | Staff | Weekdays | Barrier state, permits, accessible bays, EV chargers | Occasional |  |
| SH-82 | Sports facility manager | External | Operating shared sports space | DEP-01 | Sports facility | Staff | Weekdays and evenings | Booking, condition, access, environmental limits | Occasional |  |

**82 groups: 20 specialist, 20 external, 16 operations, 12 governance, 11 occupant, 3 visitor. Only three groups (security officers, emergency coordinators and emergency responders) have any expectation of the building outside working hours, and eight of the twenty departments that serve these groups have no out-of-hours route at all.**
