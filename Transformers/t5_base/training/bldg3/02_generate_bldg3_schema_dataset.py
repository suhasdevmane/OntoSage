"""Generate ontology (schema-focused) NL->SPARQL training dataset for bldg3.

Outputs: bldg3_schema_dataset.json adjacent to TTL file.

Dataset Entry Schema (each line/object):
  {
    "question": <natural language question>,
    "entities": [list of prefixed entities referenced explicitly in NL],
    "sparql": <SPARQL body without PREFIX declarations>,
    "category": <classification string>
  }

Notes:
  - PREFIX declarations intentionally omitted (model learns to produce body only)
  - Entities use prefixed forms (brick:, bldg:, etc.)
  - Focus: structural/semantic interrogation of ontology (TBox + limited ABox present)
  - Avoid any mention of internal IDs/UUIDs
  - Ensure each SPARQL query is syntactically consistent with Brick usage in file
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Set

random.seed(42)


def choose_ttl() -> Path:
    candidates = [
        Path("Transformers/t5_base/training/bldg3/bldg3.ttl"),
        Path("Transformers/graphs/bldg3.ttl"),
        Path("bldg3/bldg3.ttl"),
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("Could not locate bldg3.ttl in expected candidate paths")


TTL_PATH = choose_ttl()
TTL_TEXT = TTL_PATH.read_text(encoding="utf-8", errors="ignore")


# -------------------- TBox Extraction -------------------- #
CLASS_BLOCK = re.compile(r"\n(brick:[A-Za-z0-9_]+) a owl:Class[^{.]*?;([\s\S]*?)(?:(?:\n\S)|$)")
LABEL = re.compile(r'rdfs:label "([^"]+)"')
DEF = re.compile(r'skos:definition "([^"]+)"@en')
PARENT = re.compile(r'rdfs:subClassOf (brick:[A-Za-z0-9_]+)')

classes: Dict[str, Dict[str, str | None]] = {}
for m in CLASS_BLOCK.finditer(TTL_TEXT):
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

# Build reverse parent -> children map
children_map: Dict[str, Set[str]] = defaultdict(set)
for c, data in classes.items():
    p = data["parent"]
    if p:
        children_map[p].add(c)


# -------------------- ABox Extraction -------------------- #
rooms = set(re.findall(r"\n(bldg:[A-Za-z0-9_]+) a brick:Room ?;", TTL_TEXT))
zones = set(re.findall(r"\n(bldg:[A-Za-z0-9_]+) a brick:HVAC_Zone ?;", TTL_TEXT))
ahus = set(re.findall(r"\n(bldg:[A-Za-z0-9_]+) a brick:Air_Handling_Unit ?;", TTL_TEXT))

# Tag triples (room -> tag)
room_tag_triples = re.findall(r"(bldg:[A-Za-z0-9_]+) brick:hasTag ([A-Za-z0-9_:]+) *[.;]", TTL_TEXT)
room_tag_counts = Counter(t for s, t in room_tag_triples if s in rooms)
room_to_tags: Dict[str, Set[str]] = defaultdict(set)
for s, t in room_tag_triples:
    if s in rooms:
        room_to_tags[s].add(t)

# Building attributes (e.g., area)
building_area_match = re.search(r"bldg:bldg3[^.]*?brick:area \"([^\"]+)\"", TTL_TEXT)
building_area_value = building_area_match.group(1) if building_area_match else None


# -------------------- Query Generation -------------------- #
examples: List[Dict] = []


def add(example: Dict):
    examples.append(example)


# Class descriptions (sample up to 150 for variety)
cls_items = list(classes.items())
random.shuffle(cls_items)
for cls, data in cls_items[:150]:
    label = data["label"] or cls.split(":")[-1]
    q = random.choice([
        f"Describe the class {cls}.",
        f"Explain what {label} represents.",
        f"What is {label} in the Brick ontology?",
    ])
    sparql = (
        f"SELECT ?label ?definition ?parent WHERE {{ {cls} rdfs:label ?label . "
        f"OPTIONAL {{ {cls} skos:definition ?definition . }} "
        f"OPTIONAL {{ {cls} rdfs:subClassOf ?parent . }} }}"
    )
    add({
        "question": q,
        "entities": [cls],
        "sparql": sparql,
        "category": "class_description",
    })

# Parent class lookups
for cls, data in classes.items():
    parent = data["parent"]
    if parent:
        label = data["label"] or cls.split(":")[-1]
        q = random.choice([
            f"What is the parent class of {label}?",
            f"{label} derives from which class?",
            f"Identify the superclass of {label}.",
        ])
        add({
            "question": q,
            "entities": [cls],
            "sparql": f"SELECT ?parent WHERE {{ {cls} rdfs:subClassOf ?parent . }}",
            "category": "parent_class",
        })

# Subclass listings: select high-fanout parents
fanout_sorted = sorted(children_map.items(), key=lambda kv: len(kv[1]), reverse=True)
for parent, kids in fanout_sorted[:80]:
    if len(kids) < 2:
        continue
    pname = parent.split(":")[-1]
    q = random.choice([
        f"List subclasses of {pname}.",
        f"Which classes extend {pname}?",
        f"Show direct children of {pname}.",
    ])
    add({
        "question": q,
        "entities": [parent],
        "sparql": f"SELECT ?child WHERE {{ ?child rdfs:subClassOf {parent} . }}",
        "category": "subclasses",
    })

# Classes without parent
add({
    "question": "Which Brick classes have no recorded parent?",
    "entities": [],
    "sparql": "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?c rdfs:subClassOf ?p . } }",
    "category": "inventory",
})

# Ranking: class with most subclasses
add({
    "question": "Which class has the largest number of direct subclasses?",
    "entities": [],
    "sparql": "SELECT ?p (COUNT(?c) AS ?count) WHERE { ?c rdfs:subClassOf ?p . } GROUP BY ?p ORDER BY DESC(?count) LIMIT 1",
    "category": "ranking",
})

# Quality: classes missing definition
add({
    "question": "Which classes lack a definition string?",
    "entities": [],
    "sparql": "SELECT ?c WHERE { ?c a owl:Class . FILTER NOT EXISTS { ?c skos:definition ?d . } }",
    "category": "quality",
})

# Comparison counts for base classes (only include ones present)
base_candidates = ["brick:Room", "brick:Sensor", "brick:Equipment"]
present_bases = [b for b in base_candidates if b in classes]
if present_bases:
    add({
        "question": "How many subclasses do key base classes have?",
        "entities": present_bases,
        "sparql": "SELECT ?base (COUNT(?c) AS ?count) WHERE { VALUES ?base { "
        + " ".join(present_bases)
        + " } ?c rdfs:subClassOf ?base . } GROUP BY ?base",
        "category": "comparison",
    })

# Label filter example
add({
    "question": "List classes whose label mentions temperature sensor.",
    "entities": [],
    "sparql": 'SELECT ?c ?label WHERE { ?c rdfs:label ?label . FILTER(CONTAINS(LCASE(?label),"temperature") && CONTAINS(LCASE(?label),"sensor")) }',
    "category": "label_filter",
})

# -------------------- ABox Queries -------------------- #
if rooms:
    add({
        "question": "How many rooms are modeled?",
        "entities": ["brick:Room"],
        "sparql": "SELECT (COUNT(?r) AS ?count) WHERE { ?r a brick:Room . }",
        "category": "count_abox",
    })
    add({
        "question": "List all rooms in the building graph.",
        "entities": ["brick:Room"],
        "sparql": "SELECT ?r WHERE { ?r a brick:Room . }",
        "category": "inventory_abox",
    })

if zones:
    add({
        "question": "How many HVAC zones exist?",
        "entities": ["brick:HVAC_Zone"],
        "sparql": "SELECT (COUNT(?z) AS ?count) WHERE { ?z a brick:HVAC_Zone . }",
        "category": "count_abox",
    })
    add({
        "question": "Show the HVAC zones.",
        "entities": ["brick:HVAC_Zone"],
        "sparql": "SELECT ?z WHERE { ?z a brick:HVAC_Zone . }",
        "category": "inventory_abox",
    })

if rooms and zones:
    add({
        "question": "Provide counts of rooms and HVAC zones together.",
        "entities": ["brick:Room", "brick:HVAC_Zone"],
        "sparql": "SELECT (COUNT(DISTINCT ?r) AS ?rooms) (COUNT(DISTINCT ?z) AS ?zones) WHERE { { ?r a brick:Room . } UNION { ?z a brick:HVAC_Zone . } }",
        "category": "multi_count",
    })

# Tag aggregations & listings
if room_tag_counts:
    add({
        "question": "Which tags are most common on rooms?",
        "entities": ["brick:Room"],
        "sparql": "SELECT ?tag (COUNT(?r) AS ?count) WHERE { ?r a brick:Room . ?r brick:hasTag ?tag . } GROUP BY ?tag ORDER BY DESC(?count) LIMIT 10",
        "category": "aggregation",
    })

    # Sample up to 25 rooms with tags for explicit tag list queries
    tagged_rooms = [r for r, ts in room_to_tags.items() if ts]
    random.shuffle(tagged_rooms)
    for rm in tagged_rooms[:25]:
        q = random.choice([
            f"List tags for room {rm.split(':')[-1]}",
            f"What tags are associated with {rm.split(':')[-1]}?",
            f"Show all tags applied to {rm.split(':')[-1]}",
        ])
        add({
            "question": q,
            "entities": [rm],
            "sparql": f"SELECT ?tag WHERE {{ {rm} brick:hasTag ?tag . }}",
            "category": "room_tags",
        })

# Rooms without tags
if rooms:
    add({
        "question": "Which rooms have no tags associated?",
        "entities": ["brick:Room"],
        "sparql": "SELECT ?r WHERE { ?r a brick:Room . FILTER NOT EXISTS { ?r brick:hasTag ?t . } }",
        "category": "quality_abox",
    })

# Building attribute (area)
if building_area_value is not None:
    for phr in [
        "What is the area of the building?",
        "Provide the area value for bldg3.",
        "Give the building area.",
    ]:
        add({
            "question": phr,
            "entities": ["bldg:bldg3"],
            "sparql": "SELECT ?area WHERE { bldg:bldg3 brick:area ?area . }",
            "category": "building_attribute",
        })


# -------------------- Deduplicate & Persist -------------------- #
unique = []
seen = set()
for ex in examples:
    key = (ex["question"], ex["sparql"])
    if key in seen:
        continue
    seen.add(key)
    unique.append(ex)

out_path = TTL_PATH.parent / "bldg3_schema_dataset.json"
out_path.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")

# Category stats
cat_counts = Counter(e["category"] for e in unique)
summary = {"total": len(unique), "by_category": dict(sorted(cat_counts.items(), key=lambda kv: kv[0]))}
print(json.dumps(summary, indent=2))
try:
    rel = out_path.relative_to(Path.cwd())
except Exception:
    rel = out_path
print(f"Wrote schema dataset to {rel}")
