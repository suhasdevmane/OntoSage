"""
Builds bldg2_timeseries.ttl from bldg2.ttl by removing ref:hasExternalReference blocks
for sensors in the curated sensors_list range (Absolute_Humidity_Sensor..Zone_CO2_Level_Sensor),
both on class subjects (matching local name) and on instances typed as those classes.

This reproduces the final committed bldg2_timeseries.ttl semantics while keeping bldg2.ttl
as the primary source-of-truth.
"""
from pathlib import Path
from typing import List, Set
from rdflib import Graph, BNode, URIRef
from rdflib.namespace import RDF

ROOT = Path(__file__).parent
SRC = ROOT / "bldg2.ttl"
DST = ROOT / "bldg2_timeseries.ttl"
SENSORS_LIST = ROOT / "sensors_list.txt"


def local_name(term) -> str:
    if isinstance(term, URIRef):
        s = str(term)
        for sep in ("#", "/"):
            if sep in s:
                s = s.rsplit(sep, 1)[-1]
        return s
    return ""


def read_sensor_types_range(fp: Path, start: str, end: str) -> List[str]:
    lines = [ln.strip() for ln in fp.read_text(encoding="utf-8", errors="ignore").splitlines()]
    try:
        i0 = next(i for i, v in enumerate(lines) if v == start)
        i1 = next(i for i, v in enumerate(lines) if v == end and i >= i0)
    except StopIteration:
        # Fallback to all *_Sensor and *_Setpoint names
        return [v for v in lines if v.endswith("_Sensor") or v.endswith("_Setpoint")]
    picked = lines[i0 : i1 + 1]
    return [v for v in picked if v.endswith("_Sensor") or v.endswith("_Setpoint")]


def build():
    if not SRC.exists():
        raise FileNotFoundError(SRC)
    if not SENSORS_LIST.exists():
        raise FileNotFoundError(SENSORS_LIST)

    targets: Set[str] = set(read_sensor_types_range(SENSORS_LIST, "Absolute_Humidity_Sensor", "Zone_CO2_Level_Sensor"))
    g = Graph()
    g.parse(SRC.as_posix(), format="turtle")

    to_remove = []
    bnodes = set()

    for s, p, o in list(g):
        if local_name(p) != "hasExternalReference":
            continue
        # Case 1: class subject matches local name in targets
        if local_name(s) in targets:
            to_remove.append((s, p, o))
            if isinstance(o, BNode):
                bnodes.add(o)
            continue
        # Case 2: instance typed as a target class
        for _, _, t in g.triples((s, RDF.type, None)):
            if local_name(t) in targets:
                to_remove.append((s, p, o))
                if isinstance(o, BNode):
                    bnodes.add(o)
                break

    for triple in to_remove:
        g.remove(triple)
    for bn in bnodes:
        for triple in list(g.triples((bn, None, None))):
            g.remove(triple)

    DST.write_text(g.serialize(format="turtle"), encoding="utf-8")


if __name__ == "__main__":
    build()
