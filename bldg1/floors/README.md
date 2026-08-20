# Abacws floor plans → Brick/BOT knowledge graph

Turns the Abacws DWG floor plans into a SPARQL-queryable graph so a QA system
can answer questions about the building **without any visual information**.

Reads DWG **directly** — no ODA File Converter, no DXF intermediate.

```
Abacws floor 0-5.dwg
      │  tools/dwg_read.mjs  (LibreDWG compiled to WebAssembly)
      ▼
  <floor>.dwg.json ──── pipeline.extract ───▶ out/Storey_NN.json
   (cached)                (shapely)               (per floor)
                                                        │
                                            pipeline.merge  ← vertical cores
                                                        │
                                          pipeline.to_rdf (rdflib)
                                                        ▼
                                            out/abacws_building.ttl
                                          Brick + BOT + GeoSPARQL
                                                        │
                                                        ▼
                                        Fuseki / Oxigraph / GraphDB
                                            → SPARQL endpoint = your API
```

---

## Why these formats

**Turtle (Brick + BOT + GeoSPARQL) is the serving format.** Three
vocabularies, each doing one job:

| Vocabulary | Role |
|---|---|
| **BOT** (W3C LBD CG) | topology — `Site → Building → Storey → Space`, `bot:adjacentZone`, `bot:Interface`, `bot:containsElement` |
| **Brick 1.3+** | classification — `Room`, `Floor`, `Door`, `Electrical_Equipment`, and the sensor/point hierarchy your IoT data hangs off |
| **GeoSPARQL** | geometry — `geo:asWKT` polygons, so spatial questions stay answerable in SPARQL |

Every space is **one URI** shared across all three, so a single query can
cross topology, classification and geometry.

**Rejected:** PDF/SVG/PNG (appearance, not meaning), raw DXF-as-API (no query
layer), IFC (see the caveat at the bottom).

---

## Setup

```bash
pip install -r requirements.txt
cd tools && npm install && cd ..     # pulls the LibreDWG WASM build
```

Then download the DWGs from AutoCAD Web (red **A** → right-click a file →
**Download**) into `dwg/`.

## Run the whole building

```bash
python -m pipeline.cli building -c config.building.yaml --outdir out
```

That reads all six DWGs, extracts each floor, infers vertical circulation,
and writes one merged `out/abacws_building.ttl` plus per-floor JSON.

**Before trusting the output, look at a layer table.** Layer names differ
between floors more often than you would like:

```bash
python -m pipeline.cli layers "dwg/Abacws floor 3.dwg"
```

This prints every layer with entity counts and types, plus `INSUNITS`.
`INSUNITS 4` = millimetres → keep `units_to_metres: 0.001`. If a floor comes
back `6` (metres), give that floor an override in `config.building.yaml`,
otherwise its areas will be out by a factor of a million.

Single floor, if you want to iterate on config quickly:

```bash
python -m pipeline.cli extract "dwg/Abacws floor 2.dwg" -c config.yaml -o floor2.json
python -m pipeline.cli rdf floor2.json -o floor2.ttl
```

## Serve it

```bash
docker run -p 7878:7878 -v $PWD:/data oxigraph/oxigraph \
  serve --location /data/store --bind 0.0.0.0:7878
curl -X POST -H 'Content-Type: text/turtle' \
  --data-binary @out/abacws_building.ttl \
  'http://localhost:7878/store?default'
```

Apache Jena **Fuseki** is the alternative if you want GeoSPARQL spatial
functions and rule-based inference. Either way, **the SPARQL endpoint is your
API** — there is no service layer to write.

Test queries without a server first:

```bash
python -m pipeline.cli query out/abacws_building.ttl queries/10_route_across_floors.rq
```

---

## What gets extracted

| Output | Method |
|---|---|
| **Spaces** | closed polylines on `USABLE` / `POLYLINES`, de-duplicated across layers |
| **Room code + name** | text on `ROOM_NAMES` etc., joined by point-in-polygon, split top-to-bottom (`0Z21` above `41P Collab S`) |
| **Area, perimeter, centroid, bbox, WKT** | shapely, after unit scaling |
| **Elements** | block references, typed to Brick classes by layer pattern |
| **Asset attributes** | `ATTRIB` tags on block references — the only native key/value data a DWG carries |
| **Dimensions** | `DIMENSION` entities with the value the CAD app computed from the geometry |
| **Adjacency** | length of shared boundary run between space pairs |
| **Connectivity** | doors sitting on a boundary between two spaces |
| **Vertical circulation** | stair/lift cores with stacked footprints on adjacent storeys |

### Dimensions

A `DIMENSION` entity is not a picture of a measurement — it carries
`measurement`, the number the CAD application computed from the underlying
geometry. That makes "how wide is the corridor" a directly answerable fact.

Two things to know:

- **`abx:textOverride` beats `abx:measurement`.** When a drafter types a
  value in place of the computed one, they did it deliberately — often
  because the drawn geometry is schematic. Query 08 returns both; prefer the
  override where present.
- **Dimensions bypass `ignore_layers`.** `A-ANNO-DIMS` is excluded from room
  extraction because it is visual clutter, but its measurements are wanted,
  so the ignore list deliberately does not apply to `DIMENSION` entities.

### Vertical circulation is *inferred*

Nothing in a 2D plan states that the stair on floor 1 is the same stair as on
floor 2. `abx:verticallyConnectedTo` is inferred from two things: a footprint
that overlaps across adjacent storeys, and a room name that reads as
circulation (`merge.core_patterns`). Overlap is measured against the
**smaller** footprint, so a lift shaft still links to the larger stair core
enclosing it.

Treat these edges as inference, not survey. If `check_alignment` warns that
floors disagree on their bounding box, the drawings probably do not share a
coordinate origin, and every vertical link is then suspect.

---

## Gotchas worth knowing up front

**`bot:adjacentZone` ≠ passable.** Sharing a wall and being walkable between
are different facts, and a QA system that conflates them will give
confidently wrong wayfinding answers. Both are emitted separately:
`bot:adjacentZone` for shared boundary, `abx:connectedTo` only where a door
links two spaces. Query 02 shows the contrast; query 10 routes on doors and
stairs only.

**Plain literals, not `xsd:string`.** RDF 1.1 says `"0Z19"` and
`"0Z19"^^xsd:string` are the same term. rdflib does **not** equate them, so a
typed room code silently returns zero rows for every lookup. Room codes are
emitted as plain literals for this reason. (Fuseki and GraphDB canonicalise
correctly, but relying on that makes your graph store-dependent.)

**A non-zero LibreDWG pointer is not a successful read.** LibreDWG returns a
pointer alongside a non-fatal error code for a malformed file. `dwg_read.mjs`
validates the converted database instead and exits non-zero on an empty one.

**IDs are namespaced per storey.** Room codes repeat across floors in some
buildings, so every local id is prefixed with its storey (`Storey_02_Space_2Z19`).
The `abx:roomCode` literal stays unprefixed — that is your join key.

**Adjacency length carries a tolerance correction.** The shared boundary is
found by dilating one polygon's boundary by `tolerance_m` and intersecting
with the other's, which overshoots by up to `tol` at each end, so `2 × tol`
is subtracted. This also collapses corner-only touches to ≈0, which
`min_shared_boundary_m` then filters out.

**The first read of each DWG is slow.** LibreDWG parsing 10–30 MB takes a
while, so results are cached as `out/cache/<name>.dwg.json` and reused.
Delete that folder to force a re-read after changing the reader.

---

## Joining your IoT data

`sensor plan.dwg` sits in the same AutoCAD folder, which suggests this is
where you are heading:

```bash
python -m pipeline.cli building -c config.building.yaml --outdir out --sensors sensors.csv
```

CSV columns: `sensor_id, room_code, brick_class, label` (see
`sensors.example.csv`). Each becomes `brick:hasPoint` off the **same room URI**
the CAD geometry produced. `room_code` is the join key — the value estates,
timetabling and BMS systems already share, which is why it is worth
extracting carefully.

---

## Queries

| File | Question |
|---|---|
| `01_room_by_code` | everything known about one room |
| `02_adjacent_rooms` | what is next to it, and can you walk there |
| `03_reachable_rooms` | door-graph reachability within a storey |
| `04_largest_rooms` | biggest spaces on a storey |
| `05_rooms_with_equipment` | equipment locations + asset tags |
| `06_floor_summary` | room count and area per storey |
| `07_sensors_in_room` | IoT points bound to a room |
| `08_dimensions_in_room` | measured dimensions, with overrides |
| `09_vertical_circulation` | which cores link which floors |
| `10_route_across_floors` | building-wide reachability, doors + stairs |
| `11_building_summary` | rooms and area per storey, ordered |
| `12_largest_rooms_building` | biggest spaces anywhere, with footprint |

---

## Room boundary tracing (the BOUNDARY / BPOLY job)

If the drawings carry **no closed polygon per room**, `pipeline/boundary.py`
reconstructs one per room number.

```bash
python -m pipeline.cli rooms "Abacws floor 5.dxf" --dry-run     # report only
python -m pipeline.cli rooms "Abacws floor 5.dxf" -o "out/Abacws floor 5.dxf"
```

**This is not AutoCAD's BOUNDARY command.** BOUNDARY needs the AutoCAD
geometry engine and no Python or JS library reimplements it. This does the
same job a different way, and the method is worth knowing because its failure
modes differ:

1. collect every wall (and door) line as a LineString
2. `unary_union` — nodes the network at every crossing
3. `polygonize` — yields every enclosed face, i.e. every region BOUNDARY could
   possibly return
4. for each room-number TEXT, take the face containing its insertion point

Step 3 returns the **inner face** of the walls automatically: walls drawn as
two parallel lines produce a face bounded by the inner line of each, which is
exactly what BOUNDARY gives you.

### Input must be DXF, not DWG

The `rooms` command rewrites the drawing, and only ezdxf's own DXF round-trip
preserves entities it does not understand — AEC proxy objects especially.
Routing a DWG through a third-party reader first would quietly drop them, so
the command refuses DWG rather than silently degrading the file. Export
**DXF R2018 ASCII** from AutoCAD (`SAVEAS` → DXF) and run against that.

Every run prints a census proving nothing else moved: each pre-existing layer
must have the same entity count afterwards, or you get a warning.

### Failure modes, all reported rather than approximated

| Report | Cause |
|---|---|
| *region also encloses 0.03* | gap in the wall between two rooms — **both** reported, no merged polygon emitted |
| *no enclosing region* | the room leaked to the drawing exterior; wall lines around it have a gap |
| *only 0.10 m across at its widest* | pick point landed inside a wall cavity. Caught by an inscribed-circle test, because a long thin cavity has plenty of *area* and passes a naive area check |
| *N island(s), overstates area by X m²* | a column or riser inside the room. Traced fine, but see below |

### Two things that will bite on real drawings

**Doorways are gaps, and door jamb lines alone do not seal them.** A doorway
is a genuine break in the wall lines. Jamb lines partition the wall cavity
without blocking passage through it — a room still leaks through the cavity
into its neighbour. What seals an opening is the **threshold line** a door
block usually draws across it. So `A-DOOR` must be in the linework, and if
this drawing's door blocks have no threshold lines, expect every doored room
to fail as merged. The fixture tests both configurations precisely because
this is the difference between 45 rooms and 2.

**One polyline per room means columns are not subtracted.** A closed
LWPOLYLINE is a single ring and cannot carry a hole. Where a room encloses a
column or riser, AutoCAD BOUNDARY would emit a second polyline for the island;
this emits one ring and *reports how much floor area that overstates*. If you
would rather have the islands as separate polylines, say so — it is a small
change, but it breaks the "exactly one polyline per room" rule you asked for.

Each traced polyline carries its room number as XDATA under appid
`ABACWS_KG`, so the result is self-describing without adding a visible entity.

### Verifying it

```bash
python tests/make_boundary_fixture.py
python -m pipeline.cli rooms boundary_fixture.dxf --dry-run \
    --wall-layers A-WALL I-WALL --door-layers A-DOOR
```

The fixture is a plan with deliberate defects and known ground truth: 0.01
traces at 89.90 m²; 0.04 traces at 67.31 m² with one column island; 0.02 and
0.03 both fail as one merged region (1 m gap in the partition); 0.06 fails
having leaked to the exterior; 0.07 fails as a wall cavity. Drop `A-DOOR` from
the wall network and 0.04 joins the merge failure — which is the doorway point
above, demonstrated.


---

## The honest caveat about IFC

**IFC would be the better source, and these DWGs cannot become good IFC.**

In a 2D architectural drawing, walls are pairs of lines and rooms are
polylines with text near them. There are no wall solids, no space objects, no
property sets, no storey heights. Any DWG→IFC converter has to guess all of
that, and it guesses badly.

The Abacws files load AEC object enablers on open (`AEC Base`,
`AEC Project Base`, `AEC Schedule` appear during initialisation), which means
they originated in AutoCAD Architecture or were exported from Revit. **If the
estates or capital projects team still holds the Revit model or an IFC4
export, that is worth an email.** `IfcSpace` objects arrive with stable GUIDs,
names, areas and property sets already attached — query them with IfcOpenShell,
or lift to ifcOWL and merge into the same graph.

Failing that, this pipeline is the right reconstruction, and its output has the
same shape either way, so swapping the source later does not invalidate your
query layer.

## What this does not recover

Be explicit with your QA system about these, so it declines rather than guesses:

- **Heights and volumes.** These are 2D plans; there is no Z. Storey *levels*
  are ordinal, not elevations in metres.
- **Room function beyond the drawn label.** "41P Collab S" is a string, not a
  classification. Map codes to Brick subclasses of `brick:Room` yourself.
- **Materials, fire ratings, U-values, occupancy limits.** Never in a plan.
- **Whether a door is lockable, accessible, or fire-rated.** A door block is a
  door block.

---

## Layout

```
config.yaml                single-floor layer→semantics mapping
config.building.yaml       all floors + cross-floor merge settings
requirements.txt
tools/dwg_read.mjs         DWG → JSON via LibreDWG WebAssembly
tools/package.json         npm dependency for the above
pipeline/entities.py       normalised entity model shared by both readers
pipeline/readers.py        DWG and DXF front-ends
pipeline/extract.py        entities → structured floor model
pipeline/boundary.py       BOUNDARY/BPOLY equivalent: wall network -> room polygons
pipeline/merge.py          cross-floor: alignment checks, vertical cores
pipeline/to_rdf.py         floor models → Brick/BOT/GeoSPARQL Turtle
pipeline/cli.py            layers | extract | rooms | building | rdf | query
queries/*.rq               12 worked SPARQL queries
tests/make_synthetic_dxf.py    multi-storey fixture with known ground truth
tests/make_boundary_fixture.py defective plan for testing boundary tracing
dwg/                       put the downloaded DWG files here
```

## Verifying the pipeline

The synthetic fixture encodes known ground truth: 3 storeys × 4 rooms
(24 + 24 + 36 + 9 = 93 m²), a stair core with an identical footprint on every
floor, doors linking Z19↔Z21, Z19↔.29 and Z21↔Z05 but *not* Z21↔.29, and 3
dimensions per floor (6.0 m, 6.0 m outside any room, 4.0 m inside Vending).

```bash
python tests/make_synthetic_dxf.py 3
python -m pipeline.cli building -c tests/config.test.yaml --outdir /tmp/outb
python -m pipeline.cli query /tmp/outb/abacws_building.ttl queries/10_route_across_floors.rq
```

Expected: 279 m² over 3 storeys, 2 vertical links, and query 10 returning all
11 other rooms from a `0Z19` start — reachable only because the route goes
through the stair core, which is the doors-plus-stairs path doing real work.

`examples/` holds the JSON, Turtle and summary from that synthetic 3-storey
run, so you can see the exact output shape before the real DWGs go through.
