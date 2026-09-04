# Re-measurement after the register work

Model: `local/gpt-oss:20b`  ·  questions: 320

| role | n | computed before | computed after | change |
|---|---:|---:|---:|---:|
| Access-control administrators | 80 | 20% | **66%** | +46 pts |
| Cleaning and caretaking teams | 80 | 20% | **44%** | +24 pts |
| People with mobility, sensory, or other acce | 80 | 34% | **52%** | +19 pts |
| Visitors and event attendees | 80 | 19% | **59%** | +40 pts |
| **all four** | 320 | 23% | **55%** | +32 pts |

Questions that began computing: **115**
Questions that stopped computing: **12** — these are regressions

- REGRESSION `AC-031` [metadata] Which recurring time profile fits this approved out-of-hours duty without creating all-nig
- REGRESSION `AR-014` [metadata] The lift lobby is busy. Is another verified step-free route available, or is waiting the m
- REGRESSION `AR-016` [metadata] Do the verified corridor widths and turning spaces on my route fit the mobility-aid dimens
- REGRESSION `AR-054` [deliberate] Is there an authorised quiet or lower-stimulation space I can use, and when is it official
- REGRESSION `AR-059` [planner] Can I bring an assistance dog, and which current routes and areas are authorised?
- REGRESSION `AR-073` [capability] Which parts of your answer are confirmed facts, observations, calculations, estimates or r
- REGRESSION `CT-005` [capability] Which assigned tasks are now at real risk of missing their required completion time?
- REGRESSION `CT-008` [capability] Where can I begin work now without interrupting teaching, meetings or another authorised a
- REGRESSION `CT-042` [metadata] For this task, do I need a key, access card, escort, permit or local contact before I trav
- REGRESSION `CT-073` [metadata] Which cleaning-related defects or service problems keep recurring in the same place and ne

## Newly computed, by role


### Access-control administrators — 38 newly computed

- `AC-001` Which minimum approved permission package should be prepared for this verified starter on the au
- `AC-002` For this role or department transfer, which entitlements are justified to add, retain, remove-ca
- `AC-003` How should concurrent staff, student and sponsored-project affiliations be combined without wide
- `AC-005` Is this access request ready for administration, and which accountable owner must supply each mi
- `AC-011` Is this personalised credential ready for secure issue and collection, or should it remain on ho
- `AC-012` After this lost or stolen credential report, which containment steps are confirmed and what must
- `AC-013` Is this failed access attempt attributable to the credential, reader or door path, schedule, or 
- `AC-015` Does this identity have more than one active credential, and is each overlap justified, time-bou

### Cleaning and caretaking teams — 24 newly computed

- `CT-001` What is my cleaning zone and task list for this shift, including anything added, removed or hand
- `CT-002` Which rooms must be ready first today, and what is the latest practical start time for each one?
- `CT-003` Are any of my normal areas closed, restricted or temporarily reassigned on this shift?
- `CT-004` What cleaning standard, frequency and task set apply to this room on this visit?
- `CT-006` Has an event, exam or other high-use period changed where we should add cleaning effort today?
- `CT-011` Which teaching or meeting rooms are formally released and ready for us to enter for cleaning now
- `CT-012` Which assigned rooms are likely to become cleanable in the next 30 to 60 minutes so I can plan t
- `CT-017` Where has recent room use increased enough to justify an extra cleaning or replenishment check?

### People with mobility, sensory, or other accessibility requirements — 20 newly computed

- `AR-003` I have low vision. Which public entrance offers the simplest verified route to reception, with t
- `AR-006` I need more time at doors and lifts. How much arrival time should I allow before my appointment 
- `AR-007` I am arriving with a personal assistant, carer or support person. Can we use the same authorised
- `AR-013` Which lift serves my destination, is it officially in service, and is the route to it currently 
- `AR-018` How long should I allow for this route if I need extra time at doors, turns and lifts?
- `AR-019` Which authorised route between my two destinations is expected to be least crowded when I need t
- `AR-022` Is wheelchair-accessible seating confirmed for this room, and how do I verify or request it thro
- `AR-026` Is a height-adjustable desk or sufficient clear space for my mobility aid confirmed in the room 

### Visitors and event attendees — 33 newly computed

- `VE-001` I'm attending a public seminar at 6 p.m. Are visitors admitted, when does check-in open, and whe
- `VE-002` Which entrance should visitors use tomorrow evening, and will it be open when I arrive?
- `VE-003` From the station, bus stop or pick-up point I choose, how much time should I allow for walking, 
- `VE-006` Has the event venue or room changed since the information I received?
- `VE-008` What is the latest arrival time that still leaves a sensible margin before the organiser's check
- `VE-009` May I bring a large bag or coat, and is an official cloakroom or storage service available?
- `VE-011` I'm outside Abacws. Which entrance is authorised for my event?
- `VE-012` Where is check-in, and what waiting time can you responsibly estimate?
