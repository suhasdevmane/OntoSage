"""Generate a large NL->SPARQL training dataset for bldg3 Brick graph.

Output schema (extended):
[
  {
    "question": str,                # Natural language question
    "entities": [str, ...],         # List of entity surface forms appearing in question (URIs or labels)
    "sparql": str,                  # SPARQL query text (with prefixes)
    "category": str,                # Template/category id
    "notes": str                    # (optional) short rationale
  }, ...
]

Design goals:
- Mix structural graph queries and timeseries reference lookups (via ref:hasExternalReference).
- Support single and multi-entity questions.
- Provide linguistic variation per template.
- Keep queries executable against the provided TTL (no invented predicates).

Assumptions:
- bldg3.ttl is in same directory.
- rdflib is installed in the environment.

Usage:
  python generate_bldg3_dataset.py --ttl bldg3.ttl --out bldg3_dataset.json --limit 1500

You can increase --limit for a larger dataset (script will sample & cycle templates).
"""
from __future__ import annotations
import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Iterable, Tuple, Set

from rdflib import Graph, Namespace, RDF, RDFS, URIRef, Literal
import re

BRICK = Namespace("https://brickschema.org/schema/Brick#")
BLDG = Namespace("http://buildsys.org/ontologies/bldg3#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")
TAG = Namespace("https://brickschema.org/schema/BrickTag#")

PREFIXES = """"""  # Intentionally blank: user will inject prefixes later

@dataclass
class Point:
    uri: URIRef
    label: str | None
    external_ref: str | None
    classes: List[URIRef]

@dataclass
class Equip:
    uri: URIRef
    label: str | None
    classes: List[URIRef]
    points: List[Point]

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

# Template registry ---------------------------------------------------------
# Each template function returns (question, entities[list], sparql, category, notes)

TemplateFunc = callable

class TemplateGenerator:
    def __init__(self, g: Graph, points: List[Point], equips: List[Equip]):
        self.g = g
        self.points = points
        self.equips = equips

    # 1. Get external reference for a point
    def t_point_external_ref(self, p: Point):
        q_variants = [
            f"What is the external reference id for {p.uri.split('#')[-1]}?",
            f"Give me the external identifier linked to {p.uri.split('#')[-1]}",
            f"Which external reference does the point {p.uri.split('#')[-1]} have?",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT ?ref WHERE {{ {format_uri(p.uri)} ref:hasExternalReference ?ref . }}"
        entities = [str(p.uri)]
        return question, entities, sparql, "point_external_ref", "Lookup external ref"

    # 2. List points of an equipment
    def t_equipment_points(self, e: Equip):
        q_variants = [
            f"List all points of {e.uri.split('#')[-1]}",
            f"Which points belong to {e.uri.split('#')[-1]}?",
            f"Show me every point attached to {e.uri.split('#')[-1]}",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT ?point WHERE {{ {format_uri(e.uri)} brick:hasPoint ?point . }}"
        entities = [str(e.uri)]
        return question, entities, sparql, "equipment_points", "Equipment -> points"

    # 3. Equipment of a point (inverse)
    def t_point_equipment(self, p: Point, equip_uri: URIRef):
        q_variants = [
            f"Which equipment is {p.uri.split('#')[-1]} a point of?",
            f"{p.uri.split('#')[-1]} belongs to what equipment?",
            f"Identify the equipment owning point {p.uri.split('#')[-1]}",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT ?equip WHERE {{ ?equip brick:hasPoint {format_uri(p.uri)} . }}"
        entities = [str(p.uri)]
        return question, entities, sparql, "point_equipment", "Point -> equipment"

    # 4. Count points of equipment
    def t_count_equipment_points(self, e: Equip):
        q_variants = [
            f"How many points does {e.uri.split('#')[-1]} have?",
            f"Count the points under {e.uri.split('#')[-1]}",
            f"Number of points belonging to {e.uri.split('#')[-1]}?",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT (COUNT(?p) AS ?count) WHERE {{ {format_uri(e.uri)} brick:hasPoint ?p . }}"
        entities = [str(e.uri)]
        return question, entities, sparql, "count_equipment_points", "Count points"

    # 5. Get external ref + equipment in one multi-entity query
    def t_point_external_and_equipment(self, p: Point):
        q_variants = [
            f"Give the equipment and external reference for {p.uri.split('#')[-1]}",
            f"Find the equipment plus external id of point {p.uri.split('#')[-1]}",
            f"What equipment owns {p.uri.split('#')[-1]} and what is its external reference?",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT ?equip ?ref WHERE {{ ?equip brick:hasPoint {format_uri(p.uri)} . {format_uri(p.uri)} ref:hasExternalReference ?ref . }}"
        entities = [str(p.uri)]
        return question, entities, sparql, "point_equipment_and_ref", "Join equipment and ref"

    # 6. List all external refs for equipment's points
    def t_equipment_points_external_refs(self, e: Equip):
        q_variants = [
            f"List external references of points under {e.uri.split('#')[-1]}",
            f"Show external ids for {e.uri.split('#')[-1]}'s points",
            f"What are the external reference ids of each point in {e.uri.split('#')[-1]}?",
        ]
        question = random.choice(q_variants)
        sparql = f"SELECT ?point ?ref WHERE {{ {format_uri(e.uri)} brick:hasPoint ?point . OPTIONAL {{ ?point ref:hasExternalReference ?ref . }} }}"
        entities = [str(e.uri)]
        return question, entities, sparql, "equipment_points_external_refs", "Equipment points + refs"

    def all_templates(self):
        return [
            self.t_point_external_ref,
            self.t_equipment_points,
            self.t_point_equipment,
            self.t_count_equipment_points,
            self.t_point_external_and_equipment,
            self.t_equipment_points_external_refs,
        ]

# Helpers -------------------------------------------------------------------

def format_uri(u: URIRef) -> str:
    # Return prefixed name if possible (only bldg: URIs expected here)
    s = str(u)
    if s.startswith(str(BLDG)):
        return "bldg:" + s.split('#', 1)[-1]
    if s.startswith(str(BRICK)):
        return "brick:" + s.split('#', 1)[-1]
    return f"<" + s + ">"


def extract_graph_entities(g: Graph) -> Tuple[List[Equip], List[Point]]:
    # Collect equipments = subjects that have at least one brick:hasPoint triple
    equip_points: Dict[URIRef, List[URIRef]] = {}
    for s, p, o in g.triples((None, BRICK.hasPoint, None)):
        equip_points.setdefault(s, []).append(o)

    # Build point structures
    points: Dict[URIRef, Point] = {}
    for equip, pts in equip_points.items():
        for pt in pts:
            if pt not in points:
                classes = [c for _, _, c in g.triples((pt, RDF.type, None)) if isinstance(c, URIRef)]
                # external ref (if any)
                ext_ref = None
                for _, _, ref_val in g.triples((pt, REF.hasExternalReference, None)):
                    if isinstance(ref_val, Literal):
                        ext_ref = str(ref_val)
                        break
                # label
                label = None
                for _, _, lbl in g.triples((pt, RDFS.label, None)):
                    if isinstance(lbl, Literal):
                        label = str(lbl)
                        break
                points[pt] = Point(uri=pt, label=label, external_ref=ext_ref, classes=classes)

    equips: List[Equip] = []
    for equip_uri, pts in equip_points.items():
        classes = [c for _, _, c in g.triples((equip_uri, RDF.type, None)) if isinstance(c, URIRef)]
        label = None
        for _, _, lbl in g.triples((equip_uri, RDFS.label, None)):
            if isinstance(lbl, Literal):
                label = str(lbl)
                break
        equips.append(Equip(uri=equip_uri, label=label, classes=classes, points=[points[p] for p in pts if p in points]))

    return equips, list(points.values())


def generate_dataset(g: Graph, limit: int) -> List[Dict]:
    equips, points = extract_graph_entities(g)
    tg = TemplateGenerator(g, points, equips)
    templates = tg.all_templates()

    # Basic sampling pools
    random.shuffle(points)
    random.shuffle(equips)

    out = []
    if not points or not equips:
        return out

    # We'll cycle templates until we reach limit (or exhaust combinations)
    idx_point = 0
    idx_equip = 0
    while len(out) < limit:
        for tmpl in templates:
            if len(out) >= limit:
                break
            # Decide which entity types needed
            if tmpl.__name__ in ['t_point_external_ref', 't_point_equipment', 't_point_external_and_equipment']:
                p = points[idx_point % len(points)]
                # find its equipment for point_equipment template
                equip_uri = None
                if tmpl.__name__ == 't_point_equipment':
                    # naive search (could index) - acceptable for generation scale
                    for e in equips:
                        if any(pt.uri == p.uri for pt in e.points):
                            equip_uri = e.uri
                            break
                    if not equip_uri:
                        continue
                    q, ents, sp, cat, notes = tmpl(p, equip_uri)
                else:
                    q, ents, sp, cat, notes = tmpl(p)
                idx_point += 1
            elif tmpl.__name__ in ['t_equipment_points', 't_count_equipment_points', 't_equipment_points_external_refs']:
                e = equips[idx_equip % len(equips)]
                q, ents, sp, cat, notes = tmpl(e)
                idx_equip += 1
            else:
                continue
            # Convert entity URIs to prefixed forms for model training consistency
            prefixed_ents = []
            for e in ents:
                if isinstance(e, str) and e.startswith(str(BLDG)):
                    prefixed_ents.append('bldg:' + e.split('#',1)[-1])
                else:
                    prefixed_ents.append(e)
            out.append({
                "question": q,
                "entities": prefixed_ents,
                "sparql": sp,
                "category": cat,
                "notes": notes
            })
    return out


def sanitize_ttl(raw: str) -> str:
    """Sanitize invalid Turtle QNames containing '/' in the local part.

    The source TTL uses CURIEs like bldg:bldg6.CHW.Pump1_Start/Stop which are
    not valid Turtle (slash not allowed in PN_LOCAL). We replace any '/' inside
    a bldg: prefixed local part with an underscore, keeping a mapping for
    potential future use (currently just logged).
    """
    pattern = re.compile(r"\bbldg:([A-Za-z0-9_.-]*?/[^\s;,.]*)")
    replacements = {}

    def _repl(m: re.Match) -> str:
        local = m.group(1)
        fixed = local.replace('/', '_')
        replacements[local] = fixed
        return 'bldg:' + fixed

    sanitized = pattern.sub(_repl, raw)
    if replacements:
        print(f"Sanitized {len(replacements)} invalid local names with '/':")
        for k, v in list(replacements.items())[:10]:  # show up to first 10
            print(f"  {k} -> {v}")
        if len(replacements) > 10:
            print(f"  ... ({len(replacements)-10} more)")
    return sanitized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ttl', default='bldg3.ttl')
    parser.add_argument('--out', default='bldg3_dataset.json')
    parser.add_argument('--limit', type=int, default=1500)
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args()

    ttl_path = Path(args.ttl)
    if not ttl_path.exists():
        raise SystemExit(f"TTL file not found: {ttl_path}")

    g = Graph()
    raw = ttl_path.read_text(encoding='utf-8', errors='ignore')
    sanitized = sanitize_ttl(raw)
    g.parse(data=sanitized, format='turtle')

    dataset = generate_dataset(g, args.limit)

    if not dataset:
        raise SystemExit("No data generated (check that graph has brick:hasPoint relationships)")

    with open(args.out, 'w', encoding='utf-8') as f:
        if args.pretty:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        else:
            json.dump(dataset, f, ensure_ascii=False)
    print(f"Wrote {len(dataset)} examples to {args.out}")

if __name__ == '__main__':
    main()
