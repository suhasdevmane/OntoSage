"""
Lists sensors in bldg2_timeseries.ttl and writes a summary to sensors_list.txt.

Outputs:
- sensors_list.txt: counts and lists of sensor instances/classes with and without refs
"""

from pathlib import Path
from rdflib import Graph, Namespace

BRICK = Namespace("https://brickschema.org/schema/Brick#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")

HERE = Path(__file__).parent
TTL = HERE / "bldg2_timeseries.ttl"
OUT = HERE / "sensors_list.txt"


def parse_ttl_robust(ttl_path: Path) -> Graph:
  g = Graph()
  g.parse(ttl_path.as_posix(), format="turtle")
  return g


g = parse_ttl_robust(TTL)

# Instances of subclasses of brick:Sensor and their ref status
q_instances = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?s ?type ?ref WHERE {
  ?s a ?type .
  ?type rdfs:subClassOf* brick:Sensor .
  OPTIONAL { ?s ref:hasExternalReference ?ref }
}
ORDER BY ?s
"""

# Classes that are subclasses of brick:Sensor and their ref status
q_classes = """
PREFIX brick: <https://brickschema.org/schema/Brick#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:   <http://www.w3.org/2002/07/owl#>
PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
SELECT DISTINCT ?c ?ref WHERE {
  ?c a owl:Class .
  ?c rdfs:subClassOf* brick:Sensor .
  OPTIONAL { ?c ref:hasExternalReference ?ref }
}
ORDER BY ?c
"""

instances = [(str(row[0]), str(row[1]), row[2] is not None) for row in g.query(q_instances)]
classes = [(str(row[0]), row[1] is not None) for row in g.query(q_classes)]

inst_with_ref = [i for i in instances if i[2]]
inst_without_ref = [i for i in instances if not i[2]]
cls_with_ref = [c for c in classes if c[1]]
cls_without_ref = [c for c in classes if not c[1]]

with OUT.open("w", encoding="utf-8") as f:
  f.write("Sensor summary for bldg2_timeseries.ttl\n")
  f.write("======================================\n\n")
  f.write(f"Instance sensors: total={len(instances)}, with_ref={len(inst_with_ref)}, without_ref={len(inst_without_ref)}\n")
  f.write(f"Class sensors:    total={len(classes)}, with_ref={len(cls_with_ref)}, without_ref={len(cls_without_ref)}\n\n")

  f.write("-- Instance sensors WITH ref --\n")
  for s, t, _ in inst_with_ref:
    f.write(f"{s}\t{t}\n")

  f.write("\n-- Instance sensors WITHOUT ref --\n")
  for s, t, _ in inst_without_ref:
    f.write(f"{s}\t{t}\n")

  f.write("\n-- Class sensors WITH ref --\n")
  for c, _ in cls_with_ref:
    f.write(f"{c}\n")

  f.write("\n-- Class sensors WITHOUT ref --\n")
  for c, _ in cls_without_ref:
    f.write(f"{c}\n")

print(f"Wrote {OUT}")
