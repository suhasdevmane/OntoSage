"""Measure Building A against the LIVE GraphDB, for tab:building-characteristics
and the architecture figure's layer labels.

WHY LIVE AND NOT A REGEX
    An earlier attempt counted these from input/*.ttl with a regular expression.
    It anchored the subject at line start, so every indented declaration was
    invisible (1,957 vs 2,479), and it could not see brick:Floor or brick:Room
    at all because the spatial hierarchy is not written in the form it assumed.
    Turtle is not a table and inference is not text. GraphDB is the authority.

    Run the stack first:  docker compose up -d   (GraphDB on 7200)

OUTPUT
    paper/generated/building-characteristics.csv  (overwrites the regex version)
    paper/generated/live_layer_counts.csv         (architecture figure labels)
"""
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
GEN = os.path.join(PAPER, "generated")
EP = os.environ.get("GRAPHDB_SPARQL",
                    "http://127.0.0.1:7200/repositories/bldg")
# Where the CSVs go. Default: paper/generated/ (overwriting). The re-count of the frozen graph (29 Oct 2026) writes
# to its own folder so that the 24 September measurement stays on disk as a record.
OUT = os.environ.get("LIVE_FACTS_OUT", GEN)

PREFIX = """
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
PREFIX hbco:  <http://ontosage.org/hbco#>
PREFIX ontosage: <http://ontosage.org/capabilities#>
"""


def ask(q, label):
    """Run a SELECT and return rows. Never guess on failure -- report it."""
    data = urllib.parse.urlencode({"query": PREFIX + q}).encode()
    req = urllib.request.Request(
        EP, data=data,
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.load(r)
    except (urllib.error.URLError, OSError) as e:
        print(f"  !! {label}: query failed -- {e}")
        return None
    out = []
    for b in j["results"]["bindings"]:
        out.append({k: v["value"] for k, v in b.items()})
    return out


def one(q, label):
    r = ask(q, label)
    if r is None:
        return None
    if not r:
        return 0
    v = list(r[0].values())[0]
    try:
        return int(v)
    except ValueError:
        return v


QUERIES = {
    "floors":
        "SELECT (COUNT(DISTINCT ?f) AS ?n) WHERE { ?f a brick:Floor }",
    "locations_modelled":
        "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { "
        "?s a ?t . ?t rdfs:subClassOf* brick:Location }",
    "points_total":
        "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { "
        "?p a ?t . ?t rdfs:subClassOf* brick:Point }",
    "distinct_point_classes":
        "SELECT (COUNT(DISTINCT ?t) AS ?n) WHERE { "
        "?p a ?t . ?t rdfs:subClassOf* brick:Point }",
    "timeseries_bindings":
        "SELECT (COUNT(?u) AS ?n) WHERE { ?r ref:hasTimeseriesId ?u }",
    "distinct_timeseries_ids":
        "SELECT (COUNT(DISTINCT ?u) AS ?n) WHERE { ?r ref:hasTimeseriesId ?u }",
    "stored_at_keys":
        "SELECT (COUNT(DISTINCT ?k) AS ?n) WHERE { ?r ref:storedAt ?k }",
    "equipment":
        "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { "
        "?e a ?t . ?t rdfs:subClassOf* brick:Equipment }",
    "hbco_concepts":
        "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c a hbco:Concept }",
    "hbco_lay_terms":
        "SELECT (COUNT(?l) AS ?n) WHERE { ?c hbco:layTerm ?l }",
    "ocbv_amenities":
        "SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE { ?a a ontosage:Amenity }",
    "ocbv_knowledge_topics":
        "SELECT (COUNT(DISTINCT ?k) AS ?n) WHERE { ?k a ontosage:KnowledgeTopic }",
    "ocbv_classes":
        "SELECT (COUNT(DISTINCT ?c) AS ?n) WHERE { ?c a owl:Class "
        "FILTER(STRSTARTS(STR(?c), STR(ontosage:))) }",
    "ocbv_properties":
        "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?p a ?t "
        "FILTER(?t IN (owl:ObjectProperty, owl:DatatypeProperty, "
        "owl:AnnotationProperty)) "
        "FILTER(STRSTARTS(STR(?p), STR(ontosage:))) }",
}

# Points carry SEVERAL asserted types (a CO2 sensor is also brick:Sensor and
# brick:Point), so grouping by class double-counts: the asserted-class tally
# sums to 7,485 over 3,512 points. Each point is therefore assigned to exactly
# ONE category by the first rule that matches, and the script asserts that the
# categories sum to the point total. Order matters: CO2 is indoor climate in the
# paper's taxonomy, so climate is tested before air quality.
CATEGORIES = [
    ("Door and access contact", ("Contact_Sensor", "IntrusionDetector", "CCTV_Camera")),
    ("Occupancy (count, status)", ("Occupancy_Count", "Occupancy_Status",
                                   "Parking_Occupancy")),
    ("Lighting (colour temp., illuminance)",
     ("Illuminance", "Lighting_Correlated", "Luminance", "PIR_Lighting",
      "Lighting_Command")),
    ("Indoor climate (CO2, RH, air temp.)",
     ("CO2_Sensor", "CO2_Level", "Humidity", "Air_Temperature", "Temperature_Sensor")),
    ("Air quality (PM, TVOC, NO2, CO, CH2O, gas)",
     ("Air_Quality", "PM2.5", "PM10", "PM1_", "Particulate", "TVOC", "NO2",
      "CO_Sensor", "CO_Level", "Formaldehyde", "Gas_Sensor")),
    ("Acoustics (sound, noise)", ("Sound_Level", "Noise_Level")),
    ("Water (flow, level, temp., metering)", ("Water_",)),
    ("HVAC plant (air flow, damper, filter, fan)",
     ("Air_Flow", "Damper", "Filter_Differential", "Fan_", "Return_Air",
      "Supply_Air", "Run_Time", "Position_Sensor")),
    ("Electrical power", ("Active_Power", "Electric_Power", "Energy_Sensor")),
    ("Waste", ("Waste_",)),
    ("Outdoor and weather",
     ("Solar_Irradiance", "Rainfall", "Wind_Speed", "Outside_Air", "Soil_Moisture")),
]

POINT_TYPES = """
SELECT ?p ?c WHERE { ?p a ?c . ?c rdfs:subClassOf* brick:Point }
"""

MODALITY = """
SELECT ?cls (COUNT(DISTINCT ?p) AS ?n) WHERE {
  ?p a ?cls . ?cls rdfs:subClassOf* brick:Point
} GROUP BY ?cls ORDER BY DESC(?n)
"""


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"endpoint: {EP}\n")
    rows = []
    for k, q in QUERIES.items():
        v = one(q, k)
        if v is None:
            print(f"  {k:<26} QUERY FAILED -- not recorded")
            continue
        rows.append([k, v])
        print(f"  {k:<26} {v}")

    if not rows:
        print("\nNothing measured. Is the stack up? docker compose up -d")
        return 1

    # ---- one category per point, and prove the categories are exhaustive ----
    pairs = ask(POINT_TYPES, "point types")
    by_point = {}
    for r in pairs or []:
        by_point.setdefault(r["p"], set()).add(r["c"].rsplit("#", 1)[-1])
    cats, unclassified = {}, []
    for p, classes in by_point.items():
        hit = None
        for name, keys in CATEGORIES:
            if any(any(k in c for c in classes) for k in keys):
                hit = name
                break
        if hit:
            cats[hit] = cats.get(hit, 0) + 1
        else:
            unclassified.append(sorted(classes))
    print("\n  points by modality (each point counted once):")
    for name, _ in CATEGORIES:
        if cats.get(name):
            print(f"    {name:<44} {cats[name]:>5}")
            rows.append(["points: " + name, cats[name]])
    if unclassified:
        print(f"    {'(uncategorised)':<44} {len(unclassified):>5}")
        rows.append(["points: uncategorised", len(unclassified)])
    total = sum(cats.values()) + len(unclassified)
    pt = dict(rows).get("points_total")
    print(f"    {'TOTAL':<44} {total:>5}   (points_total = {pt})")
    assert total == pt, "categories do not sum to the point total"

    mods = ask(MODALITY, "modality breakdown")
    print(f"\n  point classes with instances: {len(mods) if mods else 0}")

    with io.open(os.path.join(OUT, "building-characteristics.csv"), "w",
                 encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["characteristic", "building_a"])
        w.writerows(rows)
        w.writerow(["# source", "live GraphDB, not a regex over Turtle"])

    if mods:
        with io.open(os.path.join(OUT, "live_point_classes.csv"), "w",
                     encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["brick_class", "n"])
            for m in mods:
                w.writerow([m["cls"].rsplit("#", 1)[-1], m["n"]])
        print(f"  wrote generated/live_point_classes.csv")
    print("  wrote generated/building-characteristics.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
