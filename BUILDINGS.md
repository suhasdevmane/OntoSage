# Smart Building Ontologies Overview

This document provides a comparative description of the three building knowledge graphs used across the OntoBot project. It explains:

- Purpose and provenance of each building
- Ontological modeling approach (Brick/REC/SHACL usage)
- Spatial hierarchy and HVAC emphasis
- Sensor portfolios and environmental focus
- Construction patterns of the TTL files
- How these datasets complement multi‑building NL→SPARQL training

## Summary Table

| Building | Identifier Base IRI | Nature | Domain Focus | Spatial Complexity | Sensor Diversity | Primary HVAC Focus |
|----------|--------------------|--------|--------------|--------------------|------------------|--------------------|
| Building 1 (ABACWS) | `http://abacwsbuilding.cardiff.ac.uk/abacws#` | Real testbed (Cardiff University) | Indoor environmental quality (IEQ), air quality analytics | 6 floors, rich room enumeration | Very high (air quality, multiple gas species, particulates, temp, humidity, light, occupancy/noise) | Zone environmental sensing (no synthetic AHU loops modeled) |
| Building 2 (Synthetic Office) | `http://buildsys.org/ontologies/bldg2#` | Synthetic (office) | Air Handling Unit (AHU) performance + distributed zone temps | Implicit zone graph via AHU/ZONE naming (Room IDs) | Medium–High (AHU process points + zone air temps + water/pressure/flow variants) | Single AHU-centric process instrumentation |
| Building 3 (Synthetic Data Centre) | `http://buildsys.org/ontologies/bldg3#` | Synthetic (data centre) | Critical cooling, zone & equipment taxonomy richness | Extensive class taxonomy (Brick class extensions) | High (broad Brick class coverage; many sensor classes, alarms, parameters) | Robust AHU/air loop + advanced sensor/parameter classes |

---
## 1. Building 1 – ABACWS (Real Testbed)

### Provenance & Intent
A real university building (Cardiff University – ABACWS) providing authentic spatial granularity and indoor environmental quality data for research and model grounding.

### Ontology Composition
- Namespaced with `bldg:` prefix at ABACWS IRI.
- Uses Brick core classes for spatial relations (`brick:hasPart`, `brick:hasPoint`).
- Integrates REC (`rec:Building`, `rec:Space`) for semantic alignment with broader real-estate descriptors.
- Adds QUDT unit references for potential quantitative alignment (e.g., later analytics).

### Spatial Hierarchy
- Floors explicitly enumerated: `bldg:Floor0` … `bldg:Floor5`.
- Each floor lists dozens of rooms (`bldg:RoomX.YY`), supporting fine-grained zone-based NL queries (e.g., "temperature in room 5.17").
- Example composite zones (e.g., `bldg:north-west-Zone`, `bldg:east-Zone`) aggregate logically related rooms and expose a consolidated point set.

### Sensor Portfolio (High Density IEQ)
Dominated by multi-parametric indoor environmental quality nodes—pattern repeated per room/zone:
- Air Quality (aggregate) and specific gas concentration sensors: CO, CO2, NO2, LPG/Natural Gas (MQ5), Carbon Monoxide / Coal Gas (MQ9), Alcohol (MQ3), Combustible Gas/Smoke (MQ2), Oxygen, TVOC, Formaldehyde, Ethyl Alcohol.
- Particulate Matter: PM1, PM2.5, PM10.
- Thermal & Humidity: Air Temperature, Zone Air Humidity.
- Illumination: Illuminance sensors.
- Occupancy/Activity: PIR motion sensors.
- Acoustic Environment: MEMS sound/noise sensors.

From the `sensors_list.txt` (excerpt) we see systematic numeric suffixing (e.g., `_5.17`, `_5.22`) binding sensor instances to room identifiers—this pattern facilitates programmatic linking from NL utterances referencing a room number.

### Modeling Patterns
- Reuse of Brick point classes rather than proliferating custom classes; uniqueness expressed in individual instance IRIs.
- Zones collect heterogeneous sensor modalities under `brick:hasPoint`, enabling composite queries ("all gas sensors in north-west-Zone").
- TTL size reflects enumeration (hundreds of sensor individuals) over deep process equipment modeling.

### Strengths for NL→SPARQL
Provides breadth of environmental attribute types (many synonyms and pollutant classes) ideal for generating paraphrased training pairs that test semantic disambiguation (e.g., "VOC" vs "TVOC", "CO2 level" vs "carbon dioxide sensor reading").

---
## 2. Building 2 – Synthetic Office (AHU + Zones)

### Purpose
A synthetically generated office-style ontology emphasizing a single AHU’s process variables and a broad distribution of zone temperature measurement points for thermal comfort queries.

### Ontology & Structure
- Base IRI `bldg2#`; uses Brick plus intensive SHACL rule scaffolding (numerous `sh:TripleRule` entries) to automatically tag point classes—this inflates TTL line count.
- Zone/room representation primarily encoded via naming convention under `bldg2.ZONE.AHU01.RM***` rather than explicit `brick:Room` individuals (trade-off: compact modeling vs explicit spatial graph).

### AHU & Process Focus
Representative instrumentation (from `sensor_list.txt`):
- Core air stream temperatures: Mixed_Air, Outside_Air, Return_Air, Supply_Air, Zone_Air.
- Chilled water loop metrics: Supply/Return/Discharge temperatures & flows, differential pressure & temperature.
- Air distribution: Supply Air Pressure, Damper Position, Differential Pressure, Air Flow.
- Environmental & performance augmentation: CO2 Level, Cooling Demand, Various differential & static pressure sensors.

### Broader Sensor Classes
Generic canonicalized sensor names (e.g., `Average_Exhaust_Air_Static_Pressure_Sensor.01`, `Chilled_Water_Supply_Temperature_Sensor.01`) appear as simplified training abstractions—these enable intent generalization (user may ask "average exhaust pressure" instead of full label).

### Modeling Patterns
- Heavy SHACL tagging yields consistent multi-tag semantics (e.g., Temperature + Air + Zone) supporting robust tag-driven SPARQL patterns.
- Hybrid naming pattern merges functional group (`AHU01`) + spatial token (`RM203`) + measurement type, ensuring NL queries like "room 203 supply air temperature" can be deterministically mapped.

### Strengths for NL→SPARQL
Focus on HVAC operational parameters complements Building 1’s environmental focus—broadens training distribution to process & control queries (e.g., setpoints, differential pressures, chilled water performance).

---
## 3. Building 3 – Synthetic Data Centre (Zone & Equipment Taxonomy)

### Purpose
Models a data-centre style facility emphasizing critical cooling reliability and a wide semantic taxonomy of Brick classes (alarms, parameters, setpoints, loops, energy storage, access/security) to challenge ontology coverage.

### Ontology & Structure
- Base IRI `bldg3#`; includes extensive Brick class definitions and custom subclass expansions (starting lines show many class declarations e.g., `Average_Cooling_Demand_Sensor`, `Alarm_Delay_Parameter`, `Access_Reader`).
- Emphasis on Brick’s rich equipment & sensor taxonomy rather than enumerated spatial floors (spatial scope abstracted, focusing on systems & components).

### Sensor & Class Portfolio
- Alarms & parameters: Air Flow Loss Alarm, Alarm Delay Parameter, Availability Status.
- Environmental & process sensors: Average Cooling/Heating Demand, Average Zone Air Temperature, Exhaust Air Static Pressure, Active Power, Ammonia, Absolute Humidity.
- Equipment taxonomy: Absorption Chiller, Active Chilled Beam, Access Control Equipment, Energy Storage System, Battery Room, Shading/Window control.
- System groupings: Air Loop, Automatic Tint Window Array, etc.

### Modeling Patterns
- Many owl:Class + sh:NodeShape combos with `brick:hasAssociatedTag` promoting high tag density—facilitates robust tag-based similarity retrieval and NL variant mapping.
- Provides semantically rich synonyms enabling training of transformer models to generalize across functionally related sensor types.

### Differences vs Building 2
| Aspect | Building 2 | Building 3 |
|--------|------------|------------|
| Primary focus | Single AHU & zone thermal comfort | Broad equipment + environmental taxonomy for a data centre | 
| Spatial explicitness | Implicit via names | De-emphasized; focus on class expansion | 
| SHACL rule density | High (tag propagation for points) | High (class/tag generation) | 
| Diversity of equipment classes | Moderate | High | 
| Alarm & parameter modeling | Limited | Extensive |

### Strengths for NL→SPARQL
Expands vocabulary surface (alarms, parameters, storage, access control) producing harder generalization tasks and reducing model overfitting to purely HVAC or IEQ phrasing.

---
## 4. TTL Construction Patterns

| Pattern | Building 1 | Building 2 | Building 3 |
|---------|------------|------------|------------|
| Spatial floors & rooms | Explicit individuals | Implicit via naming | Mostly abstracted | 
| Zone aggregation | Composite zones with `brick:hasPoint` | By AHU + RM naming | Not central | 
| Sensor instance naming | Type + room suffix (e.g., `_5.17`) | Functional path + measurement | Many class-level declarations, fewer explicit instances in excerpt | 
| SHACL rules | Minimal | Extensive tagging | Extensive for class taxonomy | 
| Environmental focus breadth | Very high (air quality + particulates + gases + noise + light) | Thermal + HVAC process | Cooling, power, security, alarms, parameters |

---
## 5. Multi‑Building Synergy
- Combined corpora supply varied semantic niches: IEQ (B1), AHU/HVAC process (B2), taxonomy breadth & critical systems (B3).
- Supports curriculum-style fine‑tuning: start with environmental queries (B1), introduce HVAC process complexity (B2), then broaden to taxonomy & alarm semantics (B3).
- Enables domain adaptation evaluation by holding out one building during validation.

## 6. Usage in NL→SPARQL Dataset Generation
- The dataset merge script leverages distinct naming conventions to form unique composite keys (building + sensor tag + room/zone tokens).
- Tag density (from SHACL in B2/B3) improves automatic synonym expansion when generating paraphrased natural language questions.
- Environmental and process attribute diversity reduces model hallucination by grounding queries in many distinct predicate paths.

## 7. Quick Reference by Query Intent
| User Intent Example | Best Building Source | Notes |
|---------------------|----------------------|-------|
| "What is CO2 level in room 5.17?" | Building 1 | Rich per-room gas sensors |
| "Supply air temperature of AHU01" | Building 2 | Explicit AHU instrumentation |
| "Average cooling demand status" | Building 3 | Demand sensor classes & parameters |
| "Any exhaust static pressure alarms?" | Building 3 | Alarm class taxonomy |
| "Zone 203 temperature" | Building 2 | Zone path naming under ZONE.AHU01 |

## 8. File Locations
- Real testbed TTL: `bldg1/trial/dataset/bldg1.ttl`
- Synthetic office TTL: `bldg2/trial/dataset/bldg2.ttl`
- Synthetic data centre TTL: `bldg3/trial/dataset/bldg3.ttl`
- Sensor lists: `bldg1/trial/dataset/sensors_list.txt`, `bldg2/trial/dataset/sensor_list.txt` (B3 sensors inferred from taxonomy classes).

## 9. Linking From README
The root README links here to provide deeper ontology and semantic modeling context for the three building knowledge graphs.

---
## 10. Future Enhancements
- Add explicit instance layer for Building 3 (instances of key sensor classes) to mirror B1 granularity.
- Introduce energy meters & occupancy schedules to B2 for holistic HVAC optimization queries.
- Materialize SHACL-driven inferred tags as explicit triples for faster query execution.
- Provide aggregated competency question lists per building for benchmarking.

---
© 2025 OntoBot Project
