import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Set

from rdflib import Graph, URIRef, Namespace


BLDG = Namespace("bldg:")
BRICK = Namespace("brick:")
REF = Namespace("ref:")
RDFS = Namespace("rdfs:")
RDF = Namespace("rdf:")


def is_bldg_individual(s: URIRef) -> bool:
    return isinstance(s, URIRef) and str(s).startswith("bldg:")


def load_graph(ttl_path: Path) -> Graph:
    g = Graph()
    g.parse(ttl_path.as_posix(), format="turtle")
    return g


def list_bldg_entities(g: Graph) -> Set[str]:
    ents: Set[str] = set()
    for s, p, o in g:
        if is_bldg_individual(s):
            ents.add(str(s))
        if isinstance(o, URIRef) and is_bldg_individual(o):
            ents.add(str(o))
    return ents


def has_timeseries_ref(g: Graph, ent: str) -> bool:
    # bldg:X ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference .
    q = f"""
SELECT * WHERE {{
  {ent} ref:hasExternalReference ?ref .
  ?ref a ref:TimeseriesReference .
}} LIMIT 1
"""
    return len(list(g.query(q))) > 0


def mk_type_a_questions(ent: str, labels: List[str], locations: List[str]) -> List[Dict[str, str]]:
    qs: List[Dict[str, str]] = []

    # Location lookup
    qs.append({
        "question": f"Where is {labels[0] if labels else ent.split(':')[-1]} located?",
        "entity": ent,
        "sparql": f"SELECT ?location WHERE {{ {ent} brick:hasLocation ?location . }}"
    })

    # Label(s)
    qs.append({
        "question": f"What is the label and type of {labels[0] if labels else ent.split(':')[-1]}?",
        "entity": ent,
        "sparql": f"SELECT ?label ?type WHERE {{ {ent} rdfs:label ?label . {ent} rdf:type ?type . }}"
    })

    # Count related points/sensors (generic pattern)
    qs.append({
        "question": f"How many points or connections are associated with {labels[0] if labels else ent.split(':')[-1]}?",
        "entity": ent,
        "sparql": f"SELECT (COUNT(?p) AS ?count) WHERE {{ {ent} ?p ?o . }}"
    })

    return qs


def mk_type_b_questions(ent: str) -> List[Dict[str, str]]:
    base = {
        "entity": ent,
    }
    q = f"SELECT ?timeseriesId ?storedAt WHERE {{ {ent} ref:hasExternalReference ?ref . ?ref a ref:TimeseriesReference ; ref:hasTimeseriesId ?timeseriesId ; ref:storedAt ?storedAt . }}"
    return [
        {
            **base,
            "question": f"What data stream ID and storage backend should I use to fetch recent readings for {ent.split(':')[-1]}?",
            "sparql": q,
        },
        {
            **base,
            "question": f"Provide the timeseries identifier and where it is stored for the sensor {ent.split(':')[-1]} to compute averages or trends.",
            "sparql": q,
        },
    ]


def collect_labels_locations(g: Graph, ent: str) -> Tuple[List[str], List[str]]:
    labels: List[str] = []
    locs: List[str] = []
    q1 = f"SELECT ?l WHERE {{ {ent} rdfs:label ?l . }}"
    q2 = f"SELECT ?loc WHERE {{ {ent} brick:hasLocation ?loc . }}"
    for row in g.query(q1):
        labels.append(str(row[0]))
    for row in g.query(q2):
        locs.append(str(row[0]))
    return labels, locs


def generate_pairs(g: Graph) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    entities = sorted(list_bldg_entities(g))
    for ent in entities:
        labels, locs = collect_labels_locations(g, ent)
        out.extend(mk_type_a_questions(ent, labels, locs))
        if has_timeseries_ref(g, ent):
            out.extend(mk_type_b_questions(ent))
    return out


def main():
    if len(sys.argv) < 3:
        print("Usage: python brick_nl2sparql_generator.py <input_ttl> <output_json>")
        sys.exit(1)
    ttl_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    g = load_graph(ttl_path)
    pairs = generate_pairs(g)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(pairs, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(pairs)} pairs to {out_path}")


if __name__ == "__main__":
    main()
