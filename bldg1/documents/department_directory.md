---
record_type: department
owner: "Head of Estates Operations"
authority: "Cardiff University Estates — Abacws Building Management"
source_system: "Department Directory"
effective_from: 2026-09-01
version: "2026.9"
review_due: 2027-03-01
simulated: true
tables:
  - name: "Department directory"
    maps_to: departments
---

# Department Directory — Abacws Building

## What this register records, and what it deliberately does not

Each row is a **function**, not a person. The register answers *who is accountable for this*,
*how does a request reach them*, *how quickly should it be answered* and *what happens when it
is not* — and it answers those without naming anybody, because identity is held at role level
throughout OntoSage and a directory is the easiest place to breach that by accident.

Three columns do most of the work:

- **scope** is what the department is accountable for. A question of the form *"who owns this?"*
  is answered by matching against this column, so it names assets and activities rather than
  restating the department's title.
- **responds_within_hours** makes *"is this overdue?"* a calculation. Without it the answer is
  an opinion.
- **out_of_hours** is separate from **request_channel** because they differ for most rows. An
  occupant told the daytime helpdesk queue at 22:00 has been given a confidently wrong answer.

**Reduced** is a real status, not a placeholder: two functions run reduced cover outside term,
and a request routed to them in August will wait longer than the target suggests.

## Department directory

| code | name | function | scope | based_at | coverage_hours | request_channel | out_of_hours | responds_within_hours | escalates_to | accountable_role | contact_email | contact_phone | status | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEP-01 | Estates Operations | Runs the building day to day and owns the fabric | Building fabric, doors, windows, floors, ceilings, roofs, signage | Level 0 Estates office | Mon-Fri 07:00-18:00 | Estates helpdesk queue | University Security duty line | 24 | Head of Estates Operations | Estates Operations Manager | estates-ops@example.ac.uk | 029 2087 0001 | Active | Owns the building fabric; plant sits with DEP-02 |
| DEP-02 | Mechanical and Electrical Maintenance | Maintains plant, HVAC, electrical distribution and controls | AHUs, chillers, boilers, pumps, distribution boards, BMS field devices | Level 0 plant room office | Mon-Fri 07:00-17:00 | Estates helpdesk queue, priority M and E | Duty electrician callout rota | 8 | Estates Operations | M and E Maintenance Supervisor | me-maintenance@example.ac.uk | 029 2087 0002 | Active | Holds the isolation register and the permit issue function |
| DEP-03 | Security | Protects people, property and controlled access | Access control, CCTV, patrols, incident response, lost property | Main entrance security desk | 24/7 | Security control room | Same, staffed continuously | 0.5 | Head of Security | Security Duty Manager | security@example.ac.uk | 029 2087 4444 | Active | The only continuously staffed function in the building |
| DEP-04 | Cleaning and Caretaking | Keeps the building clean, stocked and presentable | Cleaning zones, washrooms, waste points, consumables, room resets | Level 0 caretaker store | Mon-Fri 05:00-20:00 | Caretaker radio, then helpdesk | Security control room | 4 | Estates Operations | Caretaking Supervisor | cleaning@example.ac.uk | 029 2087 0004 | Active | Early shift starts 05:00; deep cleans are scheduled separately |
| DEP-05 | Health and Safety | Owns risk assessment, incident reporting and safe systems of work | Risk assessments, COSHH, LEV, incidents, near misses, contractor safety | Level 3 office | Mon-Fri 08:30-17:00 | Safety inbox or incident form | Security control room escalates | 24 | University Safety Office | Building Safety Adviser | safety@example.ac.uk | 029 2087 0005 | Active | Serious incidents bypass the target and go straight to escalation |
| DEP-06 | Fire Safety | Maintains fire precautions and evacuation readiness | Fire alarm, detection, extinguishers, doors, compartmentation, drills, PEEPs | Level 0 fire panel room | Mon-Fri 08:00-17:00 | Fire safety inbox | Security control room, then Fire Service | 8 | University Fire Safety Manager | Building Fire Warden Coordinator | fire.safety@example.ac.uk | 029 2087 0006 | Active | Weekly alarm test Wednesday 09:00; a missed test is reportable |
| DEP-07 | IT and Network Infrastructure | Runs the network, Wi-Fi, AV transport and server rooms | Switches, Wi-Fi access points, structured cabling, server rooms, AV network paths | Level 2 comms room | Mon-Fri 08:00-18:00 | IT service desk ticket | On-call network engineer | 8 | Director of IT | Network Infrastructure Lead | it-servicedesk@example.ac.uk | 029 2087 0007 | Active | Server room environmental alarms route here before Estates |
| DEP-08 | Audiovisual and Teaching Support | Keeps teaching rooms usable and supports live teaching | Projectors, displays, room PCs, lecture capture, hearing loops, room audio | Level 1 AV workshop | Mon-Fri 08:00-18:00 | AV support line | No cover, next working day | 1 | Director of IT | AV Support Team Leader | av-support@example.ac.uk | 029 2087 0008 | Active | One-hour target during teaching weeks; no evening cover |
| DEP-09 | Timetabling | Allocates teaching activity to rooms and times | Teaching timetable, room allocation, semester patterns, clash resolution | Level 4 admin office | Mon-Fri 09:00-17:00 | Timetabling request form | No cover, next working day | 48 | Registry | Timetabling Officer | timetabling@example.ac.uk | 029 2087 0009 | Reduced | Reduced cover outside term; changes in teaching weeks take priority |
| DEP-10 | Room Booking | Manages bookable space outside the teaching timetable | Bookable meeting rooms, study rooms, event space, ad hoc reservations | Level 4 admin office | Mon-Fri 09:00-17:00 | Room booking system | Self-service booking system | 24 | Registry | Room Bookings Coordinator | roombookings@example.ac.uk | 029 2087 0010 | Active | Self-service outside hours; disputes need a working day |
| DEP-11 | Energy and Sustainability | Owns energy, carbon and utility performance | Meters, tariffs, consumption reporting, carbon targets, efficiency projects | Level 5 office | Mon-Fri 09:00-17:00 | Sustainability inbox | No cover, next working day | 72 | Director of Sustainability | Energy and Carbon Manager | sustainability@example.ac.uk | 029 2087 0011 | Active | Advisory function; faults go to DEP-02, not here |
| DEP-12 | Waste Management | Runs waste streams, collections and recycling compliance | Collection points, streams, external bin store, duty of care documentation | External bin store | Mon-Fri 06:00-14:00 | Caretaker radio, then helpdesk | Security control room | 24 | Estates Operations | Waste and Recycling Officer | waste@example.ac.uk | 029 2087 0012 | Active | Collections are contracted; missed collections escalate same day |
| DEP-13 | Accessibility and Inclusion | Ensures the building is usable by disabled people | Step-free routes, PEEPs, hearing loops, accessible facilities, adjustments | Level 3 office | Mon-Fri 09:00-17:00 | Accessibility inbox | Security control room for urgent access | 24 | Director of Student Support | Accessibility Adviser | accessibility@example.ac.uk | 029 2087 0013 | Active | Owns PEEPs jointly with DEP-06 |
| DEP-14 | Finance and Procurement | Controls spend, contracts and supplier payment | Budgets, cost centres, purchase orders, contracts, supplier onboarding | Level 5 office | Mon-Fri 09:00-17:00 | Finance request form | No cover, next working day | 72 | Director of Finance | Finance Business Partner | finance@example.ac.uk | 029 2087 0014 | Active | Contract queries need the contract reference to be answered |
| DEP-15 | Space Planning | Plans how space is allocated and changed | Space allocation, occupancy standards, moves, refurbishment briefs | Level 5 office | Mon-Fri 09:00-17:00 | Space planning inbox | No cover, next working day | 120 | Director of Estates | Space Planning Manager | spaceplanning@example.ac.uk | 029 2087 0015 | Active | Advisory; physical moves are delivered by DEP-01 |
| DEP-16 | Emergency Planning | Prepares and coordinates response to major incidents | Incident plans, business continuity, exercises, coordination roles | Level 0 control room | Mon-Fri 09:00-17:00, on call 24/7 | Emergency planning inbox | Incident coordination duty phone | 2 | University Registrar | Emergency Planning Officer | emergency.planning@example.ac.uk | 029 2087 0016 | Active | Activates the coordination functions register during an incident |
| DEP-17 | Compliance and Regulatory | Evidences statutory compliance and handles inspections | Statutory inspections, certificates, regulator correspondence, audit evidence | Level 5 office | Mon-Fri 09:00-17:00 | Compliance inbox | No cover, next working day | 48 | University Secretary | Compliance Manager | compliance@example.ac.uk | 029 2087 0017 | Active | Holds the evidence pack an auditor is given |
| DEP-18 | Reception and Front of House | First point of contact for visitors and deliveries | Visitor reception, passes, deliveries, wayfinding, lost property intake | Main entrance reception | Mon-Fri 07:30-18:00 | Reception desk | Security control room | 0.25 | Head of Security | Reception Supervisor | reception@example.ac.uk | 029 2087 0018 | Active | Visitor passes outside these hours are issued by DEP-03 |
| DEP-19 | Research Support | Supports research activity, equipment and lab operations | Research equipment, lab access, sponsor requirements, data facilities | Level 5 office | Mon-Fri 09:00-17:00 | Research support inbox | No cover, next working day | 48 | Head of School | Research Support Manager | research.support@example.ac.uk | 029 2087 0019 | Reduced | Reduced cover in August; sponsor deadlines take priority |
| DEP-20 | School of Computer Science and Informatics | The academic school the building serves | Academic staff, students, teaching delivery, school policy in the building | Levels 3 to 5 | Mon-Fri 09:00-17:00 | School office | No cover, next working day | 48 | Head of School | School Manager | comsc-office@example.ac.uk | 029 2087 0020 | Active | The building's principal occupier |

**20 functions. Security is the only one staffed continuously and Emergency Planning the only
one on call, so every other out-of-hours route is a redirection rather than cover. Eight have
no out-of-hours route at all — AV and Teaching Support, Timetabling, Energy and
Sustainability, Finance and Procurement, Space Planning, Compliance and Regulatory, Research
Support and the School — and a request raised to any of them on Friday evening will not be
seen until Monday.**
