# Gap plan — baseline_20260903_152449.csv

Questions: **2393**  ·  models: gpt-oss:20b×1821, unrecorded×572

| outcome | n | share |
|---|---:|---:|
| **Computed** (figures from the building) | 870 | 36.4% |
| Quoted (a passage, not a calculation) | 490 | 20.5% |
| Honest decline (correct when data is absent) | 743 | 31.0% |
| Failed / wrong | 209 | 8.7% |
| Unmeasured (timeout — retry these) | 81 | 3.4% |

## Is the gap data, or is it routing?

| the question did not compute because | n |
|---|---:|
| every system it needs is READY - the lane did not use them | **1113** |
| at least one system it needs is not ready | 329 |

Examples of the first kind: AC-012 [capability], AC-018 [capability], AC-020 [capability], AC-021 [capability], AC-023 [capability], AC-024 [capability]

## What to build, ranked by questions it would move

| source system | readiness | non-computed questions naming it | examples |
|---|---|---:|---|
| `sensor_telemetry` | DATA | 1160 | AC-001, AC-003, AC-005, AC-024 |
| `space_inventory` | DATA | 460 | AC-001, AC-004, AC-021, AC-023 |
| `policy_governance` | DATA | 305 | AC-001, AC-002, AC-003, AC-004 |
| `it_network` | DATA | 297 | AC-021, AC-025, AC-032, AC-041 |
| `access_control` | DATA | 282 | AC-001, AC-002, AC-003, AC-008 |
| `booking` | DATA | 265 | AC-011, AC-017, AC-035, AD-021 |
| `accessibility` | DATA | 265 | AC-018, AC-028, AC-069, AC-076 |
| `asset_register` | DATA | 253 | AC-004, AC-023, AC-025, AC-045 |
| `permit_control` | DATA | 239 | AC-019, AC-079, AD-014, AD-017 |
| `contract_warranty` | DATA | 210 | AC-017, AC-039, AC-046, AC-075 |
| `project_handover` | DATA | 198 | AC-001, AC-013, AC-016, AC-023 |
| `fire_life_safety` | DATA | 177 | AC-024, AD-016, AD-024, AD-028 |
| `bms_plant` | DATA | 161 | AD-003, AD-006, AD-014, AD-055 |
| `meter_energy` | DATA | 143 | AD-003, AD-006, AD-009, AD-012 |
| `finance_cost` | DATA | 137 | AC-076, AD-053, AD-068, AU-005 |
| `timetable` | WIRED | 126 | AD-006, AD-027, AI-003, AI-020 |
| `cleaning_waste` | DATA | 125 | AD-005, AD-026, AD-029, AD-034 |
| `cmms_work` | DATA | 124 | AC-024, AD-024, AD-029, AU-021 |
| `survey_condition` | DATA | 115 | AD-001, AD-002, AD-003, AD-005 |
| `hr_identity` | ABSENT | 107 | AC-001, AC-002, AC-003, AC-004 |

## Per stakeholder role

| role | n | computed | quoted | honest | failed | unmeasured |
|---|---:|---:|---:|---:|---:|---:|
| University estates and asset-management teams | 80 | **62%** | 4% | 25% | 8% | 1 |
| Room-booking team | 80 | **50%** | 11% | 34% | 4% | 1 |
| Regulatory and institutional compliance teams | 80 | **50%** | 18% | 22% | 8% | 2 |
| BMS-HVAC operators | 80 | **45%** | 26% | 18% | 11% | 0 |
| Facilities managers | 80 | **45%** | 14% | 28% | 12% | 1 |
| Fire-safety personnel | 80 | **45%** | 24% | 25% | 5% | 1 |
| Health and safety officers | 80 | **44%** | 19% | 26% | 11% | 0 |
| Insurers and risk assessors | 80 | **44%** | 28% | 18% | 9% | 2 |
| Timetabling team | 80 | **44%** | 16% | 30% | 8% | 2 |
| Mechanical and electrical engineers | 80 | **42%** | 28% | 26% | 2% | 1 |
| Professional-services staff | 80 | **42%** | 22% | 19% | 14% | 2 |
| IT, network, and server-infrastructure teams | 80 | **40%** | 28% | 24% | 5% | 3 |
| Energy, carbon, and sustainability teams | 80 | **40%** | 18% | 25% | 14% | 3 |
| Architects and building designers | 80 | **39%** | 20% | 35% | 6% | 0 |
| Accessibility, inclusion, and well-being teams | 80 | **38%** | 21% | 30% | 11% | 0 |
| Emergency responders | 80 | **38%** | 35% | 18% | 5% | 4 |
| External maintenance contractors | 80 | **38%** | 21% | 36% | 5% | 0 |
| Space-planning teams | 80 | **35%** | 24% | 29% | 10% | 2 |
| People with mobility, sensory, or other access | 80 | **34%** | 11% | 34% | 21% | 0 |
| Teaching and audiovisual support team | 80 | **34%** | 21% | 41% | 4% | 0 |
| Emergency coordinators | 80 | **32%** | 25% | 34% | 9% | 0 |
| Researchers and data scientists | 80 | **32%** | 25% | 40% | 2% | 0 |
| Auditors and certification assessors | 80 | **31%** | 21% | 42% | 5% | 0 |
| Security officers | 80 | **29%** | 28% | 39% | 5% | 0 |
| Finance and procurement teams | 80 | **28%** | 9% | 49% | 10% | 4 |
| Prospective students and family members | 80 | **26%** | 20% | 42% | 8% | 3 |
| Access-control administrators | 80 | **20%** | 20% | 50% | 10% | 0 |
| Cleaning and caretaking teams | 80 | **19%** | 29% | 39% | 11% | 2 |
| Visitors and event attendees | 73 | **16%** | 22% | 38% | 21% | 2 |
| School leadership, university leadership, and  | 80 | **8%** | 9% | 18% | 10% | 45 |

## Per lane

| intent | n | computed | quoted | honest | failed |
|---|---:|---:|---:|---:|---:|
| capability | 1303 | 13% | 38% | 45% | 5% |
| sensor_data | 371 | 69% | 0% | 20% | 11% |
| metadata | 260 | 89% | 0% | 8% | 2% |
| events | 82 | 82% | 0% | 2% | 16% |
| (none) | 81 | 0% | 0% | 0% | 100% |
| asset_state | 47 | 66% | 0% | 0% | 34% |
| planner | 36 | 58% | 0% | 31% | 11% |
| recommend | 33 | 55% | 0% | 0% | 45% |
| deliberate | 31 | 26% | 0% | 6% | 68% |
| spatial_query | 24 | 67% | 0% | 0% | 33% |
| analytics | 18 | 78% | 0% | 22% | 0% |
| privacy_refusal | 16 | 6% | 0% | 0% | 94% |
| diagnosis | 13 | 0% | 0% | 100% | 0% |
| general_knowledge | 11 | 18% | 0% | 82% | 0% |
