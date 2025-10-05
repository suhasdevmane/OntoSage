"""
Generate a sensor -> timeseries UUID mapping for Building 1 from bldg1.ttl.

Outputs (written to the same directory as this script):
- bldg1_sensor_uuids.txt  (CSV: sensor_local_name,uuid)
- bldg1_sensors_list.txt  (Plain list of sensor local names, one per line)

Logic:
1. Load bldg1.ttl (must define prefix bldg: pointing to the building namespace
   e.g. http://abacwsbuilding.cardiff.ac.uk/abacws#).
2. Find all instance IRIs (?s) that:
      - Are typed as some ?type with rdfs:subClassOf* brick:Sensor
      - Start with the building namespace (FILTER STRSTARTS)
      - Have a ref:hasExternalReference / ref:hasTimeseriesId triple
3. Extract the local name (portion after last '#' or '/').
4. Write a deterministic, sorted list of sensors and corresponding UUIDs.

Notes:
- Only instance sensors are considered. Class-level sensors (owl:Class) are ignored
  unless they appear as instances (rare) because requirement specifies bldg:<sensor>.
- If you later need to replicate the class-based augmentation like bldg2's script,
  you can extend this with a class sensor query.
- Requires rdflib:  pip install rdflib
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from rdflib import Graph, URIRef

# -------- Configuration --------
ROOT = Path(__file__).parent
SRC_TTL = ROOT / "bldg1.ttl"
OUT_UUIDS = ROOT / "bldg1_sensor_uuids.txt"
OUT_LIST = ROOT / "bldg1_sensors_list.txt"

# Namespace for building 1 (must match the bldg: prefix base in bldg1.ttl)
BUILDING_NS = "http://abacwsbuilding.cardiff.ac.uk/abacws#"

# -------- Helpers --------

def local_name(term) -> str:
    if isinstance(term, URIRef):
        s = str(term)
        for sep in ("#", "/"):
            if sep in s:
                s = s.rsplit(sep, 1)[-1]
        return s
    return ""


def sensor_uuid_rows(g: Graph) -> List[Tuple[str, str]]:
    """Return list of (local_name, uuid) for sensors with external reference."""
    q = f"""
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?s ?uuid WHERE {{
      ?s a ?type .
      ?type rdfs:subClassOf* brick:Sensor .
      FILTER(STRSTARTS(STR(?s), "{BUILDING_NS}"))
      ?s ref:hasExternalReference ?ref .
      ?ref ref:hasTimeseriesId ?uuid .
    }}
    """
    rows: List[Tuple[str, str]] = []
    for s, uuid_val in g.query(q):  # type: ignore[arg-type]
        ln = local_name(s)
        if not ln:
            continue
        rows.append((ln, str(uuid_val)))
    rows.sort(key=lambda t: t[0])
    return rows


# -------- Main write functions --------

def write_outputs(rows: List[Tuple[str, str]]):
    if not rows:
        print("[WARN] No sensors with external references found.")
    # Sensors list (names only)
    OUT_LIST.write_text("\n".join(r[0] for r in rows) + "\n", encoding="utf-8")
    # UUID CSV
    OUT_UUIDS.write_text("\n".join(f"{n},{u}" for n, u in rows) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_LIST.name} ({len(rows)} names)")
    print(f"Wrote {OUT_UUIDS.name} ({len(rows)} rows)")


def main():
    if not SRC_TTL.exists():
        raise FileNotFoundError(f"Missing source TTL: {SRC_TTL}")
    g = Graph()
    g.parse(SRC_TTL.as_posix(), format="turtle")
    rows = sensor_uuid_rows(g)
    write_outputs(rows)


if __name__ == "__main__":
    main()
