"""Generate an extensive NL->SPARQL training dataset for the bldg2 Brick graph.

Output JSON (array of objects):
  {
    "question": str,
    "entities": [str, ...],  # prefixed names (bldg:, brick:)
    "sparql": str,           # SPARQL body (no PREFIX block inserted; left empty intentionally)
    "category": str,         # template / intent category
    "notes": str             # short rationale or disambiguation
  }

Coverage (extended vs initial version):
  - Point external reference lookups
  - Equipment -> points listing & counts
  - Point -> equipment inverse lookup
  - Equipment + point external reference join
  - Equipment points with optional refs listing
  - Class-centric queries: list points of a given sensor class, count points per class
  - Multi-class comparisons (counts for several classes)
  - Missing external reference quality checks
  - Mixed multi-entity: external references, equipment relationships, class filters
  - Random lexical variation for each template

Additions:
  * Uses sensor_list.txt (if present) to inject extra lexical diversity (but not required)
  * CLI exposes --limit, --seed, --max-class-comparisons, --max-class-queries
  * Internal sanitization of invalid local names containing '/'

Example usage:
  python generate_bldg2_dataset.py --ttl bldg2.ttl --out bldg2_dataset_extended.json --limit 4000 --pretty

Notes:
  - PREFIX declarations are intentionally omitted; you can prepend them later.
  - Assumes Brick core predicates (brick:hasPoint, ref:hasExternalReference, rdf:type).
  - No UUID wording; keeps questions natural.
"""
from __future__ import annotations
import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Iterable, Set

from rdflib import Graph, Namespace, RDF, RDFS, URIRef, Literal

BRICK = Namespace("https://brickschema.org/schema/Brick#")
BLDG = Namespace("http://buildsys.org/ontologies/bldg2#")
REF = Namespace("https://brickschema.org/schema/Brick/ref#")
PREFIXES = ""  # intentionally blank (user will inject later if needed)

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

# ----------------- Helpers -----------------

def format_uri(u: URIRef) -> str:
    s = str(u)
    if s.startswith(str(BLDG)):
        return "bldg:" + s.split('#',1)[-1]
    if s.startswith(str(BRICK)):
        return "brick:" + s.split('#',1)[-1]
    return f"<" + s + ">"

def sanitize_ttl(raw: str) -> str:
    # Replace illegal '/' in local names after bldg: prefix.
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
        for k,v in list(replacements.items())[:10]:
            print(f"  {k} -> {v}")
        if len(replacements) > 10:
            print(f"  ... ({len(replacements)-10} more)")
    return sanitized

def extract_graph_entities(g: Graph) -> Tuple[List[Equip], List[Point]]:
    equip_points: Dict[URIRef, List[URIRef]] = {}
    for s, p, o in g.triples((None, BRICK.hasPoint, None)):
        equip_points.setdefault(s, []).append(o)
    points: Dict[URIRef, Point] = {}
    for equip, pts in equip_points.items():
        for pt in pts:
            if pt not in points:
                classes = [c for _, _, c in g.triples((pt, RDF.type, None)) if isinstance(c, URIRef)]
                ext_ref = None
                for _, _, ref_val in g.triples((pt, REF.hasExternalReference, None)):
                    if isinstance(ref_val, Literal):
                        ext_ref = str(ref_val)
                        break
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

def classify_point_types(points: List[Point]) -> Dict[str, List[Point]]:
    buckets: Dict[str, List[Point]] = {}
    for p in points:
        # Build human-friendly class keys (prefixed)
        prefixed = []
        for c in p.classes:
            sc = str(c)
            if sc.startswith(str(BRICK)):
                prefixed.append('brick:' + sc.split('#',1)[-1])
            elif sc.startswith(str(BLDG)):
                prefixed.append('bldg:' + sc.split('#',1)[-1])
        key = prefixed[0] if prefixed else 'brick:Point'
        buckets.setdefault(key, []).append(p)
    return buckets

# ----------------- Template Generator -----------------
class TemplateGenerator:
    def __init__(self, g: Graph, points: List[Point], equips: List[Equip], sensor_names: List[str]):
        self.g = g
        self.points = points
        self.equips = equips
        self.sensor_names = sensor_names
        self.class_buckets = classify_point_types(points)

    # Existing templates (renamed categories remain same semantics)
    def t_point_external_ref(self, p: Point):
        base = p.uri.split('#')[-1]
        sensor_hint = random.choice(self.sensor_names) if self.sensor_names else base
        question = random.choice([
            f"What is the external reference id for {base}?",
            f"Give me the external identifier linked to {base}",
            f"Which external reference does the point {base} have?",
            f"Provide the external reference associated with sensor {sensor_hint}",
        ])
        sparql = f"SELECT ?ref WHERE {{ {format_uri(p.uri)} ref:hasExternalReference ?ref . }}"
        return question, [str(p.uri)], sparql, "point_external_ref", "Lookup external ref"

    def t_equipment_points(self, e: Equip):
        base = e.uri.split('#')[-1]
        question = random.choice([
            f"List all points of {base}",
            f"Which points belong to {base}?",
            f"Show me every point attached to {base}",
            f"Enumerate the points under {base}",
        ])
        sparql = f"SELECT ?point WHERE {{ {format_uri(e.uri)} brick:hasPoint ?point . }}"
        return question, [str(e.uri)], sparql, "equipment_points", "Equipment -> points"

    def t_point_equipment(self, p: Point, equip_uri: URIRef):
        base = p.uri.split('#')[-1]
        question = random.choice([
            f"Which equipment is {base} a point of?",
            f"{base} belongs to what equipment?",
            f"Identify the equipment owning point {base}",
            f"Show the equipment associated with {base}",
        ])
        sparql = f"SELECT ?equip WHERE {{ ?equip brick:hasPoint {format_uri(p.uri)} . }}"
        return question, [str(p.uri)], sparql, "point_equipment", "Point -> equipment"

    def t_count_equipment_points(self, e: Equip):
        base = e.uri.split('#')[-1]
        question = random.choice([
            f"How many points does {base} have?",
            f"Count the points under {base}",
            f"Number of points belonging to {base}?",
            f"Total points associated with {base}?",
        ])
        sparql = f"SELECT (COUNT(?p) AS ?count) WHERE {{ {format_uri(e.uri)} brick:hasPoint ?p . }}"
        return question, [str(e.uri)], sparql, "count_equipment_points", "Count points"

    def t_point_external_and_equipment(self, p: Point):
        base = p.uri.split('#')[-1]
        question = random.choice([
            f"Give the equipment and external reference for {base}",
            f"Find the equipment plus external id of point {base}",
            f"What equipment owns {base} and what is its external reference?",
            f"Return equipment and external reference linked to {base}",
        ])
        sparql = f"SELECT ?equip ?ref WHERE {{ ?equip brick:hasPoint {format_uri(p.uri)} . {format_uri(p.uri)} ref:hasExternalReference ?ref . }}"
        return question, [str(p.uri)], sparql, "point_equipment_and_ref", "Join equipment + external ref"

    def t_equipment_points_external_refs(self, e: Equip):
        base = e.uri.split('#')[-1]
        question = random.choice([
            f"List external references of points under {base}",
            f"Show external ids for {base}'s points",
            f"What are the external reference ids of each point in {base}?",
            f"Enumerate each point and external reference in {base}",
        ])
        sparql = f"SELECT ?point ?ref WHERE {{ {format_uri(e.uri)} brick:hasPoint ?point . OPTIONAL {{ ?point ref:hasExternalReference ?ref . }} }}"
        return question, [str(e.uri)], sparql, "equipment_points_external_refs", "Equipment points + refs"

    # New templates --------------------------------------------------
    def t_class_points_list(self, class_key: str, sample_points: List[Point]):
        cls_local = class_key.split(':',1)[-1]
        question = random.choice([
            f"List all points of class {class_key}.",
            f"Show points typed as {cls_local}.",
            f"Which points are instances of {class_key}?",
            f"Enumerate {cls_local} points.",
        ])
        # SPARQL: points with rdf:type given class
        sparql = f"SELECT ?p WHERE {{ ?p a {class_key} . }}"
        return question, [class_key], sparql, "class_points", "List points by class"

    def t_class_points_count(self, class_key: str):
        cls_local = class_key.split(':',1)[-1]
        question = random.choice([
            f"How many {cls_local} points exist?",
            f"Count points of class {class_key}.",
            f"What is the number of {cls_local} points?",
        ])
        sparql = f"SELECT (COUNT(?p) AS ?count) WHERE {{ ?p a {class_key} . }}"
        return question, [class_key], sparql, "class_point_count", "Count points by class"

    def t_multi_class_counts(self, class_keys: List[str]):
        # Compare several classes simultaneously
        question = random.choice([
            "Provide counts for these point classes.",
            "How many points exist for each listed class?",
            "Count points grouped by the given classes.",
        ])
        vals = ' '.join(class_keys)
        sparql = f"SELECT ?cls (COUNT(?p) AS ?count) WHERE {{ VALUES ?cls {{ {vals} }} ?p a ?cls . }} GROUP BY ?cls"
        return question, class_keys, sparql, "multi_class_count", "Compare class counts"

    def t_missing_external_refs(self):
        question = random.choice([
            "Which points lack an external reference?",
            "List points missing external references.",
            "Show points that do not have an external reference id.",
        ])
        sparql = "SELECT ?p WHERE { ?p a brick:Point . FILTER NOT EXISTS { ?p ref:hasExternalReference ?r . } }"
        return question, ["brick:Point"], sparql, "quality_missing_external_ref", "Quality check missing external refs"

    def t_equipment_point_class(self, e: Equip, class_key: str):
        base = e.uri.split('#')[-1]
        cls_local = class_key.split(':',1)[-1]
        question = random.choice([
            f"List {cls_local} points under {base}.",
            f"Which {cls_local} points belong to {base}?",
            f"Show {cls_local} points attached to {base}.",
        ])
        sparql = f"SELECT ?p WHERE {{ {format_uri(e.uri)} brick:hasPoint ?p . ?p a {class_key} . }}"
        return question, [str(e.uri), class_key], sparql, "equipment_points_by_class", "Equipment filtered by class"

    def all_templates(self):
        # Base templates
        base = [
            self.t_point_external_ref,
            self.t_equipment_points,
            self.t_point_equipment,
            self.t_count_equipment_points,
            self.t_point_external_and_equipment,
            self.t_equipment_points_external_refs,
        ]
        # Additional always-available (global) templates
        extra = [
            self.t_missing_external_refs,
        ]
        return base, extra

# ----------------- Dataset Generation -----------------

def generate_dataset(g: Graph, limit: int, sensor_names: List[str], max_class_queries: int, max_class_comparisons: int) -> List[Dict]:
    equips, points = extract_graph_entities(g)
    if not points:
        return []
    tg = TemplateGenerator(g, points, equips, sensor_names)
    base_templates, extra_templates = tg.all_templates()

    # Pre-select point & equipment order for deterministic cycling
    random.shuffle(points)
    random.shuffle(equips)

    # Prepare class buckets (filter very small buckets for list templates if needed)
    class_buckets = {k: v for k,v in tg.class_buckets.items() if len(v) > 0}
    class_keys = sorted(class_buckets.keys(), key=lambda k: -len(class_buckets[k]))

    output = []
    idx_point = 0
    idx_equip = 0

    # Derive dynamic counts for new class-based templates
    # 1. Class list + count queries
    selected_for_class_queries = class_keys[:max_class_queries]
    # 2. Class comparisons: take groups of up to 4 classes
    comparison_groups = []
    grp = []
    for ck in class_keys[:max_class_comparisons]:
        grp.append(ck)
        if len(grp) == 4:
            comparison_groups.append(grp)
            grp = []
    if grp:
        comparison_groups.append(grp)

    def append_record(q, ents_raw, sp, cat, notes):
        prefixed_ents = []
        for e in ents_raw:
            if isinstance(e, str) and e.startswith(str(BLDG)):
                prefixed_ents.append('bldg:' + e.split('#',1)[-1])
            elif isinstance(e, str) and e.startswith(str(BRICK)):
                prefixed_ents.append('brick:' + e.split('#',1)[-1])
            else:
                prefixed_ents.append(e)
        output.append({
            "question": q,
            "entities": prefixed_ents,
            "sparql": sp,
            "category": cat,
            "notes": notes
        })

    # Inject class-based queries early (they add variety independent of cycling)
    for ck in selected_for_class_queries:
        # list points
        q, ents, sp, cat, notes = tg.t_class_points_list(ck, class_buckets[ck])
        append_record(q, ents, sp, cat, notes)
        if len(output) >= limit:
            return output
        # count points
        q, ents, sp, cat, notes = tg.t_class_points_count(ck)
        append_record(q, ents, sp, cat, notes)
        if len(output) >= limit:
            return output

    # Multi-class comparisons
    for grp_classes in comparison_groups:
        q, ents, sp, cat, notes = tg.t_multi_class_counts(grp_classes)
        append_record(q, ents, sp, cat, notes)
        if len(output) >= limit:
            return output

    # Global templates (e.g., missing external refs)
    for tmpl in extra_templates:
        q, ents, sp, cat, notes = tmpl()
        append_record(q, ents, sp, cat, notes)
        if len(output) >= limit:
            return output

    # Cycle base templates until limit reached
    while len(output) < limit:
        for tmpl in base_templates:
            if len(output) >= limit:
                break
            name = tmpl.__name__
            if name in ['t_point_external_ref','t_point_equipment','t_point_external_and_equipment']:
                p = points[idx_point % len(points)]
                if name == 't_point_equipment':
                    # find equipment for point
                    equip_uri = None
                    for e in equips:
                        if any(pt.uri == p.uri for pt in e.points):
                            equip_uri = e.uri
                            break
                    if not equip_uri:
                        idx_point += 1
                        continue
                    q, ents, sp, cat, notes = tmpl(p, equip_uri)
                else:
                    q, ents, sp, cat, notes = tmpl(p)
                idx_point += 1
            elif name in ['t_equipment_points','t_count_equipment_points','t_equipment_points_external_refs']:
                if not equips:
                    continue
                e = equips[idx_equip % len(equips)]
                q, ents, sp, cat, notes = tmpl(e)
                # Occasionally add class-filtered variant for equipment
                if random.random() < 0.25 and class_keys:
                    ck = random.choice(class_keys[:max_class_queries])
                    q2, ents2, sp2, cat2, notes2 = tg.t_equipment_point_class(e, ck)
                    append_record(q2, ents2, sp2, cat2, notes2)
                idx_equip += 1
            else:
                continue
            append_record(q, ents, sp, cat, notes)
    return output

# ----------------- Main CLI -----------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ttl', default='bldg2.ttl')
    parser.add_argument('--out', default='bldg2_dataset_extended.json')
    parser.add_argument('--limit', type=int, default=4000)
    parser.add_argument('--pretty', action='store_true')
    parser.add_argument('--sensor-list', default='sensor_list.txt')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-class-queries', type=int, default=30, help='Max distinct classes for class list/count queries')
    parser.add_argument('--max-class-comparisons', type=int, default=24, help='Number of classes considered for multi-class comparison groups (chunked by 4)')
    args = parser.parse_args()

    random.seed(args.seed)

    ttl_path = Path(args.ttl)
    if not ttl_path.exists():
        raise SystemExit(f"TTL file not found: {ttl_path}")

    sensor_names: List[str] = []
    s_path = Path(args.sensor_list)
    if s_path.exists():
        sensor_names = [l.strip() for l in s_path.read_text(encoding='utf-8', errors='ignore').splitlines() if l.strip()]
        print(f"Loaded {len(sensor_names)} sensor names from {s_path}")

    g = Graph()
    raw = ttl_path.read_text(encoding='utf-8', errors='ignore')
    sanitized = sanitize_ttl(raw)
    g.parse(data=sanitized, format='turtle')

    dataset = generate_dataset(
        g,
        limit=args.limit,
        sensor_names=sensor_names,
        max_class_queries=args.max_class_queries,
        max_class_comparisons=args.max_class_comparisons,
    )

    if not dataset:
        raise SystemExit("No data generated (graph may lack brick:hasPoint relationships)")

    # Deduplicate (question, sparql)
    unique = []
    seen = set()
    for ex in dataset:
        key = (ex['question'], ex['sparql'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(ex)

    with open(args.out, 'w', encoding='utf-8') as f:
        if args.pretty:
            json.dump(unique, f, ensure_ascii=False, indent=2)
        else:
            json.dump(unique, f, ensure_ascii=False)
    print(f"Wrote {len(unique)} examples (deduplicated from {len(dataset)}) to {args.out}")

    # Category distribution summary
    from collections import Counter
    cat_counts = Counter(e['category'] for e in unique)
    summary = {"total": len(unique), "by_category": dict(sorted(cat_counts.items(), key=lambda kv: kv[0]))}
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
