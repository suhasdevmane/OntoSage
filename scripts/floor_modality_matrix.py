"""Which measurands reach which floors, read from the graph's own topology.

Run it inside the orchestrator container (the host cannot resolve `graphdb`):

    docker exec ontosage-orchestrator python scripts/floor_modality_matrix.py

WHY THIS EXISTS, when scripts/data_coverage_audit.py already reports coverage: that one
derives a sensor's floor from its URI or label text, so on this building ~4,000 of 5,874
sensors land in a column called "F?" and no per-floor gap list can be trusted. A sensor's
floor is a fact the building STATES -- sensor -> space -> floor -- and that is what this
reads. Measured 2026-09-16, it put all but 29 points on a named floor and showed six gases
present on exactly one floor, which the text-parsing audit could not see (TODO-624B).

It also separates a gap that MATTERS from one that is correct: a rainfall sensor absent from
Floor 2 is not a gap, and the report says which classes are present on some floors and absent
on others rather than demanding every class on every floor.

Building-agnostic: no floor list, no namespace, no class list appears here. The endpoint and
repository come from the environment, and everything else from whatever graph is live.
"""
import json
import os
import urllib.request
from collections import defaultdict

ENDPOINT = (
    os.environ.get("GRAPHDB_URL", "http://graphdb:7200").rstrip("/")
    + "/repositories/"
    + os.environ.get("GRAPHDB_REPOSITORY", "bldg")
)

QUERY = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT ?floorLabel ?cls (COUNT(DISTINCT ?p) AS ?n) WHERE {
  ?p a ?cls .
  ?cls rdfs:subClassOf* brick:Point .
  ?p ref:hasExternalReference ?r .
  ?r ref:hasTimeseriesId ?uuid .
  OPTIONAL {
    ?p brick:hasLocation|brick:isPointOf|brick:isPartOf ?space .
    ?space brick:isPartOf* ?floor .
    ?floor a brick:Floor .
    OPTIONAL { ?floor rdfs:label ?fl }
    BIND(COALESCE(?fl, REPLACE(STR(?floor), "^.*[/#]", "")) AS ?floorLabel)
  }
}
GROUP BY ?floorLabel ?cls
"""


def ask(query):
    req = urllib.request.Request(
        ENDPOINT,
        data=query.encode("utf-8"),
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as fh:
        return json.load(fh)["results"]["bindings"]


rows = ask(QUERY)
matrix = defaultdict(lambda: defaultdict(int))
floors, classes = set(), set()
for row in rows:
    floor = row.get("floorLabel", {}).get("value", "(no floor stated)")
    cls = row["cls"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    n = int(row["n"]["value"])
    matrix[floor][cls] += n
    floors.add(floor)
    classes.add(cls)

# Floors the building declares, whether or not any point sits on one.
declared = ask(
    """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?floor ?fl WHERE { ?floor a brick:Floor . OPTIONAL { ?floor rdfs:label ?fl } }
"""
)
declared_floors = sorted(
    {
        d.get("fl", {}).get("value") or d["floor"]["value"].rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        for d in declared
    }
)
print(f"Floors the building declares ({len(declared_floors)}): {declared_floors}\n")

ordered_classes = sorted(classes)
print(f"Measurand classes with a timeseries reference: {len(ordered_classes)}\n")

named = [f for f in sorted(floors) if f != "(no floor stated)"]
width = max((len(c) for c in ordered_classes), default=10) + 2
header = "class".ljust(width) + "".join(f.rjust(12) for f in named) + "unplaced".rjust(12)
print(header)
print("-" * len(header))
for cls in ordered_classes:
    line = cls.ljust(width)
    for f in named:
        n = matrix[f].get(cls, 0)
        line += (str(n) if n else "·").rjust(12)
    line += str(matrix["(no floor stated)"].get(cls, 0) or "·").rjust(12)
    print(line)

print("\nGAPS — a floor the building declares that this class does not reach:")
gaps = 0
for cls in ordered_classes:
    missing = [f for f in declared_floors if not matrix.get(f, {}).get(cls)]
    if missing and len(missing) < len(declared_floors):
        print(f"  {cls}: missing on {', '.join(missing)}")
        gaps += 1
print(f"\n{gaps} classes are present on some floors and absent on others.")
unplaced = sum(matrix["(no floor stated)"].values())
print(f"Points with a timeseries reference and NO floor in the graph: {unplaced}")
