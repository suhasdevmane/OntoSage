"""
Generate sensors_list.txt and sensor_uuids.txt in their final formats from bldg2.ttl.

Outputs:
- sensors_list.txt
  1) Instance sensor names (local names under bldg:), sorted, with a special
     duplicate of the first entry: once without a trailing tab, then again with
     a trailing tab; all subsequent instance lines end with a trailing tab.
  2) Brick sensor/setpoint class names rendered as <Name>.01, sorted lexicographically
     between Absolute_Humidity_Sensor and Zone_CO2_Level_Sensor (inclusive).

- sensor_uuids.txt (CSV: name,uuid)
  1) Instance sensor mappings (local name, ref:hasTimeseriesId)
  2) Class sensor mappings using <Name>.01 for the name and the class's timeseries id
     from its ref:hasExternalReference blank node.

Notes:
- This script uses bldg2.ttl as the canonical source to remain stable regardless
  of post-processing done in bldg2_timeseries.ttl.
- Turtle serialization order can differ; sorting makes results deterministic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import uuid

from rdflib import Graph, URIRef

ROOT = Path(__file__).parent
SRC_TTL = ROOT / "bldg2.ttl"
TS_TTL = ROOT / "bldg2_timeseries.ttl"
DEVICES_TTL = ROOT / "bldg2_new_devices_from_sensor_types.ttl"
OUT_LIST = ROOT / "sensors_list.txt"
OUT_UUIDS = ROOT / "sensor_uuids.txt"


def local_name(term) -> str:
    if isinstance(term, URIRef):
        s = str(term)
        for sep in ("#", "/"):
            if sep in s:
                s = s.rsplit(sep, 1)[-1]
        return s
    return ""


def instance_sensor_names(g: Graph) -> List[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    SELECT DISTINCT ?s WHERE {
      ?s a ?type .
      ?type rdfs:subClassOf* brick:Sensor .
      FILTER(STRSTARTS(STR(?s), "http://buildsys.org/ontologies/bldg2#"))
    }
    """
    names = [local_name(row[0]) for row in g.query(q)]
    names = [n for n in names if n]
    names.sort()
    return names


def class_sensor_names(g: Graph) -> List[str]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:   <http://www.w3.org/2002/07/owl#>
    SELECT DISTINCT ?c WHERE {
      ?c a owl:Class .
      ?c rdfs:subClassOf* brick:Sensor .
    }
    """
    names = [local_name(row[0]) for row in g.query(q)]
    names = [n for n in names if n.endswith("_Sensor") or n.endswith("_Setpoint")]
    # Lexicographic range inclusive
    lo = "Absolute_Humidity_Sensor"
    hi = "Zone_CO2_Level_Sensor"
    names = [n for n in names if lo <= n <= hi]
    names.sort()
    return names


def instance_sensor_uuid_pairs(g: Graph) -> List[Tuple[str, str]]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?s ?uuid WHERE {
      ?s a ?type .
      ?type rdfs:subClassOf* brick:Sensor .
      FILTER(STRSTARTS(STR(?s), "http://buildsys.org/ontologies/bldg2#"))
      ?s ref:hasExternalReference ?ref .
      ?ref ref:hasTimeseriesId ?uuid .
    }
    """
    rows = [(local_name(r[0]), str(r[1])) for r in g.query(q)]
    rows = [(n, u) for n, u in rows if n]
    rows.sort(key=lambda t: t[0])
    return rows


def class_sensor_uuid_pairs(g: Graph) -> List[Tuple[str, str]]:
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX owl:   <http://www.w3.org/2002/07/owl#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?c ?uuid WHERE {
      ?c a owl:Class .
      ?c rdfs:subClassOf* brick:Sensor .
      ?c ref:hasExternalReference ?ref .
      ?ref ref:hasTimeseriesId ?uuid .
    }
    """
    rows = [(local_name(r[0]), str(r[1])) for r in g.query(q)]
    rows = [(n, u) for n, u in rows if n.endswith("_Sensor") or n.endswith("_Setpoint")]
    lo = "Absolute_Humidity_Sensor"
    hi = "Zone_CO2_Level_Sensor"
    rows = [(n, u) for n, u in rows if lo <= n <= hi]
    rows.sort(key=lambda t: t[0])
    # Render name as <Name>.01
    return [(f"{n}.01", u) for n, u in rows]


def build_instance_uuid_index(g: Graph) -> Dict[str, str]:
    """Builds an index of instance-name -> uuid from the timeseries TTL.

    Supports both local-name forms: "AHU.X" and "bldg2.AHU.X" by emitting
    both keys when applicable so we can match whatever is listed in sensors_list.txt.
    """
    q = """
    PREFIX brick: <https://brickschema.org/schema/Brick#>
    PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?s ?uuid WHERE {
      ?s a ?type .
      ?type rdfs:subClassOf* brick:Sensor .
      FILTER(STRSTARTS(STR(?s), "http://buildsys.org/ontologies/bldg2#"))
      ?s ref:hasExternalReference ?ref .
      ?ref ref:hasTimeseriesId ?uuid .
    }
    """
    idx: Dict[str, str] = {}
    for s, uuid_val in g.query(q):
        ln = local_name(s)
        u = str(uuid_val)
        if not ln:
            continue
        # Primary key: local name as-is
        idx[ln] = u
        # Also support a 'bldg2.'-prefixed local name if it isn't present
        if not ln.startswith("bldg2."):
            idx.setdefault(f"bldg2.{ln}", u)
    return idx


def build_class_uuid_index_from_devices(g: Graph) -> Dict[str, str]:
    """Builds an index of class-name-with-suffix (e.g., Absolute_Humidity_Sensor.01)
    to uuid using the devices TTL whose subjects are bldg:<Name>.01.
    """
    q = """
    PREFIX ref:   <https://brickschema.org/schema/Brick/ref#>
    SELECT DISTINCT ?s ?uuid WHERE {
      ?s ref:hasExternalReference ?ref .
      ?ref ref:hasTimeseriesId ?uuid .
      FILTER(STRSTARTS(STR(?s), "http://buildsys.org/ontologies/bldg2#"))
    }
    """
    idx: Dict[str, str] = {}
    for s, uuid_val in g.query(q):
        ln = local_name(s)  # e.g., "Absolute_Humidity_Sensor.01"
        if not ln:
            continue
        idx[ln] = str(uuid_val)
    return idx


def write_sensor_uuids_from_sources(sensor_names_in_order: List[str]) -> None:
    """Populate sensor_uuids.txt for every name in sensors_list.txt using:
    - Instance UUIDs from bldg2_timeseries.ttl
    - Class .01 UUIDs from bldg2_new_devices_from_sensor_types.ttl

    If a UUID is missing from the sources, generate a deterministic UUIDv5
    in-place (preserving the exact ordering of sensors_list.txt).
    """
    if not TS_TTL.exists():
        raise FileNotFoundError(TS_TTL)
    if not DEVICES_TTL.exists():
        raise FileNotFoundError(DEVICES_TTL)

    g_ts = Graph()
    g_ts.parse(TS_TTL.as_posix(), format="turtle")
    inst_idx = build_instance_uuid_index(g_ts)

    g_dev = Graph()
    g_dev.parse(DEVICES_TTL.as_posix(), format="turtle")
    class_idx = build_class_uuid_index_from_devices(g_dev)

    rows: List[str] = []
    # Namespace uses the building URI to keep stability across runs.
    ns = uuid.uuid5(uuid.NAMESPACE_URL, "http://buildsys.org/ontologies/bldg2#")
    missing_count = 0
    for raw in sensor_names_in_order:
        name = raw.rstrip("\n\r\t ")  # keep exact name semantics without trailing whitespace
        if not name:
            continue
        found_uuid = None
        # Class names end with ".01" and do not contain dots like "AHU.AHU01" patterns
        if name.endswith(".01") and "." not in name[:-3]:
            found_uuid = class_idx.get(name)
        else:
            found_uuid = inst_idx.get(name)
        if not found_uuid:
            # Fallback inline to preserve order
            rows.append(f"{name},{uuid.uuid5(ns, name)}")
            missing_count += 1
        else:
            rows.append(f"{name},{found_uuid}")

    OUT_UUIDS.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_sensors_list(g: Graph):
    inst = instance_sensor_names(g)
    classes = class_sensor_names(g)

    lines: List[str] = []
    if inst:
        # First entry without tab, then duplicate with tab to match final file
        lines.append(f"{inst[0]}\n")
        lines.append(f"{inst[0]}\t\n")
        for n in inst[1:]:
            lines.append(f"{n}\t\n")
    for n in classes:
        lines.append(f"{n}.01\n")

    OUT_LIST.write_text("".join(lines), encoding="utf-8")


def write_sensor_uuids(g: Graph):
    inst_pairs = instance_sensor_uuid_pairs(g)
    class_pairs = class_sensor_uuid_pairs(g)
    # Join: instances first, then classes
    rows = inst_pairs + class_pairs
    OUT_UUIDS.write_text("\n".join(f"{n},{u}" for n, u in rows) + "\n", encoding="utf-8")


def main():
    if not SRC_TTL.exists():
        raise FileNotFoundError(SRC_TTL)
    g = Graph()
    g.parse(SRC_TTL.as_posix(), format="turtle")
    # Always (re)write the sensors list from canonical source
    write_sensors_list(g)

    # Now produce sensor_uuids.txt aligned to sensors_list.txt ordering
    names_in_order = OUT_LIST.read_text(encoding="utf-8").splitlines()
    write_sensor_uuids_from_sources(names_in_order)
    print(f"Wrote {OUT_LIST.name} and {OUT_UUIDS.name}")


if __name__ == "__main__":
    main()
