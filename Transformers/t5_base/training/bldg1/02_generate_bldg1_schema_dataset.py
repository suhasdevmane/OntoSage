"""Generate an extensive ontology (schema + structural ABox) NL->SPARQL dataset for bldg1.

Based on bldg2 schema generator logic; adapted namespace and building-specific attributes.

Output: bldg1_schema_dataset.json

Entry Schema:
  {
    "question": str,
    "entities": [prefixed entity strings],
    "sparql": str,  # body only
    "category": str
  }

Differences vs bldg2:
  - Building namespace http://abacwsbuilding.cardiff.ac.uk/abacws# with prefix bldg:
  - Building root resource may differ (e.g., bldg:Abacws) instead of bldg:bldg2

Usage example:
  python generate_bldg1_schema_dataset.py --ttl bldg1.ttl --out bldg1_schema_dataset.json --seed 42 --limit 0 \
       --max-class-desc 300 --max-subclass-parents 150 --max-room-tags 60
"""
from __future__ import annotations
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple
import argparse

# -------------------- CLI Discovery -------------------- #

def auto_ttl() -> Path:
    candidates = [
        Path("Transformers/t5_base/training/bldg1/bldg1.ttl"),
        Path("training/bldg1/bldg1.ttl"),
        Path("bldg1/bldg1.ttl"),
        Path("bldg1.ttl"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Could not locate bldg1.ttl in expected candidate paths")

# -------------------- Extraction Helpers -------------------- #

def extract_classes(ttl_text: str) -> Tuple[Dict[str, Dict[str, str | None]], Dict[str, Set[str]]]:
    CLASS_BLOCK = re.compile(r"\n(brick:[A-Za-z0-9_]+) a owl:Class[^.{]*?;([\s\S]*?)(?:(?:\n\S)|$)")
    LABEL = re.compile(r'rdfs:label "([^"]+)"')
    DEF = re.compile(r'skos:definition "([^"]+)"@en')
    PARENT = re.compile(r'rdfs:subClassOf (brick:[A-Za-z0-9_]+)')

    classes: Dict[str, Dict[str, str | None]] = {}
    for m in CLASS_BLOCK.finditer(ttl_text):
        cls = m.group(1)
        block = m.group(2)
        label = LABEL.search(block)
        definition = DEF.search(block)
        parent = PARENT.search(block)
        classes[cls] = {
            "label": label.group(1) if label else None,
            "definition": definition.group(1) if definition else None,
            "parent": parent.group(1) if parent else None,
        }

    from collections import defaultdict as dd
    children_map: Dict[str, Set[str]] = dd(set)
    for c, data in classes.items():
        p = data["parent"]
        if p:
            children_map[p].add(c)
    return classes, children_map


def extract_abox(ttl_text: str):
    rooms = set(re.findall(r"\n(bldg:[A-Za-z0-9_.]+) a brick:Room ?;", ttl_text))
    zones = set(re.findall(r"\n(bldg:[A-Za-z0-9_.]+) a brick:HVAC_Zone ?;", ttl_text))
    ahus  = set(re.findall(r"\n(bldg:[A-Za-z0-9_.]+) a brick:Air_Handling_Unit ?;", ttl_text))

    room_tag_triples = re.findall(r"(bldg:[A-Za-z0-9_.]+) brick:hasTag ([A-Za-z0-9_:]+) *[.;]", ttl_text)
    room_tag_counts = Counter(t for s, t in room_tag_triples if s in rooms)
    room_to_tags: Dict[str, Set[str]] = defaultdict(set)
    for s, t in room_tag_triples:
        if s in rooms:
            room_to_tags[s].add(t)

    # Building area pattern (attempt both bldg:Abacws and bldg:bldg1 style)
    building_area_match = re.search(r"bldg:(?:Abacws|bldg1)[^.]*?brick:area \"([^\"]+)\"", ttl_text)
    building_area_value = building_area_match.group(1) if building_area_match else None

    return rooms, zones, ahus, room_tag_counts, room_to_tags, building_area_value

REL_EQUIP_ROOM = re.compile(r"(bldg:[A-Za-z0-9_.]+) brick:(?:hasPart|isPartOf|isLocatedIn|locatedIn) (bldg:[A-Za-z0-9_.]+) *[.;]")

# -------------------- Generation Core -------------------- #

def build_examples(classes: Dict[str, Dict[str, str | None]],
                   children_map: Dict[str, Set[str]],
                   rooms: Set[str], zones: Set[str], ahus: Set[str],
                   room_tag_counts: Counter, room_to_tags: Dict[str, Set[str]],
                   building_area_value: str | None,
                   args,
                   ttl_text: str) -> List[Dict]:
    examples: List[Dict] = []

    def add(q, ents, sparql, cat):
        examples.append({
            "question": q,
            "entities": ents,
            "sparql": sparql,
            "category": cat
        })

    # Class Descriptions
    cls_items = list(classes.items())
    random.shuffle(cls_items)
    for cls, data in cls_items[:args.max_class_desc]:
        label = data["label"] or cls.split(":")[-1]
        q = random.choice([
            f"Describe the class {cls}.",
            f"Explain what {label} represents.",
            f"What is {label} in the Brick ontology?",
            f"Provide definition details for {label}.",
        ])
        sparql = (f"SELECT ?label ?definition ?parent WHERE {{ {cls} rdfs:label ?label . "
                  f"OPTIONAL {{ {cls} skos:definition ?definition . }} "
                  f"OPTIONAL {{ {cls} rdfs:subClassOf ?parent . }} }}")
        add(q, [cls], sparql, "class_description")

    # Parent lookups
    for cls, data in classes.items():
        parent = data["parent"]
        if parent:
            label = data["label"] or cls.split(":")[-1]
            q = random.choice([
                f"What is the parent class of {label}?",
                f"{label} derives from which class?",
                f"Identify the superclass of {label}.",
                f"Which class does {label} extend?",
            ])
            add(q, [cls], f"SELECT ?parent WHERE {{ {cls} rdfs:subClassOf ?parent . }}", "parent_class")

    # Subclasses listing (fanout)
    fanout_sorted = sorted(children_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    for parent, kids in fanout_sorted[:args.max_subclass_parents]:
        if len(kids) < 2:
            continue
        pname = parent.split(":")[-1]
        q = random.choice([
            f"List subclasses of {pname}.",
            f"Which classes extend {pname}?",
            f"Show direct children of {pname}.",
            f"Enumerate subclasses under {pname}.",
        ])
        add(q, [parent], f"SELECT ?child WHERE {{ ?child rdfs:subClassOf {parent} . }}", "subclasses")

    # Classes w/o parent
    add("Which Brick classes have no recorded parent?", [],
        "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?c rdfs:subClassOf ?p . } }", "inventory")

    # Classes w/o children
    add("Which classes have no subclasses?", [],
        "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?child rdfs:subClassOf ?c . } }", "leaf_classes")

    # Largest fanout
    add("Which class has the largest number of direct subclasses?", [],
        "SELECT ?p (COUNT(?c) AS ?count) WHERE { ?c rdfs:subClassOf ?p . } GROUP BY ?p ORDER BY DESC(?count) LIMIT 1", "ranking")

    # Top parent classes (top 5 & top 10)
    add("List the top parent classes by number of direct subclasses (top 5).", [],
        "SELECT ?p (COUNT(?c) AS ?count) WHERE { ?c rdfs:subClassOf ?p . } GROUP BY ?p ORDER BY DESC(?count) LIMIT 5", "ranking_top_parents")
    add("Show the top parent classes by number of direct subclasses (top 10).", [],
        "SELECT ?p (COUNT(?c) AS ?count) WHERE { ?c rdfs:subClassOf ?p . } GROUP BY ?p ORDER BY DESC(?count) LIMIT 10", "ranking_top10_parents")

    # Quality checks
    add("Which classes lack a definition string?", [],
        "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?c skos:definition ?d . } }", "quality_missing_definition")
    add("Which classes do not have a label?", [],
        "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?c rdfs:label ?l . } }", "quality_missing_label")

    # Multi-parent detection
    multi_parent_candidates = re.findall(r"(brick:[A-Za-z0-9_]+) rdfs:subClassOf (brick:[A-Za-z0-9_]+) *;", ttl_text)
    from collections import Counter as C
    counts_mp = C([c for c, _ in multi_parent_candidates])
    for cls, cnt in list(counts_mp.items()):
        if cnt > 1:
            q = random.choice([
                f"Which superclasses does {cls.split(':')[-1]} have?",
                f"List all parent classes of {cls.split(':')[-1]}.",
            ])
            add(q, [cls], f"SELECT ?parent WHERE {{ {cls} rdfs:subClassOf ?parent . }}", "multi_parent_class")

    # Base class comparison counts (presence filter)
    base_candidates = ["brick:Room", "brick:Sensor", "brick:Equipment"]
    present_bases = [b for b in base_candidates if b in classes]
    if present_bases:
        add("How many subclasses do key base classes have?", present_bases,
            "SELECT ?base (COUNT(?c) AS ?count) WHERE { VALUES ?base { " + " ".join(present_bases) + " } ?c rdfs:subClassOf ?base . } GROUP BY ?base",
            "comparison_subclass_counts")

    # Label filters
    add("List classes whose label mentions temperature sensor.", [],
        'SELECT ?c ?label WHERE { ?c rdfs:label ?label . FILTER(CONTAINS(LCASE(?label),"temperature") && CONTAINS(LCASE(?label),"sensor")) }',
        "label_filter")
    add("Find classes with labels referencing pressure.", [],
        'SELECT ?c ?label WHERE { ?c rdfs:label ?label . FILTER(CONTAINS(LCASE(?label),"pressure")) }',
        "label_filter")

    # ABox counts & inventories
    if rooms:
        add("How many rooms are modeled?", ["brick:Room"],
            "SELECT (COUNT(?r) AS ?count) WHERE { ?r a brick:Room . }", "count_abox")
        add("List all rooms in the building graph.", ["brick:Room"],
            "SELECT ?r WHERE { ?r a brick:Room . }", "inventory_abox")
    if zones:
        add("How many HVAC zones exist?", ["brick:HVAC_Zone"],
            "SELECT (COUNT(?z) AS ?count) WHERE { ?z a brick:HVAC_Zone . }", "count_abox")
        add("Show the HVAC zones.", ["brick:HVAC_Zone"],
            "SELECT ?z WHERE { ?z a brick:HVAC_Zone . }", "inventory_abox")
    if ahus:
        add("How many air handling units are defined?", ["brick:Air_Handling_Unit"],
            "SELECT (COUNT(?a) AS ?count) WHERE { ?a a brick:Air_Handling_Unit . }", "count_abox")

    if rooms and zones:
        add("Provide counts of rooms and HVAC zones together.", ["brick:Room", "brick:HVAC_Zone"],
            "SELECT (COUNT(DISTINCT ?r) AS ?rooms) (COUNT(DISTINCT ?z) AS ?zones) WHERE { { ?r a brick:Room . } UNION { ?z a brick:HVAC_Zone . } }",
            "multi_count")

    # Tag aggregations
    if room_tag_counts:
        add("Which tags are most common on rooms?", ["brick:Room"],
            "SELECT ?tag (COUNT(?r) AS ?count) WHERE { ?r a brick:Room . ?r brick:hasTag ?tag . } GROUP BY ?tag ORDER BY DESC(?count) LIMIT 10",
            "aggregation")
        tagged_rooms = [r for r, ts in room_to_tags.items() if ts]
        random.shuffle(tagged_rooms)
        for rm in tagged_rooms[:args.max_room_tags]:
            room_local = rm.split(":")[-1]
            q = random.choice([
                f"List tags for room {room_local}",
                f"What tags are associated with {room_local}?",
                f"Show all tags applied to {room_local}",
                f"Enumerate tags linked to room {room_local}",
            ])
            add(q, [rm], f"SELECT ?tag WHERE {{ {rm} brick:hasTag ?tag . }}", "room_tags")

    # Rooms without tags
    if rooms:
        add("Which rooms have no tags associated?", ["brick:Room"],
            "SELECT ?r WHERE { ?r a brick:Room . FILTER NOT EXISTS { ?r brick:hasTag ?t . } }", "quality_abox")

    # Building area attribute (if captured)
    if building_area_value is not None:
        for phr in [
            "What is the area of the building?",
            "Provide the area value for the building.",
            "Give the building area.",
            "Report the building area figure.",
        ]:
            # Try two possible root names
            add(phr, ["bldg:Abacws"], "SELECT ?area WHERE { bldg:Abacws brick:area ?area . }", "building_attribute")

    if args.limit and len(examples) > args.limit:
        return examples[:args.limit]
    return examples

# -------------------- Main -------------------- #

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ttl', default=None, help='Path to bldg1.ttl (auto-detect if omitted)')
    parser.add_argument('--out', default='bldg1_schema_dataset.json')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--limit', type=int, default=0, help='Hard cap on total examples (0 = no cap)')
    parser.add_argument('--max-class-desc', type=int, default=300)
    parser.add_argument('--max-subclass-parents', type=int, default=150)
    parser.add_argument('--top-parent-fanout', type=int, default=30)
    parser.add_argument('--max-room-tags', type=int, default=60)
    args = parser.parse_args()

    random.seed(args.seed)

    ttl_path = Path(args.ttl) if args.ttl else auto_ttl()
    if not ttl_path.exists():
        raise SystemExit(f"TTL file not found: {ttl_path}")

    ttl_text = ttl_path.read_text(encoding='utf-8', errors='ignore')
    classes, children_map = extract_classes(ttl_text)
    rooms, zones, ahus, room_tag_counts, room_to_tags, building_area_value = extract_abox(ttl_text)

    examples = build_examples(classes, children_map, rooms, zones, ahus,
                              room_tag_counts, room_to_tags, building_area_value, args, ttl_text)

    # Deduplicate
    unique = []
    seen = set()
    for ex in examples:
        key = (ex['question'], ex['sparql'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(ex)

    out_path = ttl_path.parent / args.out
    out_path.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding='utf-8')

    cat_counts = Counter(e['category'] for e in unique)
    summary = {"total": len(unique), "by_category": dict(sorted(cat_counts.items(), key=lambda kv: kv[0]))}
    print(json.dumps(summary, indent=2))
    try:
        rel = out_path.relative_to(Path.cwd())
    except Exception:
        rel = out_path
    print(f"Wrote schema dataset to {rel}")

if __name__ == '__main__':
    main()
