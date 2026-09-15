# Demo question bank

67 questions, drawn deterministically by `scripts/build_stakeholder_bank.py` from `docs/smart_building_questions.csv` (every stakeholder catalogue and every answer category) and the survey master table (every reasoning level). These are EXAMPLES of what each stakeholder asks — the system is expected to answer questions beyond them.

Where a catalogue states an answer boundary, a refusal inside that boundary is the CORRECT answer.

| # | source | stakeholder | category | question |
|---|---|---|---|---|
| 1 | stakeholder_catalogue_37 | Academic office occupants |  | Which remaining period today has the best supported balance of temperature, ventilation, light and quiet for concentrated work? |
| 2 | stakeholder_catalogue_37 | Access-control administrators |  | Which permission groups or zones are orphaned because no current owner, purpose or mapped opening can be evidenced? |
| 3 | stakeholder_catalogue_37 | Accessibility, inclusion, and well-being |  | Have closures, room moves and route changes reached each affected attendee and accompanying person through their selected authorised channels before travel? |
| 4 | stakeholder_catalogue_37 | Architects and building designers |  | How do observed route lengths, waits and hand-offs compare with the workflow and adjacency assumptions used in the design? |
| 5 | stakeholder_catalogue_37 | Auditors and certification assessors |  | Which matters require a formal management representation because independent evidence is unavailable, incomplete or solely management-held? |
| 6 | stakeholder_catalogue_37 | BMS-HVAC operators |  | Which systems started late or stopped late against today's approved schedule, and by how much? |
| 7 | stakeholder_catalogue_37 | Cleaning and caretaking teams |  | Where is the current approved collection point for batteries, WEEE, sharps or other special waste I may encounter? |
| 8 | stakeholder_catalogue_37 | Emergency coordinators |  | Which critical activities are displaced, what dependencies block them, and which approved continuity options are viable now? |
| 9 | stakeholder_catalogue_37 | Emergency responders |  | Which temporary works, events, parked plant, barriers or closures have changed emergency access since the latest controlled access plan? |
| 10 | stakeholder_catalogue_37 | Energy, carbon, and sustainability teams |  | Which HVAC assets operate beyond approved service windows, and is each exception justified by safety, frost, specialist service, override or fault evidence? |
| 11 | stakeholder_catalogue_37 | External maintenance contractors |  | Which maintenance, setpoint, firmware, control or building changes occurred shortly before the fault, and which are only hypotheses rather than established causes? |
| 12 | stakeholder_catalogue_37 | Facilities managers |  | Which entrances or route segments need a facilities inspection before the next high-footfall transition? |
| 13 | stakeholder_catalogue_37 | Finance and procurement teams |  | Which assets should receive survey, maintenance, refurbishment or replacement funding first when criticality, condition, risk and whole-life cost are combined? |
| 14 | stakeholder_catalogue_37 | Fire-safety personnel |  | Which occupied zones lack confirmed fire-warden or marshal coverage for the current operating period? |
| 15 | stakeholder_catalogue_37 | Health and safety officers |  | Is the approved first-aid cover and equipment provision suitable for the declared occupancy, activities, hazards and operating period? |
| 16 | stakeholder_catalogue_37 | IT, network, and server-infrastructure t |  | If the primary server room, communications room or core-network area is unavailable, which services have a verified alternative location, path and operating capacity? |
| 17 | stakeholder_catalogue_37 | Insurers and risk assessors |  | What temporary exposure is created by active construction, refurbishment, commissioning, relocation or intrusive maintenance, and during which zones and time windows? |
| 18 | stakeholder_catalogue_37 | Lecturers and tutors |  | I have a 9 a.m. lecture. Before I leave my office, what is confirmed, what is still unknown, and how early should I arrive? |
| 19 | stakeholder_catalogue_37 | Mechanical and electrical engineers |  | Which M&E asset-register records must be reconciled before they can support design, maintenance or lifecycle decisions? |
| 20 | stakeholder_catalogue_37 | People with mobility, sensory, or other  |  | Is a Changing Places toilet available in or near Abacws, and what are the current verified access arrangements? |
| 21 | stakeholder_catalogue_37 | PhD students |  | We need a room for a two-hour mock viva with four people. Which option is confidential, accessible, quiet and suitable for one hybrid participant? |
| 22 | stakeholder_catalogue_37 | Professional-services staff |  | An alarm or emergency message has occurred. What is the latest authoritative instruction for my location and role? |
| 23 | stakeholder_catalogue_37 | Prospective students and family members |  | Is my next course talk likely to be crowded or poorly ventilated enough to consider a repeat session? |
| 24 | stakeholder_catalogue_37 | Regulatory and institutional compliance  |  | Are compliance records retained for the correct period, in the authorised system and format, with integrity, access and disposal controls appropriate to their purpose? |
| 25 | stakeholder_catalogue_37 | Research staff |  | The lift on my usual route is unavailable. What current step-free alternative or suitable relocated workspace is officially verified? |
| 26 | stakeholder_catalogue_37 | Researchers and data scientists |  | Is the calibration chain traceable and accurate enough for the smallest difference or threshold the study intends to interpret? |
| 27 | stakeholder_catalogue_37 | Room-booking team |  | Which room and time categories show repeated no-shows strongly enough to justify an owner-led review of release rules? |
| 28 | stakeholder_catalogue_37 | School leadership, university leadership |  | Which dependency-aware recovery order should incident leaders adopt to restore priority services safely with the people and resources currently available? |
| 29 | stakeholder_catalogue_37 | Security officers |  | Which events are due today, and which approved Security arrangements are current, missing or no longer valid for each one? |
| 30 | stakeholder_catalogue_37 | Space-planning teams |  | Which functions must be co-located or kept within a stated travel time, which are preferences, and which adjacency claims lack evidence? |
| 31 | stakeholder_catalogue_37 | Taught postgraduate students |  | I am on campus for only one day this week. Can you plan a practical sequence for study, an online call, printing and a group meeting around my classes? |
| 32 | stakeholder_catalogue_37 | Teaching and audiovisual support team |  | During managed-network degradation, which room AV functions still have current evidence that they can operate? |
| 33 | stakeholder_catalogue_37 | Timetabling team |  | If enrolment moves within the approved planning range, which group counts or room allocations become fragile first? |
| 34 | stakeholder_catalogue_37 | Undergraduate students |  | I'm coming to Abacws next Wednesday after 2 p.m. for about 90 minutes. Where am I most likely to find a calm, relatively quiet place with low foot traffic and reasonable measured temperature and air-quality indicators, close to my 4 p.m. class? |
| 35 | stakeholder_catalogue_37 | University estates and asset-management  |  | Which closed work orders lack enough asset, test or outcome evidence for estates teams to rely on the stated result? |
| 36 | stakeholder_catalogue_37 | Visitors and event attendees |  | The event room has changed. What is the new confirmed room, and what public route should I take? |
| 37 | stakeholder_catalogue_37 | Waste-management teams |  | Were bins, skips, compactors, seals or locks exchanged and handed back exactly as recorded? |
| 38 | v5_synthetic_bank | Visitor | Accessibility | Is the building pushchair-friendly from the car park? |
| 39 | v5_synthetic_bank | Visitor | Ambiguous, underspecified & out- | Book me a hotel near the building for tomorrow. |
| 40 | v5_synthetic_bank | Facility manager | Anomaly detection & diagnosis | Which plant items are running outside their normal schedule right now? |
| 41 | v5_synthetic_bank | Executive | Benchmarking & comparison | Which capital project this year had the best measured outcome? |
| 42 | v5_synthetic_bank | Retrofit consultant | Carbon & retrofit | Rank the glazing, roof, and AHU replacements by comfort improvement per pound. |
| 43 | v5_synthetic_bank |  | Cleaning & daily operations | The bins on floor 2 are always full by lunchtime - can you check that? |
| 44 | v5_synthetic_bank | Occupant | Comfort & place-finding | I'm pregnant and overheating - where's the coolest place to work today? |
| 45 | v5_synthetic_bank | Energy manager | Cost & finance | How much would submetering every floor cost, and when does it pay back? |
| 46 | v5_synthetic_bank | Space planner | Cross-domain / open-ended reason | Whats the best empty room to convert into two phone booths, by demand? |
| 47 | v5_synthetic_bank | Facility manager | Current state / lookup | What's the delta-T across the heating circuit, and is it healthy? |
| 48 | v5_synthetic_bank | Maintenance technician | Documents, compliance & institut | What's the filter size for the FCUs on floor 4? |
| 49 | v5_synthetic_bank | Occupant | Events & scheduling | Find a room for 12 with a projector, free 2-4pm today, near the cafe. |
| 50 | v5_synthetic_bank | Energy manager | Generation, storage & grid | What's the optimal battery dispatch for tomorrow's tariff and solar forecast? |
| 51 | v5_synthetic_bank | Retrofit consultant | Lighting & acoustics | Whats the daylight hour count in the deepest workstation this December? |
| 52 | v5_synthetic_bank |  | Maintenance, tickets & complaint | How many open work orders are there, and which are overdue? |
| 53 | v5_synthetic_bank | Space planner | Occupancy & space utilisation | What percentage of bookings are recurring 'ghost' meetings that never happen? |
| 54 | v5_synthetic_bank | Facility manager | Personalisation, memory & follow | You mentioned a sensor fault earlier - has it been fixed yet? |
| 55 | v5_synthetic_bank | Energy manager | Prediction & forward-looking | What happens to comfort if we cut the AHU runtime by an hour each end of day? |
| 56 | v5_synthetic_bank | Facility manager | Retrospective analysis & reporti | Which drains have needed jetting more than twice this year? |
| 57 | v5_synthetic_bank | Fire service liaison | Safety, security & emergency | Which shutters or doors fail open versus fail locked on power loss? |
| 58 | v5_synthetic_bank | Occupant | System self-knowledge & explaina | Can my manager see when I badge in and out? |
| 59 | v5_synthetic_bank | Student | Water & waste | Is tap water free somewhere, or do I have to buy bottles? |
| 60 | v5_synthetic_bank | Contractor | Wayfinding & entity resolution | Where can I isolate the water supply for the second-floor toilets? |
| 61 | v5_synthetic_bank | Energy manager | Weather coupling | How many free-cooling hours did we capture last month versus what was available? |
| 62 | survey | IT/Data Scientists | Causal Diagnosis | why autism happens |
| 63 | survey | Health and Safety Officers | Comparative Analysis | What systems are specific for the meeting room? |
| 64 | survey | IT/Data Scientists | Factual Recall | in the barometric meter will functions |
| 65 | survey | Guests/Visitors | Inferential Reasoning | How do glare sensors work? Does that come from the monitor itself? |
| 66 | survey | IT/Data Scientists | Meta / Strategic Reasoning | how does building prevent this space? |
| 67 | survey | Student/Researchers/Academics | Systemic Synthesis | can you provide energy saving suggestion? |
