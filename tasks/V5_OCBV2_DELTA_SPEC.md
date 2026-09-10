# V5-T03 — OCBV-2 Delta Specification (Brick-first audit)

_Status: IN PREPARATION (2026-08-15). The Brick-coverage audit below is complete and
measured against `Brick_v1.4.ttl`; the gap-cluster mapping finalizes after the V5-T02
1,100-question baseline lands (run `v5_baseline_bldg2`, in progress)._

## Rule

**Extend OCBV only where Brick 1.4 has no term.** Every proposed OCBV-2 class must first
show its Brick search came back empty. The TBox never carries building-specific terms.

## Brick 1.4 coverage audit (measured, grep against Brick_v1.4.ttl)

| Family | Brick 1.4 term exists? | Verdict |
|---|---|---|
| Water metering | ✅ `brick:Water_Meter` (4 refs) | use Brick |
| Electrical submetering | ✅ `brick:Electrical_Meter` (2) | use Brick |
| Gas metering | ✅ `brick:Gas_Meter` (2) | use Brick |
| Particulates | ✅ PM2.5 sensor classes (7) | use Brick |
| Parking | ✅ Parking classes (3) | use Brick |
| Lifts | ✅ `brick:Elevator` (6) | use Brick |
| Illuminance | ✅ (27) — already in use | use Brick |
| Occupancy counting | ✅ `brick:Occupancy_Count_Sensor` (4) | use Brick (already in use) |
| PV / solar | ✅ PV classes (31) | use Brick |
| Battery / storage | ✅ Battery classes (4) | use Brick |
| Tanks (water storage, sprinkler) | ✅ (82) | use Brick |
| Alarm points | ✅ Alarm classes (31) | use Brick for alarm POINTS |
| **Bookings / reservations** | ❌ **0 mentions** | **OCBV-2 extends** |
| **Work orders / tickets** | ❌ (only Maintenance_Mode command points, 2 refs) | **OCBV-2 extends** |
| **Access events (badge)** | ❌ no event vocabulary | **OCBV-2 extends** |
| **Compliance checks with due dates** | ❌ | **OCBV-2 extends** |
| **Anomaly episodes** | ❌ (Brick alarms are live points, not persisted episodes) | **OCBV-2 extends** |
| **Forecast-skill metadata** | ❌ | **OCBV-2 extends** |

Conclusion (matches the V5 plan's three-shape thesis): every S1 scalar family V5 adds uses
existing Brick classes — zero new TBox needed there. The OCBV-2 delta is exactly the S2/S3
vocabulary: interval records and dated registers.

## Proposed OCBV-2 additions (draft — finalize against T02 gap map)

All under `http://ontosage.org/capabilities#`, versioned in-file.

### Interval records (S2)

```
ontosage:IntervalRecord              a owl:Class .   # abstract; never instantiated directly
ontosage:Booking                     rdfs:subClassOf ontosage:IntervalRecord .
ontosage:WorkOrder                   rdfs:subClassOf ontosage:IntervalRecord .
ontosage:AccessEvent                 rdfs:subClassOf ontosage:IntervalRecord .
ontosage:AlarmEvent                  rdfs:subClassOf ontosage:IntervalRecord .
ontosage:ComplianceCheck             rdfs:subClassOf ontosage:IntervalRecord .
ontosage:AnomalyEvent                rdfs:subClassOf ontosage:IntervalRecord .
```

Properties (domain IntervalRecord unless noted):

```
ontosage:aboutSpace      -> brick:Location     # the room/zone the record concerns
ontosage:aboutEquipment  -> brick:Equipment
ontosage:aboutPoint      -> brick:Point        # AnomalyEvent: the sensor concerned
ontosage:recordStatus    -> xsd:string         # open|assigned|done|cancelled|detected|resolved
ontosage:dueDate         -> xsd:dateTime       # ComplianceCheck
ontosage:completedDate   -> xsd:dateTime
ontosage:responsibleRole -> xsd:string         # role name, never a person identifier
ontosage:detectedBy      -> xsd:string         # AnomalyEvent: detector id
ontosage:baselineValue   -> xsd:double         # AnomalyEvent: expected-band context
```

Storage note: instances live in the per-building events table (`ref:storedAt` →
`events_data`), NOT as graph triples per event — the graph holds the CLASS vocabulary and
each building's *record-source declarations*; the rows are data. (Same division as sensors:
TTL declares the point, MySQL holds readings.)

### Forecast-skill vocabulary (P3)

```
ontosage:ForecastSkill    a owl:Class .        # one per (point-class x horizon), per building
ontosage:skillOf          -> brick:Point class or modality string
ontosage:horizonHours     -> xsd:double
ontosage:backtestMAE      -> xsd:double
ontosage:backtestMAPE     -> xsd:double
ontosage:ciCoverage80     -> xsd:double        # measured calibration
ontosage:skillMeasuredAt  -> xsd:dateTime
```

(Alternative considered: keep skill registry as a JSON artifact only. Decision pending —
triples make "how good are your forecasts?" SPARQL-answerable, which is the self-knowledge
story; JSON is simpler. Default: triples for the summary, JSON for the full curves.)

### Access-policy vocabulary (Pillar C — PROTECT, V5-T37)

Policies as triples: building-agnostic template + per-building `<id>_policies.ttl`.
Brick has no policy vocabulary (verified: no AccessPolicy/Permission classes) — clean OCBV
territory. Design mirrors BuildingChat's proven policy dimensions, expressed semantically:

```
ontosage:AccessPolicy            a owl:Class .
ontosage:appliesToRole           -> xsd:string          # RBAC role name (session-derived)
ontosage:scopeSpaces             -> brick:Location|tag  # own|public|any (+ explicit IRIs)
ontosage:scopeModalities         -> xsd:string list
ontosage:minAggregationSensors   -> xsd:integer         # k-anonymity floor
ontosage:minAggregationSpaces    -> xsd:integer         # e.g. >=7 spaces for cross-room
ontosage:resolutionTier          -> structured: recencyWindow -> maxResolutionSeconds
ontosage:rateLimit               -> structured: maxQueries, perWindow
ontosage:inferenceClass          -> xsd:string          # e.g. individual_presence: deny
rdfs:comment                     -> plain-language explanation (surfaced in denials/asks)
```

Enforcement contract: the deterministic PDP (V5-T38) is the only consumer; verdicts are
allow / restrict(clamps, declared as dossier assumptions + `applied_policies[]`) /
deny(reason + nearest-allowed alternative). The dossier carrying policy citations is the
"privacy provenance" claim — auditable per answer.

### Explicitly NOT added

- No person/identity classes (privacy: `responsibleRole` is a role string, never a user id).
- No building-specific amenity kinds beyond the existing DrinkingWater/ToiletFacility/
  StudyArea set unless T02 shows demand (candidates: Microwave, Locker, Shower, BikeRack,
  ChangingPlaces — decide from gap map).
- Nothing Brick already names (per audit above).

## FINALIZED (2026-08-15) — via static classification of the 1,100 bank

_The live T02 baseline was descoped by user decision (MVP-first); the gap map was derived
statically instead: every bank question tagged by required shape from its text
(`Required_Data_Sources`/`Answer_Type` columns now filled; ~100-question live partial
archived in `scripts/outputs/replay/v5_baseline_bldg2.csv`)._

**Measured primary demand per shape** (secondary tags additional): S2:booking 45 ·
pillar:predict 40 · pillar:detect 36 · compute:cost 35 · S3:register 24 · compute:route 23
· S2:workorder 18 · S2:access 15 · S1:new-modality 69 · decline-forever 16. Every proposed
OCBV-2 class has real question demand — **the spec above stands as written.**

**Amenity-kind decision** (from demand counts): extend the Amenity subclasses with
`BikeStorage` (7 asks), `FirstAidPoint` (5), `Shower` (4), `Locker` (3), `PrayerRoom` (3),
`WaterRefill` → already covered by DrinkingWater, `PrinterPoint` (3), `BabyChanging` (2).

**Event `attrs` JSON keys** (documented contract, enforced by the adapter):
booking `{organizer_role, attendees, capacity_used, recurring, ghost}` · workorder
`{trade, priority, affected_count}` · access `{entrance, direction}` · compliance
`{item_type, result}` · anomaly `{detector, score, baseline, modality}`.
