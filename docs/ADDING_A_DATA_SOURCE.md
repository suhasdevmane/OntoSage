# Adding a Data Source to OntoSage

**The canonical rule:** `input/` holds metadata/config only. Sensor time-series **live in a
database** and are referenced from the ontology via
`ref:hasExternalReference → ref:TimeseriesReference (ref:hasTimeseriesId + ref:storedAt)`.
Raw CSV sensor readings in `input/` are **deprecated** — they are at most a one-time migration
source. We recommend you keep your readings in any database (local MySQL is fine) and register
the linkage in the TTL/GraphDB.

---

## Step 0: Identify what kind of data you have

```
Time-series telemetry? (temperature, kWh, occupancy, noise, PM2.5, water flow …)
│  └─ YES → STANDARD PIPELINE below (TTL point + narrow DB table). Go to Step 1.
│
A genuinely LIVE external feed? (weather API, a system that pushes JSON/CSV on an interval)
│  └─ YES → input/feeds.yaml as a rest_poll feed. (csv_drop is deprecated for sensor data.)
│
A document, policy, or FAQ?
│  └─ YES → input/documents/ (drop a .md/.txt/.pdf, restart; no other steps).
│
A static building fact or equipment capability?
│  └─ YES → input/capability.yaml (add an entry, restart).
│
A rate schedule / tariff / one-off event?
   └─ config/recipes.yaml (rates) or input/documents/ (events) — NOT a fake sensor.
```

---

## Already have raw / BMS-named points? (auto-enrichment)

If your source TTL gives points with only a URI + a timeseries ref — no `a brick:…`,
no `rdfs:label` — e.g. a BMS/Haystack export:

```turtle
<…#bldgx.ZONE.AHU01.RM123.Zone_Air_Temp>
    ref:hasExternalReference [ a ref:TimeseriesReference ;
        ref:hasTimeseriesId "226d7ec5-…" ; ref:storedAt bldg:database1 ] .
```

…you don't have to hand-author anything. On startup the **entity enricher**
(`ENTITY_ENRICHMENT_ENABLED`, default on) scans for such points and derives a Brick
**class + human-readable label + `isPointOf`/`hasLocation` relationships** from the
URI tokens, writing them to the idempotent overlay graph `urn:ontosage:enrichment`
(your input TTL is never modified). The example above becomes:

```turtle
<…#bldgx.ZONE.AHU01.RM123.Zone_Air_Temp>
    a brick:Zone_Air_Temperature_Sensor ;
    rdfs:label "Zone Air Temperature — AHU01 / RM123" ;
    brick:isPointOf bldg:AHU01 ; brick:hasLocation bldg:RM123 .
```

After which it resolves by **class and label** like any other point — the raw URI is
never parsed at query time. Tune the token→class map for your naming scheme in
[`config/entity_enrichment.yaml`](../config/entity_enrichment.yaml) (full names +
abbreviations like `ZAT`/`SAT`/`CO2`). Preview without writing:

```bash
docker cp scripts/enrich_entities.py ontosage-orchestrator:/tmp/
docker exec ontosage-orchestrator python /tmp/enrich_entities.py --dry-run   # reports unmapped tokens
```

Unmapped points (no class inferred) are reported so you can extend the config. This
is best-effort/heuristic — it gets you queryable points without hand-authoring, but
review the dry-run for a new naming convention.

---

## The standard telemetry pipeline (one flow, every modality)

Each sensor becomes a first-class Brick point whose readings live in a NARROW
`(uuid, datetime, value)` MySQL table — the **same** SPARQL→SQL→analytics path the existing
temperature/CO₂ sensors use. No bespoke code per modality.

### Step 1 — Declare the sensor(s)

Append a row to `SENSORS` in [`scripts/generate_timeseries_extension.py`](../scripts/generate_timeseries_extension.py):

```python
Sensor(
    csv="energy_meter_floor5",          # migration CSV basename (one-time source)
    value_col="kwh",                    # the reading column
    local="Energy_Meter_Floor5",        # entity local name -> bldg:Energy_Meter_Floor5
    brick_class="brick:Energy_Sensor",  # see table below
    unit="unit:KiloW-HR",               # QUDT unit
    table="energy_data",                # narrow table == storedAt key (bldg:energy_data)
    location="bldg:Floor5",             # bldg:FloorN | bldg:Abacws | bldg:BuildingExterior
    label="Electrical Energy Meter — Floor 5",
),
```

UUIDs are deterministic (`uuid5` over the entity URI) — re-running is idempotent and the TTL,
the DB table, and the dummy publisher all agree on the same UUID per sensor. For modalities Brick
has no point class for (noise, vibration), the generator defines a custom `bldg:` subclass of
`brick:Sensor`. Multi-type instances (via `EXTRA_TYPES`) so generic class queries resolve them.

### Step 2 — Register the narrow table as a storage backend

In [`input/database_registry.yaml`](../input/database_registry.yaml):

```yaml
  energy_data:
    type: mysql_narrow
    table: energy_data
    host: "${MYSQL_HOST:-mysql}"
    port: "${MYSQL_PORT:-3306}"
    user: "${MYSQL_USER:-root}"
    password: "${MYSQL_PASSWORD:-mysql}"
    database: "${MYSQL_DATABASE:-sensordb}"
```

…and add the key to the `storage.databases` filter in `input/building.yaml` so it activates.

### Step 3 — Generate TTL + load the DB

Run **inside the orchestrator container** (where MySQL resolves with the right grants):

```bash
docker cp scripts/onboard_data_source.py   ontosage-orchestrator:/tmp/
docker cp scripts/load_timeseries_to_db.py ontosage-orchestrator:/tmp/
docker exec ontosage-orchestrator python /tmp/onboard_data_source.py
docker restart ontosage-orchestrator        # startup loader ingests input/*.ttl into GraphDB
```

`onboard_data_source.py` writes `input/bldg1_timeseries_extension.ttl` (+ a UUID-map JSON) and
creates/loads the narrow tables. **Do NOT upload the TTL by hand** — the orchestrator's startup
loader (`run_idempotent_uploads`) PUTs every `input/*.ttl` into a per-file named graph
idempotently. Manual uploads create duplicate triples across graphs.

### Step 4 — (optional) keep it live

The dummy publisher (`mysql-dummy-publish-dev/`) reads
`input/bldg1_timeseries_extension_uuids.json` and publishes live rows into the narrow tables each
interval. Real deployments point `ref:storedAt` at their own database instead.

### Picking the right Brick class (verified against the loaded ontology)

| Measurement | Brick class |
|---|---|
| Air temperature | `brick:Air_Temperature_Sensor` |
| CO₂ | `brick:CO2_Level_Sensor` |
| Relative humidity | `brick:Humidity_Sensor` |
| PM2.5 particulates | `brick:PM2.5_Level_Sensor` |
| VOC / TVOC | `brick:TVOC_Level_Sensor` (+ `brick:TVOC_Sensor`) |
| Illuminance (lux) | `brick:Illuminance_Sensor` |
| Electrical energy (kWh) | `brick:Energy_Sensor` *(not `Electrical_Energy_Sensor` — absent in Brick 1.4)* |
| Occupancy count | `brick:Occupancy_Count_Sensor` (+ `brick:Occupancy_Sensor`) |
| Water flow | `brick:Water_Flow_Sensor` |
| Equipment run time | `brick:Run_Time_Sensor` |
| Noise level (dB) | `bldg:Noise_Level_Sensor` *(custom — Brick has none)* |
| Vibration | `bldg:Vibration_Sensor` *(custom — Brick has none)* |
| Outside air temperature | `brick:Outside_Air_Temperature_Sensor` |

If you add a class the LLM-facing class map doesn't know, also add a short keyword →
class entry in `sparql_agent._get_extended_class_map` so floor-scoped queries resolve it.

---

## Step 5: (optional) lay-term + recipe

If users ask with a lay term ("is the server-room fridge too cold?"), map it in
`input/concepts.ttl`:

```turtle
@prefix hbco: <http://ontosage.org/hbco#> .
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

hbco:fridge_temperature a hbco:Concept ;
    skos:prefLabel "fridge temperature"@en ;
    hbco:layTerm "fridge"^^xsd:string ;
    hbco:mapsToBrickClass brick:Air_Temperature_Sensor ;
    hbco:requiresRecipe "fridge_temp_threshold" .
```

For threshold/range/aggregate answers, add a recipe to `input/recipes.yaml` (overrides global
`config/recipes.yaml`). Kinds: `threshold | range | aggregate | correlate | trend | estimate | benchmark`.

---

## Step 6: Verify

```bash
# Point resolves in GraphDB with UUID + storedAt
curl -s -X POST http://127.0.0.1:7200/repositories/bldg \
  -H "Content-Type: application/sparql-query" -H "Accept: text/tab-separated-values" \
  --data-binary 'PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref: <https://brickschema.org/schema/Brick/ref#>
PREFIX bldg: <http://abacwsbuilding.cardiff.ac.uk/abacws#>
SELECT ?u ?st WHERE { ?s a brick:Energy_Sensor ; brick:hasLocation bldg:Floor5 ;
  ref:hasExternalReference/ref:hasTimeseriesId ?u . ?s ref:hasExternalReference/ref:storedAt ?st }'

# Ask a question (inside the container if the host port-forward is flaky)
docker exec ontosage-orchestrator python -c "import urllib.request,json; \
b=json.dumps({'model':'ontosage','messages':[{'role':'user','content':'energy on floor 5 yesterday?'}]}).encode(); \
print(json.load(urllib.request.urlopen(urllib.request.Request('http://localhost:8000/v1/chat/completions',data=b, \
headers={'Authorization':'Bearer sk-ontobot-pipeline','Content-Type':'application/json'}),timeout=120))['choices'][0]['message']['content'][:300])"
```

---

## Common mistakes

| Symptom | Fix |
|---|---|
| Point not in SPARQL after restart | Confirm the TTL is `input/*.ttl`; the startup loader logs `[ttl_uploader] startup ingestion`. Don't upload by hand. |
| Duplicate triples / sensor counted N× | A manual GraphDB upload alongside the startup loader. Clear the extra named/default graphs; let the loader own the file. |
| "No data" from SQL | The narrow table is empty or `storedAt` key ≠ a backend in `database_registry.yaml` / `building.yaml` storage filter. |
| Floor-scoped query returns nothing | `_infer_class` doesn't map the keyword → add it; check `brick:hasLocation` links to a `brick:Floor`. |
| Stale answers | Flush resp_cache: `docker exec redis-memory-store sh -c "redis-cli --scan --pattern 'resp_cache:*' \| xargs -r redis-cli del"` |
